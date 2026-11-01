# ==============================================================================
# views/dialogs/settings_dialog.py
# Application settings that are relevant before phase 7: the PDF reader.
# ==============================================================================
import sys
from pathlib import Path
from typing import Optional

from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)


class SettingsDialog(QDialog):
    """
    Choose the external PDF reader.

    An empty path means "use the operating system's default PDF application"
    (plan.md §20). The dialog only collects the value; ``AppController``
    validates and persists it.
    """

    def __init__(
        self,
        reader_path: str = "",
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("设置 — PDF 阅读器")
        self.setModal(True)
        self._build_ui()
        self.reader_edit.setText(reader_path or "")
        self._update_hint()

    # --------------------------------------------------------------------------
    # Construction
    # --------------------------------------------------------------------------
    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)

        layout.addWidget(QLabel("用于打开 PDF 的外部阅读器：", self))

        path_row = QHBoxLayout()
        self.reader_edit = QLineEdit(self)
        self.reader_edit.setObjectName("readerPathEdit")
        self.reader_edit.setPlaceholderText("留空 = 使用系统默认 PDF 阅读器")
        self.reader_edit.textChanged.connect(self._update_hint)
        path_row.addWidget(self.reader_edit, 1)

        self.browse_button = QPushButton("浏览…", self)
        self.browse_button.setObjectName("browseReaderButton")
        self.browse_button.clicked.connect(self.browse_reader)
        path_row.addWidget(self.browse_button)
        layout.addLayout(path_row)

        self.default_button = QPushButton("使用系统默认阅读器", self)
        self.default_button.setObjectName("defaultReaderButton")
        self.default_button.clicked.connect(lambda: self.reader_edit.setText(""))
        layout.addWidget(self.default_button)

        self.hint_label = QLabel("", self)
        self.hint_label.setObjectName("readerHint")
        self.hint_label.setWordWrap(True)
        layout.addWidget(self.hint_label)
        layout.addStretch(1)

        self.buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel,
            self,
        )
        self.buttons.button(QDialogButtonBox.StandardButton.Ok).setText("保存")
        self.buttons.button(QDialogButtonBox.StandardButton.Cancel).setText("取消")
        self.buttons.accepted.connect(self._on_accept)
        self.buttons.rejected.connect(self.reject)
        layout.addWidget(self.buttons)

        self.resize(560, 220)

    # --------------------------------------------------------------------------
    # Accessors / actions
    # --------------------------------------------------------------------------
    def reader_path(self) -> str:
        """The value to persist (empty string means the system default)."""
        return self.reader_edit.text().strip()

    def browse_reader(self) -> None:
        start_directory = ""
        current = self.reader_edit.text().strip()
        if current:
            start_directory = str(Path(current).expanduser().parent)
        path, _selected_filter = QFileDialog.getOpenFileName(
            self,
            "选择 PDF 阅读器",
            start_directory,
            self._executable_filter(),
        )
        if path:
            self.reader_edit.setText(path)

    # --------------------------------------------------------------------------
    # Validation / presentation
    # --------------------------------------------------------------------------
    def _on_accept(self) -> None:
        path = self.reader_path()
        if path:
            candidate = Path(path).expanduser()
            if not candidate.is_file():
                QMessageBox.warning(self, "输入无效", f"PDF 阅读器不存在：\n{path}")
                self.reader_edit.setFocus()
                return
        self.accept()

    def _update_hint(self) -> None:
        if self.reader_path():
            self.hint_label.setText(
                "将使用上方指定的阅读器；该设置保存在 config.json。"
            )
        else:
            self.hint_label.setText(
                "留空时使用操作系统的默认 PDF 阅读器。"
            )

    @staticmethod
    def _executable_filter() -> str:
        if sys.platform.startswith("win"):
            return "可执行文件 (*.exe);;所有文件 (*)"
        if sys.platform == "darwin":
            return "所有文件 (*)"
        return "所有文件 (*)"


# ==============================================================================
# End of settings_dialog.py
# ==============================================================================
