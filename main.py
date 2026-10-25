# ==============================================================================
# main.py
# Application entry point for AP Library Manager.
# ==============================================================================
"""Start the desktop application.

Run from the project root:

    python main.py
"""
import sys
import traceback
from typing import List, Optional

from PySide6.QtWidgets import QApplication

from controllers.app_controller import AppController
from utils.constants import APP_NAME, APP_VERSION
from utils.logger import init_app_logging, log_error, log_info
from views.main_window import MainWindow


def _install_exception_hook() -> None:
    """Log any unhandled exception before the interpreter prints it."""

    def hook(exc_type, exc_value, exc_traceback) -> None:
        log_error(
            "Unhandled exception: "
            + "".join(traceback.format_exception_only(exc_type, exc_value)).strip()
        )
        traceback.print_exception(exc_type, exc_value, exc_traceback)

    sys.excepthook = hook


def main(argv: Optional[List[str]] = None) -> int:
    """Create the QApplication, show the main window and enter the event loop."""
    args = list(sys.argv if argv is None else argv)
    init_app_logging()
    _install_exception_hook()
    log_info(f"Starting {APP_NAME} v{APP_VERSION}")

    app = QApplication(args)
    app.setApplicationName(APP_NAME)
    app.setApplicationDisplayName(APP_NAME)
    app.setApplicationVersion(APP_VERSION)

    controller = AppController()
    window = MainWindow(controller=controller)
    window.show()

    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
