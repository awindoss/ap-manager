# ==============================================================================
# tests/test_relation_dialogs.py
# Tests for the Phase 5 dialogs: choosing a parent location and listing all
# positions of a multi-parent node.
# ==============================================================================
import pytest

pytest.importorskip("PySide6")

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QDialog

from controllers.app_controller import AppController
from views.dialogs.choose_parent_dialog import ChooseParentDialog
from views.dialogs.node_positions_dialog import NodePositionsDialog

pytestmark = pytest.mark.usefixtures("qapp")


@pytest.fixture
def controller(tmp_path) -> AppController:
    return AppController(db_path=tmp_path / "relation_dialogs.db")


def test_choose_parent_disables_self_descendants_and_existing_parents(
    controller: AppController,
) -> None:
    root = controller.create_node("Root")
    shelf = controller.create_node("Shelf", parent_id=root)
    book = controller.create_node("Book", parent_id=shelf)
    child = controller.create_node("Book child", parent_id=book)
    other = controller.create_node("Other")

    dialog = ChooseParentDialog(controller, book, mode="attach")
    try:
        self_item = dialog.item_for_node(book)
        child_item = dialog.item_for_node(child)
        shelf_item = dialog.item_for_node(shelf)
        root_item = dialog.item_for_node(root)
        other_item = dialog.item_for_node(other)

        assert "不可选" in self_item.text(0)
        assert "不可选" in child_item.text(0)
        assert not (self_item.flags() & Qt.ItemFlag.ItemIsUserCheckable)
        assert not (child_item.flags() & Qt.ItemFlag.ItemIsUserCheckable)
        assert "已关联" in shelf_item.text(0)
        assert not (shelf_item.flags() & Qt.ItemFlag.ItemIsUserCheckable)

        assert dialog.is_node_selectable(root) is True
        assert dialog.is_node_selectable(other) is True
        assert root_item.flags() & Qt.ItemFlag.ItemIsUserCheckable
        assert other_item.flags() & Qt.ItemFlag.ItemIsUserCheckable
        # Opening the dialog must not mutate the graph.
        assert controller.get_parent_ids(book) == [shelf]
    finally:
        dialog.close()


def test_choose_parent_collects_multiple_locations(controller: AppController) -> None:
    root = controller.create_node("Root")
    shelf = controller.create_node("Shelf", parent_id=root)
    book = controller.create_node("Book", parent_id=shelf)
    other = controller.create_node("Other")

    dialog = ChooseParentDialog(controller, book, mode="attach")
    try:
        dialog.item_for_node(root).setCheckState(0, Qt.CheckState.Checked)
        dialog.item_for_node(other).setCheckState(0, Qt.CheckState.Checked)

        assert set(dialog.selected_parent_ids()) == {root, other}
        assert dialog.ok_button.isEnabled() is True
        assert "2 个位置" in dialog.status_label.text()
    finally:
        dialog.close()


def test_choose_parent_syncs_duplicate_display_paths(controller: AppController) -> None:
    parent_a = controller.create_node("A")
    parent_b = controller.create_node("B")
    shared = controller.create_node("Shared")
    controller.attach_node_to_parents(shared, [parent_a, parent_b])
    book = controller.create_node("Book", parent_id=parent_a)

    dialog = ChooseParentDialog(controller, book, mode="attach")
    try:
        shared_items = dialog._items_by_node[shared]
        assert len(shared_items) == 2

        shared_items[0].setCheckState(0, Qt.CheckState.Checked)

        assert all(
            item.checkState(0) == Qt.CheckState.Checked for item in shared_items
        )
        # The same database node is still only one parent choice.
        assert dialog.selected_parent_ids() == [shared]

        shared_items[1].setCheckState(0, Qt.CheckState.Unchecked)
        assert all(
            item.checkState(0) == Qt.CheckState.Unchecked for item in shared_items
        )
    finally:
        dialog.close()


def test_choose_parent_move_mode_is_single_choice(controller: AppController) -> None:
    root = controller.create_node("Root")
    shelf = controller.create_node("Shelf", parent_id=root)
    book = controller.create_node("Book", parent_id=shelf)
    other = controller.create_node("Other")

    dialog = ChooseParentDialog(controller, book, mode="move")
    try:
        assert dialog.mode == "move"
        dialog.item_for_node(root).setCheckState(0, Qt.CheckState.Checked)
        dialog.item_for_node(other).setCheckState(0, Qt.CheckState.Checked)

        assert dialog.selected_parent_ids() == [other]
        assert dialog.ok_button.text() == "移动"
    finally:
        dialog.close()


def test_choose_parent_requires_a_selection(controller: AppController) -> None:
    root = controller.create_node("Root")
    book = controller.create_node("Book", parent_id=root)

    dialog = ChooseParentDialog(controller, book)
    try:
        assert dialog.ok_button.isEnabled() is False
        dialog._accept_selection()
        assert dialog.result() == QDialog.DialogCode.Rejected
        assert "请先选择" in dialog.status_label.text()
    finally:
        dialog.close()


def test_choose_parent_with_no_available_location(controller: AppController) -> None:
    only = controller.create_node("Only node")

    dialog = ChooseParentDialog(controller, only)
    try:
        assert dialog.is_node_selectable(only) is False
        assert dialog.ok_button.isEnabled() is False
        assert dialog.item_for_node(only) is not None
    finally:
        dialog.close()


def test_choose_parent_raises_for_unknown_node(controller: AppController) -> None:
    with pytest.raises(ValueError):
        ChooseParentDialog(controller, 999999)


# ------------------------------------------------------------------------------
# NodePositionsDialog
# ------------------------------------------------------------------------------
def test_positions_dialog_lists_and_selects_every_path(
    controller: AppController,
) -> None:
    a = controller.create_node("A")
    b = controller.create_node("B")
    x = controller.create_node("X")
    controller.attach_node_to_parents(x, [a, b])

    positions = controller.get_node_positions(x)
    dialog = NodePositionsDialog("X", positions, current_path=(b, x))
    try:
        assert dialog.position_count() == 2
        assert dialog.list_widget.item(0).text() == "1. A > X"
        assert dialog.list_widget.item(1).text() == "2. B > X（当前位置）"
        assert dialog.list_widget.currentRow() == 1

        dialog.list_widget.setCurrentRow(0)
        dialog._accept_selected()

        assert dialog.result() == QDialog.DialogCode.Accepted
        assert dialog.selected_path() == (a, x)
    finally:
        dialog.close()


def test_positions_dialog_without_positions_disables_locating(
    controller: AppController,
) -> None:
    a = controller.create_node("Cycle A")
    b = controller.create_node("Cycle B")
    controller.library.db.add_edge(a, b)
    controller.library.db.add_edge(b, a)

    positions = controller.get_node_positions(a)
    dialog = NodePositionsDialog("Cycle A", positions)
    try:
        assert dialog.position_count() == 0
        assert dialog.locate_button.isEnabled() is False
        assert "没有可定位的位置" in dialog.header_label.text()
        assert dialog.selected_path() is None
    finally:
        dialog.close()


def test_positions_dialog_cancel_returns_none(controller: AppController) -> None:
    root = controller.create_node("Root")
    positions = controller.get_node_positions(root)
    dialog = NodePositionsDialog("Root", positions)
    try:
        dialog.reject()
        assert dialog.selected_path() is None
    finally:
        dialog.close()


def test_positions_dialog_single_click_locates(controller: AppController) -> None:
    a = controller.create_node("A")
    b = controller.create_node("B")
    x = controller.create_node("X")
    controller.attach_node_to_parents(x, [a, b])

    dialog = NodePositionsDialog("X", controller.get_node_positions(x))
    try:
        dialog.list_widget.itemClicked.emit(dialog.list_widget.item(1))

        assert dialog.result() == QDialog.DialogCode.Accepted
        assert dialog.selected_path() == (b, x)
    finally:
        dialog.close()
