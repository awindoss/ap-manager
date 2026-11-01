# ==============================================================================
# tests/test_pdf_dialogs.py
# PDF management / selector / settings / missing-files dialogs (Phase 4).
# ==============================================================================
from pathlib import Path

import pytest

pytest.importorskip("PySide6")

from PySide6.QtWidgets import QDialog, QMessageBox

from controllers.app_controller import MissingPdf, PdfAddResult
from services.path_manager import PdfFile
from services.pdf_launcher import LaunchReport
from utils import constants
from views.dialogs import (
    missing_files_dialog,
    pdf_management_dialog,
    pdf_selector_dialog,
    settings_dialog,
)
from views.dialogs.missing_files_dialog import MissingFilesDialog
from views.dialogs.pdf_management_dialog import PdfManagementDialog
from views.dialogs.pdf_selector_dialog import PdfSelectorDialog
from views.dialogs.settings_dialog import SettingsDialog

pytestmark = pytest.mark.usefixtures("qapp")


def pdf_file(stored: str, exists: bool = True) -> PdfFile:
    return PdfFile(stored_path=stored, absolute_path=Path(stored), exists=exists)


class FakeController:
    def __init__(self, node_name: str = "资本论", files=None) -> None:
        self.node_name = node_name
        self.pdfs = list(files or [])
        self.add_calls = []
        self.remove_calls = []
        self.relink_calls = []
        self.open_calls = []
        self.open_all_calls = []
        self.add_result = None

    def get_node(self, node_id):
        if node_id != 1:
            return None

        class _Node:
            name = self.node_name
            id = 1

        return _Node()

    def describe_pdfs(self, node_id):
        return list(self.pdfs)

    def add_pdfs(self, node_id, paths, copy_to_books=False):
        self.add_calls.append((list(paths), copy_to_books))
        if self.add_result is not None:
            return self.add_result
        added = []
        for path in paths:
            stored = str(path)
            self.pdfs.append(pdf_file(stored))
            added.append(stored)
        return PdfAddResult(added=added, skipped=[], errors=[])

    def remove_pdfs(self, node_id, paths):
        self.remove_calls.append(list(paths))
        before = len(self.pdfs)
        self.pdfs = [f for f in self.pdfs if f.stored_path not in paths]
        return before - len(self.pdfs)

    def relink_pdf(self, node_id, stored_path, new_source, copy_to_books=False):
        self.relink_calls.append((stored_path, str(new_source), copy_to_books))
        for index, pdf in enumerate(self.pdfs):
            if pdf.stored_path == stored_path:
                self.pdfs[index] = pdf_file(str(new_source))
                return str(new_source)
        raise ValueError("该 PDF 不在当前节点中。")

    def open_pdfs(self, paths):
        self.open_calls.append(list(paths))
        return LaunchReport(opened=list(paths))

    def open_node_pdfs(self, node_id):
        self.open_all_calls.append(node_id)
        return LaunchReport(opened=[f.stored_path for f in self.pdfs])


def select_first_row(dialog) -> None:
    dialog.list_widget.setCurrentRow(0)
    dialog.list_widget.item(0).setSelected(True)
    dialog._update_button_states()


# ------------------------------------------------------------------------------
# PdfManagementDialog
# ------------------------------------------------------------------------------
def test_management_dialog_requires_an_existing_node() -> None:
    with pytest.raises(ValueError):
        PdfManagementDialog(FakeController(), 999)


def test_management_dialog_lists_files_and_marks_missing_ones() -> None:
    controller = FakeController(files=[pdf_file("books/a.pdf"), pdf_file("books/gone.pdf", False)])

    dialog = PdfManagementDialog(controller, 1)

    assert dialog.list_widget.count() == 2
    assert "缺失" in dialog.list_widget.item(1).text()
    assert constants.WARNING_ICON_MISSING_FILE in dialog.list_widget.item(1).text()
    assert "1 个缺失" in dialog.header_label.text()
    assert dialog.remove_button.isEnabled() is True
    assert dialog.open_all_button.isEnabled() is True


def test_management_dialog_preselects_a_requested_path() -> None:
    controller = FakeController(files=[pdf_file("books/a.pdf"), pdf_file("books/b.pdf")])

    dialog = PdfManagementDialog(controller, 1, select_path="books/b.pdf")

    assert [pdf.stored_path for pdf in dialog.selected_files()] == ["books/b.pdf"]


def test_management_dialog_empty_state_disables_actions() -> None:
    dialog = PdfManagementDialog(FakeController(files=[]), 1)

    assert dialog.list_widget.count() == 0
    assert dialog.remove_button.isEnabled() is False
    assert dialog.open_button.isEnabled() is False
    assert dialog.relink_button.isEnabled() is False
    assert dialog.open_all_button.isEnabled() is False


def test_management_add_uses_selected_copy_mode(monkeypatch, tmp_path) -> None:
    controller = FakeController(files=[])
    dialog = PdfManagementDialog(controller, 1)
    first = tmp_path / "a.pdf"
    second = tmp_path / "b.pdf"
    monkeypatch.setattr(
        pdf_management_dialog.QFileDialog,
        "getOpenFileNames",
        staticmethod(lambda *args, **kwargs: ([str(first), str(second)], "")),
    )
    dialog.copy_check.setChecked(True)

    dialog.add_files()

    assert controller.add_calls == [([str(first), str(second)], True)]
    assert dialog.list_widget.count() == 2
    assert "已添加 2 个 PDF" in dialog.status_label.text()


def test_management_add_reports_partial_errors(monkeypatch, tmp_path) -> None:
    controller = FakeController(files=[])
    controller.add_result = PdfAddResult(
        added=["books/ok.pdf"],
        skipped=["books/dup.pdf"],
        errors=[("bad.txt", "不支持的文件类型")],
    )
    controller.pdfs = [pdf_file("books/ok.pdf")]
    warnings = []
    monkeypatch.setattr(
        pdf_management_dialog.QFileDialog,
        "getOpenFileNames",
        staticmethod(lambda *args, **kwargs: (["books/ok.pdf", "books/dup.pdf", "bad.txt"], "")),
    )
    monkeypatch.setattr(
        pdf_management_dialog.QMessageBox,
        "warning",
        staticmethod(lambda *args, **kwargs: warnings.append(args)),
    )
    dialog = PdfManagementDialog(controller, 1)

    dialog.add_files()

    assert warnings
    assert "跳过 1 个" in dialog.status_label.text()
    assert "1 个文件添加失败" in dialog.status_label.text()


def test_management_add_cancel_does_nothing(monkeypatch) -> None:
    controller = FakeController(files=[])
    dialog = PdfManagementDialog(controller, 1)
    monkeypatch.setattr(
        pdf_management_dialog.QFileDialog,
        "getOpenFileNames",
        staticmethod(lambda *args, **kwargs: ([], "")),
    )

    dialog.add_files()

    assert controller.add_calls == []


def test_management_remove_confirms_and_removes(monkeypatch) -> None:
    controller = FakeController(files=[pdf_file("books/a.pdf"), pdf_file("books/b.pdf")])
    dialog = PdfManagementDialog(controller, 1)
    select_first_row(dialog)
    questions = []
    monkeypatch.setattr(
        pdf_management_dialog.QMessageBox,
        "question",
        staticmethod(lambda *args, **kwargs: questions.append(args) or QMessageBox.StandardButton.Yes),
    )

    dialog.remove_selected()

    assert questions
    assert controller.remove_calls == [["books/a.pdf"]]
    assert dialog.list_widget.count() == 1
    assert "已从节点移除 1 个" in dialog.status_label.text()


def test_management_remove_cancel_keeps_files(monkeypatch) -> None:
    controller = FakeController(files=[pdf_file("books/a.pdf")])
    dialog = PdfManagementDialog(controller, 1)
    select_first_row(dialog)
    monkeypatch.setattr(
        pdf_management_dialog.QMessageBox,
        "question",
        staticmethod(lambda *args, **kwargs: QMessageBox.StandardButton.No),
    )

    dialog.remove_selected()

    assert controller.remove_calls == []
    assert dialog.list_widget.count() == 1


def test_management_remove_without_selection_reports() -> None:
    controller = FakeController(files=[])
    dialog = PdfManagementDialog(controller, 1)

    dialog.remove_selected()

    assert "请先选择" in dialog.status_label.text()


def test_management_relink_updates_the_file(monkeypatch, tmp_path) -> None:
    controller = FakeController(files=[pdf_file("books/gone.pdf", False)])
    dialog = PdfManagementDialog(controller, 1)
    select_first_row(dialog)
    replacement = tmp_path / "found.pdf"
    monkeypatch.setattr(
        pdf_management_dialog.QFileDialog,
        "getOpenFileName",
        staticmethod(lambda *args, **kwargs: (str(replacement), "")),
    )

    dialog.relink_selected()

    assert controller.relink_calls == [("books/gone.pdf", str(replacement), False)]
    assert dialog.list_widget.count() == 1
    assert "已更新 PDF 位置" in dialog.status_label.text()


def test_management_relink_requires_exactly_one_selection() -> None:
    controller = FakeController(files=[pdf_file("books/a.pdf"), pdf_file("books/b.pdf")])
    dialog = PdfManagementDialog(controller, 1)
    dialog.list_widget.item(0).setSelected(True)
    dialog.list_widget.item(1).setSelected(True)
    dialog._update_button_states()

    dialog.relink_selected()

    assert "选择一个" in dialog.status_label.text()
    assert controller.relink_calls == []


def test_management_open_selected_and_all() -> None:
    controller = FakeController(files=[pdf_file("books/a.pdf"), pdf_file("books/b.pdf")])
    dialog = PdfManagementDialog(controller, 1)
    select_first_row(dialog)

    dialog.open_selected()
    assert controller.open_calls == [["books/a.pdf"]]
    assert "已打开 1 个 PDF" in dialog.status_label.text()

    dialog.open_all()
    assert controller.open_all_calls == [1]


def test_management_open_failures_are_reported(monkeypatch) -> None:
    controller = FakeController(files=[pdf_file("books/a.pdf")])
    dialog = PdfManagementDialog(controller, 1)
    warnings = []
    monkeypatch.setattr(
        pdf_management_dialog.QMessageBox,
        "warning",
        staticmethod(lambda *args, **kwargs: warnings.append(args)),
    )

    dialog._report_launch(
        LaunchReport(opened=[], failures=[("books/a.pdf", "PDF 文件不存在")])
    )

    assert warnings


# ------------------------------------------------------------------------------
# PdfSelectorDialog
# ------------------------------------------------------------------------------
def test_selector_lists_files_and_selects_first_existing() -> None:
    dialog = PdfSelectorDialog(
        "资本论",
        [pdf_file("books/a.pdf"), pdf_file("books/b.pdf")],
    )

    assert dialog.list_widget.count() == 2
    assert dialog.selected_pdf().stored_path == "books/a.pdf"
    assert dialog.open_button.isEnabled() is True
    assert "资本论" in dialog.windowTitle()


def test_selector_marks_missing_and_disables_opening() -> None:
    dialog = PdfSelectorDialog("资本论", [pdf_file("books/gone.pdf", False)])

    item = dialog.list_widget.item(0)
    assert "缺失" in item.text()
    assert dialog.open_button.isEnabled() is False


def test_selector_accept_opens_an_existing_file() -> None:
    dialog = PdfSelectorDialog("资本论", [pdf_file("books/a.pdf")])

    assert dialog.selected_pdf().stored_path == "books/a.pdf"
    dialog._on_accept()

    assert dialog.result() == int(QDialog.DialogCode.Accepted)


def test_selector_rejects_a_missing_file_with_a_warning(monkeypatch) -> None:
    warnings = []
    monkeypatch.setattr(
        pdf_selector_dialog.QMessageBox,
        "warning",
        staticmethod(lambda *args, **kwargs: warnings.append(args)),
    )
    dialog = PdfSelectorDialog("资本论", [pdf_file("books/gone.pdf", False)])
    dialog.list_widget.setCurrentRow(0)

    dialog._on_accept()

    assert warnings
    assert dialog.result() != int(QDialog.DialogCode.Accepted)


def test_selector_double_click_opens_the_item() -> None:
    dialog = PdfSelectorDialog("资本论", [pdf_file("books/a.pdf")])

    dialog._on_item_double_clicked(dialog.list_widget.item(0))

    assert dialog.result() == int(QDialog.DialogCode.Accepted)


# ------------------------------------------------------------------------------
# SettingsDialog
# ------------------------------------------------------------------------------
def test_settings_prefills_and_returns_reader_path() -> None:
    dialog = SettingsDialog("C:/Tools/reader.exe")

    assert dialog.reader_edit.text() == "C:/Tools/reader.exe"
    assert dialog.reader_path() == "C:/Tools/reader.exe"


def test_settings_default_button_clears_the_reader(tmp_path) -> None:
    dialog = SettingsDialog("C:/Tools/reader.exe")

    dialog.default_button.click()

    assert dialog.reader_path() == ""
    assert "留空" in dialog.hint_label.text()
    assert "默认" in dialog.hint_label.text()


def test_settings_rejects_a_missing_executable(monkeypatch, tmp_path) -> None:
    warnings = []
    monkeypatch.setattr(
        settings_dialog.QMessageBox,
        "warning",
        staticmethod(lambda *args, **kwargs: warnings.append(args)),
    )
    dialog = SettingsDialog(str(tmp_path / "gone.exe"))

    dialog._on_accept()

    assert warnings
    assert dialog.result() != int(QDialog.DialogCode.Accepted)


def test_settings_accepts_an_existing_executable(tmp_path) -> None:
    reader = tmp_path / "reader.exe"
    reader.write_bytes(b"")
    dialog = SettingsDialog(str(reader))

    dialog._on_accept()

    assert dialog.result() == int(QDialog.DialogCode.Accepted)


def test_settings_browse_sets_the_path(monkeypatch, tmp_path) -> None:
    chosen = tmp_path / "chosen.exe"
    monkeypatch.setattr(
        settings_dialog.QFileDialog,
        "getOpenFileName",
        staticmethod(lambda *args, **kwargs: (str(chosen), "")),
    )
    dialog = SettingsDialog("")

    dialog.browse_reader()

    assert dialog.reader_path() == str(chosen)


# ------------------------------------------------------------------------------
# MissingFilesDialog
# ------------------------------------------------------------------------------
class MissingController(FakeController):
    def __init__(self, entries) -> None:
        super().__init__()
        self.entries = list(entries)
        self.relinked = []

    def find_missing_pdfs(self):
        return list(self.entries)

    def relink_pdf(self, node_id, stored_path, new_source, copy_to_books=False):
        self.relinked.append((node_id, stored_path, str(new_source), copy_to_books))
        self.entries = [entry for entry in self.entries if entry.stored_path != stored_path]
        return str(new_source)


def missing_entry(node_id: int = 1, stored: str = "books/gone.pdf") -> MissingPdf:
    return MissingPdf(
        node_id=node_id,
        node_name=f"Node {node_id}",
        stored_path=stored,
        absolute_path=Path(stored),
    )


def test_missing_dialog_lists_entries() -> None:
    controller = MissingController([missing_entry(1), missing_entry(2, "books/lost.pdf")])

    dialog = MissingFilesDialog(controller)

    assert dialog.table.rowCount() == 2
    assert "2 个缺失 PDF" in dialog.header_label.text()
    assert "2 个节点" in dialog.header_label.text()
    assert dialog.relink_button.isEnabled() is False


def test_missing_dialog_relinks_the_selected_entry(monkeypatch, tmp_path) -> None:
    controller = MissingController([missing_entry(1)])
    dialog = MissingFilesDialog(controller)
    dialog.table.selectRow(0)
    replacement = tmp_path / "found.pdf"
    monkeypatch.setattr(
        missing_files_dialog.QFileDialog,
        "getOpenFileName",
        staticmethod(lambda *args, **kwargs: (str(replacement), "")),
    )
    dialog.copy_check.setChecked(True)

    dialog.relink_selected()

    assert controller.relinked == [(1, "books/gone.pdf", str(replacement), True)]
    assert dialog.changed is True
    assert dialog.table.rowCount() == 0
    assert "没有发现缺失" in dialog.header_label.text()
    assert "已更新" in dialog.status_label.text()


def test_missing_dialog_relink_errors_are_reported(monkeypatch, tmp_path) -> None:
    controller = MissingController([missing_entry(1)])
    dialog = MissingFilesDialog(controller)
    dialog.table.selectRow(0)
    warnings = []
    monkeypatch.setattr(
        missing_files_dialog.QFileDialog,
        "getOpenFileName",
        staticmethod(lambda *args, **kwargs: (str(tmp_path / "found.pdf"), "")),
    )

    def failing_relink(*args, **kwargs):
        raise ValueError("该文件已经关联到当前节点。")

    monkeypatch.setattr(controller, "relink_pdf", failing_relink)
    monkeypatch.setattr(
        missing_files_dialog.QMessageBox,
        "warning",
        staticmethod(lambda *args, **kwargs: warnings.append(args)),
    )

    dialog.relink_selected()

    assert warnings
    assert dialog.changed is False
    assert dialog.table.rowCount() == 1


def test_missing_dialog_reveal_calls_the_callback() -> None:
    controller = MissingController([missing_entry(7, "books/lost.pdf")])
    revealed = []
    dialog = MissingFilesDialog(
        controller,
        reveal_callback=lambda node_id, stored: revealed.append((node_id, stored)),
    )
    dialog.table.selectRow(0)

    dialog.reveal_selected()

    assert revealed == [(7, "books/lost.pdf")]


def test_missing_dialog_reload_refreshes_the_table() -> None:
    controller = MissingController([missing_entry(1)])
    dialog = MissingFilesDialog(controller)

    controller.entries = []
    dialog.refresh_button.click()

    assert dialog.table.rowCount() == 0


def test_missing_dialog_empty_state() -> None:
    dialog = MissingFilesDialog(MissingController([]))

    assert dialog.table.rowCount() == 0
    assert "没有发现缺失" in dialog.header_label.text()
    assert dialog.reveal_button.isEnabled() is False
