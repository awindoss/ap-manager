# ==============================================================================
# views/dialogs/choose_parent_dialog.py
# Choose one or more additional parent locations for a node (stage.md 5.1).
#
# The tree mirrors the projected library so users can pick a place by context.
# Nodes that would create a cycle (the node itself or one of its descendants)
# and locations that already contain the node are shown but cannot be checked.
# ==============================================================================
from typing import TYPE_CHECKING, Dict, Iterable, List, Optional, Set

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QLabel,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from utils import constants
from utils.icon_utils import load_icon
from utils.logger import log_warning

if TYPE_CHECKING:  # pragma: no cover - type checking only
    from controllers.app_controller import AppController


class ChooseParentDialog(QDialog):
    """
    Pick target parent(s) for ``node_id``.

    ``mode="attach"`` allows several parents (one node may live in many
    places); ``mode="move"`` enforces a single target because a move rewrites
    exactly one existing edge. The dialog only collects a choice: the caller
    performs the database write, so cancelling never mutates the library.
    """

    def __init__(
        self,
        controller: "AppController",
        node_id: int,
        parent: Optional[QWidget] = None,
        *,
        excluded_parent_ids: Iterable[int] = (),
        mode: str = "attach",
    ) -> None:
        super().__init__(parent)
        node = controller.get_node(node_id)
        if node is None:
            raise ValueError(f"节点 {node_id} 不存在。")

        self._controller = controller
        self._node_id = node_id
        self._node_name = node.name
        self._mode = "move" if str(mode).lower() == "move" else "attach"
        self._excluded_ids: Set[int] = {
            int(parent_id) for parent_id in excluded_parent_ids or ()
        }
        # An existing edge cannot be attached twice; showing it as "已关联"
        # explains why the location is not selectable. This also covers the
        # old parent of a move without the caller having to pass it.
        self._excluded_ids.update(controller.get_parent_ids(node_id))
        self._forbidden_ids: Set[int] = {node_id}
        self._forbidden_ids.update(controller.get_descendant_ids(node_id))

        self._items_by_node: Dict[int, List[QTreeWidgetItem]] = {}
        self._displayed_ids: Set[int] = set()
        self._syncing = False
        self._item_count = 0

        self.setWindowTitle(
            f"{'移动' if self._mode == 'move' else '关联'}到其他位置 — {self._node_name}"
        )
        self.setModal(True)
        self._build_ui()
        self._populate()

    # --------------------------------------------------------------------------
    # Construction
    # --------------------------------------------------------------------------
    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)

        verb = "移动" if self._mode == "move" else "关联"
        multi_hint = "（单选）" if self._mode == "move" else "（可多选）"
        self.header_label = QLabel(
            f"选择要把「{self._node_name}」{verb}到的位置{multi_hint}：",
            self,
        )
        self.header_label.setWordWrap(True)
        layout.addWidget(self.header_label)

        hint = QLabel(
            "自身及其下级节点不可选，避免形成循环引用；已关联的位置也不可重复选择。",
            self,
        )
        hint.setWordWrap(True)
        hint.setStyleSheet("color: palette(mid);")
        layout.addWidget(hint)

        self.tree = QTreeWidget(self)
        self.tree.setObjectName("chooseParentTree")
        self.tree.setHeaderHidden(True)
        self.tree.setColumnCount(1)
        self.tree.itemChanged.connect(self._on_item_changed)
        layout.addWidget(self.tree, 1)

        self.status_label = QLabel("", self)
        self.status_label.setObjectName("chooseParentStatus")
        self.status_label.setWordWrap(True)
        layout.addWidget(self.status_label)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel,
            self,
        )
        self.ok_button = buttons.button(QDialogButtonBox.StandardButton.Ok)
        self.ok_button.setText("移动" if self._mode == "move" else "关联")
        self.ok_button.setEnabled(False)
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText("取消")
        buttons.accepted.connect(self._accept_selection)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        self.resize(620, 540)

    def _populate(self) -> None:
        """Build the tree projection of the whole library (paths, not just ids)."""
        roots = self._controller.get_all_roots()
        for root in roots:
            self._add_node(root, None, set())

        all_nodes = self._controller.get_all_nodes()
        unreachable = len(all_nodes) - len(self._displayed_ids)
        if self._items_by_node:
            if len(self._items_by_node) < 200:
                self.tree.expandAll()
            else:
                self.tree.expandToDepth(1)

        if not self._items_by_node:
            self.status_label.setText("当前书库还没有任何节点，无法选择父级位置。")
        elif unreachable > 0:
            self.status_label.setText(
                f"注意：有 {unreachable} 个节点无法从根节点到达，未显示在此列表中。"
            )
        else:
            self.status_label.setText("")

    def _add_node(
        self,
        node,
        parent_item: Optional[QTreeWidgetItem],
        current_path: Set[int],
    ) -> None:
        if node.id is None or node.id in current_path:
            return
        if self._item_count >= constants.TREE_MAX_ITEMS:
            log_warning("选择父级对话框达到节点上限，列表被截断。")
            return
        if len(current_path) >= constants.TREE_MAX_DEPTH:
            log_warning("选择父级对话框达到深度上限，列表被截断。")
            return

        item = QTreeWidgetItem([self._label_for(node.id, node.name)])
        item.setData(0, Qt.ItemDataRole.UserRole, node.id)
        item.setData(0, Qt.ItemDataRole.UserRole + 1, tuple(current_path) + (node.id,))
        item.setToolTip(0, self._tooltip_for(node.id, node.name))

        if node.icon:
            icon = load_icon(node.icon, constants.TREE_ICON_SIZE)
            if not icon.isNull():
                item.setIcon(0, icon)

        selectable = self._is_candidate(node.id)
        flags = Qt.ItemFlag.ItemIsEnabled
        if selectable:
            flags |= Qt.ItemFlag.ItemIsUserCheckable
            item.setCheckState(0, Qt.CheckState.Unchecked)
        item.setFlags(flags)

        if parent_item is None:
            self.tree.addTopLevelItem(item)
        else:
            parent_item.addChild(item)

        self._items_by_node.setdefault(node.id, []).append(item)
        self._displayed_ids.add(node.id)
        self._item_count += 1

        next_path = current_path | {node.id}
        for child in self._controller.get_node_children(node.id):
            self._add_node(child, item, next_path)

    # --------------------------------------------------------------------------
    # Candidate rules
    # --------------------------------------------------------------------------
    def _is_candidate(self, node_id: int) -> bool:
        return (
            node_id not in self._forbidden_ids
            and node_id not in self._excluded_ids
        )

    def _label_for(self, node_id: int, name: str) -> str:
        if node_id in self._forbidden_ids:
            return f"{name}（不可选：自身或下级节点）"
        if node_id in self._excluded_ids:
            return f"{name}（已关联）"
        return name

    def _tooltip_for(self, node_id: int, name: str) -> str:
        if node_id in self._forbidden_ids:
            return (
                f"{name}\n选择此位置会形成循环引用（它是当前节点的自身或下级节点）。"
            )
        if node_id in self._excluded_ids:
            return f"{name}\n当前节点已经关联到这个位置。"
        return f"{name}\n点击复选框选择此位置。"

    # --------------------------------------------------------------------------
    # Selection
    # --------------------------------------------------------------------------
    def _on_item_changed(self, item: QTreeWidgetItem, column: int) -> None:
        if self._syncing or column != 0:
            return
        node_id = item.data(0, Qt.ItemDataRole.UserRole)
        if not isinstance(node_id, int) or not self._is_candidate(node_id):
            return

        checked = item.checkState(0) == Qt.CheckState.Checked
        self._syncing = True
        try:
            same_node_items = self._items_by_node.get(node_id, [])
            if checked:
                if self._mode == "move":
                    # A move targets exactly one parent: clear every other node.
                    for other_id, other_items in self._items_by_node.items():
                        if other_id == node_id:
                            continue
                        for other_item in other_items:
                            other_item.setCheckState(0, Qt.CheckState.Unchecked)
                for same_item in same_node_items:
                    if same_item.flags() & Qt.ItemFlag.ItemIsUserCheckable:
                        same_item.setCheckState(0, Qt.CheckState.Checked)
            else:
                # Duplicate paths of the same database node are one choice.
                for same_item in same_node_items:
                    if same_item.flags() & Qt.ItemFlag.ItemIsUserCheckable:
                        same_item.setCheckState(0, Qt.CheckState.Unchecked)
        finally:
            self._syncing = False
        self._update_state()

    def _update_state(self) -> None:
        selected = self.selected_parent_ids()
        self.ok_button.setEnabled(bool(selected))
        if not selected:
            self.status_label.setText("尚未选择位置。")
            return
        if self._mode == "move":
            target = self._controller.get_node(selected[0])
            self.status_label.setText(
                f"将移动到此位置：{target.name if target is not None else selected[0]}"
            )
        else:
            self.status_label.setText(f"已选择 {len(selected)} 个位置。")

    def selected_parent_ids(self) -> List[int]:
        """Checked parent ids, deduplicated, in first-appearance order."""
        selected: List[int] = []
        for node_id, items in self._items_by_node.items():
            if not self._is_candidate(node_id):
                continue
            if any(
                item.flags() & Qt.ItemFlag.ItemIsUserCheckable
                and item.checkState(0) == Qt.CheckState.Checked
                for item in items
            ):
                selected.append(node_id)
        return selected

    def _accept_selection(self) -> None:
        if not self.selected_parent_ids():
            self.status_label.setText("请先选择至少一个位置。")
            return
        self.accept()

    # --------------------------------------------------------------------------
    # Introspection helpers (used by tests and the main window)
    # --------------------------------------------------------------------------
    @property
    def mode(self) -> str:
        return self._mode

    def item_for_node(self, node_id: int) -> Optional[QTreeWidgetItem]:
        """First tree item representing ``node_id`` (any display path)."""
        items = self._items_by_node.get(node_id)
        return items[0] if items else None

    def is_node_selectable(self, node_id: int) -> bool:
        return self._is_candidate(node_id)


# ==============================================================================
# End of choose_parent_dialog.py
# ==============================================================================
