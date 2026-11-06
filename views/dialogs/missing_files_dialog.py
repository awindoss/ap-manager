# ==============================================================================
# views/dialogs/missing_files_dialog.py
# Library-wide list of missing PDF files with a per-entry re-location action
# (plan.md §22 / §34 "文件检查" and "重新定位缺失 PDF").
# ==============================================================================
from pathlib import Path
import sqlite3
from typing import TYPE_CHECKING, Callable, List, Optional

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from utils import constants
from utils.error_messages import describe_error
from utils.logger import log_info

if TYPE_CHECKING:  # pragma: no cover - type checking only
    from controllers.app_controller import AppController, MissingPdf

RevealCallback = Callable[[int, Optional[str]], None]


class MissingFilesDialog(QDialog):
    """
    Show every PDF reference whose file is gone and let the user re-point it.

    Re-linking changes only the stored path; the node keeps its position in the
    category graph (plan.md §22: never delete the reference automatically).
    """

    def __init__(
        self,
        controller: "AppController",
        parent: Optional[QWidget] = None,
        *,
        reveal_callback: Optional[RevealCallback] = None,
    ) -> None:
        super().__init__(parent)
        self._controller = controller
        self._reveal_callback = reveal_callback
        self._entries: List["MissingPdf"] = []
        self.changed = False

        self.setWindowTitle("重新定位缺失 PDF")
        self.setModal(True)
        self._build_ui()
        self.reload()

    # --------------------------------------------------------------------------
    # Construction
    # --------------------------------------------------------------------------
    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)

        self.header_label = QLabel("", self)
        self.header_label.setObjectName("missingHeader")
        self.header_label.setWordWrap(True)
        layout.addWidget(self.header_label)

        self.table = QTableWidget(0, 3, self)
        self.table.setObjectName("missingTable")
        self.table.setHorizontalHeaderLabels(["节点", "存储路径", "实际路径"])
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setSectionResizeMode(
            0, QHeaderView.ResizeMode.ResizeToContents
        )
        self.table.horizontalHeader().setSectionResizeMode(
            1, QHeaderView.ResizeMode.Stretch
        )
        self.table.horizontalHeader().setSectionResizeMode(
            2, QHeaderView.ResizeMode.Stretch
        )
        self.table.itemSelectionChanged.connect(self._update_button_states)
        layout.addWidget(self.table)

        action_row = QHBoxLayout()
        self.relink_button = QPushButton("重新定位…", self)
        self.relink_button.setObjectName("relinkMissingButton")
        self.relink_button.clicked.connect(self.relink_selected)
        action_row.addWidget(self.relink_button)

        self.batch_button = QPushButton("批量重新定位…", self)
        self.batch_button.setObjectName("batchRelinkButton")
        self.batch_button.setToolTip(
            "选择一个文件夹，按文件名自动匹配并重新定位选中的（或全部）缺失 PDF"
        )
        self.batch_button.clicked.connect(self.batch_relink_selected)
        action_row.addWidget(self.batch_button)

        self.reveal_button = QPushButton("定位节点", self)
        self.reveal_button.setObjectName("revealNodeButton")
        self.reveal_button.setToolTip("在主窗口中展开并管理该节点")
        self.reveal_button.clicked.connect(self.reveal_selected)
        action_row.addWidget(self.reveal_button)

        self.refresh_button = QPushButton("刷新", self)
        self.refresh_button.setObjectName("refreshMissingButton")
        self.refresh_button.clicked.connect(self.reload)
        action_row.addWidget(self.refresh_button)

        self.copy_check = QCheckBox("复制到 books/ 目录", self)
        self.copy_check.setObjectName("copyRelocatedCheck")
        self.copy_check.setToolTip("重新定位时把文件复制到应用的 books/ 目录")
        action_row.addWidget(self.copy_check)

        self.recursive_check = QCheckBox("包含子文件夹", self)
        self.recursive_check.setObjectName("recursiveRelinkCheck")
        self.recursive_check.setChecked(True)
        self.recursive_check.setToolTip("批量重新定位时在所选文件夹的子文件夹中查找")
        action_row.addWidget(self.recursive_check)
        action_row.addStretch(1)
        layout.addLayout(action_row)

        self.status_label = QLabel("", self)
        self.status_label.setObjectName("missingStatus")
        self.status_label.setWordWrap(True)
        layout.addWidget(self.status_label)

        self.buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Close,
            self,
        )
        self.buttons.button(QDialogButtonBox.StandardButton.Close).setText("关闭")
        self.buttons.rejected.connect(self.accept)
        layout.addWidget(self.buttons)

        self.resize(820, 420)

    # --------------------------------------------------------------------------
    # Data / presentation
    # --------------------------------------------------------------------------
    def reload(self) -> None:
        """Re-scan the library and rebuild the table."""
        self._entries = self._controller.find_missing_pdfs()
        self.table.setRowCount(len(self._entries))

        for row, entry in enumerate(self._entries):
            node_item = QTableWidgetItem(entry.node_name)
            node_item.setData(Qt.ItemDataRole.UserRole, entry.node_id)
            path_item = QTableWidgetItem(entry.stored_path)
            path_item.setToolTip(entry.stored_path)
            absolute_item = QTableWidgetItem(entry.display_path)
            absolute_item.setToolTip(entry.display_path)
            self.table.setItem(row, 0, node_item)
            self.table.setItem(row, 1, path_item)
            self.table.setItem(row, 2, absolute_item)

        if self._entries:
            node_count = len({entry.node_id for entry in self._entries})
            self.header_label.setText(
                f"共发现 {len(self._entries)} 个缺失 PDF，分布在 {node_count} 个节点中。\n"
                "可以逐条重新定位，也可以选择一个文件夹批量按文件名匹配；"
                "两种方式都只更新路径，不会改变节点在分类中的位置。"
            )
        else:
            self.header_label.setText("没有发现缺失的 PDF 文件。")

        self.status_label.setText("")
        self._update_button_states()
        log_info(f"Missing-files dialog loaded {len(self._entries)} entry/entries.")

    def selected_entries(self) -> List["MissingPdf"]:
        """Entries behind the selected rows."""
        rows = sorted({index.row() for index in self.table.selectionModel().selectedRows()})
        return [
            self._entries[row]
            for row in rows
            if 0 <= row < len(self._entries)
        ]

    def _update_button_states(self) -> None:
        selected = self.selected_entries()
        self.relink_button.setEnabled(len(selected) == 1)
        self.batch_button.setEnabled(bool(self._entries))
        self.reveal_button.setEnabled(bool(selected))

    # --------------------------------------------------------------------------
    # Actions
    # --------------------------------------------------------------------------
    def relink_selected(self) -> None:
        selected = self.selected_entries()
        if len(selected) != 1:
            self.status_label.setText("请选择一个需要重新定位的 PDF。")
            return

        entry = selected[0]
        start_directory = (
            str(Path(entry.absolute_path).parent)
            if entry.absolute_path is not None
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
                entry.node_id,
                entry.stored_path,
                new_path,
                copy_to_books=self.copy_check.isChecked(),
            )
        except (ValueError, OSError, sqlite3.Error) as error:
            QMessageBox.warning(self, "无法重新定位 PDF", describe_error(error))
            return

        self.changed = True
        self.reload()
        self.status_label.setText(f"已更新「{entry.node_name}」的 PDF 位置：{stored}")

    def batch_relink_selected(self) -> None:
        """
        Re-link several missing PDFs by scanning a folder for same-named files.

        Selected rows are used when there is a selection; otherwise the whole
        list is processed, which is the common case after moving a books folder.
        """
        entries = self.selected_entries() or list(self._entries)
        if not entries:
            self.status_label.setText("没有需要重新定位的 PDF。")
            return

        start_directory = ""
        for entry in entries:
            if entry.absolute_path is not None:
                candidate = Path(entry.absolute_path).parent
                if candidate.is_dir():
                    start_directory = str(candidate)
                    break

        folder = QFileDialog.getExistingDirectory(
            self,
            "选择包含 PDF 的文件夹",
            start_directory,
        )
        if not folder:
            return

        relink_missing = getattr(self._controller, "relink_missing_from_folder", None)
        if not callable(relink_missing):
            QMessageBox.warning(
                self,
                "无法批量重新定位",
                "当前控制器不支持批量重新定位，请逐条重新定位。",
            )
            return

        try:
            outcome = relink_missing(
                folder,
                entries=entries,
                recursive=self.recursive_check.isChecked(),
                copy_to_books=self.copy_check.isChecked(),
            )
        except (ValueError, OSError, sqlite3.Error) as error:
            QMessageBox.warning(
                self,
                "无法批量重新定位",
                describe_error(error),
            )
            return

        self.changed = self.changed or bool(getattr(outcome, "has_changes", False))
        self.reload()
        self._report_batch_outcome(outcome)

    def _report_batch_outcome(self, outcome) -> None:
        """Summarise a batch relocation in the status area and a message box."""
        requested = int(getattr(outcome, "requested", 0))
        relinked = int(getattr(outcome, "relinked", 0))
        ambiguous = list(getattr(outcome, "ambiguous", ()))
        not_found = list(getattr(outcome, "not_found", ()))
        errors = list(getattr(outcome, "errors", ()))

        summary = f"已重新定位 {relinked}/{requested} 个 PDF。"
        if ambiguous or not_found:
            summary += f" 仍有 {len(ambiguous) + len(not_found)} 个未能匹配。"
        if errors:
            summary += f" {len(errors)} 个写入失败。"
        self.status_label.setText(summary)

        if not ambiguous and not not_found and not errors:
            QMessageBox.information(self, "批量重新定位完成", summary)
            return

        lines = [summary]
        if ambiguous:
            lines.append("")
            lines.append(f"同名文件有多个（未修改，共 {len(ambiguous)} 个）：")
            for entry in ambiguous[:5]:
                lines.append(f"• {entry.node_name}：{Path(entry.stored_path).name}")
            if len(ambiguous) > 5:
                lines.append("…")
        if not_found:
            lines.append("")
            lines.append(f"没有找到同名文件（共 {len(not_found)} 个）：")
            for entry in not_found[:5]:
                lines.append(f"• {entry.node_name}：{Path(entry.stored_path).name}")
            if len(not_found) > 5:
                lines.append("…")
        if errors:
            lines.append("")
            lines.append(f"写入失败（共 {len(errors)} 个）：")
            for entry, message in errors[:5]:
                lines.append(f"• {entry.node_name}：{message}")
            if len(errors) > 5:
                lines.append("…")

        QMessageBox.warning(self, "批量重新定位完成（部分未处理）", "\n".join(lines))

    def reveal_selected(self) -> None:
        selected = self.selected_entries()
        if not selected:
            return
        entry = selected[0]
        if self._reveal_callback is not None:
            self._reveal_callback(entry.node_id, entry.stored_path)
            # The callback may have opened the PDF manager; re-scan so the table
            # reflects anything that was re-linked or removed there.
            self.reload()


# ==============================================================================
# End of missing_files_dialog.py
# ==============================================================================
