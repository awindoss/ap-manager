# ==============================================================================
# views/dialogs/pdf_management_dialog.py
# Manage the PDF references of one node (stage.md 4.4):
# add several files, remove references, re-locate missing files, open files.
#
# The dialog applies changes immediately through the controller, so the list,
# the database and the tree never disagree; "关闭" only closes the window.
# ==============================================================================
from pathlib import Path
import sqlite3
from typing import TYPE_CHECKING, Iterable, List, Optional

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from services.path_manager import PdfFile
from services.pdf_launcher import LaunchReport
from utils import constants
from utils.logger import log_info

if TYPE_CHECKING:  # pragma: no cover - type checking only
    from controllers.app_controller import AppController


class PdfManagementDialog(QDialog):
    """List and edit ``nodes.pdf_paths`` for a single node."""

    def __init__(
        self,
        controller: "AppController",
        node_id: int,
        parent: Optional[QWidget] = None,
        *,
        select_path: Optional[str] = None,
    ) -> None:
        super().__init__(parent)
        self._controller = controller
        self._node_id = node_id
        self._pdf_files: List[PdfFile] = []

        node = controller.get_node(node_id)
        if node is None:
            raise ValueError(f"节点 {node_id} 不存在。")
        self._node_name = node.name

        self.setWindowTitle(f"管理 PDF — {self._node_name}")
        self.setModal(True)
        self._build_ui()
        self.reload(select_paths=[select_path] if select_path else None)

    # --------------------------------------------------------------------------
    # Construction
    # --------------------------------------------------------------------------
    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)

        self.header_label = QLabel("", self)
        self.header_label.setObjectName("pdfHeader")
        layout.addWidget(self.header_label)

        self.list_widget = QListWidget(self)
        self.list_widget.setObjectName("pdfList")
        self.list_widget.setSelectionMode(QListWidget.SelectionMode.ExtendedSelection)
        self.list_widget.itemSelectionChanged.connect(self._update_button_states)
        self.list_widget.itemDoubleClicked.connect(lambda _item: self.open_selected())
        layout.addWidget(self.list_widget)

        add_row = QHBoxLayout()
        self.add_button = QPushButton("添加文件…", self)
        self.add_button.setObjectName("addPdfButton")
        self.add_button.setToolTip("选择一个或多个 PDF 文件")
        self.add_button.clicked.connect(self.add_files)
        add_row.addWidget(self.add_button)

        self.copy_check = QCheckBox("复制到 books/ 目录", self)
        self.copy_check.setObjectName("copyToBooksCheck")
        self.copy_check.setToolTip(
            "勾选后，添加的文件会复制到应用的 books/ 目录，并以相对路径入库，便于整体迁移。"
        )
        add_row.addWidget(self.copy_check)
        add_row.addStretch(1)
        layout.addLayout(add_row)

        action_row = QHBoxLayout()
        self.remove_button = QPushButton("移除选中", self)
        self.remove_button.setObjectName("removePdfButton")
        self.remove_button.clicked.connect(self.remove_selected)
        action_row.addWidget(self.remove_button)

        self.relink_button = QPushButton("重新定位…", self)
        self.relink_button.setObjectName("relinkPdfButton")
        self.relink_button.setToolTip("为选中的 PDF 引用指定新的文件位置")
        self.relink_button.clicked.connect(self.relink_selected)
        action_row.addWidget(self.relink_button)

        self.open_button = QPushButton("打开选中", self)
        self.open_button.setObjectName("openPdfButton")
        self.open_button.clicked.connect(self.open_selected)
        action_row.addWidget(self.open_button)

        self.open_all_button = QPushButton("打开全部", self)
        self.open_all_button.setObjectName("openAllPdfButton")
        self.open_all_button.clicked.connect(self.open_all)
        action_row.addWidget(self.open_all_button)
        action_row.addStretch(1)
        layout.addLayout(action_row)

        self.status_label = QLabel("", self)
        self.status_label.setObjectName("pdfStatus")
        self.status_label.setWordWrap(True)
        layout.addWidget(self.status_label)

        self.buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Close,
            self,
        )
        self.close_button = self.buttons.button(QDialogButtonBox.StandardButton.Close)
        self.close_button.setText("关闭")
        self.close_button.setObjectName("closePdfButton")
        self.buttons.rejected.connect(self.accept)
        layout.addWidget(self.buttons)

        self.resize(680, 460)

    # --------------------------------------------------------------------------
    # Data / presentation
    # --------------------------------------------------------------------------
    def reload(self, select_paths: Optional[Iterable[str]] = None) -> None:
        """Rebuild the list from the database, keeping the selection when possible."""
        keep = list(select_paths) if select_paths is not None else self._selected_stored_paths()
        self._pdf_files = self._controller.describe_pdfs(self._node_id)

        self.list_widget.blockSignals(True)
        self.list_widget.clear()
        for pdf_file in self._pdf_files:
            item = QListWidgetItem(self._label_for(pdf_file))
            item.setData(Qt.ItemDataRole.UserRole, pdf_file.stored_path)
            item.setToolTip(self._tooltip_for(pdf_file))
            if pdf_file.missing:
                item.setForeground(QColor("#D32F2F"))
            self.list_widget.addItem(item)
        self.list_widget.blockSignals(False)

        missing_count = sum(1 for pdf_file in self._pdf_files if pdf_file.missing)
        header = f"节点「{self._node_name}」— {len(self._pdf_files)} 个 PDF"
        if missing_count:
            header += f"（{missing_count} 个缺失）"
        self.header_label.setText(header)

        self._restore_selection(keep)
        self._update_button_states()

    def _restore_selection(self, stored_paths: Iterable[str]) -> None:
        wanted = {str(path) for path in stored_paths}
        for row in range(self.list_widget.count()):
            item = self.list_widget.item(row)
            if item.data(Qt.ItemDataRole.UserRole) in wanted:
                item.setSelected(True)
        if not self.list_widget.selectedItems() and self.list_widget.count() > 0:
            self.list_widget.setCurrentRow(0)

    def selected_files(self) -> List[PdfFile]:
        """PDFs currently selected in the list (multi-selection aware)."""
        selected: List[PdfFile] = []
        for item in self.list_widget.selectedItems():
            stored = item.data(Qt.ItemDataRole.UserRole)
            for pdf_file in self._pdf_files:
                if pdf_file.stored_path == stored:
                    selected.append(pdf_file)
                    break
        return selected

    def _selected_stored_paths(self) -> List[str]:
        return [pdf_file.stored_path for pdf_file in self.selected_files()]

    def _update_button_states(self) -> None:
        selected = self.selected_files()
        has_selection = bool(selected)
        self.remove_button.setEnabled(has_selection)
        self.open_button.setEnabled(has_selection)
        self.relink_button.setEnabled(len(selected) == 1)
        self.open_all_button.setEnabled(bool(self._pdf_files))

    def _set_status(self, message: str) -> None:
        self.status_label.setText(message)
        log_info(message)

    # --------------------------------------------------------------------------
    # Actions
    # --------------------------------------------------------------------------
    def add_files(self) -> None:
        paths, _selected_filter = QFileDialog.getOpenFileNames(
            self,
            "添加 PDF 文件",
            "",
            constants.PDF_FILE_FILTER,
        )
        if not paths:
            return

        try:
            result = self._controller.add_pdfs(
                self._node_id,
                list(paths),
                copy_to_books=self.copy_check.isChecked(),
            )
        except (ValueError, OSError, sqlite3.Error) as error:
            QMessageBox.warning(self, "无法添加 PDF", str(error))
            return

        self.reload(select_paths=result.added)
        parts: List[str] = []
        if result.added:
            parts.append(f"已添加 {len(result.added)} 个 PDF。")
        if result.skipped:
            parts.append(f"跳过 {len(result.skipped)} 个已关联的文件。")
        if result.errors:
            parts.append(f"{len(result.errors)} 个文件添加失败。")
        self._set_status(" ".join(parts))

        if result.errors:
            details = "\n".join(
                f"• {source}\n  {message}" for source, message in result.errors[:5]
            )
            QMessageBox.warning(
                self,
                "部分文件未能添加",
                f"{len(result.errors)} 个文件无法添加：\n\n{details}",
            )

    def remove_selected(self) -> None:
        selected = self.selected_files()
        if not selected:
            self._set_status("请先选择要移除的 PDF。")
            return

        answer = QMessageBox.question(
            self,
            "移除 PDF",
            f"确定从节点中移除 {len(selected)} 个 PDF 引用？\n\n"
            "只移除分类引用，不会删除磁盘上的 PDF 文件。",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return

        try:
            removed = self._controller.remove_pdfs(
                self._node_id,
                [pdf_file.stored_path for pdf_file in selected],
            )
        except (ValueError, OSError, sqlite3.Error) as error:
            QMessageBox.warning(self, "无法移除 PDF", str(error))
            return
        self.reload(select_paths=None)
        self._set_status(f"已从节点移除 {removed} 个 PDF 引用。")

    def relink_selected(self) -> None:
        selected = self.selected_files()
        if len(selected) != 1:
            self._set_status("请选择一个需要重新定位的 PDF。")
            return

        pdf_file = selected[0]
        start_directory = (
            str(Path(pdf_file.absolute_path).parent)
            if pdf_file.absolute_path is not None
            else ""
        )
        new_path, _selected_filter = QFileDialog.getOpenFileName(
            self,
            "重新定位 PDF",
            start_directory,
            constants.PDF_FILE_FILTER,
        )
        if not new_path:
            return

        try:
            stored = self._controller.relink_pdf(
                self._node_id,
                pdf_file.stored_path,
                new_path,
                copy_to_books=self.copy_check.isChecked(),
            )
        except (ValueError, OSError, sqlite3.Error) as error:
            QMessageBox.warning(self, "无法重新定位 PDF", str(error))
            return

        self.reload(select_paths=[stored])
        self._set_status(f"已更新 PDF 位置：{stored}")

    def open_selected(self) -> None:
        selected = self.selected_files()
        if not selected:
            self._set_status("请先选择要打开的 PDF。")
            return
        try:
            report = self._controller.open_pdfs(
                [pdf_file.stored_path for pdf_file in selected]
            )
        except (ValueError, OSError, sqlite3.Error) as error:
            QMessageBox.warning(self, "无法打开 PDF", str(error))
            return
        self._report_launch(report)

    def open_all(self) -> None:
        if not self._pdf_files:
            self._set_status("当前节点没有 PDF。")
            return
        try:
            report = self._controller.open_node_pdfs(self._node_id)
        except (ValueError, OSError, sqlite3.Error) as error:
            QMessageBox.warning(self, "无法打开 PDF", str(error))
            return
        self._report_launch(report)

    def _report_launch(self, report: LaunchReport) -> None:
        if report.failures:
            details = "\n".join(
                f"• {path}\n  {message}" for path, message in report.failures[:5]
            )
            if len(report.failures) > 5:
                details += "\n…"
            prefix = (
                f"已打开 {report.opened_count} 个 PDF，"
                if report.opened_count
                else ""
            )
            QMessageBox.warning(
                self,
                "部分 PDF 未能打开",
                f"{prefix}{report.failure_count} 个 PDF 无法打开：\n\n{details}",
            )
            return
        self._set_status(f"已打开 {report.opened_count} 个 PDF。")

    # --------------------------------------------------------------------------
    # Presentation helpers
    # --------------------------------------------------------------------------
    @staticmethod
    def _label_for(pdf_file: PdfFile) -> str:
        prefix = constants.WARNING_ICON_MISSING_FILE + " " if pdf_file.missing else ""
        suffix = "（缺失）" if pdf_file.missing else ""
        return f"{prefix}{pdf_file.file_name}{suffix}"

    @staticmethod
    def _tooltip_for(pdf_file: PdfFile) -> str:
        lines = [f"名称：{pdf_file.file_name}", f"存储路径：{pdf_file.stored_path}"]
        lines.append(f"实际路径：{pdf_file.display_path}")
        lines.append("状态：文件不存在" if pdf_file.missing else "状态：正常")
        return "\n".join(lines)


# ==============================================================================
# End of pdf_management_dialog.py
# ==============================================================================
