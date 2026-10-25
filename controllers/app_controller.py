# ==============================================================================
# controllers/app_controller.py
# Thin controller between the Qt views and the library business layer.
#
# plan.md section 27 fixes the call direction: View -> Controller -> Library ->
# Database. The controller therefore owns the LibraryService (and, through it,
# the Database) and exposes the few operations the views need. As later phases
# add editing, PDF opening and import/export, those entry points belong here.
# ==============================================================================
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

from models.library import LibraryService
from models.node import Node, normalize_color, normalize_icon
from utils import constants
from utils.logger import log_info, log_warning


class AppController:
    """Coordinates the main window with `LibraryService`."""

    def __init__(
        self,
        library_service: Optional[LibraryService] = None,
        db_path: Optional[Union[str, Path]] = None,
    ) -> None:
        # `library_service` is injectable for tests; production code simply lets
        # LibraryService pick the configured database path.
        self.library: LibraryService = library_service or LibraryService(db_path=db_path)
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
    # Actions (stubs completed in later phases)
    # --------------------------------------------------------------------------
    def request_open_pdfs(self, node_id: int) -> bool:
        """
        Open the PDF(s) attached to a node.

        Phase 2 only needs the double-click decision; the actual launch is
        implemented in Phase 4 (`services/pdf_launcher.py` plus the PDF selector
        dialog). Returns False while the feature is unavailable.
        """
        node = self.library.get_node(node_id)
        if node is None:
            log_warning(f"PDF open requested for unknown node {node_id}.")
            return False

        log_info(
            f"PDF open requested for node {node_id} ({node.name!r}, "
            f"{len(node.pdf_paths)} file(s)); deferred to Phase 4."
        )
        return False

    def shutdown(self) -> None:
        """Release resources before the application exits."""
        log_info("Application controller shut down.")
