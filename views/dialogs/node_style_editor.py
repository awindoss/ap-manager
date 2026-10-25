# ==============================================================================
# views/dialogs/node_style_editor.py
# Reusable "icon / bold / colour" editor shared by the new-node and
# node-properties dialogs.
# ==============================================================================
from typing import Dict, Optional

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QCheckBox,
    QColorDialog,
    QDialog,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from models.node import normalize_color, normalize_icon
from utils import constants
from utils.icon_utils import is_custom_icon, load_icon
from views.dialogs.icon_selector_dialog import IconSelectorDialog


class NodeStyleEditor(QWidget):
    """
    Editor for the three visual node properties: icon, bold, text colour.

    The widget only collects values; persistence is the controller's job. All
    values returned by :meth:`values` are already normalised (``#rrggbb`` colour,
    stripped icon) so a dialog cannot write an invalid style to the database.
    """

    def __init__(
        self,
        icon: object = "",
        bold: bool = False,
        color: str = constants.DEFAULT_TEXT_COLOR,
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self._icon = normalize_icon(icon)
        self._bold = bool(bold)
        self._color = normalize_color(color)

        self._build_ui()
        self.set_bold(self._bold)
        self._refresh_icon_button()
        self._refresh_color_button()

    # --------------------------------------------------------------------------
    # Construction
    # --------------------------------------------------------------------------
    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)

        icon_row = QHBoxLayout()
        icon_row.addWidget(QLabel("图标", self))
        self.icon_button = QPushButton("选择图标…", self)
        self.icon_button.setObjectName("iconButton")
        self.icon_button.clicked.connect(self.choose_icon)
        icon_row.addWidget(self.icon_button, 1)

        self.clear_icon_button = QPushButton("清除", self)
        self.clear_icon_button.setObjectName("clearIconButton")
        self.clear_icon_button.setToolTip("移除节点图标")
        self.clear_icon_button.clicked.connect(lambda: self.set_icon(""))
        icon_row.addWidget(self.clear_icon_button)
        layout.addLayout(icon_row)

        self.bold_check = QCheckBox("字体加粗", self)
        self.bold_check.setObjectName("boldCheck")
        self.bold_check.toggled.connect(self.set_bold)
        layout.addWidget(self.bold_check)

        color_row = QHBoxLayout()
        color_row.addWidget(QLabel("颜色", self))
        self.color_button = QPushButton(self._color, self)
        self.color_button.setObjectName("colorButton")
        self.color_button.setMinimumWidth(96)
        self.color_button.clicked.connect(self.choose_color)
        color_row.addWidget(self.color_button)

        self.reset_color_button = QPushButton("默认", self)
        self.reset_color_button.setObjectName("resetColorButton")
        self.reset_color_button.setToolTip(f"恢复默认文字颜色 {constants.DEFAULT_TEXT_COLOR}")
        self.reset_color_button.clicked.connect(
            lambda: self.set_color(constants.DEFAULT_TEXT_COLOR)
        )
        color_row.addWidget(self.reset_color_button)
        color_row.addStretch(1)
        layout.addLayout(color_row)

        self.preview_label = QLabel("示例文字 Aa 123", self)
        self.preview_label.setObjectName("stylePreview")
        self.preview_label.setContentsMargins(4, 2, 4, 2)
        layout.addWidget(self.preview_label)

        self._refresh_preview()

    # --------------------------------------------------------------------------
    # Accessors
    # --------------------------------------------------------------------------
    def values(self) -> Dict[str, object]:
        """Normalised style values, ready to be persisted."""
        return {
            "icon": self._icon,
            "style_bold": self._bold,
            "style_color": self._color,
        }

    def icon(self) -> str:
        return self._icon

    def is_bold(self) -> bool:
        return self._bold

    def color(self) -> str:
        return self._color

    # --------------------------------------------------------------------------
    # Mutators
    # --------------------------------------------------------------------------
    def set_icon(self, icon: object) -> None:
        self._icon = normalize_icon(icon)
        self._refresh_icon_button()

    def set_bold(self, bold: bool) -> None:
        self._bold = bool(bold)
        if self.bold_check.isChecked() != self._bold:
            self.bold_check.blockSignals(True)
            self.bold_check.setChecked(self._bold)
            self.bold_check.blockSignals(False)
        self._refresh_preview()

    def set_color(self, color: object) -> None:
        self._color = normalize_color(color)
        self._refresh_color_button()
        self._refresh_preview()

    # --------------------------------------------------------------------------
    # Actions
    # --------------------------------------------------------------------------
    def choose_icon(self) -> None:
        dialog = IconSelectorDialog(self._icon, self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self.set_icon(dialog.selected_icon())

    def choose_color(self) -> None:
        selected = QColorDialog.getColor(
            QColor(self._color), self, "选择文字颜色"
        )
        if selected.isValid():
            self.set_color(selected.name())

    # --------------------------------------------------------------------------
    # Presentation
    # --------------------------------------------------------------------------
    def _refresh_icon_button(self) -> None:
        if not self._icon:
            self.icon_button.setIcon(load_icon(""))
            self.icon_button.setText("选择图标…")
        elif is_custom_icon(self._icon):
            self.icon_button.setIcon(load_icon(self._icon, constants.TREE_ICON_SIZE))
            self.icon_button.setText("自定义图片")
        else:
            self.icon_button.setIcon(load_icon(self._icon, constants.TREE_ICON_SIZE))
            self.icon_button.setText("内置图标")
        self.icon_button.setToolTip(self._icon or "未设置图标")
        self.clear_icon_button.setEnabled(bool(self._icon))

    def _refresh_color_button(self) -> None:
        color = QColor(self._color)
        text_color = "#ffffff" if color.lightness() < 128 else "#000000"
        self.color_button.setText(self._color)
        self.color_button.setStyleSheet(
            f"background-color: {self._color}; color: {text_color};"
        )

    def _refresh_preview(self) -> None:
        font = self.preview_label.font()
        font.setBold(self._bold)
        self.preview_label.setFont(font)
        self.preview_label.setStyleSheet(
            f"color: {self._color}; border: 1px solid palette(mid); border-radius: 3px;"
        )
        self.preview_label.setTextInteractionFlags(Qt.TextInteractionFlag.NoTextInteraction)


# ==============================================================================
# End of node_style_editor.py
# ==============================================================================
