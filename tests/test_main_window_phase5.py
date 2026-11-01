# ==============================================================================
# tests/test_main_window_phase5.py
# Main-window integration tests for Phase 5 multi-parent interactions.
# ==============================================================================
import pytest

pytest.importorskip("PySide6")

from PySide6.QtCore import QModelIndex
from PySide6.QtWidgets import QDialog, QMessageBox

import views.main_window as main_window_module
from controllers.app_controller import AppController
from views.library_tree_view import LibraryTreeView
from views.main_window import MainWindow
from views.tree_model import TreeModel

pytestmark = pytest.mark.usefixtures("qapp")


@pytest.fixture
def controller(tmp_path) -> AppController:
    return AppController(db_path=tmp_path / "main_window_phase5.db")


@pytest.fixture
def window(controller: AppController):
    main_window = MainWindow(controller=controller)
    main_window.show()
    try:
        yield main_window
    finally:
        main_window.close()


def index_of(model: TreeModel, path) -> QModelIndex:
    return model.find_index_by_display_path(tuple(path))


def current_path(window: MainWindow):
    item = window.model.item_from_index(window.tree_view.currentIndex())
    return item.display_path if item is not None else ()


def test_tree_view_is_phase5_drag_and_drop_view(window: MainWindow) -> None:
    assert isinstance(window.tree_view, LibraryTreeView)
    assert window.tree_view.dragEnabled() is True
    assert window.tree_view.acceptDrops() is True
    assert window.tree_view.dragDropMode().name == "DragDrop"
    assert window.tree_view.selectionMode().name == "ExtendedSelection"


def test_context_menu_disables_remove_move_for_roots(
    window: MainWindow, controller: AppController
) -> None:
    root = controller.create_node("Root")
    window.refresh()
    menu = window.build_context_menu(index_of(window.model, (root,)))
    actions = {action.text(): action for action in menu.actions() if not action.isSeparator()}

    assert "关联到其他位置…" in actions
    assert "查看所有位置…" in actions
    assert actions["关联到其他位置…"].isEnabled() is True
    assert actions["移动到其他位置…"].isEnabled() is False
    assert actions["从当前父级移除"].isEnabled() is False
    assert actions["彻底删除节点…"].isEnabled() is True


def test_context_menu_enables_relation_actions_for_children(
    window: MainWindow, controller: AppController
) -> None:
    root = controller.create_node("Root")
    child = controller.create_node("Child", parent_id=root)
    window.refresh()
    menu = window.build_context_menu(index_of(window.model, (root, child)))
    actions = {action.text(): action for action in menu.actions() if not action.isSeparator()}

    assert actions["移动到其他位置…"].isEnabled() is True
    assert actions["从当前父级移除"].isEnabled() is True
    assert actions["查看所有位置…"].data() == child


def test_selection_updates_relation_action_states(
    window: MainWindow, controller: AppController
) -> None:
    root = controller.create_node("Root")
    child = controller.create_node("Child", parent_id=root)
    window.refresh()

    window.tree_view.setCurrentIndex(index_of(window.model, (root,)))
    assert window._move_action.isEnabled() is False
    assert window._detach_action.isEnabled() is False
    assert window._attach_action.isEnabled() is True
    assert window._positions_action.isEnabled() is True

    window.tree_view.setCurrentIndex(index_of(window.model, (root, child)))
    assert window._move_action.isEnabled() is True
    assert window._detach_action.isEnabled() is True


def test_detach_removes_exactly_one_parent_position(
    window: MainWindow, controller: AppController
) -> None:
    a = controller.create_node("A")
    b = controller.create_node("B")
    x = controller.create_node("X")
    controller.attach_node_to_parents(x, [a, b])
    window.refresh()
    assert window.model.parent_count(x) == 2

    item = window.model.item_from_index(index_of(window.model, (a, x)))
    window._confirm_detach = lambda node_id, parent_id: True
    window._detach_item(item)

    assert controller.get_parent_ids(x) == [b]
    assert window.model.parent_count(x) == 1
    assert [instance.display_path for instance in window.model.find_items_by_node_id(x)] == [
        (b, x)
    ]
    assert "已从「A」中移除「X」" in window.statusBar().currentMessage()


def test_detach_can_be_cancelled(
    window: MainWindow, controller: AppController
) -> None:
    a = controller.create_node("A")
    x = controller.create_node("X", parent_id=a)
    window.refresh()

    item = window.model.item_from_index(index_of(window.model, (a, x)))
    window._confirm_detach = lambda node_id, parent_id: False
    window._detach_item(item)

    assert controller.get_parent_ids(x) == [a]


def test_detach_confirmation_explains_remaining_positions(
    window: MainWindow, controller: AppController, monkeypatch
) -> None:
    a = controller.create_node("A")
    b = controller.create_node("B")
    x = controller.create_node("X")
    controller.attach_node_to_parents(x, [a, b])
    seen = {}

    def fake_question(parent, title, text, *args, **kwargs):
        seen["text"] = text
        return QMessageBox.StandardButton.No

    monkeypatch.setattr(main_window_module.QMessageBox, "question", staticmethod(fake_question))
    assert window._confirm_detach(x, a) is False
    assert "还保留在另外 1 个位置" in seen["text"]
    assert "不会删除节点本身" in seen["text"]


def test_detach_root_is_reported(window: MainWindow, controller: AppController) -> None:
    root = controller.create_node("Root")
    window.refresh()
    window.tree_view.setCurrentIndex(index_of(window.model, (root,)))

    window._detach_for_selection()

    assert "根节点没有父级位置" in window.statusBar().currentMessage()


def test_delete_confirmation_mentions_positions_and_files(
    window: MainWindow, controller: AppController, monkeypatch
) -> None:
    a = controller.create_node("A")
    b = controller.create_node("B")
    x = controller.create_node("X")
    controller.attach_node_to_parents(x, [a, b])
    seen = {}

    def fake_question(parent, title, text, *args, **kwargs):
        seen["text"] = text
        return QMessageBox.StandardButton.No

    monkeypatch.setattr(main_window_module.QMessageBox, "question", staticmethod(fake_question))
    assert window._confirm_delete_node(x) is False
    assert "2 个位置" in seen["text"]
    assert "PDF 文件不会被删除" in seen["text"]
    assert "不可撤销" in seen["text"]


def test_delete_node_completely_from_window(
    window: MainWindow, controller: AppController
) -> None:
    a = controller.create_node("A")
    b = controller.create_node("B")
    x = controller.create_node("X")
    controller.attach_node_to_parents(x, [a, b])
    window.refresh()
    window._confirm_delete_node = lambda node_id: True

    window._delete_node(x)

    assert controller.get_node(x) is None
    assert controller.get_node_children(a) == []
    assert controller.get_node_children(b) == []
    assert "已彻底删除节点「X」" in window.statusBar().currentMessage()


def test_delete_cancel_keeps_the_node(
    window: MainWindow, controller: AppController
) -> None:
    x = controller.create_node("X")
    window.refresh()
    window._confirm_delete_node = lambda node_id: False

    window._delete_node(x)

    assert controller.get_node(x) is not None


class FakePositionsDialog:
    instances = []

    def __init__(self, node_name, positions, parent=None, *, current_path=None):
        self.node_name = node_name
        self.positions = list(positions)
        self.current_path = current_path
        self._path = None
        FakePositionsDialog.instances.append(self)

    def exec(self):
        return QDialog.DialogCode.Accepted

    def selected_path(self):
        return self._path


def test_show_positions_reveals_the_selected_instance(
    window: MainWindow, controller: AppController, monkeypatch
) -> None:
    a = controller.create_node("A")
    b = controller.create_node("B")
    x = controller.create_node("X")
    controller.attach_node_to_parents(x, [a, b])
    window.refresh()
    window.tree_view.setCurrentIndex(index_of(window.model, (a, x)))

    FakePositionsDialog.instances.clear()

    def make_dialog(node_name, positions, parent=None, *, current_path=None):
        dialog = FakePositionsDialog(
            node_name, positions, parent, current_path=current_path
        )
        dialog._path = (b, x)
        return dialog

    monkeypatch.setattr(main_window_module, "NodePositionsDialog", make_dialog)
    window._show_positions_for_selection()

    captured = FakePositionsDialog.instances[0]
    assert captured.node_name == "X"
    assert [position.path for position in captured.positions] == [(a, x), (b, x)]
    assert captured.current_path == (a, x)
    assert current_path(window) == (b, x)
    assert window.tree_view.isExpanded(index_of(window.model, (b,)))
    assert "已定位" in window.statusBar().currentMessage()


class FakeChooseParentDialog:
    target_parents = []
    modes = []
    exclusions = []

    def __init__(
        self,
        controller,
        node_id,
        parent=None,
        *,
        excluded_parent_ids=(),
        mode="attach",
    ) -> None:
        self.node_id = node_id
        self.excluded = set(excluded_parent_ids)
        FakeChooseParentDialog.modes.append(mode)
        FakeChooseParentDialog.exclusions.append(self.excluded)

    def exec(self):
        return QDialog.DialogCode.Accepted

    def selected_parent_ids(self):
        return list(type(self).target_parents)


def test_attach_node_creates_an_additional_position(
    window: MainWindow, controller: AppController, monkeypatch
) -> None:
    a = controller.create_node("A")
    b = controller.create_node("B")
    x = controller.create_node("X", parent_id=a)
    window.refresh()

    FakeChooseParentDialog.target_parents = [b]
    FakeChooseParentDialog.modes.clear()
    FakeChooseParentDialog.exclusions.clear()
    monkeypatch.setattr(main_window_module, "ChooseParentDialog", FakeChooseParentDialog)

    window._attach_node(x)

    assert controller.get_parent_ids(x) == [a, b]
    assert window.model.parent_count(x) == 2
    assert FakeChooseParentDialog.modes == ["attach"]
    assert FakeChooseParentDialog.exclusions == [{a}]
    assert current_path(window) == (b, x)
    assert "已关联 1 个新位置" in window.statusBar().currentMessage()


def test_attach_cycle_is_reported_without_writing(
    window: MainWindow, controller: AppController, monkeypatch
) -> None:
    a = controller.create_node("A")
    x = controller.create_node("X", parent_id=a)
    window.refresh()
    warnings = []
    monkeypatch.setattr(
        main_window_module,
        "ChooseParentDialog",
        type(
            "CycleDialog",
            (FakeChooseParentDialog,),
            {"target_parents": [x]},
        ),
    )
    monkeypatch.setattr(
        main_window_module.QMessageBox,
        "warning",
        staticmethod(lambda *args, **kwargs: warnings.append(args)),
    )

    window._attach_node(a)

    assert controller.get_parent_ids(a) == []
    assert warnings
    assert "循环" in warnings[0][2]


def test_move_node_through_dialog(
    window: MainWindow, controller: AppController, monkeypatch
) -> None:
    a = controller.create_node("A")
    b = controller.create_node("B")
    x = controller.create_node("X", parent_id=a)
    window.refresh()
    window.tree_view.setCurrentIndex(index_of(window.model, (a, x)))

    FakeChooseParentDialog.target_parents = [b]
    FakeChooseParentDialog.modes.clear()
    FakeChooseParentDialog.exclusions.clear()
    monkeypatch.setattr(main_window_module, "ChooseParentDialog", FakeChooseParentDialog)

    window._move_for_selection()

    assert controller.get_parent_ids(x) == [b]
    assert FakeChooseParentDialog.modes == ["move"]
    assert a in FakeChooseParentDialog.exclusions[0]
    assert current_path(window) == (b, x)
    assert "移动到「B」" in window.statusBar().currentMessage()


def test_move_root_from_menu_is_reported(
    window: MainWindow, controller: AppController
) -> None:
    root = controller.create_node("Root")
    window.refresh()
    window.tree_view.setCurrentIndex(index_of(window.model, (root,)))

    window._move_for_selection()

    assert "根节点没有原位置" in window.statusBar().currentMessage()


def test_drop_prompt_attach_and_move_paths(
    window: MainWindow, controller: AppController, monkeypatch
) -> None:
    a = controller.create_node("A")
    b = controller.create_node("B")
    x = controller.create_node("X", parent_id=a)
    c = controller.create_node("C", parent_id=b)
    window.refresh()

    monkeypatch.setattr(window, "_prompt_drop_action", lambda paths, target: "attach")
    window._on_nodes_dropped([(a, x)], b)
    assert controller.get_parent_ids(x) == [a, b]

    monkeypatch.setattr(window, "_prompt_drop_action", lambda paths, target: "move")
    window._on_nodes_dropped([(a, x)], b)
    assert controller.get_parent_ids(x) == [b]

    # Multi-selection attach is supported.
    monkeypatch.setattr(window, "_prompt_drop_action", lambda paths, target: "attach")
    window._on_nodes_dropped([(b, c), (b, x)], a)
    assert controller.get_parent_ids(c) == [a, b]
    assert controller.get_parent_ids(x) == [a, b]


def test_drop_cancel_does_nothing(
    window: MainWindow, controller: AppController, monkeypatch
) -> None:
    a = controller.create_node("A")
    b = controller.create_node("B")
    x = controller.create_node("X", parent_id=a)
    window.refresh()
    monkeypatch.setattr(window, "_prompt_drop_action", lambda paths, target: None)

    window._on_nodes_dropped([(a, x)], b)

    assert controller.get_parent_ids(x) == [a]


def test_drop_rejection_is_shown_in_status_bar(window: MainWindow) -> None:
    window._on_drop_rejected("不能关联：会形成循环引用。")

    assert "循环" in window.statusBar().currentMessage()


def test_reorder_drop_updates_sibling_order(
    window: MainWindow, controller: AppController
) -> None:
    parent = controller.create_node("Parent")
    x = controller.create_node("X", parent_id=parent)
    y = controller.create_node("Y", parent_id=parent)
    z = controller.create_node("Z", parent_id=parent)
    window.refresh()

    window._on_reorder_dropped((parent, x), (parent, z), before=True)

    assert [node.name for node in controller.get_node_children(parent)] == [
        "Y",
        "X",
        "Z",
    ]
    assert current_path(window) == (parent, x)
    assert "已调整节点顺序" in window.statusBar().currentMessage()


def test_reorder_drop_across_parents_is_rejected(
    window: MainWindow, controller: AppController
) -> None:
    p1 = controller.create_node("P1")
    p2 = controller.create_node("P2")
    x = controller.create_node("X", parent_id=p1)
    z = controller.create_node("Z", parent_id=p2)
    window.refresh()

    window._on_reorder_dropped((p1, x), (p2, z), before=True)

    assert [node.name for node in controller.get_node_children(p1)] == ["X"]
    assert [node.name for node in controller.get_node_children(p2)] == ["Z"]
    assert "同一个父级" in window.statusBar().currentMessage()


def test_reveal_invalid_display_path_reports(
    window: MainWindow, controller: AppController
) -> None:
    root = controller.create_node("Root")
    window.refresh()

    assert window._reveal_display_path((root, 999999)) is False
    assert "已不存在" in window.statusBar().currentMessage()
