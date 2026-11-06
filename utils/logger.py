# ==============================================================================
# utils/logger.py
# Logging for AP Library Manager (plan.md §39, stage.md Phase 7).
#
# Every module logs through the ``log_*`` helpers below. The file handler writes
# to ``logs/<app>_log.txt`` with rotation, so a long-running portable install
# cannot fill the disk; the console handler mirrors warnings and errors.
# ==============================================================================
"""Application logger.

Usage::

    from utils.logger import log_info, log_error, log_exception

    log_info("Operation completed")
    try:
        ...
    except Exception as error:
        log_exception("Operation failed", error)   # traceback goes to the log
        QMessageBox.critical(parent, "操作失败", describe_error(error))
"""

import json
import logging
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Optional, Union

from utils.constants import (
    BASE_ROOT,
    CONFIG_PATH,
    KEY_LOG_LEVEL,
    LOG_FILE_BACKUP_COUNT,
    LOG_FILE_MAX_BYTES,
    LOG_FILE_NAME,
    LOG_LEVEL_DEBUG,
    LOG_LEVEL_INFO,
    LOGS_DIR_NAME,
    SECTION_LOGGING,
)

logger_instance: Optional[logging.Logger] = None

LOGGER_NAME = "ap_logger"


# --------------------------------------------------------------------------
# 1. Configuration & setup
# --------------------------------------------------------------------------
def _get_log_file_path() -> Path:
    """Absolute path of the current log file (``logs/<app>_log.txt``)."""
    return BASE_ROOT / LOGS_DIR_NAME / LOG_FILE_NAME


def _configured_level() -> int:
    """
    Read ``logging.level`` from config.json without importing ConfigManager.

    Importing the config manager here would create a cycle (it logs while it
    loads), and the logger must stay usable even when the config file is broken.
    """
    try:
        raw = json.loads(Path(CONFIG_PATH).read_text(encoding="utf-8"))
        section = raw.get(SECTION_LOGGING, {})
        name = str(section.get(KEY_LOG_LEVEL, "INFO")).strip().upper()
    except (OSError, ValueError, TypeError, AttributeError):
        return LOG_LEVEL_INFO
    level = getattr(logging, name, None)
    return level if isinstance(level, int) else LOG_LEVEL_INFO


def _setup_logger(level: int) -> logging.Logger:
    """Create the file + console handlers once per process."""
    logger = logging.getLogger(LOGGER_NAME)

    if logger.handlers:
        return logger

    logger.setLevel(level)

    # Rotating file handler: logs/ is a runtime artifact (ignored by git).
    try:
        log_file_path = _get_log_file_path()
        log_file_path.parent.mkdir(parents=True, exist_ok=True)
        file_handler = RotatingFileHandler(
            str(log_file_path),
            maxBytes=LOG_FILE_MAX_BYTES,
            backupCount=LOG_FILE_BACKUP_COUNT,
            encoding="utf-8",
        )
        file_handler.setFormatter(
            logging.Formatter(
                fmt="[%(asctime)s] [%(levelname)s] [%(filename)s:%(lineno)d] %(message)s",
                datefmt="%Y-%m-%d %H:%M:%S",
            )
        )
        logger.addHandler(file_handler)
    except OSError as error:
        # A read-only install must still start; the console handler remains.
        sys.stderr.write(f"Cannot write log file: {error}\n")

    console_handler = logging.StreamHandler(sys.stderr)
    console_handler.setFormatter(logging.Formatter(fmt="%(levelname)s: %(message)s"))
    logger.addHandler(console_handler)
    return logger


# --------------------------------------------------------------------------
# 2. Convenience wrappers
# --------------------------------------------------------------------------
def _get_logger_instance() -> logging.Logger:
    global logger_instance
    if logger_instance is not None:
        return logger_instance
    logger_instance = _setup_logger(_configured_level())
    return logger_instance


def _log(level: int, msg: str) -> None:
    try:
        _get_logger_instance().log(level, msg)
    except Exception as error:  # pragma: no cover - logging must never crash the app
        sys.stderr.write(f"Failed to log message: {error}\n")


def log_debug(msg: str) -> None:
    _log(logging.DEBUG, msg)


def log_info(msg: str) -> None:
    _log(logging.INFO, msg)


def log_warning(msg: str) -> None:
    _log(logging.WARNING, msg)


def log_error(msg: str) -> None:
    _log(logging.ERROR, msg)


def log_critical(msg: str) -> None:
    _log(logging.CRITICAL, msg)


def log_exception(
    msg: str,
    error: Optional[BaseException] = None,
) -> None:
    """
    Log an exception with its traceback.

    Use inside ``except`` blocks; the traceback is what makes a user support
    report actionable while the UI only shows :func:`utils.error_messages.describe_error`.
    """
    if error is not None:
        msg = f"{msg}: {type(error).__name__}: {error}"
    try:
        _get_logger_instance().error(msg, exc_info=True)
    except Exception as log_error_value:  # pragma: no cover - defensive
        sys.stderr.write(f"Failed to log exception: {log_error_value}\n")


def get_log_path() -> Path:
    """Path of the current application log file."""
    return _get_log_file_path()


# --------------------------------------------------------------------------
# 3. Runtime level control / lifecycle
# --------------------------------------------------------------------------
def set_verbose_mode(enabled: bool = True) -> None:
    """Switch the logger (and its console handler) to DEBUG/INFO."""
    try:
        logger = _get_logger_instance()
        level = LOG_LEVEL_DEBUG if enabled else LOG_LEVEL_INFO
        logger.setLevel(level)
        for handler in logger.handlers:
            if isinstance(handler, logging.StreamHandler) and not isinstance(
                handler, logging.FileHandler
            ):
                handler.setLevel(level)
    except Exception:  # pragma: no cover - optional debugging aid
        pass


def init_app_logging(level: Union[int, str, None] = None) -> None:
    """
    Explicitly initialise the application logger.

    Called by main.py before the QApplication is created. ``level`` accepts a
    logging level or a name (``"DEBUG"``); when omitted, ``logging.level`` from
    config.json is used.
    """
    global logger_instance
    if isinstance(level, str):
        resolved = getattr(logging, level.strip().upper(), None)
        level = resolved if isinstance(resolved, int) else None
    if logger_instance is None:
        logger_instance = _setup_logger(level or _configured_level())
    else:
        logger_instance.setLevel(level or _configured_level())
    for handler in logger_instance.handlers:
        if isinstance(handler, logging.StreamHandler) and not isinstance(
            handler, logging.FileHandler
        ):
            handler.setFormatter(logging.Formatter(" %(levelname)s: %(message)s"))


def shutdown_logging() -> None:
    """
    Flush and detach every handler.

    The desktop application calls this on exit; tests also use it to rebuild
    the logger against a different working directory.
    """
    global logger_instance
    logger = logging.getLogger(LOGGER_NAME)
    for handler in list(logger.handlers):
        try:
            handler.flush()
        except Exception:
            pass
        try:
            handler.close()
        except Exception:
            pass
        logger.removeHandler(handler)
    logger_instance = None


# --------------------------------------------------------------------------
# End of logger.py
# --------------------------------------------------------------------------
