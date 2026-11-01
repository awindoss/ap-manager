# ==============================================================================
# utils/config_manager.py
# Read/write access to ``config.json`` (plan.md §33).
#
# Phase 4 only needs the PDF reader settings, but the loader is deliberately
# generic: it preserves unknown sections so later phases (window geometry,
# expanded state, theme) can add keys without losing hand-edited settings.
#
# Writes are atomic (temp file + ``os.replace``) and a corrupt config file is
# backed up before being replaced, so a bad edit never destroys the previous
# content silently.
# ==============================================================================
import json
import os
import shutil
from copy import deepcopy
from pathlib import Path
from typing import Any, Dict, Optional

from utils import constants
from utils.logger import log_debug, log_error, log_info, log_warning


DEFAULT_CONFIG: Dict[str, Any] = {
    constants.SECTION_PDF_READER: {
        constants.KEY_PDF_READER_PATH: "",
        constants.KEY_PDF_READER_ARGS: "",
    },
    constants.SECTION_UI: {
        constants.KEY_WINDOW_WIDTH: constants.DEFAULT_WINDOW_WIDTH,
        constants.KEY_WINDOW_HEIGHT: constants.DEFAULT_WINDOW_HEIGHT,
        constants.KEY_WINDOW_X: None,
        constants.KEY_WINDOW_Y: None,
    },
    constants.SECTION_LIBRARY: {
        constants.KEY_DB_PATH: constants.DEFAULT_DB_PATH_RELATIVE,
    },
}


class ConfigManager:
    """Loads, queries and persists the application configuration."""

    def __init__(
        self,
        config_path: Optional[str | Path] = None,
        *,
        autoload: bool = True,
    ) -> None:
        self.path: Path = (
            Path(config_path) if config_path is not None else Path(constants.CONFIG_PATH)
        )
        self._data: Dict[str, Any] = deepcopy(DEFAULT_CONFIG)
        self._needs_backup = False
        if autoload:
            self.load()

    # --------------------------------------------------------------------------
    # Loading / saving
    # --------------------------------------------------------------------------
    def load(self) -> Dict[str, Any]:
        """(Re)read the file, falling back to defaults on any problem."""
        self._data = deepcopy(DEFAULT_CONFIG)
        self._needs_backup = False

        if not self.path.is_file():
            log_debug(f"Config file not found; using defaults: {self.path}")
            return self._data

        try:
            raw_text = self.path.read_text(encoding="utf-8")
            raw = json.loads(raw_text)
        except (OSError, json.JSONDecodeError) as error:
            log_error(f"Could not read config {self.path}: {error}")
            self._needs_backup = True
            return self._data

        if not isinstance(raw, dict):
            log_error(f"Config {self.path} must contain a JSON object; using defaults.")
            self._needs_backup = True
            return self._data

        self._data = _merge_defaults(self._data, raw)
        log_debug(f"Loaded config from {self.path}.")
        return self._data

    def save(self) -> None:
        """
        Write the current configuration atomically.

        If the previous file could not be parsed, it is copied to
        ``<name>.bak`` first so the user can recover any hand-edited content.
        """
        self.path.parent.mkdir(parents=True, exist_ok=True)

        if self._needs_backup and self.path.is_file():
            backup = self.path.with_name(self.path.name + ".bak")
            try:
                shutil.copy2(self.path, backup)
                log_warning(f"Backed up unreadable config to {backup}.")
            except OSError as error:
                log_error(f"Could not back up config to {backup}: {error}")
            self._needs_backup = False

        temporary = self.path.with_name(self.path.name + ".tmp")
        try:
            temporary.write_text(
                json.dumps(self._data, ensure_ascii=False, indent=4) + "\n",
                encoding="utf-8",
            )
            os.replace(temporary, self.path)
        except OSError as error:
            log_error(f"Could not save config {self.path}: {error}")
            try:
                temporary.unlink(missing_ok=True)
            except OSError:
                pass
            raise

        log_debug(f"Saved config to {self.path}.")

    # --------------------------------------------------------------------------
    # Generic accessors
    # --------------------------------------------------------------------------
    @property
    def data(self) -> Dict[str, Any]:
        """A copy of the in-memory configuration."""
        return deepcopy(self._data)

    def get(self, section: str, key: str, default: Any = None) -> Any:
        section_value = self._data.get(section)
        if not isinstance(section_value, dict):
            return default
        return section_value.get(key, default)

    def set(self, section: str, key: str, value: Any, *, save: bool = True) -> None:
        section_value = self._data.get(section)
        if not isinstance(section_value, dict):
            section_value = {}
            self._data[section] = section_value
        section_value[key] = value
        if save:
            self.save()

    # --------------------------------------------------------------------------
    # PDF reader settings (Phase 4)
    # --------------------------------------------------------------------------
    def get_pdf_reader_path(self) -> str:
        """Configured reader executable, or ``""`` for the system default."""
        value = self.get(constants.SECTION_PDF_READER, constants.KEY_PDF_READER_PATH, "")
        return "" if value is None else str(value).strip()

    def set_pdf_reader_path(self, reader_path: object) -> None:
        value = "" if reader_path is None else str(reader_path).strip()
        self.set(
            constants.SECTION_PDF_READER,
            constants.KEY_PDF_READER_PATH,
            value,
        )
        log_info(
            "PDF reader setting updated: "
            + (value if value else "system default")
        )

    def get_pdf_reader_args(self) -> object:
        """Raw reader arguments (string or list; parsed by the launcher)."""
        return self.get(constants.SECTION_PDF_READER, constants.KEY_PDF_READER_ARGS, "")

    # --------------------------------------------------------------------------
    # Library settings
    # --------------------------------------------------------------------------
    def get_library_db_path(self) -> str:
        """Configured database path, falling back to the schema default."""
        value = self.get(
            constants.SECTION_LIBRARY,
            constants.KEY_DB_PATH,
            constants.DEFAULT_DB_PATH_RELATIVE,
        )
        text = "" if value is None else str(value).strip()
        return text or constants.DEFAULT_DB_PATH_RELATIVE


def _merge_defaults(defaults: Dict[str, Any], loaded: Dict[str, Any]) -> Dict[str, Any]:
    """
    Merge ``loaded`` into a copy of ``defaults``.

    Known sections are merged key by key so a partially written config still
    gets sane defaults; unknown top-level keys are preserved verbatim.
    """
    merged = deepcopy(defaults)
    for key, value in loaded.items():
        existing = merged.get(key)
        if isinstance(existing, dict) and isinstance(value, dict):
            existing.update(value)
        else:
            if key in defaults and not isinstance(value, type(defaults[key])):
                log_warning(
                    f"Config key {key!r} has an unexpected type "
                    f"({type(value).__name__}); keeping the default."
                )
                continue
            merged[key] = deepcopy(value)
    return merged


# ==============================================================================
# End of config_manager.py
# ==============================================================================
