# ==============================================================================
# tests/test_main_window.py
# Tests for the main window and controller wiring (Phase 2).
# ==============================================================================
import pytest

pytest.importorskip("PySide6")

from PySide6.QtCore import QModelIndex, Qt
from PySide6.QtWidgets import QDialog, QTreeView

import views.main_window as main_window_module
from controllers.app_controller import AppController
from views.delegates.tree_delegate import TreeDelegate
from views.main_window import MainWindow

pytestmark = pytest.mark.usefixtures("qapp")


@pytest.fixture
def controller(tmp_path) -> AppController:
    return AppController(db_path=tmp_path / "main_window_test.db")


@pytest.fixture
def window(controller: AppController):
    main_window = MainWindow(controller=controller)
    main_window.show()
    try:
        yield main_window
    finally:
        main_window.close()


def test_window_uses_the_tree_model(window: MainWindow, controller: AppController) -> None:
    id_root = controller.library.create_node("经济政治")
    controller.library.create_node("马列", parent_id=id_root)
    window.refresh()

    assert isinstance(window.tree_view, QTreeView)
    assert window.tree_view.model() is window.model
    assert window.tree_view.isHeaderHidden()
    assert window.tree_view.expandsOnDoubleClick() is False

    assert window.model.root_count == 1
    root_index = window.model.index(0, 0, QModelIndex())
    assert window.model.rowCount(root_index) == 1


def test_double_click_toggles_expand_and_collapse(window: MainWindow, controller: AppController) -> None:
    id_root = controller.library.create_node("Root")
    controller.library.create_node("Child", parent_id=id_root)
    window.refresh()

    root_index = window.model.index(0, 0, QModelIndex())
    assert window.model.rowCount(root_index) == 1
    assert not window.tree_view.isExpanded(root_index)

    window._on_double_clicked(root_index)
    assert window.tree_view.isExpanded(root_index)

    window._on_double_clicked(root_index)
    assert not window.tree_view.isExpanded(root_index)


def test_double_click_on_leaf_with_pdf_requests_open(tmp_path) -> None:
    """A childless node with PDFs delegates to the controller instead of toggling."""

    class SpyController(AppController):
        def __init__(self, *args, **kwargs) -> None:
            super().__init__(*args, **kwargs)
            self.opened_node_ids = []

        def request_open_pdfs(self, node_id: int) -> bool:
            self.opened_node_ids.append(node_id)
            return True

    spy = SpyController(db_path=tmp_path / "spy.db")
    main_window = MainWindow(controller=spy)
    main_window.show()
    try:
        id_book = spy.library.create_node("资本论", pdf_paths=["books/capital.pdf"])
        main_window.refresh()
        book_index = main_window.model.index(0, 0, QModelIndex())

        main_window._on_double_clicked(book_index)

        assert spy.opened_node_ids == [id_book]
        assert not main_window.tree_view.isExpanded(book_index)
    finally:
        main_window.close()


def test_double_click_on_leaf_without_pdf_does_not_open(tmp_path) -> None:
    class SpyController(AppController):
        def __init__(self, *args, **kwargs) -> None:
            super().__init__(*args, **kwargs)
            self.opened_node_ids = []

        def request_open_pdfs(self, node_id: int) -> bool:
            self.opened_node_ids.append(node_id)
            return True

    spy = SpyController(db_path=tmp_path / "spy_empty.db")
    main_window = MainWindow(controller=spy)
    main_window.show()
    try:
        spy.library.create_node("Empty leaf")
        main_window.refresh()
        leaf_index = main_window.model.index(0, 0, QModelIndex())

        main_window._on_double_clicked(leaf_index)

        assert spy.opened_node_ids == []
    finally:
        main_window.close()


def test_double_click_on_invalid_index_is_ignored(window: MainWindow) -> None:
    # Must not raise.
    window._on_double_clicked(QModelIndex())


def test_status_bar_reports_counts(window: MainWindow, controller: AppController) -> None:
    id_root = controller.library.create_node("Root")
    controller.library.create_node("Shared", parent_id=id_root)
    window.refresh()

    status_text = window._status_label.text()
    assert "根节点 1" in status_text
    assert "显示实例 2" in status_text


def test_controller_pdf_request_is_a_phase_4_stub(tmp_path) -> None:
    controller = AppController(db_path=tmp_path / "controller.db")
    id_book = controller.library.create_node("Book", pdf_paths=["books/book.pdf"])

    assert controller.get_node(id_book).name == "Book"
    # Phase 2 only decides; the launcher arrives in Phase 4.
    assert controller.request_open_pdfs(id_book) is False
    assert controller.request_open_pdfs(999999) is False
    assert controller.get_all_roots() != []
    assert controller.get_node_children(id_book) == []


# ------------------------------------------------------------------------------
# Phase 3: delegate, refresh state, context menu and editing
# ------------------------------------------------------------------------------
def test_tree_uses_the_phase_3_delegate(window: MainWindow) -> None:
    assert isinstance(window.tree_view.itemDelegate(), TreeDelegate)
    assert window.tree_view.contextMenuPolicy() == Qt.ContextMenuPolicy.CustomContextMenu


def test_refresh_preserves_expansion_and_selection(window: MainWindow, controller: AppController) -> None:
    id_root = controller.create_node("Root")
    id_shelf = controller.create_node("Shelf", parent_id=id_root)
    id_book = controller.create_node("Book", parent_id=id_shelf)
    window.refresh()

    root_index = window.model.index(0, 0, QModelIndex())
    window.tree_view.expand(root_index)
    shelf_index = window.model.index(0, 0, root_index)
    window.tree_view.expand(shelf_index)
    book_index = window.model.index(0, 0, shelf_index)
    window.tree_view.setCurrentIndex(book_index)

    window.refresh()

    root_index = window.model.index(0, 0, QModelIndex())
    shelf_index = window.model.index(0, 0, root_index)
    assert window.tree_view.isExpanded(root_index)
    assert window.tree_view.isExpanded(shelf_index)
    assert window.model.node_id_from_index(window.tree_view.currentIndex()) == id_book

    # A deliberately collapsed branch stays collapsed after a refresh.
    window.tree_view.collapse(shelf_index)
    window.refresh()
    root_index = window.model.index(0, 0, QModelIndex())
    shelf_index = window.model.index(0, 0, root_index)
    assert window.tree_view.isExpanded(root_index)
    assert not window.tree_view.isExpanded(shelf_index)


def test_context_menu_on_node_offers_editing(window: MainWindow, controller: AppController) -> None:
    id_root = controller.create_node("Root")
    window.refresh()
    index = window.model.index(0, 0, QModelIndex())

    menu = window.build_context_menu(index)
    actions = {action.text(): action for action in menu.actions() if not action.isSeparator()}

    assert "新建子节点…" in actions
    assert "编辑属性…" in actions
    assert "设置样式…" in actions
    assert actions["编辑属性…"].data() == id_root
    assert actions["设置样式…"].data() == id_root


def test_context_menu_on_blank_area_only_creates_roots(window: MainWindow) -> None:
    menu = window.build_context_menu(QModelIndex())
    actions = {action.text(): action for action in menu.actions() if not action.isSeparator()}

    assert "新建根节点…" in actions
    assert "刷新" in actions
    assert "编辑属性…" not in actions
    assert "新建子节点…" not in actions


def test_create_child_node_through_dialog(window: MainWindow, controller: AppController, monkeypatch) -> None:
    id_root = controller.create_node("Parent")
    window.refresh()
    seen = {}

    class FakeAddDialog:
        def __init__(self, parent_name="", parent=None) -> None:
            seen["parent_name"] = parent_name

        def exec(self):
            return QDialog.DialogCode.Accepted

        def node_values(self):
            return {
                "name": "Child",
                "icon": "📚",
                "style_bold": True,
                "style_color": "#B22222",
            }

    monkeypatch.setattr(main_window_module, "AddNodeDialog", FakeAddDialog)

    window._create_child_node(id_root)

    children = controller.get_node_children(id_root)
    assert [node.name for node in children] == ["Child"]
    assert seen["parent_name"] == "Parent"
    child = children[0]
    assert child.style_bold is True
    assert child.style_color == "#b22222"
    assert child.icon == "📚"

    # The new node is revealed and selected.
    assert window.model.node_id_from_index(window.tree_view.currentIndex()) == child.id
    assert window.tree_view.isExpanded(window.model.index(0, 0, QModelIndex()))
    assert "已创建节点" in window.statusBar().currentMessage()


def test_create_root_node_through_dialog(window: MainWindow, controller: AppController, monkeypatch) -> None:
    window.refresh()

    class FakeAddDialog:
        def __init__(self, parent_name="", parent=None) -> None:
            seen_parent = parent_name
            assert seen_parent == ""

        def exec(self):
            return QDialog.DialogCode.Accepted

        def node_values(self):
            return {
                "name": "New root",
                "icon": "⭐",
                "style_bold": False,
                "style_color": "#000000",
            }

    monkeypatch.setattr(main_window_module, "AddNodeDialog", FakeAddDialog)

    window._create_root_node()

    roots = controller.get_all_roots()
    assert [node.name for node in roots] == ["New root"]
    assert window.model.node_id_from_index(window.tree_view.currentIndex()) == roots[0].id


def test_create_dialog_cancel_does_not_write(window: MainWindow, controller: AppController, monkeypatch) -> None:
    class CancelAddDialog:
        def __init__(self, parent_name="", parent=None) -> None:
            pass

        def exec(self):
            return QDialog.DialogCode.Rejected

    monkeypatch.setattr(main_window_module, "AddNodeDialog", CancelAddDialog)

    window._create_root_node()

    assert controller.get_all_roots() == []
    assert window.statusBar().currentMessage() == ""


def test_edit_node_updates_in_place_and_keeps_selection(window: MainWindow, controller: AppController, monkeypatch) -> None:
    id_root = controller.create_node("Root")
    id_child = controller.create_node("Child", parent_id=id_root, icon="📚")
    window.refresh()

    root_index = window.model.index(0, 0, QModelIndex())
    window.tree_view.expand(root_index)
    child_index = window.model.index(0, 0, root_index)
    window.tree_view.setCurrentIndex(child_index)
    resets = []
    window.model.modelReset.connect(lambda: resets.append(True))

    class FakePropertiesDialog:
        def __init__(self, node, parent=None) -> None:
            self.node = node

        def focus_style(self) -> None:
            pass

        def exec(self):
            return QDialog.DialogCode.Accepted

        def changes(self):
            return {
                "name": "Renamed",
                "icon": "⭐",
                "style_bold": True,
                "style_color": "#123456",
            }

    monkeypatch.setattr(main_window_module, "NodePropertiesDialog", FakePropertiesDialog)

    window._edit_node(id_child)

    assert resets == []
    assert window.tree_view.isExpanded(root_index)
    assert window.model.node_id_from_index(window.tree_view.currentIndex()) == id_child
    assert window.model.data(child_index, Qt.ItemDataRole.DisplayRole) == "Renamed"
    font = window.model.data(child_index, Qt.ItemDataRole.FontRole)
    assert font is not None and font.bold() is True
    color = window.model.data(child_index, Qt.ItemDataRole.ForegroundRole)
    assert color is not None and color.name() == "#123456"
    assert window.model.data(child_index, Qt.ItemDataRole.DecorationRole) is not None


def test_edit_dialog_without_changes_writes_nothing(window: MainWindow, controller: AppController, monkeypatch) -> None:
    id_root = controller.create_node("Root")
    window.refresh()

    class NoChangeDialog:
        def __init__(self, node, parent=None) -> None:
            pass

        def focus_style(self) -> None:
            pass

        def exec(self):
            return QDialog.DialogCode.Accepted

        def changes(self):
            return {}

    monkeypatch.setattr(main_window_module, "NodePropertiesDialog", NoChangeDialog)

    window._edit_node(id_root)

    assert controller.get_node(id_root).name == "Root"


def test_edit_selected_without_selection_reports(window: MainWindow) -> None:
    window._edit_selected()

    assert "请先选择" in window.statusBar().currentMessage()


def test_create_child_without_selection_reports(window: MainWindow) -> None:
    window._create_child_from_selection()

    assert "请先选择" in window.statusBar().currentMessage()


def test_selection_actions_follow_current_index(window: MainWindow, controller: AppController) -> None:
    assert window._edit_action.isEnabled() is False

    controller.create_node("Root")
    window.refresh()
    assert window._edit_action.isEnabled() is False

    root_index = window.model.index(0, 0, QModelIndex())
    window.tree_view.setCurrentIndex(root_index)

    assert window._edit_action.isEnabled() is True
    assert window._style_action.isEnabled() is True
    assert window._new_child_action.isEnabled() is True

