# ==============================================================================
# controllers/app_controller.py
# Thin controller between the Qt views and the library business layer.
#
# plan.md section 27 fixes the call direction: View -> Controller -> Library ->
# Database. The controller therefore owns the LibraryService (and, through it,
# the Database) and exposes the few operations the views need. As later phases
# add editing, PDF opening and import/export, those entry points belong here.
# ==============================================================================
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union

from models.library import LibraryService
from models.node import Node, normalize_color, normalize_icon
from services import path_manager
from services.pdf_launcher import LaunchReport, PdfLaunchError, PdfLauncher
from utils import constants
from utils.config_manager import ConfigManager
from utils.logger import log_error, log_info, log_warning


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

        self.library.relink_pdf(node_id, old, new_stored)
        log_info(f"Node {node_id}: re-linked PDF reference {old!r} -> {new_stored!r}.")
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

    def _require_node(self, node_id: int) -> Node:
        node = self.library.get_node(node_id)
        if node is None:
            log_error(f"Node {node_id} does not exist.")
            raise ValueError(f"节点 {node_id} 不存在。")
        return node

    def shutdown(self) -> None:
        """Release resources before the application exits."""
        log_info("Application controller shut down.")
