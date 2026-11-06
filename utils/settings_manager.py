# ==============================================================================
# utils/settings_manager.py
# Persistent UI state for the main window (Phase 7).
#
# config.json already stores application settings (plan.md §33). This module
# adds the *session* part of that file:
#
#   ui.window_width / window_height / window_x / window_y / window_maximized
#   ui.expanded_paths        - expanded display branches (lists of node ids)
#   ui.search_panel_visible  - whether the search result dock was open
#
# Geometry is kept as four plain integers rather than an opaque Qt geometry
# blob, so the file stays hand-editable (plan.md §33). Expanded state uses
# *display paths* instead of a flat node-id set: one node can be expanded in one
# position and collapsed in another (multi-parent projection, plan.md §10).
# ==============================================================================
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, List, Mapping, Optional, Sequence, Tuple

from utils import constants
from utils.config_manager import ConfigManager
from utils.logger import log_debug, log_warning

# A display branch: root id, ..., deepest expanded node id.
DisplayPath = Tuple[int, ...]


@dataclass(frozen=True)
class WindowGeometry:
    """Persisted window rectangle plus the maximised flag."""

    width: int
    height: int
    x: Optional[int] = None
    y: Optional[int] = None
    maximized: bool = False

    @property
    def has_position(self) -> bool:
        """True when an explicit top-left corner was stored."""
        return self.x is not None and self.y is not None

    def to_rect(self):
        """Return a ``QRect`` (Qt is imported lazily so this module stays light)."""
        from PySide6.QtCore import QRect

        return QRect(self.x or 0, self.y or 0, self.width, self.height)


class SettingsManager:
    """
    Reads and writes the UI section of ``config.json``.

    The manager deliberately never raises on save: losing window geometry must
    not prevent the application from closing. Errors are logged instead.
    """

    def __init__(
        self,
        config_manager: Optional[ConfigManager] = None,
        *,
        config_path: Optional[str] = None,
    ) -> None:
        # Convenience: ``SettingsManager("config.json")`` treats a bare path as
        # the config location rather than as a ConfigManager instance.
        if isinstance(config_manager, (str, Path)):
            if config_path is None:
                config_path = str(config_manager)
            config_manager = None
        self.config: ConfigManager = config_manager or ConfigManager(config_path)

    # --------------------------------------------------------------------------
    # Window geometry
    # --------------------------------------------------------------------------
    def save_window_geometry(self, geometry: Any, *, maximized: Optional[bool] = None) -> bool:
        """
        Persist the window rectangle.

        ``geometry`` may be a ``QRect``/``QRectF``/``QSize``, a mapping with
        ``width``/``height``/``x``/``y`` keys, or ``(x, y, width, height)``.
        Returns True when the values were written.
        """
        values = _extract_geometry(geometry, maximized=maximized)
        if values is None:
            log_warning("Window geometry was not saved: unusable geometry value.")
            return False
        width, height, x, y, is_maximized = values
        self._write_geometry(width, height, x, y, is_maximized)
        return self._save()

    def load_window_geometry(self) -> Optional[WindowGeometry]:
        """Return the saved window rectangle, or ``None`` when unusable."""
        width = _coerce_int(
            self.config.get(
                constants.SECTION_UI,
                constants.KEY_WINDOW_WIDTH,
                constants.DEFAULT_WINDOW_WIDTH,
            )
        )
        height = _coerce_int(
            self.config.get(
                constants.SECTION_UI,
                constants.KEY_WINDOW_HEIGHT,
                constants.DEFAULT_WINDOW_HEIGHT,
            )
        )
        if width is None or height is None:
            log_warning("Saved window size is invalid; using the default size.")
            return None

        width = _clamp(width, constants.MIN_WINDOW_WIDTH, constants.MAX_WINDOW_WIDTH)
        height = _clamp(height, constants.MIN_WINDOW_HEIGHT, constants.MAX_WINDOW_HEIGHT)
        x = _coerce_int(
            self.config.get(constants.SECTION_UI, constants.KEY_WINDOW_X, None)
        )
        y = _coerce_int(
            self.config.get(constants.SECTION_UI, constants.KEY_WINDOW_Y, None)
        )
        maximized = _coerce_bool(
            self.config.get(
                constants.SECTION_UI,
                constants.KEY_WINDOW_MAXIMIZED,
                constants.DEFAULT_WINDOW_MAXIMIZED,
            ),
            default=constants.DEFAULT_WINDOW_MAXIMIZED,
        )
        return WindowGeometry(
            width=width,
            height=height,
            x=x,
            y=y,
            maximized=maximized,
        )

    # --------------------------------------------------------------------------
    # Expanded branches
    # --------------------------------------------------------------------------
    def save_expanded_paths(self, paths: Iterable[Sequence[int]]) -> bool:
        """Persist the expanded display branches, de-duplicated and capped."""
        cleaned = _normalise_paths(paths)
        self._write_expanded_paths(cleaned)
        return self._save()

    def load_expanded_paths(self) -> Tuple[DisplayPath, ...]:
        """Return every saved display branch that is still structurally valid."""
        return tuple(_normalise_paths(self._raw_expanded_paths()))

    def save_expanded_nodes(self, node_ids: Iterable[int]) -> bool:
        """
        Compatibility helper (stage.md 7.1): persist expanded node ids.

        A bare node id cannot distinguish the two display instances of a
        multi-parent node, so it is stored as the one-element branch ``[id]``;
        :meth:`load_expanded_nodes` reads the deepest id back.
        """
        paths: List[DisplayPath] = []
        for node_id in node_ids or ():
            value = _coerce_int(node_id)
            if value is not None and value > 0:
                paths.append((value,))
        return self.save_expanded_paths(paths)

    def load_expanded_nodes(self) -> List[int]:
        """Node ids of the saved branches (deepest id of each branch)."""
        return [path[-1] for path in self.load_expanded_paths()]

    # --------------------------------------------------------------------------
    # Search dock
    # --------------------------------------------------------------------------
    def save_search_panel_visible(self, visible: bool) -> bool:
        self.config.set(
            constants.SECTION_UI,
            constants.KEY_SEARCH_PANEL_VISIBLE,
            bool(visible),
            save=False,
        )
        return self._save()

    def load_search_panel_visible(self) -> bool:
        return _coerce_bool(
            self.config.get(
                constants.SECTION_UI,
                constants.KEY_SEARCH_PANEL_VISIBLE,
                False,
            ),
            default=False,
        )

    # --------------------------------------------------------------------------
    # Combined close-time save
    # --------------------------------------------------------------------------
    def save_state(
        self,
        geometry: Any,
        *,
        maximized: bool = False,
        expanded_paths: Iterable[Sequence[int]] = (),
        search_panel_visible: bool = False,
    ) -> bool:
        """
        Write geometry, expanded branches and dock visibility in one file write.

        Used by ``MainWindow.closeEvent`` so a single config.json replacement
        covers the whole session state.
        """
        return self.save_window_state(
            geometry,
            maximized=maximized,
            expanded_paths=expanded_paths,
            search_panel_visible=search_panel_visible,
        )

    def save_window_state(
        self,
        geometry: Any,
        *,
        maximized: bool = False,
        expanded_paths: Iterable[Sequence[int]] = (),
        search_panel_visible: bool = False,
    ) -> bool:
        """Explicit variant of :meth:`save_state` with the maximised flag."""
        expanded = _normalise_paths(expanded_paths)
        values = _extract_geometry(geometry, maximized=maximized)
        if values is None:
            log_warning("Window geometry was not saved: unusable geometry value.")
            return False
        self._write_geometry(*values)
        self._write_expanded_paths(expanded)
        self.config.set(
            constants.SECTION_UI,
            constants.KEY_SEARCH_PANEL_VISIBLE,
            bool(search_panel_visible),
            save=False,
        )
        return self._save()

    # --------------------------------------------------------------------------
    # Internals
    # --------------------------------------------------------------------------
    def _write_geometry(
        self,
        width: int,
        height: int,
        x: Optional[int],
        y: Optional[int],
        maximized: bool,
    ) -> None:
        self.config.set(
            constants.SECTION_UI, constants.KEY_WINDOW_WIDTH, width, save=False
        )
        self.config.set(
            constants.SECTION_UI, constants.KEY_WINDOW_HEIGHT, height, save=False
        )
        self.config.set(
            constants.SECTION_UI, constants.KEY_WINDOW_X, x, save=False
        )
        self.config.set(
            constants.SECTION_UI, constants.KEY_WINDOW_Y, y, save=False
        )
        self.config.set(
            constants.SECTION_UI,
            constants.KEY_WINDOW_MAXIMIZED,
            bool(maximized),
            save=False,
        )

    def _write_expanded_paths(self, paths: List[DisplayPath]) -> None:
        self.config.set(
            constants.SECTION_UI,
            constants.KEY_EXPANDED_PATHS,
            [list(path) for path in paths],
            save=False,
        )

    def _raw_expanded_paths(self) -> Any:
        return self.config.get(
            constants.SECTION_UI, constants.KEY_EXPANDED_PATHS, []
        )

    def _save(self) -> bool:
        try:
            self.config.save()
        except OSError as error:
            log_warning(f"Could not persist UI settings: {error}")
            return False
        log_debug("UI settings saved.")
        return True


# ------------------------------------------------------------------------------
# Value coercion helpers
# ------------------------------------------------------------------------------
def _coerce_int(value: Any) -> Optional[int]:
    """Best-effort integer conversion that rejects bools and bad strings."""
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float) and value.is_integer():
        return int(value)
    if isinstance(value, str):
        text = value.strip()
        if text.lstrip("+-").isdigit():
            try:
                return int(text)
            except ValueError:
                return None
    return None


def _coerce_bool(value: Any, *, default: bool = False) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    if isinstance(value, str):
        text = value.strip().lower()
        if text in {"1", "true", "yes", "on"}:
            return True
        if text in {"0", "false", "no", "off"}:
            return False
    return default


def _clamp(value: int, minimum: int, maximum: int) -> int:
    return max(minimum, min(int(value), maximum))


def _extract_geometry(
    geometry: Any,
    *,
    maximized: Optional[bool] = None,
) -> Optional[Tuple[int, int, Optional[int], Optional[int], bool]]:
    """Return ``(width, height, x, y, maximized)`` from several input shapes."""
    if geometry is None:
        return None

    width = height = None
    x = y = None
    is_maximized = bool(maximized) if maximized is not None else False

    if isinstance(geometry, Mapping):
        width = _coerce_int(geometry.get("width"))
        height = _coerce_int(geometry.get("height"))
        x = _coerce_int(geometry.get("x"))
        y = _coerce_int(geometry.get("y"))
        if maximized is None:
            is_maximized = _coerce_bool(geometry.get("maximized"), default=False)
    elif isinstance(geometry, (tuple, list)):
        if len(geometry) == 2:
            width = _coerce_int(geometry[0])
            height = _coerce_int(geometry[1])
        elif len(geometry) >= 4:
            x = _coerce_int(geometry[0])
            y = _coerce_int(geometry[1])
            width = _coerce_int(geometry[2])
            height = _coerce_int(geometry[3])
            if len(geometry) >= 5 and maximized is None:
                is_maximized = _coerce_bool(geometry[4], default=False)
    else:
        # QRect/QRectF/QSize: all expose width()/height(); only rectangles
        # have x()/y(). Duck typing keeps Qt out of the module import path.
        width_getter = getattr(geometry, "width", None)
        height_getter = getattr(geometry, "height", None)
        if callable(width_getter) and callable(height_getter):
            width = _coerce_int(width_getter())
            height = _coerce_int(height_getter())
            x_getter = getattr(geometry, "x", None)
            y_getter = getattr(geometry, "y", None)
            if callable(x_getter) and callable(y_getter):
                x = _coerce_int(x_getter())
                y = _coerce_int(y_getter())

    if width is None or height is None:
        return None
    if width <= 0 or height <= 0:
        return None

    width = _clamp(width, constants.MIN_WINDOW_WIDTH, constants.MAX_WINDOW_WIDTH)
    height = _clamp(height, constants.MIN_WINDOW_HEIGHT, constants.MAX_WINDOW_HEIGHT)
    return width, height, x, y, is_maximized


def _normalise_paths(paths: Iterable[Sequence[int]]) -> List[DisplayPath]:
    """
    Validate, de-duplicate and cap persisted display branches.

    A path must contain at least one positive integer and may not exceed the
    projection depth guard. Deeper/duplicate entries are dropped rather than
    rejected so a hand-edited config cannot stop the application from starting.
    """
    cleaned: List[DisplayPath] = []
    seen = set()
    try:
        source = list(paths or ())
    except TypeError:
        return cleaned

    for raw in source:
        if isinstance(raw, (str, bytes)) or not isinstance(raw, Iterable):
            continue
        parts: List[int] = []
        valid = True
        for part in raw:
            value = _coerce_int(part)
            if value is None or value <= 0:
                valid = False
                break
            parts.append(value)
        if not valid or not parts:
            continue
        path = tuple(parts[: constants.TREE_MAX_DEPTH])
        if path in seen:
            continue
        seen.add(path)
        cleaned.append(path)

    # Parents first, so restoring them in order can reveal their children.
    cleaned.sort(key=lambda item: (len(item), item))
    return cleaned[: constants.MAX_SAVED_EXPANDED_PATHS]


# ==============================================================================
# End of settings_manager.py
# ==============================================================================
