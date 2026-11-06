# ==============================================================================
# main.py
# Application entry point for AP Library Manager.
# ==============================================================================
"""Start the desktop application.

Run from the project root:

    python main.py
"""
import platform
import sys
import traceback
from typing import List, Optional

from PySide6.QtCore import qVersion
from PySide6.QtWidgets import QApplication

from controllers.app_controller import AppController
from utils import constants
from utils.constants import APP_NAME, APP_VERSION
from utils.logger import (
    get_log_path,
    init_app_logging,
    log_exception,
    log_info,
    shutdown_logging,
)
from views.main_window import MainWindow


def _install_exception_hook() -> None:
    """Log any unhandled exception (with traceback) before the interpreter prints it."""

    def hook(exc_type, exc_value, exc_traceback) -> None:
        log_exception("Unhandled exception", exc_value)
        traceback.print_exception(exc_type, exc_value, exc_traceback)

    sys.excepthook = hook


def main(argv: Optional[List[str]] = None) -> int:
    """Create the QApplication, show the main window and enter the event loop."""
    args = list(sys.argv if argv is None else argv)
    init_app_logging()
    _install_exception_hook()
    log_info(f"Starting {APP_NAME} v{APP_VERSION}")
    log_info(
        f"Runtime: Python {platform.python_version()} / Qt {qVersion()} / "
        f"{platform.platform()}"
    )
    log_info(f"Application root: {constants.BASE_ROOT}")
    log_info(f"Configuration: {constants.CONFIG_PATH}")
    log_info(f"Log file: {get_log_path()}")

    app = QApplication(args)
    app.setApplicationName(APP_NAME)
    app.setApplicationDisplayName(APP_NAME)
    app.setApplicationVersion(APP_VERSION)

    controller = AppController()
    window = MainWindow(controller=controller)
    window.show()

    exit_code = app.exec()
    log_info(f"Exiting {APP_NAME}.")
    shutdown_logging()
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
