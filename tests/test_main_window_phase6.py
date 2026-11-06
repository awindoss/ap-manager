# ==============================================================================
# tests/test_main_window_phase6.py
# Main-window integration for the library import/export menu actions.
# ==============================================================================
import json
from pathlib import Path

import pytest

pytest.importorskip("PySide6")

from PySide6.QtWidgets import QMessageBox

from controllers.app_controller import AppController
from views.main_window import MainWindow

pytestmark = pytest.mark.usefixtures("qapp")


@pytest.fixture
def controller(tmp_path) -> AppController:
    return AppController(db_path=tmp_path / "main_window_phase6.db")


@pytest.fixture
def window(controller: AppController):
    main_window = MainWindow(controller=controller)
    main_window.show()
    try:
        yield main_window
    finally:
        main_window.close()


def write_library(
    path: Path,
    nodes,
    edges=None,
    *,
    version: str = "0.1",
) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    document = {
        "format": "ap_manager_library",
        "version": version,
        "nodes": nodes,
        "edges": list(edges or []),
    }
    path.write_text(json.dumps(document, ensure_ascii=False), encoding="utf-8")
    return path


def simple_node(external_id: str, name: str, pdfs=None) -> dict:
    return {
        "id": external_id,
        "name": name,
        "pdfs": list(pdfs or []),
        "icon": "",
        "style": {"bold": False, "color": "#000000"},
        "metadata": {},
    }


def silence_info(monkeypatch):
    calls = []

    def fake_information(*args, **kwargs):
        calls.append((args, kwargs))
        return QMessageBox.StandardButton.Ok

    monkeypatch.setattr(QMessageBox, "information", fake_information)
    return calls


def silence_warning(monkeypatch):
    calls = []

    def fake_warning(*args, **kwargs):
        calls.append((args, kwargs))
        return QMessageBox.StandardButton.Ok

    monkeypatch.setattr(QMessageBox, "warning", fake_warning)
    return calls


def silence_critical(monkeypatch):
    calls = []

    def fake_critical(*args, **kwargs):
        calls.append((args, kwargs))
        return QMessageBox.StandardButton.Ok

    monkeypatch.setattr(QMessageBox, "critical", fake_critical)
    return calls


def test_file_menu_exposes_import_and_export(window: MainWindow) -> None:
    assert window._import_action.text() == "导入图书馆(&I)…"
    assert window._export_action.text() == "导出图书馆(&E)…"
    assert window._import_action.shortcut().toString() == "Ctrl+I"
    assert window._export_action.shortcut().toString() == "Ctrl+E"


def test_import_action_triggers_the_import_entry_point(window: MainWindow, monkeypatch) -> None:
    called = []
    monkeypatch.setattr(
        window, "_import_library", lambda: called.append(True)
    )

    window._import_action.trigger()

    assert called == [True]


def test_import_from_file_refreshes_the_tree(
    window: MainWindow, tmp_path, monkeypatch
) -> None:
    info_calls = silence_info(monkeypatch)
    source = write_library(
        tmp_path / "import.json",
        [
            simple_node("n1", "经济政治"),
            simple_node("n2", "马列"),
        ],
        [{"parent": "n1", "child": "n2", "sort_order": 0}],
    )

    result = window._import_library_from(source, mode="merge")

    assert result is not None
    assert result.node_count == 2
    assert window.model.root_count == 1
    root_item = window.model.find_items_by_node_id(result.id_map["n1"])[0]
    assert root_item.name == "经济政治"
    assert [child.name for child in window.model.find_items_by_node_id(result.id_map["n1"])[0].children] == ["马列"]
    assert "已追加导入 2 个节点" in window.statusBar().currentMessage()
    assert info_calls


def test_import_replace_removes_the_previous_library(
    window: MainWindow, controller: AppController, tmp_path, monkeypatch
) -> None:
    silence_info(monkeypatch)
    controller.create_node("旧节点")
    window.refresh()
    source = write_library(tmp_path / "replace.json", [simple_node("n1", "新节点")])

    result = window._import_library_from(source, mode="replace")

    assert result is not None
    assert [node.name for node in controller.get_all_nodes()] == ["新节点"]
    assert [item.name for item in window.model.find_items_by_node_id(result.id_map["n1"])] == ["新节点"]


def test_import_failure_reports_and_keeps_the_library(
    window: MainWindow, controller: AppController, tmp_path, monkeypatch
) -> None:
    controller.create_node("保留")
    window.refresh()
    critical_calls = silence_critical(monkeypatch)
    broken = tmp_path / "broken.json"
    broken.write_text("{not json", encoding="utf-8")

    result = window._import_library_from(broken, mode="merge")

    assert result is None
    assert [node.name for node in controller.get_all_nodes()] == ["保留"]
    assert critical_calls
    assert "当前书库没有被修改" in critical_calls[0][0][2]


def test_import_with_missing_pdf_shows_a_warning(
    window: MainWindow, controller: AppController, tmp_path, monkeypatch
) -> None:
    _info_calls = silence_info(monkeypatch)
    warning_calls = silence_warning(monkeypatch)
    source = write_library(
        tmp_path / "missing.json",
        [simple_node("n1", "缺文件", pdfs=["./books/gone.pdf"])],
    )

    result = window._import_library_from(source, mode="merge")

    assert result is not None
    assert result.missing_pdfs
    assert warning_calls
    assert "找不到" in window.statusBar().currentMessage()


def test_export_to_directory_writes_a_library_file(
    window: MainWindow, controller: AppController, tmp_path, monkeypatch
) -> None:
    controller.create_node("A")
    window.refresh()
    info_calls = silence_info(monkeypatch)
    export_dir = tmp_path / "export"

    result = window._export_library_to(
        export_dir, copy_pdfs=False, overwrite=True
    )

    assert result is not None
    assert result.node_count == 1
    assert (export_dir / "library.json").is_file()
    assert "已导出图书馆" in window.statusBar().currentMessage()
    assert info_calls


def test_export_declined_overwrite_keeps_the_old_file(
    window: MainWindow, controller: AppController, tmp_path, monkeypatch
) -> None:
    controller.create_node("A")
    export_dir = tmp_path / "export"
    export_dir.mkdir()
    target = export_dir / "library.json"
    target.write_text("original", encoding="utf-8")
    monkeypatch.setattr(
        QMessageBox,
        "question",
        lambda *args, **kwargs: QMessageBox.StandardButton.No,
    )

    result = window._export_library_to(export_dir, copy_pdfs=False)

    assert result is None
    assert target.read_text(encoding="utf-8") == "original"


def test_export_cancelled_pdf_copy_prompt_writes_nothing(
    window: MainWindow, controller: AppController, tmp_path, monkeypatch
) -> None:
    controller.create_node("A")
    export_dir = tmp_path / "export"
    monkeypatch.setattr(
        QMessageBox,
        "question",
        lambda *args, **kwargs: QMessageBox.StandardButton.Cancel,
    )

    result = window._export_library_to(export_dir, overwrite=True)

    assert result is None
    assert not (export_dir / "library.json").exists()


def test_import_mode_prompt_defaults_to_merge_for_an_empty_library(
    window: MainWindow,
) -> None:
    assert window._prompt_import_mode() == "merge"
