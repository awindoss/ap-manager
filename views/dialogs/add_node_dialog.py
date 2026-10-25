# ==============================================================================
# views/dialogs/add_node_dialog.py
# Create a new root node or a child of an existing node.
# ==============================================================================
from typing import Dict, Optional

from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QVBoxLayout,
    QWidget,
)

from utils import constants
from views.dialogs.node_style_editor import NodeStyleEditor


class AddNodeDialog(QDialog):
    """
    Collects the name and initial style of a new node.

    The dialog does not touch the database: the caller (``MainWindow`` through
    ``AppController``) persists the values. This keeps the View -> Controller ->
    Library direction required by plan.md §27.
    """

    def __init__(
        self,
        parent_name: str = "",
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self._parent_name = (parent_name or "").strip()
        self.setWindowTitle(
            f"新建子节点 — {self._parent_name}" if self._parent_name else "新建根节点"
        )
        self.setModal(True)

        self._build_ui()

    # --------------------------------------------------------------------------
    # Construction
    # --------------------------------------------------------------------------
    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        form = QFormLayout()

        self.name_edit = QLineEdit(self)
        self.name_edit.setObjectName("nameEdit")
        self.name_edit.setMaxLength(constants.MAX_NODE_NAME_LENGTH)
        self.name_edit.setPlaceholderText("例如：马克思、资本论 第一卷…")
        form.addRow("名称", self.name_edit)

        self.parent_label = QLabel(self._parent_name or "（根节点）", self)
        self.parent_label.setObjectName("parentLabel")
        form.addRow("父级", self.parent_label)

        self.style_editor = NodeStyleEditor(parent=self)
        form.addRow("样式", self.style_editor)
        layout.addLayout(form)

        self.buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel,
            self,
        )
        self.ok_button = self.buttons.button(QDialogButtonBox.StandardButton.Ok)
        self.ok_button.setText("创建")
        self.buttons.button(QDialogButtonBox.StandardButton.Cancel).setText("取消")
        self.buttons.accepted.connect(self._on_accept)
        self.buttons.rejected.connect(self.reject)
        layout.addWidget(self.buttons)

        self.name_edit.setFocus()
        self.resize(460, 300)

    # --------------------------------------------------------------------------
    # Validation / result
    # --------------------------------------------------------------------------
    def validate(self) -> Optional[str]:
        """Return an error message, or None when the input is valid."""
        name = self.name_edit.text().strip()
        if not name:
            return "节点名称不能为空。"
        if len(name) > constants.MAX_NODE_NAME_LENGTH:
            return f"节点名称不能超过 {constants.MAX_NODE_NAME_LENGTH} 个字符。"
        return None

    def node_values(self) -> Dict[str, object]:
        """All values needed by ``AppController.create_node``."""
        values: Dict[str, object] = {"name": self.name_edit.text().strip()}
        values.update(self.style_editor.values())
        return values

    def _on_accept(self) -> None:
        error = self.validate()
        if error is not None:
            QMessageBox.warning(self, "输入无效", error)
            self.name_edit.setFocus()
            return
        self.accept()


# ==============================================================================
# End of add_node_dialog.py
# ==============================================================================
