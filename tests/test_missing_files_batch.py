# ==============================================================================
# tests/test_missing_files_batch.py
# Phase 7: batch re-location action in the missing-files dialog.
# ==============================================================================
from pathlib import Path

import pytest

pytest.importorskip("PySide6")

from PySide6.QtWidgets import QMessageBox

import views.dialogs.missing_files_dialog as missing_files_dialog
from controllers.app_controller import AppController, BatchRelinkOutcome, MissingPdf


def make_pdf(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"%PDF-1.4\n")
    return path


def test_batch_relink_uses_all_rows_when_nothing_is_selected(
    tmp_path, monkeypatch
) -> None:
    controller = AppController(db_path=tmp_path / "batch.db")
    controller.library.create_node("资本论", pdf_paths=["books/gone.pdf"])
    make_pdf(tmp_path / "recovered" / "gone.pdf")

    dialog = missing_files_dialog.MissingFilesDialog(
        controller,
        reveal_callback=None,
    )
    monkeypatch.setattr(
        missing_files_dialog.QFileDialog,
        "getExistingDirectory",
        staticmethod(lambda *args, **kwargs: str(tmp_path / "recovered")),
    )
    monkeypatch.setattr(
        missing_files_dialog.QMessageBox,
        "information",
        staticmethod(lambda *args, **kwargs: QMessageBox.StandardButton.Ok),
    )

    dialog.batch_relink_selected()

    assert dialog.changed is True
    assert dialog.table.rowCount() == 0
    assert "没有发现" in dialog.header_label.text()
    stored = controller.list_pdfs(controller.get_all_roots()[0].id)
    assert Path(stored[0]).name == "gone.pdf"
    assert Path(stored[0]).is_file()
    assert "已重新定位 1/1" in dialog.status_label.text()


def test_batch_relink_reports_partial_matches(
    tmp_path, monkeypatch
) -> None:
    controller = AppController(db_path=tmp_path / "batch_partial.db")
    controller.library.create_node(
        "Two books",
        pdf_paths=["books/found.pdf", "books/missing.pdf"],
    )
    make_pdf(tmp_path / "recovered" / "found.pdf")

    dialog = missing_files_dialog.MissingFilesDialog(controller)
    monkeypatch.setattr(
        missing_files_dialog.QFileDialog,
        "getExistingDirectory",
        staticmethod(lambda *args, **kwargs: str(tmp_path / "recovered")),
    )
    warnings = []
    monkeypatch.setattr(
        missing_files_dialog.QMessageBox,
        "warning",
        staticmethod(lambda *args, **kwargs: warnings.append(args)),
    )

    dialog.batch_relink_selected()

    assert dialog.table.rowCount() == 1
    assert "已重新定位 1/2" in dialog.status_label.text()
    assert "未能匹配" in dialog.status_label.text()
    assert warnings
    assert "没有找到同名文件" in warnings[0][2]


def test_batch_relink_reports_controller_errors(tmp_path, monkeypatch) -> None:
    controller = AppController(db_path=tmp_path / "batch_error.db")
    controller.library.create_node("A", pdf_paths=["books/gone.pdf"])
    dialog = missing_files_dialog.MissingFilesDialog(controller)
    monkeypatch.setattr(
        missing_files_dialog.QFileDialog,
        "getExistingDirectory",
        staticmethod(lambda *args, **kwargs: str(tmp_path)),
    )
    monkeypatch.setattr(
        controller,
        "relink_missing_from_folder",
        lambda *args, **kwargs: (_ for _ in ()).throw(ValueError("模拟失败")),
    )
    warnings = []
    monkeypatch.setattr(
        missing_files_dialog.QMessageBox,
        "warning",
        staticmethod(lambda *args, **kwargs: warnings.append(args)),
    )

    dialog.batch_relink_selected()

    assert warnings
    assert "模拟失败" in warnings[0][2]
    assert dialog.changed is False


def test_batch_button_is_disabled_without_entries() -> None:
    class EmptyController:
        def find_missing_pdfs(self):
            return []

    dialog = missing_files_dialog.MissingFilesDialog(EmptyController())

    assert dialog.batch_button.isEnabled() is False
    assert dialog.recursive_check.isChecked() is True


def test_batch_relink_passes_the_selection_and_options(tmp_path, monkeypatch) -> None:
    entries = [
        MissingPdf(1, "A", "books/a.pdf", Path("books/a.pdf")),
        MissingPdf(2, "B", "books/b.pdf", Path("books/b.pdf")),
    ]

    class BatchController:
        def __init__(self) -> None:
            self.calls = []

        def find_missing_pdfs(self):
            return list(entries)

        def relink_missing_from_folder(self, folder, **kwargs):
            self.calls.append((folder, kwargs))
            return BatchRelinkOutcome(
                search_root=Path(folder),
                requested=len(kwargs["entries"]),
                relinked=len(kwargs["entries"]),
            )

    controller = BatchController()
    dialog = missing_files_dialog.MissingFilesDialog(controller)
    dialog.table.selectRow(1)
    dialog.copy_check.setChecked(True)
    dialog.recursive_check.setChecked(False)
    monkeypatch.setattr(
        missing_files_dialog.QFileDialog,
        "getExistingDirectory",
        staticmethod(lambda *args, **kwargs: str(tmp_path)),
    )
    monkeypatch.setattr(
        missing_files_dialog.QMessageBox,
        "information",
        staticmethod(lambda *args, **kwargs: QMessageBox.StandardButton.Ok),
    )

    dialog.batch_relink_selected()

    assert len(controller.calls) == 1
    folder, kwargs = controller.calls[0]
    assert Path(folder) == tmp_path
    assert kwargs["entries"] == [entries[1]]
    assert kwargs["copy_to_books"] is True
    assert kwargs["recursive"] is False
