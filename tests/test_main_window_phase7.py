# ==============================================================================
# tests/test_main_window_phase7.py
# Phase 7: window geometry / expansion persistence and search menu wiring.
# ==============================================================================
import json

import pytest

pytest.importorskip("PySide6")

from PySide6.QtCore import QModelIndex
from PySide6.QtGui import QAction, QGuiApplication, QKeySequence
from PySide6.QtWidgets import QDialog

import views.main_window as main_window_module
from controllers.app_controller import AppController
from utils.config_manager import ConfigManager
from utils.settings_manager import WindowGeometry
from views.main_window import MainWindow

pytestmark = pytest.mark.usefixtures("qapp")


@pytest.fixture
def config_path(tmp_path):
    return tmp_path / "config.json"


@pytest.fixture
def controller(config_path, tmp_path) -> AppController:
    config = ConfigManager(config_path)
    return AppController(
        db_path=tmp_path / "phase7.db",
        config_manager=config,
    )


@pytest.fixture
def window(controller: AppController):
    main_window = MainWindow(controller=controller)
    main_window.show()
    try:
        yield main_window
    finally:
        main_window.close()


def read_config(path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def expand_root(window: MainWindow) -> QModelIndex:
    index = window.model.index(0, 0, QModelIndex())
    window.tree_view.expand(index)
    return index


def test_save_state_persists_geometry_and_expansion(
    window: MainWindow, controller: AppController, config_path
) -> None:
    root = controller.create_node("Root")
    controller.create_node("Child", parent_id=root)
    window.refresh()
    expand_root(window)
    window.setGeometry(50, 40, 900, 650)

    window.save_state()

    document = read_config(config_path)
    assert document["ui"]["window_width"] == 900
    assert document["ui"]["window_height"] == 650
    assert document["ui"]["window_x"] == 50
    assert document["ui"]["window_y"] == 40
    assert [root] in document["ui"]["expanded_paths"]


def test_close_event_saves_the_session(
    controller: AppController, config_path
) -> None:
    main_window = MainWindow(controller=controller)
    main_window.show()
    controller.create_node("Root")
    main_window.refresh()

    main_window.close()

    document = read_config(config_path)
    assert "window_width" in document["ui"]
    assert "expanded_paths" in document["ui"]


def test_reopened_window_restores_expansion(
    controller: AppController, config_path
) -> None:
    first = MainWindow(controller=controller)
    first.show()
    root = controller.create_node("Root")
    controller.create_node("Child", parent_id=root)
    first.refresh()
    expand_root(first)
    first.save_state()
    first.close()

    second = MainWindow(controller=controller)
    second.show()
    try:
        index = second.model.index(0, 0, QModelIndex())
        assert second.tree_view.isExpanded(index)
    finally:
        second.close()


def test_offscreen_position_is_centred_on_screen(window: MainWindow) -> None:
    window._apply_saved_geometry(WindowGeometry(800, 600, -5000, -5000))

    screen = QGuiApplication.primaryScreen()
    assert screen is not None
    assert window.geometry().intersects(screen.availableGeometry())


def test_search_dock_visibility_is_persisted(
    window: MainWindow, controller: AppController, config_path
) -> None:
    controller.create_node("Target")
    window.refresh()
    window.search_box.setText("Target")
    window.run_search()
    assert window.search_dock.isVisible()

    window.save_state()

    assert read_config(config_path)["ui"]["search_panel_visible"] is True


def test_saved_search_dock_visibility_is_restored(
    controller: AppController, config_path
) -> None:
    controller.config.set("ui", "search_panel_visible", True)
    controller.config.save()

    main_window = MainWindow(controller=controller)
    main_window.show()
    try:
        assert main_window.search_dock.isVisible()
    finally:
        main_window.close()


def test_search_shortcuts_are_registered(window: MainWindow) -> None:
    shortcuts = {
        action.shortcut().toString()
        for action in window.findChildren(QAction)
        if not action.shortcut().isEmpty()
    }

    assert QKeySequence("Ctrl+F").toString() in shortcuts
    assert QKeySequence("Ctrl+Shift+F").toString() in shortcuts


def test_open_search_dialog_reveals_a_selected_location(
    window: MainWindow, controller: AppController, monkeypatch
) -> None:
    root = controller.create_node("Root")
    child = controller.create_node("Target", parent_id=root)
    window.refresh()

    class FakeSearchDialog:
        def __init__(self, controller, parent=None) -> None:
            self.selected_path = (root, child)
            self.selected_node_id = None

        def set_query(self, query) -> None:
            self.query = query

        def exec(self):
            return QDialog.DialogCode.Accepted

    monkeypatch.setattr(main_window_module, "SearchDialog", FakeSearchDialog)
    window.search_box.setText("Target")

    window._open_search_dialog()

    current = window.tree_view.currentIndex()
    assert window.model.display_path_for_index(current) == (root, child)
