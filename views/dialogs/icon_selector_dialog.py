# ==============================================================================
# views/dialogs/icon_selector_dialog.py
# Choose a built-in emoji or import a custom image into icons/.
# ==============================================================================
from pathlib import Path
from typing import Optional

from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QFont, QPixmap
from PySide6.QtWidgets import (
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

from utils import constants
from utils.icon_utils import import_custom_icon, is_custom_icon, load_icon
from utils.logger import log_info


class IconSelectorDialog(QDialog):
    """
    Icon picker.

    Built-in emoji are always offered. "浏览自定义图片…" copies the selected
    file into the application's ``icons/`` directory and stores the resulting
    relative path, never the user's original location (plan.md §13.2).
    """

    PREVIEW_SIZE = 48
    GRID_SIZE = 56

    def __init__(self, current_icon: object = "", parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("选择图标")
        self.setModal(True)
        self._cleared = False

        self._build_ui()
        self._populate(current_icon)

    # --------------------------------------------------------------------------
    # Construction
    # --------------------------------------------------------------------------
    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)

        self.list_widget = QListWidget(self)
        self.list_widget.setObjectName("iconList")
        self.list_widget.setViewMode(QListWidget.ViewMode.IconMode)
        self.list_widget.setResizeMode(QListWidget.ResizeMode.Adjust)
        self.list_widget.setMovement(QListWidget.Movement.Static)
        self.list_widget.setIconSize(QSize(32, 32))
        self.list_widget.setGridSize(QSize(self.GRID_SIZE, self.GRID_SIZE))
        self.list_widget.setSpacing(2)
        self.list_widget.setUniformItemSizes(True)
        self.list_widget.currentItemChanged.connect(self._on_current_changed)
        self.list_widget.itemDoubleClicked.connect(lambda _item: self.accept())
        layout.addWidget(self.list_widget)

        preview_row = QHBoxLayout()
        preview_row.addWidget(QLabel("预览", self))
        self.preview_label = QLabel("（无图标）", self)
        self.preview_label.setObjectName("iconPreview")
        self.preview_label.setMinimumSize(self.PREVIEW_SIZE, self.PREVIEW_SIZE)
        self.preview_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.preview_label.setStyleSheet("border: 1px solid palette(mid); border-radius: 4px;")
        preview_row.addWidget(self.preview_label)
        preview_row.addStretch(1)

        self.browse_button = QPushButton("浏览自定义图片…", self)
        self.browse_button.setObjectName("browseIconButton")
        self.browse_button.clicked.connect(self.browse_custom)
        preview_row.addWidget(self.browse_button)

        self.clear_button = QPushButton("清除图标", self)
        self.clear_button.setObjectName("clearSelectedIconButton")
        self.clear_button.clicked.connect(self.clear_selection)
        preview_row.addWidget(self.clear_button)
        layout.addLayout(preview_row)

        self.buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel,
            self,
        )
        self.buttons.button(QDialogButtonBox.StandardButton.Ok).setText("确定")
        self.buttons.button(QDialogButtonBox.StandardButton.Cancel).setText("取消")
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)
        layout.addWidget(self.buttons)

        self.resize(420, 300)

    # --------------------------------------------------------------------------
    # Population
    # --------------------------------------------------------------------------
    def _populate(self, current_icon: object) -> None:
        current = "" if current_icon is None else str(current_icon).strip()
        self._cleared = False

        emoji_font = self._emoji_font(self.list_widget.font())
        selected_item: Optional[QListWidgetItem] = None

        for emoji in constants.DEFAULT_ICON_EMOJIS:
            item = QListWidgetItem(emoji)
            item.setData(Qt.ItemDataRole.UserRole, emoji)
            item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            item.setFont(emoji_font)
            item.setToolTip(f"内置图标 {emoji}")
            self.list_widget.addItem(item)
            if emoji == current:
                selected_item = item

        if is_custom_icon(current):
            selected_item = self._append_custom_item(current) or selected_item

        if selected_item is not None:
            self.list_widget.setCurrentItem(selected_item)
        self._update_preview(self.list_widget.currentItem())

    def _append_custom_item(self, relative_path: str) -> Optional[QListWidgetItem]:
        icon = load_icon(relative_path, 32)
        item = QListWidgetItem("自定义")
        item.setData(Qt.ItemDataRole.UserRole, relative_path)
        item.setToolTip(relative_path)
        item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
        if not icon.isNull():
            item.setIcon(icon)
        self.list_widget.addItem(item)
        return item

    # --------------------------------------------------------------------------
    # Selection
    # --------------------------------------------------------------------------
    def selected_icon(self) -> str:
        """The chosen icon value (emoji, ``icons/...`` path, or empty string)."""
        if self._cleared:
            return ""
        item = self.list_widget.currentItem()
        if item is None:
            return ""
        value = item.data(Qt.ItemDataRole.UserRole)
        return "" if value is None else str(value)

    def clear_selection(self) -> None:
        """Clear the icon and close the dialog as accepted."""
        self._cleared = True
        self.list_widget.clearSelection()
        self.list_widget.setCurrentRow(-1)
        self._update_preview(None)
        self.accept()

    # --------------------------------------------------------------------------
    # Actions
    # --------------------------------------------------------------------------
    def browse_custom(self) -> None:
        path, _selected_filter = QFileDialog.getOpenFileName(
            self,
            "选择图标图片",
            "",
            "图标图片 (*.png *.ico *.svg)",
        )
        if not path:
            return

        try:
            relative_path = import_custom_icon(Path(path))
        except (OSError, ValueError) as error:
            QMessageBox.warning(self, "无法使用该图片", str(error))
            return

        self._cleared = False
        item = self._append_custom_item(relative_path)
        if item is not None:
            self.list_widget.setCurrentItem(item)
            self._update_preview(item)
        log_info(f"Custom icon selected: {relative_path}")

    # --------------------------------------------------------------------------
    # Presentation
    # --------------------------------------------------------------------------
    def _on_current_changed(
        self,
        current: Optional[QListWidgetItem],
        _previous: Optional[QListWidgetItem],
    ) -> None:
        if current is not None:
            self._cleared = False
        self._update_preview(current)

    def _update_preview(self, item: Optional[QListWidgetItem]) -> None:
        if item is None:
            self.preview_label.setPixmap(QPixmap())
            self.preview_label.setText("（无图标）")
            return

        value = item.data(Qt.ItemDataRole.UserRole)
        if value is None:
            self.preview_label.setText("（无图标）")
            return

        text = str(value)
        icon = load_icon(text, self.PREVIEW_SIZE)
        if not icon.isNull():
            self.preview_label.setText("")
            self.preview_label.setPixmap(icon.pixmap(self.PREVIEW_SIZE, self.PREVIEW_SIZE))
        else:
            self.preview_label.setPixmap(QPixmap())
            self.preview_label.setText(text)

    @staticmethod
    def _emoji_font(base_font: QFont) -> QFont:
        font = QFont(base_font)
        font.setFamilies(
            [
                "Segoe UI Emoji",
                "Apple Color Emoji",
                "Noto Color Emoji",
                "Segoe UI Symbol",
            ]
        )
        font.setPixelSize(22)
        return font


# ==============================================================================
# End of icon_selector_dialog.py
# ==============================================================================
