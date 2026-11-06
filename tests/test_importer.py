# ==============================================================================
# tests/test_importer.py
# JSON import: external id mapping, edge rebuilding, path/icon rebasing,
# merge vs replace, missing files and transactional rollback (Phase 6).
# ==============================================================================
import json
import sqlite3
from pathlib import Path

import pytest

from models.library import LibraryService
from utils import icon_utils
from services.exporter import export_library
from services.importer import import_library
from utils import constants
from utils.json_utils import LibraryFormatError


def make_pdf(path: Path, content: bytes = b"%PDF-1.4\n% fixture\n") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    return path


def node(
    external_id: str,
    name: str,
    *,
    pdfs=None,
    icon: str = "",
    bold: bool = False,
    color: str = constants.DEFAULT_TEXT_COLOR,
    metadata=None,
) -> dict:
    return {
        "id": external_id,
        "name": name,
        "pdfs": list(pdfs or []),
        "icon": icon,
        "style": {"bold": bold, "color": color},
        "metadata": dict(metadata or {}),
    }


def edge(parent: str, child: str, sort_order: int = 0) -> dict:
    return {"parent": parent, "child": child, "sort_order": sort_order}


def write_library(
    path: Path,
    nodes,
    edges,
    *,
    version: str = constants.LIBRARY_FORMAT_VERSION,
) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    document = {
        "format": constants.LIBRARY_FORMAT_NAME,
        "version": version,
        "nodes": list(nodes),
        "edges": list(edges),
    }
    path.write_text(json.dumps(document, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


@pytest.fixture
def library(tmp_path) -> LibraryService:
    return LibraryService(db_path=tmp_path / "target.db")


def test_import_restores_nodes_edges_attributes_and_multi_parent(
    tmp_path, library: LibraryService
) -> None:
    source_root = tmp_path / "source_app"
    make_pdf(source_root / "books" / "critique.pdf")
    source = LibraryService(db_path=tmp_path / "source.db")
    market = source.create_node("经济政治", icon="🏛️")
    shelf = source.create_node("马列", parent_id=market, icon="📜")
    marx = source.create_node(
        "马克思", icon="👤", style_bold=True, style_color="#B22222"
    )
    source.attach_nodes(market, marx)
    source.attach_nodes(shelf, marx)
    source.update_node(
        marx,
        pdf_paths=["books/critique.pdf"],
        metadata={"tags": ["哲学"]},
    )
    export_dir = tmp_path / "portable"
    export_library(source, export_dir, copy_pdfs=True, base_root=source_root)
    exported = read_json(export_dir / "library.json")

    result = import_library(
        library, export_dir / "library.json", base_root=export_dir
    )

    assert result.node_count == 3
    assert result.edge_count == 3
    assert result.mode == constants.IMPORT_MODE_MERGE
    assert result.warnings == []
    assert set(result.id_map) == {"n1", "n2", "n3"}
    assert len(set(result.id_map.values())) == 3

    imported = {item.name: item for item in library.get_all_nodes()}
    assert set(imported) == {"经济政治", "马列", "马克思"}
    imported_marx = imported["马克思"]
    assert imported_marx.id == result.id_map["n3"]
    assert imported_marx.style_bold is True
    assert imported_marx.style_color == "#b22222"
    assert imported_marx.icon == "👤"
    assert imported_marx.metadata == {"tags": ["哲学"]}
    assert imported_marx.pdf_paths == ["books/critique.pdf"]

    root_id = result.id_map["n1"]
    shelf_id = result.id_map["n2"]
    assert [child.name for child in library.get_node_children(root_id)] == ["马列", "马克思"]
    assert [child.name for child in library.get_node_children(shelf_id)] == ["马克思"]
    assert sorted(path for path in library.get_node_paths(imported_marx.id)) == sorted(
        [
            [root_id, shelf_id, imported_marx.id],
            [root_id, imported_marx.id],
        ]
    )

    # The exported document remains unchanged by the import.
    assert read_json(export_dir / "library.json") == exported


def test_export_clear_import_export_roundtrip_is_lossless(
    tmp_path, library: LibraryService
) -> None:
    source_root = tmp_path / "source_app"
    make_pdf(source_root / "books" / "a.pdf", b"%PDF a")
    make_pdf(source_root / "books" / "b.pdf", b"%PDF b")
    icon_source = tmp_path / "art" / "star.png"
    icon_source.parent.mkdir()
    icon_source.write_bytes(b"\x89PNG\r\n\x1a\nicon")
    icon_ref = icon_utils.import_custom_icon(
        icon_source, base_root=source_root, icons_dir=source_root / "icons"
    )

    a = library.create_node("A", icon=icon_ref)
    b = library.create_node("B", parent_id=a, style_bold=True)
    x = library.create_node("X", style_color="#112233", metadata={"k": "v"})
    library.attach_nodes(a, x, sort_order=5)
    library.attach_nodes(b, x, sort_order=2)
    library.update_node(a, pdf_paths=["books/a.pdf", "books/b.pdf"])

    first_dir = tmp_path / "first_export"
    first_result = export_library(
        library,
        first_dir,
        copy_pdfs=True,
        base_root=source_root,
        icons_dir=source_root / "icons",
    )
    assert first_result.pdf_copies == 2
    first_document = read_json(first_dir / "library.json")

    library.clear_library()
    assert library.get_all_nodes() == []

    import_library(
        library,
        first_dir / "library.json",
        base_root=first_dir,
        icons_dir=first_dir / "icons",
    )

    second_dir = tmp_path / "second_export"
    export_library(
        library,
        second_dir,
        copy_pdfs=True,
        base_root=first_dir,
        icons_dir=first_dir / "icons",
    )
    second_document = read_json(second_dir / "library.json")

    assert second_document == first_document


def test_import_merges_by_default(tmp_path, library: LibraryService) -> None:
    existing = library.create_node("已有节点")
    source = write_library(
        tmp_path / "merge.json",
        [node("n1", "导入节点", pdfs=["./books/a.pdf"])],
        [],
    )
    make_pdf(tmp_path / "books" / "a.pdf")

    result = import_library(library, source, base_root=tmp_path)

    assert result.mode == constants.IMPORT_MODE_MERGE
    assert {item.name for item in library.get_all_nodes()} == {"已有节点", "导入节点"}
    assert library.get_node(existing) is not None


def test_import_replace_clears_the_previous_graph(tmp_path, library: LibraryService) -> None:
    old_root = library.create_node("旧根")
    library.create_node("旧子节点", parent_id=old_root)
    source = write_library(tmp_path / "replace.json", [node("n1", "新根")], [])

    result = import_library(
        library, source, mode=constants.IMPORT_MODE_REPLACE, base_root=tmp_path
    )

    assert result.mode == constants.IMPORT_MODE_REPLACE
    assert [item.name for item in library.get_all_nodes()] == ["新根"]
    assert library.get_all_edges() == []


def test_import_missing_pdf_keeps_the_reference_and_warns(
    tmp_path, library: LibraryService
) -> None:
    source = write_library(
        tmp_path / "missing.json",
        [node("n1", "缺文件", pdfs=["./books/gone.pdf"])],
        [],
    )

    result = import_library(library, source, base_root=tmp_path)

    assert result.missing_pdfs == ["books/gone.pdf"]
    assert any("gone.pdf" in warning for warning in result.warnings)
    imported = library.get_all_nodes()[0]
    assert imported.pdf_paths == ["books/gone.pdf"]


def test_import_deduplicates_repeated_pdf_entries(tmp_path, library: LibraryService) -> None:
    make_pdf(tmp_path / "books" / "a.pdf")
    source = write_library(
        tmp_path / "dupe.json",
        [node("n1", "A", pdfs=["./books/a.pdf", "./books/a.pdf", "books/a.pdf"])],
        [],
    )

    import_library(library, source, base_root=tmp_path)

    assert library.get_all_nodes()[0].pdf_paths == ["books/a.pdf"]


def test_invalid_document_does_not_touch_the_database(tmp_path, library: LibraryService) -> None:
    library.create_node("保留")
    cyclic = write_library(
        tmp_path / "cycle.json",
        [node("a", "A"), node("b", "B"), node("c", "C")],
        [edge("a", "b"), edge("b", "c"), edge("c", "a")],
    )

    with pytest.raises(LibraryFormatError):
        import_library(library, cyclic)

    assert [item.name for item in library.get_all_nodes()] == ["保留"]
    assert library.get_all_edges() == []


def test_unsupported_version_does_not_touch_the_database(
    tmp_path, library: LibraryService
) -> None:
    library.create_node("保留")
    source = write_library(tmp_path / "future.json", [node("n1", "A")], [], version="9.9")

    with pytest.raises(LibraryFormatError, match="9.9"):
        import_library(library, source)

    assert [item.name for item in library.get_all_nodes()] == ["保留"]


def test_database_failure_rolls_back_the_whole_import(
    tmp_path, library: LibraryService, monkeypatch
) -> None:
    source = write_library(
        tmp_path / "two.json",
        [node("n1", "A"), node("n2", "B")],
        [edge("n1", "n2")],
    )

    def boom(conn, parent_id, child_id, sort_order=0):
        raise sqlite3.Error("simulated write failure")

    monkeypatch.setattr(library.db, "_insert_edge_with_conn", boom)

    with pytest.raises(sqlite3.Error):
        import_library(library, source)

    # Neither node may survive a failure that happened while writing the edge.
    assert library.get_all_nodes() == []
    assert library.get_all_edges() == []


def test_replace_failure_restores_the_previous_library(
    tmp_path, library: LibraryService, monkeypatch
) -> None:
    keep = library.create_node("保留")
    library.create_node("保留子节点", parent_id=keep)
    source = write_library(
        tmp_path / "replace-fail.json",
        [node("n1", "A"), node("n2", "B")],
        [edge("n1", "n2")],
    )

    def boom(conn, parent_id, child_id, sort_order=0):
        raise sqlite3.Error("simulated write failure")

    monkeypatch.setattr(library.db, "_insert_edge_with_conn", boom)

    with pytest.raises(sqlite3.Error):
        import_library(library, source, mode=constants.IMPORT_MODE_REPLACE)

    # The DELETE that "replace" performs must be rolled back with the insert.
    assert [item.name for item in library.get_all_nodes()] == ["保留", "保留子节点"]
    assert len(library.get_all_edges()) == 1


def test_import_copies_custom_icons_into_the_local_icons_dir(
    tmp_path, library: LibraryService
) -> None:
    source_dir = tmp_path / "portable"
    icon_dir = source_dir / "icons"
    icon_dir.mkdir(parents=True)
    (icon_dir / "star_abcd1234.png").write_bytes(b"\x89PNG\r\n\x1a\nicon")
    source = write_library(
        source_dir / "library.json",
        [node("n1", "带图标", icon="icons/star_abcd1234.png")],
        [],
    )
    target_root = tmp_path / "target_app"
    target_icons = target_root / "icons"

    import_library(
        library,
        source,
        base_root=target_root,
        icons_dir=target_icons,
    )

    imported = library.get_all_nodes()[0]
    assert imported.icon.startswith("icons/")
    assert (target_root / imported.icon).is_file()
    assert imported.icon in {
        f"icons/{path.name}" for path in target_icons.iterdir()
    }


def test_import_ignores_icons_outside_the_import_directory(
    tmp_path, library: LibraryService
) -> None:
    target_root = tmp_path / "target_app"
    target_root.mkdir()
    (tmp_path / "outside.png").write_bytes(b"\x89PNG\r\n\x1a\noutside")
    source = write_library(
        tmp_path / "export" / "library.json",
        [node("n1", "越界图标", icon="../outside.png")],
        [],
    )

    result = import_library(
        library,
        source,
        base_root=target_root,
        icons_dir=target_root / "icons",
    )

    imported = library.get_all_nodes()[0]
    assert imported.icon == ""
    assert any("不在导入目录内" in warning for warning in result.warnings)


def test_import_accepts_a_database_target(tmp_path, library: LibraryService) -> None:
    source = write_library(tmp_path / "db-target.json", [node("n1", "A")], [])

    result = import_library(library.db, source, base_root=tmp_path)

    assert result.node_count == 1
    assert library.get_all_nodes()[0].name == "A"


def test_import_rejects_an_unknown_mode(tmp_path, library: LibraryService) -> None:
    source = write_library(tmp_path / "mode.json", [node("n1", "A")], [])

    with pytest.raises(ValueError, match="未知的导入方式"):
        import_library(library, source, mode="overwrite")


def test_import_reports_a_missing_input_file(tmp_path, library: LibraryService) -> None:
    with pytest.raises(FileNotFoundError):
        import_library(library, tmp_path / "missing.json")
