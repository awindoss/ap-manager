# ==============================================================================
# tests/test_settings_manager.py
# Phase 7: persistent window geometry and expanded branches in config.json.
# ==============================================================================
import json

import pytest

pytest.importorskip("PySide6")

from utils import constants
from utils.config_manager import ConfigManager
from utils.settings_manager import WindowGeometry, SettingsManager


def make_settings(tmp_path, name: str = "config.json"):
    path = tmp_path / name
    return SettingsManager(ConfigManager(path)), path


def test_missing_geometry_uses_default_size(tmp_path) -> None:
    settings, _ = make_settings(tmp_path)

    geometry = settings.load_window_geometry()

    assert geometry == WindowGeometry(
        width=constants.DEFAULT_WINDOW_WIDTH,
        height=constants.DEFAULT_WINDOW_HEIGHT,
        x=None,
        y=None,
        maximized=False,
    )
    assert geometry.has_position is False


def test_constructor_accepts_a_bare_config_path(tmp_path) -> None:
    path = tmp_path / "bare.json"

    settings = SettingsManager(path)
    settings.save_search_panel_visible(True)

    assert path.is_file()
    assert SettingsManager(path).load_search_panel_visible() is True


def test_geometry_round_trips(tmp_path) -> None:
    settings, path = make_settings(tmp_path)

    assert settings.save_window_geometry((10, 20, 900, 700)) is True

    loaded = settings.load_window_geometry()
    assert loaded == WindowGeometry(width=900, height=700, x=10, y=20)
    assert loaded.has_position is True

    document = json.loads(path.read_text(encoding="utf-8"))
    assert document["ui"]["window_width"] == 900
    assert document["ui"]["window_height"] == 700
    assert document["ui"]["window_x"] == 10
    assert document["ui"]["window_y"] == 20


def test_qrect_geometry_is_accepted(tmp_path) -> None:
    from PySide6.QtCore import QRect

    settings, _ = make_settings(tmp_path)
    settings.save_window_geometry(QRect(30, 40, 1000, 720), maximized=True)

    loaded = settings.load_window_geometry()
    assert (loaded.x, loaded.y, loaded.width, loaded.height) == (30, 40, 1000, 720)
    assert loaded.maximized is True


def test_invalid_geometry_is_rejected(tmp_path) -> None:
    settings, path = make_settings(tmp_path)

    assert settings.save_window_geometry(None) is False
    assert settings.save_window_geometry((0, 0, 0, 0)) is False
    assert not path.exists()


def test_too_small_geometry_is_clamped(tmp_path) -> None:
    settings, _ = make_settings(tmp_path)
    settings.save_window_geometry((0, 0, 10, 10))

    loaded = settings.load_window_geometry()
    assert loaded.width == constants.MIN_WINDOW_WIDTH
    assert loaded.height == constants.MIN_WINDOW_HEIGHT


def test_expanded_paths_are_deduplicated_and_parent_first(tmp_path) -> None:
    settings, _ = make_settings(tmp_path)

    settings.save_expanded_paths([(1, 2), (1,), (1, 2), (0,), (-1,), ("x",)])

    assert settings.load_expanded_paths() == ((1,), (1, 2))


def test_expanded_paths_are_capped(tmp_path) -> None:
    settings, _ = make_settings(tmp_path)
    paths = [(index,) for index in range(1, constants.MAX_SAVED_EXPANDED_PATHS + 50)]

    settings.save_expanded_paths(paths)

    loaded = settings.load_expanded_paths()
    assert len(loaded) == constants.MAX_SAVED_EXPANDED_PATHS
    assert loaded[0] == (1,)


def test_expanded_nodes_compatibility_helpers(tmp_path) -> None:
    settings, _ = make_settings(tmp_path)

    settings.save_expanded_nodes([3, 1, 2, 1])

    assert settings.load_expanded_nodes() == [1, 2, 3]


def test_search_panel_visibility_round_trips(tmp_path) -> None:
    settings, _ = make_settings(tmp_path)
    assert settings.load_search_panel_visible() is False

    settings.save_search_panel_visible(True)

    assert settings.load_search_panel_visible() is True


def test_save_state_writes_geometry_expansion_and_dock(tmp_path) -> None:
    settings, path = make_settings(tmp_path)

    settings.save_state(
        (5, 6, 800, 600),
        maximized=True,
        expanded_paths=[(1,), (1, 2)],
        search_panel_visible=True,
    )

    document = json.loads(path.read_text(encoding="utf-8"))
    assert document["ui"]["window_x"] == 5
    assert document["ui"]["window_maximized"] is True
    assert document["ui"]["expanded_paths"] == [[1], [1, 2]]
    assert document["ui"]["search_panel_visible"] is True

    loaded = SettingsManager(ConfigManager(path)).load_window_geometry()
    assert loaded.maximized is True


def test_saved_window_position_survives_config_merge(tmp_path) -> None:
    """A concrete x/y must replace the ``None`` default (regression guard)."""
    path = tmp_path / "config.json"
    path.write_text(
        json.dumps({"ui": {"window_x": 123, "window_y": 45}}), encoding="utf-8"
    )

    config = ConfigManager(path)

    assert config.get(constants.SECTION_UI, constants.KEY_WINDOW_X) == 123
    assert config.get(constants.SECTION_UI, constants.KEY_WINDOW_Y) == 45
    assert config.get(constants.SECTION_UI, constants.KEY_WINDOW_MAXIMIZED) is False
