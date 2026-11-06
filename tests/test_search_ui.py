# ==============================================================================
# tests/test_search_ui.py
# Phase 7: main-window search box, result dock and search dialog.
# ==============================================================================
import pytest

pytest.importorskip("PySide6")

from PySide6.QtWidgets import QDialog

from controllers.app_controller import AppController
from views.dialogs.search_dialog import SearchDialog
from views.main_window import MainWindow

pytestmark = pytest.mark.usefixtures("qapp")


@pytest.fixture
def controller(tmp_path) -> AppController:
    return AppController(db_path=tmp_path / "search_ui.db")


@pytest.fixture
def window(controller: AppController):
    main_window = MainWindow(controller=controller)
    main_window.show()
    try:
        yield main_window
    finally:
        main_window.close()


def test_search_box_shows_results_and_dock(window: MainWindow, controller: AppController) -> None:
    root = controller.create_node("Root")
    controller.create_node("Target", parent_id=root)
    window.refresh()

    window.search_box.setText("Target")
    result = window.run_search()

    assert result is not None
    assert result.hit_count == 1
    assert window.search_dock.isVisible()
    assert window.search_panel.result is result
    assert "1 个节点" in window.search_panel.header_label.text()
    assert window.search_count_label.text() == "1 个节点"


def test_clicking_a_location_reveals_the_exact_instance(
    window: MainWindow, controller: AppController
) -> None:
    root_a = controller.create_node("A")
    root_b = controller.create_node("B")
    child = controller.create_node("X", parent_id=root_a)
    controller.attach_node_to_parents(child, [root_b])
    window.refresh()

    window.search_box.setText("X")
    window.run_search()

    view = window.search_panel.results
    top = view.topLevelItem(0)
    assert top is not None
    assert top.childCount() == 2
    location_items = [top.child(index) for index in range(top.childCount())]
    paths = {
        tuple(item.data(0, view.LocationPathRole)) for item in location_items
    }
    assert paths == {(root_a, child), (root_b, child)}

    target_path = (root_b, child)
    target_item = next(
        item
        for item in location_items
        if tuple(item.data(0, view.LocationPathRole)) == target_path
    )
    view.activate_item(target_item, 0)

    current = window.tree_view.currentIndex()
    assert current.isValid()
    assert window.model.display_path_for_index(current) == target_path
    assert window.tree_view.isExpanded(
        window.model.find_index_by_display_path((root_b,))
    )


def test_clearing_the_query_hides_the_dock(window: MainWindow, controller: AppController) -> None:
    controller.create_node("Target")
    window.refresh()
    window.search_box.setText("Target")
    window.run_search()
    assert window.search_dock.isVisible()

    window.search_box.clear()

    assert window.search_dock.isVisible() is False
    assert window.search_panel.result is None
    assert window.search_count_label.text() == ""


def test_empty_query_is_not_searched(window: MainWindow) -> None:
    window.search_box.setText("   ")

    assert window.run_search() is None
    assert window.search_dock.isVisible() is False


def test_search_results_are_refreshed_with_the_tree(
    window: MainWindow, controller: AppController
) -> None:
    controller.create_node("X")
    window.refresh()
    window.search_box.setText("X")
    window.run_search()
    assert window.search_panel.result.hit_count == 1

    controller.create_node("X2")
    window.refresh()

    assert window.search_panel.result.hit_count == 2


def test_focus_search_opens_the_dock(window: MainWindow) -> None:
    window._focus_search()

    assert window.search_dock.isVisible()


def test_pdf_only_match_is_labelled_in_the_result(
    window: MainWindow, controller: AppController
) -> None:
    controller.library.create_node("A book", pdf_paths=["books/capital.pdf"])
    window.refresh()

    window.search_box.setText("capital")
    window.run_search()

    top = window.search_panel.results.topLevelItem(0)
    assert top is not None
    assert "capital.pdf" in top.text(1)


def test_search_dialog_returns_the_chosen_location(controller: AppController) -> None:
    root = controller.create_node("A")
    child = controller.create_node("X", parent_id=root)

    dialog = SearchDialog(controller)
    dialog.set_query("X")

    assert dialog.results_panel.result.hit_count == 1
    assert dialog.results_panel.activate_first_location() is True
    assert dialog.selected_path == (root, child)
    assert dialog.result() == QDialog.DialogCode.Accepted


def test_search_dialog_shows_the_empty_state(controller: AppController) -> None:
    controller.create_node("A")

    dialog = SearchDialog(controller)
    dialog.set_query("does-not-exist")

    result = dialog.results_panel.result
    assert result is not None and result.is_empty
    assert "没有找到" in dialog.results_panel.header_label.text()
