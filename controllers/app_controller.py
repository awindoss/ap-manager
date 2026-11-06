# ==============================================================================
# controllers/app_controller.py
# Thin controller between the Qt views and the library business layer.
#
# plan.md section 27 fixes the call direction: View -> Controller -> Library ->
# Database. The controller therefore owns the LibraryService (and, through it,
# the Database) and exposes the few operations the views need. As later phases
# add editing, PDF opening and import/export, those entry points belong here.
# ==============================================================================
from dataclasses import dataclass, field
from pathlib import Path
import sqlite3
from typing import Any, Dict, List, Optional, Tuple, Union

from models.library import GraphCycleError, LibraryService
from models.node import Node, normalize_color, normalize_icon
from services import path_manager
from services.exporter import ExportResult, export_library as export_library_file
from services.importer import ImportResult, import_library as import_library_file
from services.pdf_launcher import LaunchReport, PdfLaunchError, PdfLauncher
from services.relocator import RelinkPlan, RelinkRequest, plan_batch_relink
from services.search import SearchResult, SearchService
from utils import constants
from utils.config_manager import ConfigManager
from utils.logger import log_debug, log_error, log_info, log_warning


@dataclass(frozen=True)
class PdfAddResult:
    """Outcome of adding user-picked files to a node."""

    added: List[str]
    skipped: List[str]
    errors: List[Tuple[str, str]]

    @property
    def has_changes(self) -> bool:
        return bool(self.added)

    @property
    def has_errors(self) -> bool:
        return bool(self.errors)


@dataclass(frozen=True)
class MissingPdf:
    """A stored PDF reference whose file cannot be found."""

    node_id: int
    node_name: str
    stored_path: str
    absolute_path: Optional[Path]

    @property
    def display_path(self) -> str:
        return str(self.absolute_path) if self.absolute_path is not None else self.stored_path


@dataclass(frozen=True)
class PdfInspection:
    """Result of the whole-library file check (plan.md §34 tools menu)."""

    nodes_with_pdfs: int
    total_pdfs: int
    missing: List[MissingPdf]

    @property
    def existing_count(self) -> int:
        return self.total_pdfs - len(self.missing)


@dataclass(frozen=True)
class BatchRelinkOutcome:
    """Result of matching missing PDFs against a user-picked folder."""

    search_root: Path
    requested: int
    relinked: int
    ambiguous: List[MissingPdf] = field(default_factory=list)
    not_found: List[MissingPdf] = field(default_factory=list)
    errors: List[Tuple[MissingPdf, str]] = field(default_factory=list)

    @property
    def has_changes(self) -> bool:
        return self.relinked > 0

    @property
    def unmatched_count(self) -> int:
        return len(self.ambiguous) + len(self.not_found)

    @property
    def failed_count(self) -> int:
        return len(self.errors)


@dataclass(frozen=True)
class NodePosition:
    """One root-to-node path (a display location) of a database node."""

    node_id: int
    path: Tuple[int, ...]
    names: Tuple[str, ...]

    @property
    def label(self) -> str:
        """Human-readable breadcrumb, e.g. ``经济政治 > 马列 > 马克思``."""
        return " > ".join(self.names)


@dataclass(frozen=True)
class AttachResult:
    """Outcome of a batch "attach to other location(s)" request.

    Pairs are ``(parent_id, child_id)`` so both the "one child, many parents"
    (context menu) and "many children, one parent" (drag and drop) directions
    can share the same result type.
    """

    attached: List[Tuple[int, int]] = field(default_factory=list)
    already: List[Tuple[int, int]] = field(default_factory=list)
    errors: List[Tuple[Tuple[int, int], str]] = field(default_factory=list)

    @property
    def has_changes(self) -> bool:
        return bool(self.attached)

    @property
    def has_errors(self) -> bool:
        return bool(self.errors)


@dataclass(frozen=True)
class MoveOutcome:
    """Result of moving one display instance to another parent.

    ``kind`` is one of:
      * ``"moved"``    - the edge was moved to the new parent;
      * ``"merged"``   - the target already had the node, the source edge was removed;
      * ``"attached"`` - a root instance (no source edge) was attached to the target;
      * ``"already"``  - a root instance that is already attached to the target;
      * ``"same"``     - source and target parents are identical.
    """

    kind: str
    old_parent_id: Optional[int]
    new_parent_id: int
    child_id: int

    @property
    def moved(self) -> bool:
        return self.kind in ("moved", "merged", "attached")


class AppController:
    """Coordinates the main window with `LibraryService`."""

    def __init__(
        self,
        library_service: Optional[LibraryService] = None,
        db_path: Optional[Union[str, Path]] = None,
        *,
        config_manager: Optional[ConfigManager] = None,
        pdf_launcher: Optional[PdfLauncher] = None,
    ) -> None:
        # `library_service` is injectable for tests; production code simply lets
        # LibraryService pick the configured database path.
        self.config: ConfigManager = config_manager or ConfigManager()

        if library_service is not None:
            self.library: LibraryService = library_service
        else:
            if db_path is None:
                db_path = path_manager.normalize_path(self.config.get_library_db_path())
            self.library = LibraryService(db_path=db_path)

        # Search is a read-only service over the same business layer; the UI
        # never queries SQLite directly (plan.md §27).
        self.search_service: SearchService = SearchService(self.library)

        # The launcher is injectable for tests; otherwise it reads the reader
        # configured in config.json (empty -> platform default).
        self.launcher: PdfLauncher = pdf_launcher or PdfLauncher(
            reader_path=self.get_pdf_reader_path(),
            reader_args=self.config.get_pdf_reader_args(),
        )
        log_info("Application controller initialised.")

    # --------------------------------------------------------------------------
    # Read-only pass-throughs
    # --------------------------------------------------------------------------
    def get_node(self, node_id: int) -> Optional[Node]:
        """Retrieve a single node."""
        return self.library.get_node(node_id)

    def get_all_roots(self) -> List[Node]:
        """Retrieve every root node (nodes without a parent)."""
        return self.library.get_all_roots()

    def get_node_children(self, parent_id: int) -> List[Node]:
        """Retrieve the children of a node, ordered by `sort_order`."""
        return self.library.get_node_children(parent_id)

    def get_node_parents(self, node_id: int) -> List[Node]:
        """Retrieve every parent of a node (multi-parent support)."""
        return self.library.get_node_parents(node_id)

    def get_parent_count_map(self) -> Dict[int, int]:
        """Return ``{node_id: parent_count}`` for badge rendering."""
        return self.library.get_parent_count_map()

    def get_all_nodes(self) -> List[Node]:
        """Every node in the library, ordered by id."""
        return self.library.get_all_nodes()

    def get_parent_ids(self, node_id: int) -> List[int]:
        """Parent ids of ``node_id`` (one per incoming edge)."""
        return self.library.get_parent_ids(node_id)

    def has_edge(self, parent_id: int, child_id: int) -> bool:
        """True when ``parent_id -> child_id`` already exists."""
        return self.library.db.get_edge(parent_id, child_id) is not None

    def would_create_cycle(self, parent_id: int, child_id: int) -> bool:
        """True when attaching ``child_id`` below ``parent_id`` would cycle."""
        return self.library.would_create_cycle(parent_id, child_id)

    def get_descendant_ids(self, node_id: int) -> List[int]:
        """Every node below ``node_id`` (transitively, excluding itself)."""
        return self.library.get_descendant_ids(node_id)

    def get_node_positions(self, node_id: int) -> List[NodePosition]:
        """
        Every root-to-node path of a node, with names resolved for the UI.

        A node inside a cycle-only component has no root path and therefore
        returns an empty list (plan.md §10); callers must handle that case.
        """
        node = self._require_node(node_id)
        paths = self.library.get_node_paths(node_id)
        name_cache: Dict[int, str] = {node_id: node.name}

        positions: List[NodePosition] = []
        for raw_path in paths:
            path = tuple(int(part) for part in raw_path)
            names: List[str] = []
            for part_id in path:
                if part_id not in name_cache:
                    part = self.library.get_node(part_id)
                    name_cache[part_id] = part.name if part is not None else f"#{part_id}"
                names.append(name_cache[part_id])
            positions.append(
                NodePosition(node_id=node_id, path=path, names=tuple(names))
            )
        return positions

    # --------------------------------------------------------------------------
    # Multi-parent relations (Phase 5)
    # --------------------------------------------------------------------------
    def attach_node_to_parents(
        self,
        child_id: int,
        parent_ids: List[int],
    ) -> AttachResult:
        """Attach one node below one or more additional parents."""
        pairs = [(parent_id, child_id) for parent_id in parent_ids or ()]
        return self._attach_pairs(pairs)

    def attach_nodes_to_parent(
        self,
        child_ids: List[int],
        parent_id: int,
    ) -> AttachResult:
        """Attach several nodes below one parent (drag and drop source set)."""
        pairs = [(parent_id, child_id) for child_id in child_ids or ()]
        return self._attach_pairs(pairs)

    def _attach_pairs(
        self,
        pairs: List[Tuple[int, int]],
    ) -> AttachResult:
        """
        Attach ``(parent, child)`` pairs one by one.

        Duplicates, self-links, missing nodes and cycle-producing pairs are
        collected as per-pair results instead of aborting the whole batch, so
        dragging a multi-selection still attaches every legal node.
        """
        result = AttachResult()
        seen_pairs = set()

        for parent_id, child_id in pairs:
            pair = (int(parent_id), int(child_id))
            if pair in seen_pairs:
                continue
            seen_pairs.add(pair)

            parent = self.library.get_node(pair[0])
            child = self.library.get_node(pair[1])
            if parent is None or child is None:
                result.errors.append((pair, "节点不存在，可能已被删除，请刷新后重试。"))
                continue
            if pair[0] == pair[1]:
                result.errors.append((pair, "不能把节点关联到它自身。"))
                continue
            if self.has_edge(pair[0], pair[1]):
                result.already.append(pair)
                continue
            if self.would_create_cycle(pair[0], pair[1]):
                result.errors.append((pair, self._cycle_message(pair[0], pair[1])))
                continue

            try:
                self.library.attach_nodes(pair[0], pair[1])
            except (ValueError, sqlite3.Error) as error:
                result.errors.append((pair, str(error)))
            except Exception as error:  # defensive: never abort the batch
                log_error(
                    f"Could not attach {pair[1]} below {pair[0]}: {error}"
                )
                result.errors.append((pair, f"数据库写入失败：{error}"))
            else:
                result.attached.append(pair)

        if result.has_changes:
            log_info(
                f"Attached {len(result.attached)} location(s); "
                f"{len(result.already)} already existed, {len(result.errors)} rejected."
            )
        return result

    def detach_node(self, parent_id: int, child_id: int) -> bool:
        """
        Remove exactly one position (edge), leaving the node and its other
        positions untouched. Returns True when an edge was removed.
        """
        self._require_node(child_id)
        removed = self.library.detach_nodes(parent_id, child_id)
        if removed:
            log_info(f"Detached node {child_id} from parent {parent_id}.")
        return removed

    def delete_node_completely(self, node_id: int) -> None:
        """Delete a node and every edge that references it (files stay on disk)."""
        node = self._require_node(node_id)
        self.library.delete_node_completely(node_id)
        log_info(f"Permanently deleted node {node_id} ({node.name!r}).")

    def move_node(
        self,
        old_parent_id: Optional[int],
        child_id: int,
        new_parent_id: int,
    ) -> MoveOutcome:
        """
        Move one display instance to a new parent.

        * A normal move deletes the old edge and inserts the new one atomically.
        * Moving onto a parent that already contains the node simply removes the
          old position ("merged"), which avoids violating the unique edge rule.
        * A root instance has no edge to delete; "move" then behaves like an
          attach and reports ``kind == "attached"``.
        """
        child = self._require_node(child_id)
        new_parent = self._require_node(new_parent_id)

        if old_parent_id is not None:
            self._require_node(old_parent_id)
        if old_parent_id == new_parent_id:
            return MoveOutcome("same", old_parent_id, new_parent_id, child_id)
        if new_parent_id == child_id:
            raise GraphCycleError(
                f"无法移动：「{child.name}」不能放到它自己下面。"
            )
        if old_parent_id is not None and not self.has_edge(old_parent_id, child_id):
            raise ValueError("原位置已不存在，请刷新后重试。")

        target_exists = self.has_edge(new_parent_id, child_id)
        if target_exists:
            if old_parent_id is None:
                return MoveOutcome("already", None, new_parent_id, child_id)
            self.library.detach_nodes(old_parent_id, child_id)
            log_info(
                f"Moved node {child_id} to existing position below {new_parent_id}; "
                f"old edge from {old_parent_id} removed."
            )
            return MoveOutcome("merged", old_parent_id, new_parent_id, child_id)

        if self.would_create_cycle(new_parent_id, child_id):
            raise GraphCycleError(self._cycle_message(new_parent_id, child_id))

        if old_parent_id is None:
            self.library.attach_nodes(new_parent_id, child_id)
            log_info(f"Attached root node {child_id} below {new_parent_id}.")
            return MoveOutcome("attached", None, new_parent_id, child_id)

        if not self.library.move_node(old_parent_id, child_id, new_parent_id):
            raise ValueError("移动失败，请刷新后重试。")
        log_info(
            f"Moved node {child_id} from parent {old_parent_id} to {new_parent_id}."
        )
        return MoveOutcome("moved", old_parent_id, new_parent_id, child_id)

    def reorder_relative(
        self,
        parent_id: int,
        child_id: int,
        target_child_id: int,
        before: bool = True,
    ) -> bool:
        """Move one sibling before/after another sibling (drag sorting)."""
        return self.library.reorder_relative(
            parent_id, child_id, target_child_id, before=before
        )

    def reorder_children(self, parent_id: int, ordered_child_ids: List[int]) -> bool:
        """Replace the whole sibling order below one parent."""
        return self.library.reorder_children(parent_id, ordered_child_ids)

    def _cycle_message(self, parent_id: int, child_id: int) -> str:
        """User-facing explanation for a rejected cycle-producing operation."""
        parent = self.library.get_node(parent_id)
        child = self.library.get_node(child_id)
        parent_name = parent.name if parent is not None else f"#{parent_id}"
        child_name = child.name if child is not None else f"#{child_id}"
        return (
            f"无法完成操作：把「{child_name}」放到「{parent_name}」下面会形成循环引用。"
            "请选择其上级之外的另一个位置。"
        )

    # --------------------------------------------------------------------------
    # Editing (Phase 3)
    # --------------------------------------------------------------------------
    @staticmethod
    def _validate_name(name: Any) -> str:
        """Trim and validate a node name; raises ValueError for unusable input."""
        clean = "" if name is None else str(name).strip()
        if not clean:
            raise ValueError("节点名称不能为空。")
        if len(clean) > constants.MAX_NODE_NAME_LENGTH:
            raise ValueError(
                f"节点名称不能超过 {constants.MAX_NODE_NAME_LENGTH} 个字符。"
            )
        return clean

    def create_node(
        self,
        name: str,
        parent_id: Optional[int] = None,
        icon: object = "",
        style_bold: bool = False,
        style_color: str = constants.DEFAULT_TEXT_COLOR,
    ) -> Optional[int]:
        """
        Create a node and (optionally) its edge to ``parent_id``.

        Values are validated/normalised here so a programmatic caller cannot
        store an empty name or an invalid colour even if it bypasses the dialog.
        """
        clean_name = self._validate_name(name)
        node_id = self.library.create_node(
            clean_name,
            parent_id=parent_id,
            icon=normalize_icon(icon),
            style_bold=bool(style_bold),
            style_color=normalize_color(style_color),
        )
        log_info(
            f"Created node {node_id} ({clean_name!r})"
            + (f" under parent {parent_id}" if parent_id is not None else " as a root")
        )
        return node_id

    def update_node(
        self,
        node_id: int,
        *,
        name: Optional[str] = None,
        icon: object = None,
        style_bold: Optional[bool] = None,
        style_color: Optional[str] = None,
    ) -> bool:
        """
        Update the editable properties of a node.

        ``None`` means "leave unchanged"; pass an empty string to clear the
        icon. Returns True when at least one field was written.
        """
        changes: Dict[str, object] = {}
        if name is not None:
            changes["name"] = self._validate_name(name)
        if icon is not None:
            changes["icon"] = normalize_icon(icon)
        if style_bold is not None:
            changes["style_bold"] = bool(style_bold)
        if style_color is not None:
            changes["style_color"] = normalize_color(style_color)

        if not changes:
            return False

        if self.library.get_node(node_id) is None:
            raise ValueError(f"节点 {node_id} 不存在。")

        self.library.update_node(node_id, **changes)
        log_info(f"Updated node {node_id}: {sorted(changes)}")
        return True

    # --------------------------------------------------------------------------
    # PDF management (Phase 4)
    # --------------------------------------------------------------------------
    def list_pdfs(self, node_id: int) -> List[str]:
        """Stored PDF references of a node, in display order."""
        return self.library.get_pdf_list(node_id)

    def describe_pdfs(self, node_id: int) -> List[path_manager.PdfFile]:
        """Resolve a node's PDF references against the current application root."""
        return path_manager.describe_pdfs(self.library.get_pdf_list(node_id))

    def add_pdfs(
        self,
        node_id: int,
        file_paths: List[object],
        *,
        copy_to_books: bool = False,
    ) -> PdfAddResult:
        """
        Add user-picked PDF files to a node.

        Each source is converted by ``path_manager.make_stored_path`` (relative
        when inside the application root, absolute otherwise, or copied into
        ``books/``). Conversion failures are reported per file and do not roll
        back the files that were added successfully.
        """
        self._require_node(node_id)

        converted: List[Tuple[str, str]] = []
        errors: List[Tuple[str, str]] = []
        for raw in file_paths or ():
            source = "" if raw is None else str(raw).strip()
            if not source:
                continue
            try:
                stored = path_manager.make_stored_path(
                    source,
                    copy_to_books=copy_to_books,
                )
            except (OSError, ValueError) as error:
                log_warning(f"Could not add PDF {source!r}: {error}")
                errors.append((source, str(error)))
            else:
                converted.append((source, stored))

        added = self.library.add_pdfs(node_id, [stored for _, stored in converted])
        added_set = set(added)
        skipped = [source for source, stored in converted if stored not in added_set]

        if added:
            log_info(
                f"Node {node_id}: added {len(added)} PDF(s), "
                f"skipped {len(skipped)} duplicate(s), {len(errors)} error(s)."
            )
        return PdfAddResult(added=added, skipped=skipped, errors=errors)

    def remove_pdfs(self, node_id: int, stored_paths: List[object]) -> int:
        """Detach PDF references from a node (never deletes files on disk)."""
        self._require_node(node_id)
        cleaned = [
            path_manager.normalize_stored_path(path)
            for path in stored_paths or ()
            if path_manager.normalize_stored_path(path)
        ]
        return self.library.remove_pdfs(node_id, cleaned)

    def relink_pdf(
        self,
        node_id: int,
        stored_path: object,
        new_source: object,
        *,
        copy_to_books: bool = False,
    ) -> str:
        """
        Point an existing PDF reference at a new file, keeping its list position.

        Raises ``ValueError`` when the old reference is not attached, the new
        file is invalid, or the new file is already attached elsewhere on the
        same node. Returns the newly stored path.
        """
        self._require_node(node_id)
        old = path_manager.normalize_stored_path(stored_path)
        if not old:
            raise ValueError("请选择要重新定位的 PDF。")

        existing = self.library.get_pdf_list(node_id)
        old_key = path_manager.pdf_path_key(old)
        if old_key not in {path_manager.pdf_path_key(path) for path in existing}:
            raise ValueError("该 PDF 不在当前节点中。")

        new_stored = path_manager.make_stored_path(
            new_source,
            copy_to_books=copy_to_books,
        )
        new_key = path_manager.pdf_path_key(new_stored)
        if new_key != old_key:
            for path in existing:
                if path_manager.pdf_path_key(path) == new_key:
                    raise ValueError("该文件已经关联到当前节点。")

        changed = self.library.relink_pdf(node_id, old, new_stored)
        if changed:
            log_info(f"Node {node_id}: re-linked PDF reference {old!r} -> {new_stored!r}.")
        else:
            # Same file (e.g. only the spelling changed): nothing was written.
            log_debug(
                f"Node {node_id}: PDF reference {old!r} already resolved to "
                f"{new_stored!r}; no change written."
            )
        return new_stored

    def open_pdf(self, stored_path: object) -> bool:
        """Open one PDF; raises :class:`PdfLaunchError` on failure."""
        pdf_file = path_manager.describe_pdf(stored_path)
        if not pdf_file.exists:
            raise PdfLaunchError(
                f"PDF 文件不存在：{pdf_file.stored_path or '(空路径)'}"
                "\n可使用「管理 PDF…」重新定位文件。"
            )

        self.launcher.launch(pdf_file.absolute_path)
        log_info(f"Opened PDF: {pdf_file.stored_path!r}")
        return True

    def open_pdfs(self, stored_paths: List[object]) -> LaunchReport:
        """Open several PDFs, collecting per-file failures for the UI."""
        report = LaunchReport()
        for raw in stored_paths or ():
            pdf_file = path_manager.describe_pdf(raw)
            label = pdf_file.stored_path or str(raw)
            if not pdf_file.exists:
                report.failures.append((label, f"PDF 文件不存在：{label}"))
                continue
            try:
                self.launcher.launch(pdf_file.absolute_path)
            except PdfLaunchError as error:
                report.failures.append((label, str(error)))
            else:
                report.opened.append(label)
        return report

    def open_node_pdfs(self, node_id: int) -> LaunchReport:
        """Open every PDF attached to a node."""
        return self.open_pdfs(self.list_pdfs(node_id))

    def inspect_pdfs(self) -> PdfInspection:
        """Check every PDF reference in the library for missing files."""
        nodes_with_pdfs = 0
        total_pdfs = 0
        missing: List[MissingPdf] = []

        for node in self.library.get_all_nodes():
            if node.id is None or not node.pdf_paths:
                continue
            nodes_with_pdfs += 1
            total_pdfs += len(node.pdf_paths)
            for pdf_file in path_manager.describe_pdfs(node.pdf_paths):
                if pdf_file.exists:
                    continue
                missing.append(
                    MissingPdf(
                        node_id=node.id,
                        node_name=node.name,
                        stored_path=pdf_file.stored_path,
                        absolute_path=pdf_file.absolute_path,
                    )
                )

        if missing:
            log_warning(
                f"File check found {len(missing)} missing PDF(s) across "
                f"{len({entry.node_id for entry in missing})} node(s)."
            )
        return PdfInspection(
            nodes_with_pdfs=nodes_with_pdfs,
            total_pdfs=total_pdfs,
            missing=missing,
        )

    def find_missing_pdfs(self) -> List[MissingPdf]:
        """Missing PDF references only (used by the re-location dialog)."""
        return self.inspect_pdfs().missing

    # --------------------------------------------------------------------------
    # Search (Phase 7)
    # --------------------------------------------------------------------------
    def search_library(
        self,
        query: object,
        *,
        limit: Optional[int] = None,
    ) -> SearchResult:
        """
        Search node names and PDF references.

        Returns one hit per matching node with every root-to-node position, so
        the UI can show all locations of a multi-parent node (plan.md §28).
        """
        result = self.search_service.search(query, limit=limit)
        if result.query:
            log_debug(
                f"Search {result.query!r}: {result.hit_count} node(s), "
                f"{result.location_count} location(s)"
                + (" (truncated)." if result.truncated else ".")
            )
        return result

    # --------------------------------------------------------------------------
    # Batch relocation (Phase 7)
    # --------------------------------------------------------------------------
    def plan_missing_relocation(
        self,
        search_root: object,
        *,
        entries: Optional[List[MissingPdf]] = None,
        recursive: bool = True,
    ) -> RelinkPlan:
        """
        Preview which missing PDFs a folder can satisfy, without changing data.

        ``entries`` defaults to every missing reference in the library, so the
        dialog can batch-fix the whole collection or only the selected rows.
        """
        entries_list = list(entries) if entries is not None else self.find_missing_pdfs()
        requests = [
            RelinkRequest(node_id=entry.node_id, stored_path=entry.stored_path)
            for entry in entries_list
        ]
        return plan_batch_relink(requests, search_root, recursive=recursive)

    def relink_missing_from_folder(
        self,
        search_root: object,
        *,
        entries: Optional[List[MissingPdf]] = None,
        recursive: bool = True,
        copy_to_books: bool = False,
    ) -> BatchRelinkOutcome:
        """
        Match missing PDFs by file name against a folder and re-link the matches.

        Unmatched/ambiguous entries are reported instead of guessed, and a
        failure on one file never aborts the remaining batch. Only database
        references change; disk files are untouched (plan.md §40).
        """
        entries_list = list(entries) if entries is not None else self.find_missing_pdfs()
        plan = self.plan_missing_relocation(
            search_root,
            entries=entries_list,
            recursive=recursive,
        )

        relinked = 0
        ambiguous: List[MissingPdf] = []
        not_found: List[MissingPdf] = []
        errors: List[Tuple[MissingPdf, str]] = []

        for entry, decision in zip(entries_list, plan.decisions):
            if not decision.matched:
                if decision.status == constants.RELINK_STATUS_AMBIGUOUS:
                    ambiguous.append(entry)
                else:
                    not_found.append(entry)
                continue

            try:
                self.relink_pdf(
                    entry.node_id,
                    entry.stored_path,
                    decision.new_path,
                    copy_to_books=copy_to_books,
                )
            except (ValueError, OSError, sqlite3.Error) as error:
                log_error(
                    f"Batch relocation could not re-link {entry.stored_path!r} "
                    f"for node {entry.node_id}: {error}"
                )
                errors.append((entry, str(error)))
            except Exception as error:  # defensive: keep the batch moving
                log_error(
                    f"Unexpected batch relocation failure for {entry.stored_path!r}: {error}"
                )
                errors.append((entry, f"未预期的错误：{error}"))
            else:
                relinked += 1

        outcome = BatchRelinkOutcome(
            search_root=plan.search_root,
            requested=len(entries_list),
            relinked=relinked,
            ambiguous=ambiguous,
            not_found=not_found,
            errors=errors,
        )
        log_info(
            f"Batch relocation from {plan.search_root}: "
            f"{relinked}/{len(entries_list)} re-linked, "
            f"{len(ambiguous)} ambiguous, {len(not_found)} not found, "
            f"{len(errors)} error(s)."
        )
        return outcome

    # --------------------------------------------------------------------------
    # PDF reader settings
    # --------------------------------------------------------------------------
    def get_pdf_reader_path(self) -> str:
        """
        Configured reader executable, or ``""`` for the system default.

        A relative value (possible only via a hand-edited config) is resolved
        against the application root, so launching does not depend on the
        process working directory.
        """
        raw = self.config.get_pdf_reader_path()
        if not raw:
            return ""
        candidate = Path(raw).expanduser()
        if candidate.is_absolute():
            return str(candidate)
        return str(path_manager.normalize_path(candidate))

    def get_pdf_reader_label(self) -> str:
        """Human-readable reader description for menus and status messages."""
        return self.get_pdf_reader_path() or "系统默认阅读器"

    def set_pdf_reader_path(self, reader_path: object) -> str:
        """
        Persist the PDF reader choice (empty string restores the system default).

        A non-empty value must point at an existing file; passing a bare command
        name is intentionally rejected so typos surface immediately.
        """
        raw = "" if reader_path is None else str(reader_path).strip()
        if raw:
            candidate = Path(raw).expanduser()
            if not candidate.is_absolute():
                candidate = path_manager.normalize_path(candidate)
            if not candidate.is_file():
                raise ValueError(f"PDF 阅读器不存在：{raw}")
            raw = str(candidate)

        self.config.set_pdf_reader_path(raw)
        self.launcher.set_reader_path(raw, self.config.get_pdf_reader_args())
        log_info(f"PDF reader set to: {raw or 'system default'}")
        return raw

    # --------------------------------------------------------------------------
    # Library import / export (Phase 6)
    # --------------------------------------------------------------------------
    def export_library(
        self,
        export_dir: object,
        *,
        copy_pdfs: bool = False,
        overwrite: bool = True,
    ) -> ExportResult:
        """
        Export the whole library to ``export_dir`` as ``library.json``.

        The view only chooses the directory and the copy policy; the actual
        document layout and path rebasing live in :mod:`services.exporter`.
        """
        raw = "" if export_dir is None else str(export_dir).strip()
        if not raw:
            raise ValueError("请选择导出目录。")
        result = export_library_file(
            self.library,
            Path(raw).expanduser(),
            copy_pdfs=bool(copy_pdfs),
            overwrite=bool(overwrite),
        )
        log_info(
            f"Library exported to {result.json_path}: "
            f"{result.node_count} node(s), {result.edge_count} edge(s)."
        )
        return result

    def import_library(
        self,
        json_path: object,
        *,
        mode: str = constants.IMPORT_MODE_MERGE,
    ) -> ImportResult:
        """
        Import a ``library.json`` file into the current library.

        ``mode`` is ``"merge"`` (append) or ``"replace"`` (clear first). The
        whole import is one transaction; on any error the previous library is
        preserved.
        """
        if mode not in constants.IMPORT_MODES:
            raise ValueError(
                f"未知的导入方式：{mode!r}（可用：{'、'.join(constants.IMPORT_MODES)}）。"
            )
        raw = "" if json_path is None else str(json_path).strip()
        if not raw:
            raise ValueError("请选择要导入的图书馆文件。")
        result = import_library_file(
            self.library,
            Path(raw).expanduser(),
            mode=mode,
        )
        log_info(
            f"Library imported from {result.json_path}: "
            f"{result.node_count} node(s), {result.edge_count} edge(s), "
            f"mode {result.mode}."
        )
        return result

    def get_library_counts(self) -> Tuple[int, int]:
        """``(node_count, edge_count)`` for menus and import-mode prompts."""
        return len(self.library.get_all_nodes()), len(self.library.get_all_edges())

    def _require_node(self, node_id: int) -> Node:
        node = self.library.get_node(node_id)
        if node is None:
            log_error(f"Node {node_id} does not exist.")
            raise ValueError(f"节点 {node_id} 不存在。")
        return node

    def shutdown(self) -> None:
        """Release resources before the application exits."""
        log_info("Application controller shut down.")
