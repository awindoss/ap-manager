# ==============================================================================
# views/dialogs/node_positions_dialog.py
# Show every root-to-node path of a multi-parent node (stage.md 5.2).
#
# Selecting a position and confirming asks the main window to expand the tree
# to that exact display instance. Positions are display paths (node id tuples),
# not just node ids, because the same node can be visible in several branches.
# ==============================================================================
from typing import TYPE_CHECKING, Optional, Sequence, Tuple

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QVBoxLayout,
    QWidget,
)

if TYPE_CHECKING:  # pragma: no cover - type checking only
    from controllers.app_controller import NodePosition


class NodePositionsDialog(QDialog):
    """List all display positions of one node and let the user locate one."""

    def __init__(
        self,
        node_name: str,
        positions: Sequence["NodePosition"],
        parent: Optional[QWidget] = None,
        *,
        current_path: Optional[Tuple[int, ...]] = None,
    ) -> None:
        super().__init__(parent)
        self._node_name = node_name
        self._positions = list(positions)
        self._current_path = tuple(current_path) if current_path else None
        self._selected_path: Optional[Tuple[int, ...]] = None

        self.setWindowTitle(f"查看所有位置 — {node_name}")
        self.setModal(True)
        self._build_ui()
        self._populate()

    # --------------------------------------------------------------------------
    # Construction
    # --------------------------------------------------------------------------
    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)

        count = len(self._positions)
        if count:
            header_text = f"「{self._node_name}」当前共有 {count} 个位置："
        else:
            header_text = f"「{self._node_name}」目前没有可定位的位置。"
        self.header_label = QLabel(header_text, self)
        self.header_label.setWordWrap(True)
        layout.addWidget(self.header_label)

        if not count:
            hint = QLabel(
                "该节点可能存在循环引用，或所在位置的上级关系已损坏。\n"
                "请使用「全部展开」检查结构，或通过「关联到其他位置」重新建立位置。",
                self,
            )
            hint.setWordWrap(True)
            hint.setStyleSheet("color: palette(mid);")
            layout.addWidget(hint)

        self.list_widget = QListWidget(self)
        self.list_widget.setObjectName("nodePositionsList")
        self.list_widget.itemSelectionChanged.connect(self._update_button_states)
        # plan.md §16: clicking a position should take the user there. A single
        # click accepts (the tree is behind this modal dialog); double-click and
        # the "定位" button provide the same action for keyboard/button users.
        self.list_widget.itemClicked.connect(self._accept_item)
        self.list_widget.itemDoubleClicked.connect(self._accept_item)
        layout.addWidget(self.list_widget, 1)

        self.buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel,
            self,
        )
        self.locate_button = self.buttons.button(QDialogButtonBox.StandardButton.Ok)
        self.locate_button.setText("定位")
        self.buttons.button(QDialogButtonBox.StandardButton.Cancel).setText("取消")
        self.buttons.accepted.connect(self._accept_selected)
        self.buttons.rejected.connect(self.reject)
        layout.addWidget(self.buttons)

        self.resize(560, 360)

    def _populate(self) -> None:
        for number, position in enumerate(self._positions, start=1):
            label = f"{number}. {position.label}"
            if self._current_path is not None and tuple(position.path) == self._current_path:
                label += "（当前位置）"
            item = QListWidgetItem(label)
            item.setData(Qt.ItemDataRole.UserRole, tuple(position.path))
            item.setToolTip(" > ".join(position.names))
            self.list_widget.addItem(item)

        if self.list_widget.count():
            target_row = 0
            if self._current_path is not None:
                for row in range(self.list_widget.count()):
                    if self.list_widget.item(row).data(Qt.ItemDataRole.UserRole) == self._current_path:
                        target_row = row
                        break
            self.list_widget.setCurrentRow(target_row)
        self._update_button_states()

    # --------------------------------------------------------------------------
    # Selection
    # --------------------------------------------------------------------------
    def _update_button_states(self) -> None:
        self.locate_button.setEnabled(self.list_widget.currentItem() is not None)

    def _accept_selected(self) -> None:
        item = self.list_widget.currentItem()
        if item is None:
            return
        self._accept_item(item)

    def _accept_item(self, item: QListWidgetItem) -> None:
        if item is None:
            return
        path = item.data(Qt.ItemDataRole.UserRole)
        self._selected_path = tuple(path) if path else None
        self.accept()

    def selected_path(self) -> Optional[Tuple[int, ...]]:
        """Path chosen by the user, or None when the dialog was cancelled."""
        return self._selected_path

    def position_count(self) -> int:
        return self.list_widget.count()


# ==============================================================================
# End of node_positions_dialog.py
# ==============================================================================
