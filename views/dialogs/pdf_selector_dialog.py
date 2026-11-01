# ==============================================================================
# views/dialogs/pdf_selector_dialog.py
# Pick which PDF to open when a node carries several files (plan.md §19.1).
# ==============================================================================
from typing import List, Optional

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QVBoxLayout,
    QWidget,
)

from services.path_manager import PdfFile
from utils import constants


class PdfSelectorDialog(QDialog):
    """
    Single-choice PDF picker.

    Entries whose file is missing are still listed (so the user understands why
    the node cannot be opened) but are not selectable for opening; they are
    drawn in red and get a warning prefix.
    """

    def __init__(
        self,
        node_name: str,
        pdf_files: List[PdfFile],
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self._pdf_files: List[PdfFile] = list(pdf_files)
        self.setWindowTitle(f"打开 PDF — {node_name}")
        self.setModal(True)
        self._build_ui()
        self._populate()
        self._update_open_button()

    # --------------------------------------------------------------------------
    # Construction
    # --------------------------------------------------------------------------
    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("该节点包含多个 PDF，请选择要打开的文件：", self))

        self.list_widget = QListWidget(self)
        self.list_widget.setObjectName("pdfSelectorList")
        self.list_widget.setSelectionMode(QListWidget.SelectionMode.SingleSelection)
        self.list_widget.currentItemChanged.connect(lambda *_: self._update_open_button())
        self.list_widget.itemDoubleClicked.connect(self._on_item_double_clicked)
        layout.addWidget(self.list_widget)

        self.buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel,
            self,
        )
        self.open_button = self.buttons.button(QDialogButtonBox.StandardButton.Ok)
        self.open_button.setText("打开")
        self.buttons.button(QDialogButtonBox.StandardButton.Cancel).setText("取消")
        self.buttons.accepted.connect(self._on_accept)
        self.buttons.rejected.connect(self.reject)
        layout.addWidget(self.buttons)

        self.resize(520, 320)

    def _populate(self) -> None:
        first_existing: Optional[QListWidgetItem] = None
        for pdf_file in self._pdf_files:
            item = QListWidgetItem(self._label_for(pdf_file))
            item.setData(Qt.ItemDataRole.UserRole, pdf_file.stored_path)
            item.setToolTip(self._tooltip_for(pdf_file))
            if pdf_file.missing:
                item.setForeground(QColor("#D32F2F"))
            elif first_existing is None:
                first_existing = item
            self.list_widget.addItem(item)

        if first_existing is not None:
            self.list_widget.setCurrentItem(first_existing)
        elif self.list_widget.count() > 0:
            self.list_widget.setCurrentRow(0)

    # --------------------------------------------------------------------------
    # Accessors
    # --------------------------------------------------------------------------
    def selected_pdf(self) -> Optional[PdfFile]:
        """The highlighted PDF, or None when nothing is selected."""
        item = self.list_widget.currentItem()
        if item is None:
            return None
        stored = item.data(Qt.ItemDataRole.UserRole)
        for pdf_file in self._pdf_files:
            if pdf_file.stored_path == stored:
                return pdf_file
        return None

    # --------------------------------------------------------------------------
    # Actions
    # --------------------------------------------------------------------------
    def _on_accept(self) -> None:
        pdf_file = self.selected_pdf()
        if pdf_file is None:
            return
        if pdf_file.missing:
            QMessageBox.warning(
                self,
                "文件不存在",
                f"找不到该 PDF：\n{pdf_file.stored_path}\n\n"
                "请使用「管理 PDF…」重新定位文件。",
            )
            return
        self.accept()

    def _on_item_double_clicked(self, item: QListWidgetItem) -> None:
        self.list_widget.setCurrentItem(item)
        self._on_accept()

    def _update_open_button(self) -> None:
        pdf_file = self.selected_pdf()
        self.open_button.setEnabled(pdf_file is not None and pdf_file.exists)

    # --------------------------------------------------------------------------
    # Presentation
    # --------------------------------------------------------------------------
    @staticmethod
    def _label_for(pdf_file: PdfFile) -> str:
        prefix = constants.WARNING_ICON_MISSING_FILE + " " if pdf_file.missing else ""
        suffix = "（缺失）" if pdf_file.missing else ""
        return f"{prefix}{pdf_file.file_name}{suffix}"

    @staticmethod
    def _tooltip_for(pdf_file: PdfFile) -> str:
        lines = [f"存储路径：{pdf_file.stored_path}", f"实际路径：{pdf_file.display_path}"]
        if pdf_file.missing:
            lines.append("状态：文件不存在")
        return "\n".join(lines)


# ==============================================================================
# End of pdf_selector_dialog.py
# ==============================================================================
