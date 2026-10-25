# ==============================================================================
# views/dialogs/node_properties_dialog.py
# Edit an existing node's name and visual style.
# ==============================================================================
from typing import Dict, Optional

from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QGroupBox,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QVBoxLayout,
    QWidget,
)

from models.node import Node, normalize_color, normalize_icon
from utils import constants
from views.dialogs.node_style_editor import NodeStyleEditor


class NodePropertiesDialog(QDialog):
    """
    Edit an existing node.

    PDFs are shown read-only here; managing them is Phase 4 (stage.md 3.5).
    Like :class:`AddNodeDialog` the dialog only reports the differences, so the
    controller remains the only component that writes to the library.
    """

    def __init__(self, node: Node, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._node = node
        self.setWindowTitle(f"节点属性 — {node.name}")
        self.setModal(True)
        self._build_ui()

    # --------------------------------------------------------------------------
    # Construction
    # --------------------------------------------------------------------------
    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        form = QFormLayout()

        self.name_edit = QLineEdit(self._node.name, self)
        self.name_edit.setObjectName("nameEdit")
        self.name_edit.setMaxLength(constants.MAX_NODE_NAME_LENGTH)
        form.addRow("名称", self.name_edit)

        node_id_label = QLabel(str(self._node.id) if self._node.id is not None else "（未保存）", self)
        node_id_label.setObjectName("nodeIdLabel")
        form.addRow("节点 ID", node_id_label)

        self.style_editor = NodeStyleEditor(
            self._node.icon,
            self._node.style_bold,
            self._node.style_color,
            parent=self,
        )
        form.addRow("样式", self.style_editor)
        layout.addLayout(form)

        self.pdf_group = QGroupBox(f"PDF（{len(self._node.pdf_paths)}）", self)
        pdf_layout = QVBoxLayout(self.pdf_group)
        self.pdf_list = QListWidget(self)
        self.pdf_list.setObjectName("pdfList")
        self.pdf_list.setSelectionMode(QListWidget.SelectionMode.NoSelection)
        for pdf_path in self._node.pdf_paths:
            self.pdf_list.addItem(QListWidgetItem(pdf_path))
        pdf_layout.addWidget(self.pdf_list)

        if not self._node.pdf_paths:
            hint = QLabel("（暂无 PDF，PDF 管理将在 Phase 4 提供）", self)
            hint.setObjectName("pdfHint")
            pdf_layout.addWidget(hint)

        self.pdf_list.setMaximumHeight(90)
        layout.addWidget(self.pdf_group)

        self.buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel,
            self,
        )
        self.buttons.button(QDialogButtonBox.StandardButton.Ok).setText("保存")
        self.buttons.button(QDialogButtonBox.StandardButton.Cancel).setText("取消")
        self.buttons.accepted.connect(self._on_accept)
        self.buttons.rejected.connect(self.reject)
        layout.addWidget(self.buttons)

        self.name_edit.setFocus()
        self.resize(480, 420)

    # --------------------------------------------------------------------------
    # Validation / result
    # --------------------------------------------------------------------------
    def validate(self) -> Optional[str]:
        name = self.name_edit.text().strip()
        if not name:
            return "节点名称不能为空。"
        if len(name) > constants.MAX_NODE_NAME_LENGTH:
            return f"节点名称不能超过 {constants.MAX_NODE_NAME_LENGTH} 个字符。"
        return None

    def changes(self) -> Dict[str, object]:
        """Only the fields the user actually changed, normalised."""
        changes: Dict[str, object] = {}

        name = self.name_edit.text().strip()
        if name != self._node.name:
            changes["name"] = name

        style = self.style_editor.values()
        if style["icon"] != normalize_icon(self._node.icon):
            changes["icon"] = style["icon"]
        if style["style_bold"] != bool(self._node.style_bold):
            changes["style_bold"] = style["style_bold"]
        if style["style_color"] != normalize_color(self._node.style_color):
            changes["style_color"] = style["style_color"]
        return changes

    def focus_style(self) -> None:
        """Open on the style controls (used by the "设置样式" menu action)."""
        self.style_editor.icon_button.setFocus()

    def _on_accept(self) -> None:
        error = self.validate()
        if error is not None:
            QMessageBox.warning(self, "输入无效", error)
            self.name_edit.setFocus()
            return
        self.accept()


# ==============================================================================
# End of node_properties_dialog.py
# ==============================================================================
