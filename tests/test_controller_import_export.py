# ==============================================================================
# tests/test_controller_import_export.py
# Controller-level entry points for Phase 6 import/export.
# ==============================================================================
import pytest

from controllers.app_controller import AppController


@pytest.fixture
def controller(tmp_path) -> AppController:
    return AppController(db_path=tmp_path / "controller.db")


def test_controller_exports_and_imports_a_library(controller: AppController, tmp_path) -> None:
    root = controller.create_node("经济政治", icon="🏛️")
    controller.create_node("马列", parent_id=root, icon="📜")

    export_dir = tmp_path / "export"
    export_result = controller.export_library(export_dir, copy_pdfs=False)

    assert export_result.node_count == 2
    assert export_result.edge_count == 1
    assert export_result.json_path.is_file()

    target = AppController(db_path=tmp_path / "target.db")
    import_result = target.import_library(export_result.json_path, mode="replace")

    assert import_result.node_count == 2
    assert import_result.edge_count == 1
    assert [node.name for node in target.get_all_nodes()] == ["经济政治", "马列"]
    assert target.get_all_roots()[0].name == "经济政治"
    assert target.get_node_children(target.get_all_roots()[0].id)[0].name == "马列"


def test_controller_export_rejects_an_empty_directory(controller: AppController) -> None:
    with pytest.raises(ValueError, match="导出目录"):
        controller.export_library("")


def test_controller_import_rejects_an_empty_path(controller: AppController) -> None:
    with pytest.raises(ValueError, match="图书馆文件"):
        controller.import_library("")


def test_controller_import_rejects_an_unknown_mode(controller: AppController, tmp_path) -> None:
    with pytest.raises(ValueError, match="未知的导入方式"):
        controller.import_library(tmp_path / "library.json", mode="append")


def test_controller_reports_library_counts(controller: AppController) -> None:
    assert controller.get_library_counts() == (0, 0)

    root = controller.create_node("A")
    controller.create_node("B", parent_id=root)

    assert controller.get_library_counts() == (2, 1)
