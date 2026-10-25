# ==============================================================================
# views/tree_model.py
# Qt item model that projects the node/edge graph onto a QTreeView.
#
# The database stores a directed acyclic graph (nodes + edges), while the view
# only understands a tree. Every visible row is one display instance (TreeItem)
# of a database node, so the same node_id may appear under several parents.
# Cycle protection is therefore scoped to the *current recursion path* rather
# than to a global "visited" set: A -> X and B -> X are both legitimate and X
# must be shown twice (plan.md sections 9 and 10).
# ==============================================================================
from typing import Dict, List, Optional, Sequence, Set, Tuple

from PySide6.QtCore import QAbstractItemModel, QModelIndex, QObject, Qt
from PySide6.QtGui import QColor, QFont, QIcon

from models.library import LibraryService
from models.node import Node
from services import path_manager
from utils import constants
from utils.icon_utils import clear_icon_cache, compose_warning_icon, load_icon
from utils.logger import log_debug, log_warning

# Path of a display instance: the node ids from a root down to this item.
DisplayPath = Tuple[int, ...]


class TreeItem:
    """
    One display instance of a database node inside the tree view.

    `node_id` points at the real `nodes.id`; this object itself is only a
    position in the projected tree. The same `node_id` can back multiple
    TreeItems (multi-parent support).
    """

    __slots__ = ("node_id", "node", "parent_item", "children", "display_path", "row")

    def __init__(
        self,
        node_id: int,
        node: Optional[Node] = None,
        parent_item: Optional["TreeItem"] = None,
        display_path: DisplayPath = (),
    ) -> None:
        self.node_id: int = node_id
        self.node: Optional[Node] = node
        self.parent_item: Optional["TreeItem"] = parent_item
        self.children: List["TreeItem"] = []
        # Path including this item, e.g. (root_id, ..., node_id). Used for
        # duplicate detection in Phase 5 and for cycle reporting.
        self.display_path: DisplayPath = display_path or (node_id,)
        # Row index inside the parent (or inside the model roots). Maintained
        # by the model because QModelIndex construction requires it.
        self.row: int = 0

    @property
    def name(self) -> str:
        """Display name, falling back to the id if the node payload is missing."""
        if self.node is not None:
            return self.node.name
        return f"#{self.node_id}"

    def append_child(self, child: "TreeItem") -> None:
        """Append a child and assign its row index."""
        child.row = len(self.children)
        child.parent_item = self
        self.children.append(child)

    def __repr__(self) -> str:  # pragma: no cover - debugging aid only
        return f"TreeItem(node_id={self.node_id}, path={self.display_path})"


class TreeModel(QAbstractItemModel):
    """
    Read-only model that materialises the whole library as a tree.

    Phase 2 intentionally rebuilds everything on `refresh()`: it is simple,
    always consistent with the database, and fast enough for the library sizes
    targeted by the first version (plan.md section 37).
    """

    # Custom roles so views/controllers can recover the database identity of a
    # displayed row without reaching into the TreeItem internals.
    NodeIdRole = int(Qt.ItemDataRole.UserRole) + 1
    DisplayPathRole = int(Qt.ItemDataRole.UserRole) + 2
    # Number of parents of the database node behind this row (0 for a root).
    # Cached per build, so the delegate can paint the multi-parent badge cheaply.
    ParentCountRole = int(Qt.ItemDataRole.UserRole) + 3

    def __init__(self, library_service: LibraryService, parent: Optional[QObject] = None) -> None:
        super().__init__(parent)
        self._library = library_service

        self._root_items: List[TreeItem] = []
        # Cached child lists (per parent id) so a subtree shared by several
        # parents is queried once instead of once per display instance.
        self._children_cache: Dict[int, List[Node]] = {}
        self._displayed_node_ids: Set[int] = set()
        # node_id -> parent count, refreshed once per build.
        self._parent_counts: Dict[int, int] = {}
        # node_id -> stored paths that currently do not exist on disk.
        self._missing_pdf_paths: Dict[int, List[str]] = {}
        # node_id -> composed warning icon (rebuilt when the model is rebuilt).
        self._warning_icons: Dict[int, QIcon] = {}
        self._item_count = 0

        self._cycle_warnings: List[Tuple[int, DisplayPath]] = []
        self._unreachable_node_ids: List[int] = []
        self._truncated = False
        self._loaded = False

    # --------------------------------------------------------------------------
    # Query helpers used by views/controllers/tests
    # --------------------------------------------------------------------------
    @property
    def root_count(self) -> int:
        return len(self._root_items)

    @property
    def displayed_node_count(self) -> int:
        """Number of distinct database nodes currently visible."""
        return len(self._displayed_node_ids)

    @property
    def displayed_item_count(self) -> int:
        """Number of display instances (rows + descendants) currently built."""
        return self._item_count

    @property
    def cycle_warnings(self) -> Tuple[Tuple[int, DisplayPath], ...]:
        """
        Cycles skipped during the last build, as (repeated_child_id, path) pairs.
        A non-empty list means the data contains a cycle; the view still renders.
        """
        return tuple(self._cycle_warnings)

    @property
    def unreachable_node_ids(self) -> Tuple[int, ...]:
        """
        Nodes that exist in the database but are not reachable from any root.
        This is normally only produced by a cycle-only component.
        """
        return tuple(self._unreachable_node_ids)

    @property
    def is_truncated(self) -> bool:
        """True if the projection hit TREE_MAX_ITEMS / TREE_MAX_DEPTH."""
        return self._truncated

    @property
    def missing_pdf_node_ids(self) -> Tuple[int, ...]:
        """Nodes with at least one PDF path that does not exist on disk."""
        return tuple(sorted(self._missing_pdf_paths))

    def missing_pdf_paths(self, node_id: int) -> Tuple[str, ...]:
        """Stored PDF paths of ``node_id`` that are currently missing."""
        return tuple(self._missing_pdf_paths.get(node_id, ()))

    def item_from_index(self, index: QModelIndex) -> Optional[TreeItem]:
        """Return the TreeItem behind a QModelIndex, or None if invalid."""
        if not index.isValid():
            return None
        item = index.internalPointer()
        return item if isinstance(item, TreeItem) else None

    def node_id_from_index(self, index: QModelIndex) -> Optional[int]:
        """Return the database node id behind a QModelIndex, or None."""
        item = self.item_from_index(index)
        return item.node_id if item is not None else None

    # --------------------------------------------------------------------------
    # Building / refreshing
    # --------------------------------------------------------------------------
    def refresh(self) -> None:
        """Rebuild the whole projection and notify attached views."""
        self.beginResetModel()
        try:
            self.load_roots()
        finally:
            self.endResetModel()

    def load_roots(self) -> None:
        """
        Clear every TreeItem and rebuild the tree from all root nodes.

        This does not emit model signals; callers that need the views to update
        must use `refresh()` instead (or wrap this call in begin/endResetModel).
        """
        self._root_items = []
        self._children_cache.clear()
        self._displayed_node_ids.clear()
        self._parent_counts = {}
        self._missing_pdf_paths = {}
        self._warning_icons = {}
        self._cycle_warnings = []
        self._unreachable_node_ids = []
        self._item_count = 0
        self._truncated = False

        # Custom image files may have been replaced or deleted since the last
        # build, so decoded icons are not reused across rebuilds.
        clear_icon_cache()
        self._parent_counts = self._library.get_parent_count_map()

        for root_node in self._library.get_all_roots():
            if self._item_count >= constants.TREE_MAX_ITEMS:
                self._mark_truncated("item limit reached while adding root nodes")
                break
            if root_node.id is None:
                log_warning(f"Skipping root node without a database id: {root_node.name!r}")
                continue

            item = self._create_item(root_node, parent_item=None, path_prefix=())
            item.row = len(self._root_items)
            self._root_items.append(item)
            self.build_subtree(item, {root_node.id})

        all_nodes = self._library.get_all_nodes()
        self._detect_unreachable_nodes(all_nodes)
        self._scan_pdf_files(all_nodes)
        self._loaded = True

        log_debug(
            f"Tree model built: {self.root_count} root(s), {self._item_count} display item(s), "
            f"{len(self._cycle_warnings)} cycle warning(s)."
        )

    def build_subtree(self, parent_item: TreeItem, current_path_set: Set[int]) -> None:
        """
        Recursively create the children of `parent_item`.

        `current_path_set` contains every node id on the path from the root to
        `parent_item`. A child already present in that set would close a cycle,
        so it is skipped and reported instead of being rendered.
        """
        if self._truncated:
            return

        if len(current_path_set) >= constants.TREE_MAX_DEPTH:
            self._mark_truncated(
                f"maximum tree depth ({constants.TREE_MAX_DEPTH}) reached below node "
                f"{parent_item.node_id}; deeper nodes are not displayed"
            )
            return

        for child_node in self._get_children(parent_item.node_id):
            if child_node.id is None:
                continue
            if child_node.id in current_path_set:
                self._record_cycle(parent_item, child_node)
                continue
            if self._item_count >= constants.TREE_MAX_ITEMS:
                self._mark_truncated("item limit reached while expanding the tree")
                return

            child_item = self._create_item(
                child_node,
                parent_item=parent_item,
                path_prefix=parent_item.display_path,
            )
            parent_item.append_child(child_item)
            self.build_subtree(child_item, current_path_set | {child_node.id})

    # --------------------------------------------------------------------------
    # Internal building helpers
    # --------------------------------------------------------------------------
    def _create_item(self, node: Node, parent_item: Optional[TreeItem], path_prefix: DisplayPath) -> TreeItem:
        assert node.id is not None
        item = TreeItem(
            node_id=node.id,
            node=node,
            parent_item=parent_item,
            display_path=path_prefix + (node.id,),
        )
        self._displayed_node_ids.add(node.id)
        self._item_count += 1
        return item

    def _get_children(self, parent_id: int) -> List[Node]:
        children = self._children_cache.get(parent_id)
        if children is None:
            children = self._library.get_node_children(parent_id)
            self._children_cache[parent_id] = children
        return children

    def _record_cycle(self, parent_item: TreeItem, child_node: Node) -> None:
        path = parent_item.display_path + (child_node.id,)
        self._cycle_warnings.append((child_node.id, path))
        path_text = " -> ".join(str(part) for part in path)
        log_warning(
            f"Cycle detected while building the tree: node {child_node.id} "
            f"({child_node.name!r}) already appears on path {path_text}; "
            "its subtree is skipped."
        )

    def _mark_truncated(self, reason: str) -> None:
        if not self._truncated:
            self._truncated = True
            log_warning(f"Tree projection truncated: {reason}.")

    def _detect_unreachable_nodes(self, all_nodes: Sequence[Node]) -> None:
        """
        Report nodes that no root can reach (normally only cycles without a root).

        A full node scan is acceptable here because Phase 2 loads the whole
        library anyway; it should be revisited if/when lazy loading is added.
        """
        unreachable = sorted(
            node.id for node in all_nodes
            if node.id is not None and node.id not in self._displayed_node_ids
        )
        self._unreachable_node_ids = unreachable
        if unreachable:
            preview = ", ".join(str(node_id) for node_id in unreachable[:10])
            suffix = ", ..." if len(unreachable) > 10 else ""
            log_warning(
                f"{len(unreachable)} node(s) are not reachable from any root and are "
                f"therefore not displayed: {preview}{suffix}"
            )

    def _scan_pdf_files(self, all_nodes: Sequence[Node]) -> None:
        """
        Record which nodes have at least one PDF that cannot be found.

        This is a single batched pass per build (not a per-row disk check), and
        it never removes the database reference: a missing file only produces a
        warning marker and tooltip entry (plan.md §22).
        """
        self._missing_pdf_paths = {}
        for node in all_nodes:
            if node.id is None or not node.pdf_paths:
                continue
            missing = path_manager.missing_pdf_paths(node.pdf_paths)
            if missing:
                self._missing_pdf_paths[node.id] = missing

        if self._missing_pdf_paths:
            log_warning(
                f"{len(self._missing_pdf_paths)} node(s) reference PDF files that "
                "cannot be found; they are shown with a warning marker."
            )

    # --------------------------------------------------------------------------
    # QAbstractItemModel interface
    # --------------------------------------------------------------------------
    def index(self, row: int, column: int, parent: QModelIndex = QModelIndex()) -> QModelIndex:
        if not self.hasIndex(row, column, parent):
            return QModelIndex()

        parent_item = self.item_from_index(parent)
        siblings = parent_item.children if parent_item is not None else self._root_items
        if 0 <= row < len(siblings):
            return self.createIndex(row, column, siblings[row])
        return QModelIndex()

    def parent(self, index: QModelIndex = QModelIndex()) -> QModelIndex:  # type: ignore[override]
        if not index.isValid():
            return QModelIndex()
        item = self.item_from_index(index)
        if item is None or item.parent_item is None:
            return QModelIndex()
        parent_item = item.parent_item
        return self.createIndex(parent_item.row, 0, parent_item)

    def rowCount(self, parent: QModelIndex = QModelIndex()) -> int:  # type: ignore[override]
        if parent.column() > 0:
            return 0
        if not parent.isValid():
            return len(self._root_items)
        item = self.item_from_index(parent)
        return len(item.children) if item is not None else 0

    def columnCount(self, parent: QModelIndex = QModelIndex()) -> int:  # type: ignore[override]
        return 1

    def data(self, index: QModelIndex, role: int = Qt.ItemDataRole.DisplayRole):  # type: ignore[override]
        if not index.isValid() or index.column() != 0:
            return None
        item = self.item_from_index(index)
        if item is None:
            return None

        if role == Qt.ItemDataRole.DisplayRole:
            return item.name
        if role == Qt.ItemDataRole.ToolTipRole:
            return self._tooltip_for(item)
        if role == Qt.ItemDataRole.DecorationRole:
            return self._decoration_for(item)
        if role == Qt.ItemDataRole.FontRole:
            return self._font_for(item)
        if role == Qt.ItemDataRole.ForegroundRole:
            return self._foreground_for(item)
        if role == self.NodeIdRole:
            return item.node_id
        if role == self.DisplayPathRole:
            return item.display_path
        if role == self.ParentCountRole:
            return self._parent_counts.get(item.node_id, 0)
        return None

    def headerData(self, section: int, orientation: Qt.Orientation, role: int = Qt.ItemDataRole.DisplayRole):  # type: ignore[override]
        if (
            orientation == Qt.Orientation.Horizontal
            and role == Qt.ItemDataRole.DisplayRole
            and section == 0
        ):
            return "名称"
        return super().headerData(section, orientation, role)

    def flags(self, index: QModelIndex) -> Qt.ItemFlag:
        if not index.isValid():
            return Qt.ItemFlag.NoItemFlags
        # Editing happens through the property dialog; dragging arrives in Phase 5.
        return Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable

    # --------------------------------------------------------------------------
    # Presentation helpers
    # --------------------------------------------------------------------------
    def _decoration_for(self, item: TreeItem):
        """
        Icon for a row, or None when there is nothing to draw.

        Nodes with a missing PDF get a warning badge composed onto their icon
        (or shown alone when the node has no icon). The composed icon is cached
        per node id for the lifetime of the current projection.
        """
        node = item.node
        if node is None:
            return None

        if item.node_id in self._missing_pdf_paths:
            warning_icon = self._warning_icons.get(item.node_id)
            if warning_icon is None:
                base_icon = (
                    load_icon(node.icon, constants.TREE_ICON_SIZE)
                    if node.icon
                    else load_icon("", constants.TREE_ICON_SIZE)
                )
                warning_icon = compose_warning_icon(base_icon, constants.TREE_ICON_SIZE)
                self._warning_icons[item.node_id] = warning_icon
            return warning_icon if not warning_icon.isNull() else None

        if not node.icon:
            return None
        icon = load_icon(node.icon, constants.TREE_ICON_SIZE)
        return icon if not icon.isNull() else None

    @staticmethod
    def _font_for(item: TreeItem):
        """Bold font override; None keeps the view's default font."""
        node = item.node
        if node is None or not node.style_bold:
            return None
        font = QFont()
        font.setBold(True)
        return font

    @staticmethod
    def _foreground_for(item: TreeItem):
        """
        Text colour override.

        The schema default (``#000000``) is treated as "no override" so the
        platform palette still decides the normal text colour (important for
        dark themes); a user-chosen colour is returned as-is.
        """
        node = item.node
        if node is None:
            return None
        if node.style_color == constants.DEFAULT_TEXT_COLOR:
            return None
        color = QColor(node.style_color)
        return color if color.isValid() else None

    def _tooltip_for(self, item: TreeItem) -> str:
        names: List[str] = []
        current: Optional[TreeItem] = item
        while current is not None:
            names.append(current.name)
            current = current.parent_item
        names.reverse()

        lines = [" > ".join(names)]
        parent_count = self._parent_counts.get(item.node_id, 0)
        if parent_count > 1:
            lines.append(f"位置: {parent_count} 个")
        node = item.node
        if node is not None and node.pdf_paths:
            lines.append(f"PDF: {len(node.pdf_paths)}")

        missing = self._missing_pdf_paths.get(item.node_id, ())
        if missing:
            lines.append(f"⚠ 缺失 PDF: {len(missing)} 个")
            for path_text in missing[:3]:
                lines.append(f"  {path_text}")
            if len(missing) > 3:
                lines.append("  …")

        if node is not None and node.icon:
            lines.append(f"图标: {node.icon}")
        return "\n".join(lines)

    def parent_count(self, node_id: int) -> int:
        """Cached number of parents of a database node (0 for roots)."""
        return self._parent_counts.get(node_id, 0)

    # --------------------------------------------------------------------------
    # Future-facing helpers
    # --------------------------------------------------------------------------
    def notify_node_changed(self, node_id: int) -> bool:
        """
        Refresh one database node in place, without resetting the model.

        Every display instance of the node gets the new payload and a
        ``dataChanged`` for the presentation roles. Unlike ``refresh()`` this
        keeps the expand/collapse state and the current selection intact, which
        is what "edit properties" needs (plan.md §13).
        """
        node = self._library.get_node(node_id)
        if node is None:
            log_warning(f"Cannot notify change for unknown node {node_id}.")
            return False

        items = self.find_items_by_node_id(node_id)
        if not items:
            # Reachable-node changes always have at least one instance; a node
            # that is only part of an unreachable cycle has none.
            log_debug(f"Node {node_id} has no display instance; nothing to repaint.")
            return False

        # The PDF list is not editable in Phase 3, but keeping this cache in sync
        # costs nothing and makes the method safe for Phase 4 updates.
        if node.pdf_paths:
            missing = path_manager.missing_pdf_paths(node.pdf_paths)
            if missing:
                self._missing_pdf_paths[node_id] = missing
            else:
                self._missing_pdf_paths.pop(node_id, None)
        else:
            self._missing_pdf_paths.pop(node_id, None)
        self._warning_icons.pop(node_id, None)

        roles = [
            Qt.ItemDataRole.DisplayRole,
            Qt.ItemDataRole.DecorationRole,
            Qt.ItemDataRole.FontRole,
            Qt.ItemDataRole.ForegroundRole,
            Qt.ItemDataRole.ToolTipRole,
            self.ParentCountRole,
        ]
        for item in items:
            item.node = node
            index = self.createIndex(item.row, 0, item)
            self.dataChanged.emit(index, index, roles)

        # Keep cached sibling lists consistent for any later incremental build.
        for siblings in self._children_cache.values():
            for position, sibling in enumerate(siblings):
                if sibling.id == node_id:
                    siblings[position] = node
        return True

    def find_index_by_display_path(self, display_path: Sequence[int]) -> QModelIndex:
        """Return the QModelIndex of an exact display instance, or an invalid one."""
        if not display_path:
            return QModelIndex()

        parent = QModelIndex()
        for depth, node_id in enumerate(display_path):
            found = QModelIndex()
            for row in range(self.rowCount(parent)):
                candidate = self.index(row, 0, parent)
                if self.node_id_from_index(candidate) == node_id:
                    found = candidate
                    break
            if not found.isValid():
                log_debug(f"Display path {tuple(display_path)} no longer exists at depth {depth}.")
                return QModelIndex()
            parent = found
        return parent

    def find_items_by_node_id(self, node_id: int) -> Sequence[TreeItem]:
        """
        Return every display instance of `node_id` (used by "show all positions"
        and by search in later phases). Traversal is depth-first following the
        visible order.
        """
        matches: List[TreeItem] = []

        def visit(item: TreeItem) -> None:
            if item.node_id == node_id:
                matches.append(item)
            for child in item.children:
                visit(child)

        for root_item in self._root_items:
            visit(root_item)
        return tuple(matches)

    @property
    def is_loaded(self) -> bool:
        """True once at least one build completed (even an empty one)."""
        return self._loaded


# ==============================================================================
# End of tree_model.py
# ==============================================================================
