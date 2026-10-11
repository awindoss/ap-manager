# ==============================================================================
# utils/logger.py
# Logger utility for AP Library Manager
# ==============================================================================
"""
Logger module for AP Library Manager.
Provides structured logging to file and stderr as appropriate for desktop apps.
Based on plan.md (Section 39: Error Handling, Phase 1 & Phase 7 tasks) and stage.md.
Usage:
    from logger import log_info, log_error
    log_info("Operation completed")
"""

import sys
import logging
from pathlib import Path
from utils.constants import BASE_ROOT, LOGS_DIR_NAME, LOG_FILE_NAME, LOG_LEVEL_INFO, LOG_LEVEL_DEBUG

logger_instance: logging.Logger | None = None

# --------------------------------------------------------------------------
# 1. Configuration & Setup
# --------------------------------------------------------------------------

def _get_log_file_path() -> Path:
    """
    Returns the absolute path for the log file.
    Relies on the logic in constants.py (BASE_ROOT) but ensures portability.
    """
    log_dir = BASE_ROOT / LOGS_DIR_NAME
    log_file_name = LOG_FILE_NAME
    return log_dir / log_file_name

def _setup_logger(level: int) -> logging.Logger:
    """
    Sets up the logger instance with a file handler and console handler.
    Ensures the log directory exists before writing.
    """
    logger = logging.getLogger("ap_logger")

    if logger.handlers:
        return logger

    logger.setLevel(level)

    log_file_path = _get_log_file_path()
    
    # Ensure logs directory exists
    try:
        log_dir = log_file_path.parent
        log_dir.mkdir(parents=True, exist_ok=True)
        
        # Create or open the log file (append mode)
        handler = logging.FileHandler(str(log_file_path), encoding='utf-8')
        handler.setFormatter(logging.Formatter(
            fmt="[%(asctime)s] [%(levelname)s] [%(filename)s:%(lineno)d] %(message)s",
            datefmt='%Y-%m-%d %H:%M:%S'
        ))
        logger.addHandler(handler)
    except OSError as e:
        # If we cannot write to the intended location (e.g., /), log a warning
        sys.stderr.write(f"Cannot write log file: {e}\n")
        
    console_handler = logging.StreamHandler(sys.stderr)
    console_handler.setFormatter(logging.Formatter(
        fmt="%(levelname)s: %(message)s",
    ))
    logger.addHandler(console_handler)

    return logger

# Note: if file handler creation fails, we intentionally do not retry during this run.

# --------------------------------------------------------------------------
# 2. Convenience Wrappers
# --------------------------------------------------------------------------

# The main logger instance will be initialized when first used or explicitly called in main.py
def _get_logger_instance() -> logging.Logger:
    global logger_instance
    if logger_instance is not None:
        return logger_instance
    logger_instance = _setup_logger(LOG_LEVEL_INFO)
    return logger_instance

def log_debug(msg: str) -> None:
    try:
        _get_logger_instance().debug(msg)
    except Exception as e:
        sys.stderr.write(f"Failed to log debug: {e}\n")

def log_info(msg: str) -> None:
    try:
        _get_logger_instance().info(msg)
    except Exception as e:
        sys.stderr.write(f"Failed to log info: {e}\n")

def log_warning(msg: str) -> None:
    try:
        _get_logger_instance().warning(msg)
    except Exception as e:
        sys.stderr.write(f"Failed to log warning: {e}\n")

def log_error(msg: str) -> None:
    try:
        _get_logger_instance().error(msg)
    except Exception as e:
        sys.stderr.write(f"Failed to log error: {e}\n")

def log_critical(msg: str) -> None:
    try:
        _get_logger_instance().critical(msg)
    except Exception as e:
        sys.stderr.write(f"Failed to log critical: {e}\n")

def get_log_path() -> Path:
    """Returns the path to the current application's log file."""
    return _get_log_file_path()

# --------------------------------------------------------------------------
# 3. Utility for Debugging/Verbose Mode (Optional)
# --------------------------------------------------------------------------

def set_verbose_mode(enabled: bool = True) -> None:
    """
    Optional utility to change logging level if needed in future phases.
    Currently defaults to INFO on startup, WARNING/ERROR printed.
    In Phase 7, we might store this setting in config.json.
    """
    try:
        logger = _get_logger_instance()
        # Adjust console handler level to match file or be more verbose
        for h in logger.handlers:
            if isinstance(h, logging.StreamHandler) and not isinstance(h, logging.FileHandler):
                h.setLevel(logging.DEBUG if enabled else logging.INFO)
        logger_instance.setLevel(LOG_LEVEL_DEBUG if enabled else LOG_LEVEL_INFO)
    except Exception:
        pass

# --------------------------------------------------------------------------
# 4. Initialization Trigger
# --------------------------------------------------------------------------

def init_app_logging() -> None:
    """
    Explicitly initializes the app logger. 
    Call this in main.py at startup, before creating QApplication.
    """
    global logger_instance
    if logger_instance is None:
        logger_instance = _get_logger_instance()
    # Ensure console handler isn't blocked or filtered unexpectedly
    for handler in logger_instance.handlers:
        if isinstance(handler, logging.StreamHandler) and not isinstance(handler, logging.FileHandler):
            handler.setFormatter(logging.Formatter(" %(levelname)s: %(message)s"))

# --------------------------------------------------------------------------
# End of logger.py
# --------------------------------------------------------------------------
