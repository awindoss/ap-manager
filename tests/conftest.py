# ==============================================================================
# tests/conftest.py
# Shared fixtures for the test suite.
# ==============================================================================
import os

# The GUI tests must run headless (CI, plain terminals). The platform plugin
# has to be selected before PySide6 is imported, which is why this lives in
# conftest.py rather than in an individual test module.
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest


@pytest.fixture(autouse=True)
def isolated_default_config(tmp_path, monkeypatch):
    """
    Keep tests away from the developer's real config.json.

    AppController/MainWindow read ``constants.CONFIG_PATH`` when no explicit
    ConfigManager is supplied. Pointing it at a per-test temp path also lets the
    Phase 7 state-persistence tests run without touching the repository file.
    """
    from utils import constants

    monkeypatch.setattr(constants, "CONFIG_PATH", tmp_path / "config.json")
    yield


@pytest.fixture(scope="session")
def qapp():
    """
    Provide a single QApplication for the whole test session.

    Qt allows only one application object per process, and creating widgets
    without one aborts, so every GUI test depends on this fixture (directly or
    through `pytestmark`).
    """
    pytest.importorskip("PySide6")
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    yield app
