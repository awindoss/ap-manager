# ==============================================================================
# tests/test_controller_pdfs.py
# AppController PDF workflows: storage conversion, add/remove/relink, launch,
# missing-file inspection and reader settings (Phase 4).
# ==============================================================================
from pathlib import Path

import pytest

from controllers.app_controller import AppController, PdfAddResult
from services.pdf_launcher import LaunchReport, PdfLaunchError
from utils import constants
from utils.config_manager import ConfigManager


def make_pdf(path: Path, content: bytes = b"%PDF-1.4\n") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    return path


class FakeLauncher:
    """Records launches; fails when the file does not exist."""

    def __init__(self) -> None:
        self.reader_path = ""
        self.reader_args = []
        self.launched = []

    def set_reader_path(self, reader_path, reader_args=None) -> None:
        self.reader_path = "" if reader_path is None else str(reader_path)
        self.reader_args = list(reader_args or [])

    def launch(self, pdf_path) -> str:
        candidate = Path(pdf_path)
        if not candidate.is_file():
            raise PdfLaunchError(f"PDF 文件不存在：{candidate}")
        self.launched.append(str(candidate))
        return str(candidate)


@pytest.fixture
def app_root(tmp_path, monkeypatch) -> Path:
    root = tmp_path / "app"
    root.mkdir()
    # path_manager resolves relative paths against constants.BASE_ROOT at call
    # time, so patching it keeps the tests out of the real project directory.
    monkeypatch.setattr(constants, "BASE_ROOT", root)
    monkeypatch.setattr(constants, "BOOKS_PATH", root / constants.BOOKS_DIR_NAME)
    monkeypatch.setattr(constants, "CONFIG_PATH", root / constants.CONFIG_FILE_NAME)
    return root


@pytest.fixture
def controller(app_root: Path, tmp_path):
    config = ConfigManager(app_root / "config.json")
    launcher = FakeLauncher()
    app_controller = AppController(
        db_path=app_root / "data" / "test.db",
        config_manager=config,
        pdf_launcher=launcher,
    )
    return app_controller, launcher, config


# ------------------------------------------------------------------------------
# Adding
# ------------------------------------------------------------------------------
def test_add_pdf_inside_the_app_root_stores_a_relative_path(app_root, controller) -> None:
    app_controller, _launcher, _config = controller
    node_id = app_controller.create_node("资本论")
    pdf = make_pdf(app_root / "books" / "capital.pdf")

    result = app_controller.add_pdfs(node_id, [str(pdf)])

    assert isinstance(result, PdfAddResult)
    assert result.added == ["books/capital.pdf"]
    assert result.skipped == []
    assert result.errors == []
    assert app_controller.list_pdfs(node_id) == ["books/capital.pdf"]


def test_add_pdf_outside_the_app_root_stores_an_absolute_path(app_root, controller) -> None:
    app_controller, _launcher, _config = controller
    node_id = app_controller.create_node("Book")
    pdf = make_pdf(app_root.parent / "elsewhere" / "book.pdf")

    result = app_controller.add_pdfs(node_id, [str(pdf)])

    stored = result.added[0]
    assert Path(stored).is_absolute()
    assert stored == pdf.as_posix()


def test_add_pdfs_can_copy_into_books(app_root, controller) -> None:
    app_controller, _launcher, _config = controller
    node_id = app_controller.create_node("Book")
    pdf = make_pdf(app_root.parent / "downloads" / "book.pdf")

    result = app_controller.add_pdfs(node_id, [str(pdf)], copy_to_books=True)

    assert result.added == ["books/book.pdf"]
    assert (app_root / "books" / "book.pdf").is_file()


def test_add_pdfs_reports_duplicates_and_partial_failures(app_root, controller) -> None:
    app_controller, _launcher, _config = controller
    node_id = app_controller.create_node("Book")
    pdf = make_pdf(app_root / "books" / "a.pdf")
    text_file = app_root / "notes.txt"
    text_file.write_text("x", encoding="utf-8")

    first = app_controller.add_pdfs(node_id, [str(pdf)])
    assert first.added == ["books/a.pdf"]

    second = app_controller.add_pdfs(
        node_id,
        [str(pdf), str(text_file), str(app_root / "missing.pdf")],
    )

    assert second.added == []
    assert second.skipped == [str(pdf)]
    assert len(second.errors) == 2
    assert second.has_errors is True
    assert second.has_changes is False
    assert app_controller.list_pdfs(node_id) == ["books/a.pdf"]


def test_add_pdfs_with_no_input_is_a_no_op(app_root, controller) -> None:
    app_controller, _launcher, _config = controller
    node_id = app_controller.create_node("Book")

    result = app_controller.add_pdfs(node_id, [])

    assert result == PdfAddResult(added=[], skipped=[], errors=[])


def test_add_pdfs_requires_an_existing_node(app_root, controller) -> None:
    app_controller, _launcher, _config = controller

    with pytest.raises(ValueError):
        app_controller.add_pdfs(999, ["books/a.pdf"])


# ------------------------------------------------------------------------------
# Removing / re-linking
# ------------------------------------------------------------------------------
def test_remove_pdfs(app_root, controller) -> None:
    app_controller, _launcher, _config = controller
    node_id = app_controller.create_node("Book")
    app_controller.add_pdfs(
        node_id,
        [
            str(make_pdf(app_root / "books" / "a.pdf")),
            str(make_pdf(app_root / "books" / "b.pdf")),
        ],
    )

    removed = app_controller.remove_pdfs(node_id, ["books/a.pdf", "books/gone.pdf"])

    assert removed == 1
    assert app_controller.list_pdfs(node_id) == ["books/b.pdf"]
    assert (app_root / "books" / "a.pdf").is_file()  # never deletes files


def test_relink_pdf_updates_the_path_in_place(app_root, controller) -> None:
    app_controller, _launcher, _config = controller
    node_id = app_controller.create_node("Book")
    app_controller.add_pdfs(
        node_id,
        [
            str(make_pdf(app_root / "books" / "a.pdf")),
            str(make_pdf(app_root / "books" / "b.pdf")),
        ],
    )
    replacement = make_pdf(app_root / "books" / "b-new.pdf")

    stored = app_controller.relink_pdf(node_id, "books/b.pdf", str(replacement))

    assert stored == "books/b-new.pdf"
    assert app_controller.list_pdfs(node_id) == ["books/a.pdf", "books/b-new.pdf"]


def test_relink_pdf_can_copy_the_replacement_into_books(app_root, controller) -> None:
    app_controller, _launcher, _config = controller
    node_id = app_controller.create_node("Book")
    app_controller.add_pdfs(node_id, [str(make_pdf(app_root / "books" / "a.pdf"))])
    replacement = make_pdf(app_root.parent / "downloads" / "new.pdf")

    stored = app_controller.relink_pdf(
        node_id,
        "books/a.pdf",
        str(replacement),
        copy_to_books=True,
    )

    assert stored == "books/new.pdf"
    assert app_controller.list_pdfs(node_id) == ["books/new.pdf"]


def test_relink_pdf_rejects_invalid_requests(app_root, controller) -> None:
    app_controller, _launcher, _config = controller
    node_id = app_controller.create_node("Book")
    app_controller.add_pdfs(
        node_id,
        [
            str(make_pdf(app_root / "books" / "a.pdf")),
            str(make_pdf(app_root / "books" / "b.pdf")),
        ],
    )

    with pytest.raises(ValueError):
        app_controller.relink_pdf(node_id, "", "books/new.pdf")
    with pytest.raises(ValueError):
        app_controller.relink_pdf(node_id, "books/unknown.pdf", "books/new.pdf")
    with pytest.raises(ValueError):
        app_controller.relink_pdf(node_id, "books/a.pdf", "books/b.pdf")


# ------------------------------------------------------------------------------
# Opening
# ------------------------------------------------------------------------------
def test_open_pdf_uses_the_launcher(app_root, controller) -> None:
    app_controller, launcher, _config = controller
    node_id = app_controller.create_node("Book")
    pdf = make_pdf(app_root / "books" / "a.pdf")
    app_controller.add_pdfs(node_id, [str(pdf)])

    assert app_controller.open_pdf("books/a.pdf") is True
    assert len(launcher.launched) == 1
    assert Path(launcher.launched[0]) == pdf


def test_open_pdf_reports_a_missing_file(app_root, controller) -> None:
    app_controller, launcher, _config = controller

    with pytest.raises(PdfLaunchError):
        app_controller.open_pdf("books/gone.pdf")

    assert launcher.launched == []


def test_open_pdfs_and_open_node_pdfs_collect_failures(app_root, controller) -> None:
    app_controller, launcher, _config = controller
    node_id = app_controller.create_node("Book")
    existing = make_pdf(app_root / "books" / "a.pdf")
    missing = make_pdf(app_root / "books" / "gone.pdf")
    app_controller.add_pdfs(node_id, [str(existing), str(missing)])
    missing.unlink()

    report = app_controller.open_node_pdfs(node_id)

    assert isinstance(report, LaunchReport)
    assert report.opened == ["books/a.pdf"]
    assert [path for path, _message in report.failures] == ["books/gone.pdf"]
    assert len(launcher.launched) == 1
    assert Path(launcher.launched[0]) == existing

    assert app_controller.open_pdfs([]).failure_count == 0


# ------------------------------------------------------------------------------
# Inspection
# ------------------------------------------------------------------------------
def test_inspect_pdfs_reports_missing_entries(app_root, controller) -> None:
    app_controller, _launcher, _config = controller
    first = app_controller.create_node("Capital")
    second = app_controller.create_node("Other")
    missing_a = make_pdf(app_root / "books" / "missing-a.pdf")
    missing_b = make_pdf(app_root / "books" / "missing-b.pdf")
    app_controller.add_pdfs(
        first,
        [
            str(make_pdf(app_root / "books" / "a.pdf")),
            str(missing_a),
            str(make_pdf(app_root / "books" / "b.pdf")),
        ],
    )
    app_controller.add_pdfs(second, [str(missing_b)])
    # Simulate files that disappeared after they were classified.
    missing_a.unlink()
    missing_b.unlink()

    inspection = app_controller.inspect_pdfs()

    assert inspection.nodes_with_pdfs == 2
    assert inspection.total_pdfs == 4
    assert inspection.existing_count == 2
    assert len(inspection.missing) == 2
    assert [entry.node_id for entry in inspection.missing] == [first, second]
    assert [entry.stored_path for entry in inspection.missing] == [
        "books/missing-a.pdf",
        "books/missing-b.pdf",
    ]
    assert [entry.node_name for entry in inspection.missing] == ["Capital", "Other"]
    assert app_controller.find_missing_pdfs() == inspection.missing


def test_inspect_pdfs_with_no_pdfs(app_root, controller) -> None:
    app_controller, _launcher, _config = controller
    app_controller.create_node("Empty")

    inspection = app_controller.inspect_pdfs()

    assert inspection.total_pdfs == 0
    assert inspection.missing == []
    assert app_controller.find_missing_pdfs() == []


# ------------------------------------------------------------------------------
# Reader settings
# ------------------------------------------------------------------------------
def test_reader_setting_is_persisted_and_applied(app_root, controller) -> None:
    app_controller, launcher, config = controller
    reader = app_root / "tools" / "reader.exe"
    reader.parent.mkdir()
    reader.write_bytes(b"")

    stored = app_controller.set_pdf_reader_path(str(reader))

    assert stored == str(reader)
    assert app_controller.get_pdf_reader_path() == str(reader)
    assert app_controller.get_pdf_reader_label() == str(reader)
    assert launcher.reader_path == str(reader)

    reloaded = ConfigManager(app_root / "config.json")
    assert reloaded.get_pdf_reader_path() == str(reader)

    app_controller.set_pdf_reader_path("")
    assert app_controller.get_pdf_reader_label() == "系统默认阅读器"
    assert launcher.reader_path == ""


def test_reader_setting_rejects_a_missing_executable(app_root, controller) -> None:
    app_controller, launcher, _config = controller

    with pytest.raises(ValueError):
        app_controller.set_pdf_reader_path(str(app_root / "tools" / "missing.exe"))

    assert app_controller.get_pdf_reader_path() == ""


def test_relative_reader_path_is_resolved_against_the_app_root(app_root) -> None:
    reader = app_root / "tools" / "reader.exe"
    reader.parent.mkdir(parents=True)
    reader.write_bytes(b"")
    config = ConfigManager(app_root / "config.json")
    config.set(
        constants.SECTION_PDF_READER,
        constants.KEY_PDF_READER_PATH,
        "tools/reader.exe",
    )

    app_controller = AppController(
        db_path=app_root / "data" / "reader.db",
        config_manager=config,
        pdf_launcher=FakeLauncher(),
    )

    assert app_controller.get_pdf_reader_path() == str(reader)


def test_library_db_path_comes_from_config(tmp_path, monkeypatch) -> None:
    root = tmp_path / "app"
    root.mkdir()
    monkeypatch.setattr(constants, "BASE_ROOT", root)
    config = ConfigManager(root / "config.json")
    config.set(constants.SECTION_LIBRARY, constants.KEY_DB_PATH, "custom/library.db")

    app_controller = AppController(
        config_manager=config,
        pdf_launcher=FakeLauncher(),
    )

    assert Path(app_controller.library.db.db_path) == root / "custom" / "library.db"
