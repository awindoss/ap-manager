# ==============================================================================
# tests/test_logger.py
# Phase 7: file logging, tracebacks and log rotation.
# ==============================================================================
import logging
from logging.handlers import RotatingFileHandler
import uuid

from utils import constants
from utils import logger as logger_module


def read_current_log() -> str:
    path = logger_module.get_log_path()
    assert path.is_file()
    return path.read_text(encoding="utf-8", errors="replace")


def flush_handlers() -> None:
    for handler in logger_module._get_logger_instance().handlers:
        handler.flush()


def test_log_file_lives_under_logs_and_records_messages() -> None:
    token = f"phase7-info-{uuid.uuid4().hex}"

    logger_module.log_info(token)
    flush_handlers()

    assert logger_module.get_log_path().parent.name == constants.LOGS_DIR_NAME
    assert token in read_current_log()


def test_log_exception_writes_the_traceback() -> None:
    token = f"phase7-error-{uuid.uuid4().hex}"

    try:
        raise ValueError("boom")
    except ValueError as error:
        logger_module.log_exception(token, error)
    flush_handlers()

    log_text = read_current_log()
    assert token in log_text
    assert "Traceback" in log_text
    assert "ValueError: boom" in log_text


def test_file_handler_rotates() -> None:
    logger = logger_module._get_logger_instance()

    rotating_handlers = [
        handler
        for handler in logger.handlers
        if isinstance(handler, RotatingFileHandler)
    ]

    assert rotating_handlers
    assert rotating_handlers[0].maxBytes == constants.LOG_FILE_MAX_BYTES
    assert rotating_handlers[0].backupCount == constants.LOG_FILE_BACKUP_COUNT


def test_verbose_mode_switches_levels() -> None:
    logger_module.set_verbose_mode(True)
    try:
        assert logger_module._get_logger_instance().level == logging.DEBUG
    finally:
        logger_module.set_verbose_mode(False)
    assert logger_module._get_logger_instance().level == logging.INFO


def test_shutdown_logging_removes_handlers() -> None:
    logger_module._get_logger_instance()

    logger_module.shutdown_logging()

    assert logging.getLogger(logger_module.LOGGER_NAME).handlers == []
    # The next call must transparently rebuild the file + console handlers.
    logger_module.log_info("logger rebuilt")
    assert logger_module._get_logger_instance().handlers
