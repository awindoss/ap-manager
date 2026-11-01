# ==============================================================================
# tests/test_main_window.py
# Tests for the main window and controller wiring (Phase 2/3/4).
# ==============================================================================
import pytest

pytest.importorskip("PySide6")

from PySide6.QtCore import QModelIndex, Qt
from PySide6.QtWidgets import QDialog, QMessageBox, QTreeView

import views.main_window as main_window_module
from controllers.app_controller import AppController
from services.pdf_launcher import LaunchReport
from views.delegates.tree_delegate import TreeDelegate
from views.main_window import MainWindow

pytestmark = pytest.mark.usefixtures("qapp")


def make_pdf(path, content: bytes = b"%PDF-1.4\n"):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    return path


def pdf_paths(*paths) -> list:
    return [str(path) for path in paths]


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


def test_double_click_on_leaf_with_single_pdf_opens_it(tmp_path) -> None:
    """A childless node with one PDF opens it instead of toggling."""

    class SpyController(AppController):
        def __init__(self, *args, **kwargs) -> None:
            super().__init__(*args, **kwargs)
            self.opened = []

        def open_pdf(self, stored_path: str) -> bool:
            self.opened.append(stored_path)
            return True

    pdf = make_pdf(tmp_path / "books" / "capital.pdf")
    spy = SpyController(db_path=tmp_path / "spy.db")
    main_window = MainWindow(controller=spy)
    main_window.show()
    try:
        spy.library.create_node("资本论", pdf_paths=[str(pdf)])
        main_window.refresh()
        book_index = main_window.model.index(0, 0, QModelIndex())

        main_window._on_double_clicked(book_index)

        assert spy.opened == [str(pdf)]
        assert not main_window.tree_view.isExpanded(book_index)
    finally:
        main_window.close()


def test_double_click_on_leaf_without_pdf_does_not_open(tmp_path) -> None:
    class SpyController(AppController):
        def __init__(self, *args, **kwargs) -> None:
            super().__init__(*args, **kwargs)
            self.opened = []

        def open_pdf(self, stored_path: str) -> bool:
            self.opened.append(stored_path)
            return True

    spy = SpyController(db_path=tmp_path / "spy_empty.db")
    main_window = MainWindow(controller=spy)
    main_window.show()
    try:
        spy.library.create_node("Empty leaf")
        main_window.refresh()
        leaf_index = main_window.model.index(0, 0, QModelIndex())

        main_window._on_double_clicked(leaf_index)

        assert spy.opened == []
    finally:
        main_window.close()


def test_double_click_with_multiple_pdfs_uses_the_selector(tmp_path, monkeypatch) -> None:
    first = make_pdf(tmp_path / "books" / "one.pdf", b"one")
    second = make_pdf(tmp_path / "books" / "two.pdf", b"two")

    class SpyController(AppController):
        def __init__(self, *args, **kwargs) -> None:
            super().__init__(*args, **kwargs)
            self.opened = []

        def open_pdf(self, stored_path: str) -> bool:
            self.opened.append(stored_path)
            return True

    seen = {}

    class FakeSelector:
        def __init__(self, node_name, pdf_files, parent=None) -> None:
            seen["node_name"] = node_name
            self.files = list(pdf_files)

        def exec(self):
            return QDialog.DialogCode.Accepted

        def selected_pdf(self):
            return self.files[1]

    monkeypatch.setattr(main_window_module, "PdfSelectorDialog", FakeSelector)
    spy = SpyController(db_path=tmp_path / "selector.db")
    main_window = MainWindow(controller=spy)
    main_window.show()
    try:
        spy.library.create_node("资本论", pdf_paths=[str(first), str(second)])
        main_window.refresh()

        main_window._on_double_clicked(main_window.model.index(0, 0, QModelIndex()))

        assert seen["node_name"] == "资本论"
        assert spy.opened == [str(second)]
    finally:
        main_window.close()


def test_double_click_when_all_pdfs_are_missing_offers_relink(tmp_path, monkeypatch) -> None:
    calls = []
    monkeypatch.setattr(
        main_window_module.QMessageBox,
        "question",
        staticmethod(lambda *args, **kwargs: QMessageBox.StandardButton.Yes),
    )

    controller = AppController(db_path=tmp_path / "missing.db")
    id_book = controller.library.create_node("Book", pdf_paths=["books/gone.pdf"])
    main_window = MainWindow(controller=controller)
    main_window.show()
    try:
        main_window.refresh()
        monkeypatch.setattr(
            main_window,
            "_manage_pdfs",
            lambda node_id, select_path=None: calls.append((node_id, select_path)),
        )

        main_window._on_double_clicked(main_window.model.index(0, 0, QModelIndex()))

        assert calls == [(id_book, "books/gone.pdf")]
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


def test_controller_pdf_open_reports_a_missing_file(tmp_path) -> None:
    from services.pdf_launcher import PdfLaunchError

    controller = AppController(db_path=tmp_path / "controller.db")
    controller.library.create_node("Book", pdf_paths=["books/book.pdf"])

    with pytest.raises(PdfLaunchError):
        controller.open_pdf("books/book.pdf")


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
    assert window._manage_pdf_action.isEnabled() is True
    assert window._open_pdf_action.isEnabled() is False
    assert window._open_all_pdf_action.isEnabled() is False


# ------------------------------------------------------------------------------
# Phase 4: PDF actions, reader settings and missing-file workflow
# ------------------------------------------------------------------------------
def test_pdf_menu_actions_exist(window: MainWindow) -> None:
    assert window._manage_pdf_action is not None
    assert window._open_pdf_action is not None
    assert window._open_all_pdf_action is not None
    assert window._inspect_action is not None
    assert window._relink_missing_action is not None
    assert window._pdf_reader_action is not None


def test_context_menu_offers_pdf_actions(window: MainWindow, controller: AppController, tmp_path) -> None:
    first = make_pdf(tmp_path / "books" / "one.pdf", b"one")
    second = make_pdf(tmp_path / "books" / "two.pdf", b"two")
    id_node = controller.library.create_node(
        "Book", pdf_paths=[str(first), str(second)]
    )
    window.refresh()
    index = window.model.index(0, 0, QModelIndex())

    menu = window.build_context_menu(index)
    actions = {action.text(): action for action in menu.actions() if not action.isSeparator()}

    assert "管理 PDF…" in actions
    assert actions["管理 PDF…"].data() == id_node
    assert actions["打开 PDF"].isEnabled() is True
    assert actions["打开全部 PDF"].isEnabled() is True
    # Both files exist, so there is nothing to re-locate.
    assert actions["重新定位缺失 PDF…"].isEnabled() is False


def test_context_menu_disables_open_actions_for_a_node_without_pdfs(
    window: MainWindow, controller: AppController
) -> None:
    controller.create_node("No PDFs")
    window.refresh()

    menu = window.build_context_menu(window.model.index(0, 0, QModelIndex()))
    actions = {action.text(): action for action in menu.actions() if not action.isSeparator()}

    assert actions["管理 PDF…"].isEnabled() is True
    assert actions["打开 PDF"].isEnabled() is False
    assert actions["打开全部 PDF"].isEnabled() is False
    assert actions["重新定位缺失 PDF…"].isEnabled() is False


def test_manage_pdf_dialog_updates_the_tree_in_place(
    window: MainWindow, controller: AppController, tmp_path, monkeypatch
) -> None:
    pdf = make_pdf(tmp_path / "books" / "new.pdf")
    id_node = controller.create_node("Book")
    window.refresh()
    resets = []
    window.model.modelReset.connect(lambda: resets.append(True))
    seen = {}

    class FakeManagementDialog:
        def __init__(self, dialog_controller, node_id, parent=None, select_path=None) -> None:
            seen["node_id"] = node_id
            seen["select_path"] = select_path
            dialog_controller.library.add_pdf(node_id, str(pdf))

        def exec(self):
            return QDialog.DialogCode.Accepted

    monkeypatch.setattr(main_window_module, "PdfManagementDialog", FakeManagementDialog)

    window._manage_pdfs(id_node)

    assert seen == {"node_id": id_node, "select_path": None}
    assert resets == []
    index = window.model.find_index_by_display_path((id_node,))
    assert "PDF: 1" in window.model.data(index, Qt.ItemDataRole.ToolTipRole)


def test_manage_pdf_dialog_unknown_node_warns(
    window: MainWindow, monkeypatch
) -> None:
    warnings = []
    monkeypatch.setattr(
        main_window_module.QMessageBox,
        "warning",
        staticmethod(lambda *args, **kwargs: warnings.append(args)),
    )

    class FailingDialog:
        def __init__(self, *args, **kwargs) -> None:
            raise ValueError("节点 999 不存在。")

    monkeypatch.setattr(main_window_module, "PdfManagementDialog", FailingDialog)

    window._manage_pdfs(999)

    assert warnings


def test_open_settings_persists_the_reader(
    tmp_path, monkeypatch
) -> None:
    reader = tmp_path / "reader.exe"
    reader.write_bytes(b"")

    class SpyController(AppController):
        def __init__(self, *args, **kwargs) -> None:
            super().__init__(*args, **kwargs)
            self.saved_reader = None

        def set_pdf_reader_path(self, reader_path):
            self.saved_reader = str(reader_path)
            return str(reader_path)

    class FakeSettingsDialog:
        def __init__(self, reader_path="", parent=None) -> None:
            self.initial = reader_path

        def exec(self):
            return QDialog.DialogCode.Accepted

        def reader_path(self) -> str:
            return str(reader)

    monkeypatch.setattr(main_window_module, "SettingsDialog", FakeSettingsDialog)
    controller = SpyController(db_path=tmp_path / "settings.db")
    main_window = MainWindow(controller=controller)
    main_window.show()
    try:
        main_window._open_settings()
        assert controller.saved_reader == str(reader)
        assert "PDF 阅读器" in main_window.statusBar().currentMessage()
    finally:
        main_window.close()


def test_inspect_pdfs_offers_relink_for_missing_files(
    window: MainWindow, controller: AppController, monkeypatch
) -> None:
    controller.library.create_node("Book", pdf_paths=["books/gone.pdf"])
    window.refresh()
    calls = []
    monkeypatch.setattr(
        main_window_module.QMessageBox,
        "question",
        staticmethod(lambda *args, **kwargs: QMessageBox.StandardButton.Yes),
    )
    monkeypatch.setattr(window, "_relink_missing_pdfs", lambda: calls.append(True))

    window._inspect_pdfs()

    assert calls == [True]


def test_inspect_pdfs_reports_a_clean_library(
    window: MainWindow, monkeypatch
) -> None:
    messages = []
    monkeypatch.setattr(
        main_window_module.QMessageBox,
        "information",
        staticmethod(lambda *args, **kwargs: messages.append(args)),
    )

    window._inspect_pdfs()

    assert messages
    assert "全部 PDF 文件均可访问" in messages[0][2]


def test_open_all_pdfs_reports_failures(tmp_path, monkeypatch) -> None:
    class SpyController(AppController):
        def open_node_pdfs(self, node_id):
            return LaunchReport(
                opened=["books/a.pdf"],
                failures=[("books/b.pdf", "PDF 文件不存在")],
            )

    warnings = []
    monkeypatch.setattr(
        main_window_module.QMessageBox,
        "warning",
        staticmethod(lambda *args, **kwargs: warnings.append(args)),
    )
    controller = SpyController(db_path=tmp_path / "open_all.db")
    main_window = MainWindow(controller=controller)
    main_window.show()
    try:
        main_window._open_all_pdfs(1)
        assert warnings
        assert "已打开 1 个 PDF" in main_window.statusBar().currentMessage()
    finally:
        main_window.close()


def test_relink_missing_dialog_refreshes_after_changes(
    window: MainWindow, monkeypatch
) -> None:
    class FakeMissingDialog:
        def __init__(self, controller, parent=None, reveal_callback=None) -> None:
            self.changed = True

        def exec(self):
            return QDialog.DialogCode.Accepted

    monkeypatch.setattr(main_window_module, "MissingFilesDialog", FakeMissingDialog)
    refreshes = []
    monkeypatch.setattr(window, "refresh", lambda: refreshes.append(True))

    window._relink_missing_pdfs()

    assert refreshes == [True]

