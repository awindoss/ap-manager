# ==============================================================================
# views/dialogs/search_dialog.py
# Stand-alone search window (Phase 7, stage.md 7.2).
#
# The main window also hosts an inline search box and a result dock; this dialog
# is the keyboard/window-menu entry point ("查看 > 搜索…", Ctrl+Shift+F). It
# reuses the same result widget so both entry points behave identically.
# ==============================================================================
from typing import Optional, Sequence, Tuple

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QLineEdit,
    QMessageBox,
    QVBoxLayout,
    QWidget,
)

from services.search import SearchResult
from utils import constants
from utils.error_messages import describe_error
from utils.logger import log_exception
from views.search_panel import SearchResultsPanel


class SearchDialog(QDialog):
    """Search the library from a dedicated dialog."""

    def __init__(
        self,
        controller,
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self._controller = controller
        self.selected_path: Optional[Tuple[int, ...]] = None
        self.selected_node_id: Optional[int] = None

        self.setWindowTitle("搜索书库")
        self.setModal(True)
        self.resize(680, 480)

        layout = QVBoxLayout(self)

        self.search_box = QLineEdit(self)
        self.search_box.setObjectName("searchDialogInput")
        self.search_box.setPlaceholderText("搜索节点名称或 PDF 文件名…")
        self.search_box.setClearButtonEnabled(True)
        self.search_box.textChanged.connect(self._on_text_changed)
        self.search_box.returnPressed.connect(self.run_search)
        layout.addWidget(self.search_box)

        self.results_panel = SearchResultsPanel(self)
        self.results_panel.locationActivated.connect(self._on_location_activated)
        self.results_panel.nodeActivated.connect(self._on_node_activated)
        layout.addWidget(self.results_panel, 1)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close, self)
        buttons.button(QDialogButtonBox.StandardButton.Close).setText("关闭")
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(constants.SEARCH_DEBOUNCE_MS)
        self._timer.timeout.connect(self.run_search)

        self.results_panel.clear()

    # --------------------------------------------------------------------------
    # Search
    # --------------------------------------------------------------------------
    def set_query(self, query: str) -> None:
        """Set the query and run it immediately (tests/command-line entry)."""
        self.search_box.setText(query or "")
        self.run_search()

    def run_search(self) -> Optional[SearchResult]:
        """Execute the current query; keeps the last result for tooling/tests."""
        self._timer.stop()
        query = self.search_box.text().strip()
        if not query:
            self.results_panel.clear()
            return None
        try:
            result = self._controller.search_library(query)
        except Exception as error:  # pragma: no cover - defensive
            log_exception(f"Search dialog failed for query {query!r}", error)
            QMessageBox.warning(self, "无法搜索", describe_error(error))
            return None
        self.results_panel.show_result(result)
        return result

    def _on_text_changed(self, _text: str) -> None:
        self._timer.start()

    # --------------------------------------------------------------------------
    # Activation
    # --------------------------------------------------------------------------
    def _on_location_activated(self, path: Sequence[int]) -> None:
        self.selected_path = tuple(int(part) for part in path)
        self.accept()

    def _on_node_activated(self, node_id: int) -> None:
        self.selected_node_id = int(node_id)
        self.accept()

    # --------------------------------------------------------------------------
    # Qt events
    # --------------------------------------------------------------------------
    def showEvent(self, event) -> None:  # noqa: N802 - Qt naming
        super().showEvent(event)
        self.search_box.setFocus(Qt.FocusReason.ShortcutFocusReason)
        self.search_box.selectAll()


# ==============================================================================
# End of search_dialog.py
# ==============================================================================
