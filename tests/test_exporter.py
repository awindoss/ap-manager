# ==============================================================================
# tests/test_exporter.py
# JSON export: flat node/edge document, relative paths, icon/PDF copying,
# deterministic output and warning collection (Phase 6).
# ==============================================================================
import json
from pathlib import Path

import pytest

from models.library import LibraryService
from utils import icon_utils
from services.exporter import export_library
from utils import constants


def make_pdf(path: Path, content: bytes = b"%PDF-1.4\n% fixture\n") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    return path


def read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


@pytest.fixture
def app_root(tmp_path) -> Path:
    root = tmp_path / "app"
    root.mkdir()
    return root


@pytest.fixture
def library(tmp_path) -> LibraryService:
    return LibraryService(db_path=tmp_path / "source.db")


def test_export_writes_a_flat_document_with_stable_external_ids(
    library: LibraryService, app_root: Path, tmp_path
) -> None:
    root = library.create_node("经济政治", icon="🏛️")
    shelf = library.create_node("马列", parent_id=root, icon="📜")
    marx = library.create_node(
        "马克思", icon="👤", style_bold=True, style_color="#B22222"
    )
    library.attach_nodes(root, marx)
    library.attach_nodes(shelf, marx)
    library.update_node(
        marx,
        pdf_paths=["books/critique.pdf"],
        metadata={"tags": ["哲学", "政治经济学"]},
    )
    make_pdf(app_root / "books" / "critique.pdf")

    export_dir = tmp_path / "export"
    result = export_library(
        library, export_dir, copy_pdfs=False, base_root=app_root
    )

    assert result.node_count == 3
    assert result.edge_count == 3
    assert result.warnings == []
    document = read_json(export_dir / constants.LIBRARY_JSON_FILE_NAME)
    assert document["format"] == constants.LIBRARY_FORMAT_NAME
    assert document["version"] == constants.LIBRARY_FORMAT_VERSION
    assert [node["id"] for node in document["nodes"]] == ["n1", "n2", "n3"]

    exported_marx = document["nodes"][2]
    assert exported_marx["name"] == "马克思"
    assert exported_marx["style"] == {"bold": True, "color": "#b22222"}
    assert exported_marx["metadata"] == {"tags": ["哲学", "政治经济学"]}
    # The reference is relative to the export directory and resolves back.
    reference = exported_marx["pdfs"][0]
    assert (export_dir / reference).resolve() == (app_root / "books" / "critique.pdf").resolve()

    edges = {
        (edge["parent"], edge["child"]): edge["sort_order"]
        for edge in document["edges"]
    }
    assert edges == {("n1", "n2"): 0, ("n1", "n3"): 1, ("n2", "n3"): 0}


def test_export_copies_pdfs_into_books_and_reuses_duplicates(
    library: LibraryService, app_root: Path, tmp_path
) -> None:
    pdf = make_pdf(app_root / "books" / "capital.pdf", b"%PDF capital")
    first = library.create_node("资本论")
    second = library.create_node("资本论 副本")
    library.update_node(first, pdf_paths=["books/capital.pdf"])
    library.update_node(second, pdf_paths=["books/capital.pdf"])

    export_dir = tmp_path / "portable"
    result = export_library(
        library, export_dir, copy_pdfs=True, base_root=app_root
    )

    assert result.pdf_copies == 1
    for node in read_json(export_dir / "library.json")["nodes"]:
        assert node["pdfs"] == ["./books/capital.pdf"]
    copied = export_dir / "books" / "capital.pdf"
    assert copied.is_file()
    assert copied.read_bytes() == pdf.read_bytes()


def test_export_copies_custom_icons_into_the_export(
    library: LibraryService, app_root: Path, tmp_path
) -> None:
    source = tmp_path / "icons" / "marx.png"
    source.parent.mkdir()
    source.write_bytes(b"\x89PNG\r\n\x1a\nfixture")
    icons_dir = app_root / "icons"
    stored_icon = icon_utils.import_custom_icon(
        source, base_root=app_root, icons_dir=icons_dir
    )
    library.create_node("马克思", icon=stored_icon)

    export_dir = tmp_path / "export"
    result = export_library(
        library,
        export_dir,
        copy_pdfs=False,
        base_root=app_root,
        icons_dir=icons_dir,
    )

    assert result.icon_copies == 1
    icon_name = Path(stored_icon).name
    exported_icon = export_dir / "icons" / icon_name
    assert exported_icon.is_file()
    exported = read_json(export_dir / "library.json")["nodes"][0]
    assert exported["icon"] == f"icons/{icon_name}"
    assert exported["id"] == "n1"


def test_export_warns_about_missing_pdfs_but_keeps_the_reference(
    library: LibraryService, app_root: Path, tmp_path
) -> None:
    node = library.create_node("缺失")
    library.update_node(node, pdf_paths=["books/gone.pdf"])

    export_dir = tmp_path / "export"
    result = export_library(
        library, export_dir, copy_pdfs=True, base_root=app_root
    )

    assert result.has_warnings is True
    assert any("gone.pdf" in warning for warning in result.warnings)
    exported = read_json(export_dir / "library.json")["nodes"][0]
    assert exported["pdfs"] and "gone.pdf" in exported["pdfs"][0]


def test_export_warns_about_a_missing_custom_icon(
    library: LibraryService, app_root: Path, tmp_path
) -> None:
    node = library.create_node("图标缺失", icon="icons/not-there.png")

    export_dir = tmp_path / "export"
    result = export_library(
        library, export_dir, copy_pdfs=False, base_root=app_root
    )

    assert result.has_warnings is True
    assert any("图标" in warning for warning in result.warnings)
    assert read_json(export_dir / "library.json")["nodes"][0]["icon"] == "icons/not-there.png"
    assert node is not None


def test_export_is_deterministic(
    library: LibraryService, app_root: Path, tmp_path
) -> None:
    root = library.create_node("A")
    library.create_node("B", parent_id=root)
    export_dir = tmp_path / "export"
    export_library(library, export_dir, base_root=app_root)
    first = (export_dir / "library.json").read_bytes()

    export_library(library, export_dir, base_root=app_root)

    assert (export_dir / "library.json").read_bytes() == first


def test_export_refuses_to_overwrite_when_disabled(
    library: LibraryService, app_root: Path, tmp_path
) -> None:
    library.create_node("A")
    export_dir = tmp_path / "export"
    export_dir.mkdir()
    target = export_dir / constants.LIBRARY_JSON_FILE_NAME
    target.write_text("original", encoding="utf-8")

    with pytest.raises(FileExistsError):
        export_library(
            library, export_dir, overwrite=False, base_root=app_root
        )

    assert target.read_text(encoding="utf-8") == "original"


def test_export_rejects_a_file_as_the_target(library: LibraryService, tmp_path) -> None:
    library.create_node("A")
    target = tmp_path / "not-a-directory"
    target.write_text("x", encoding="utf-8")

    with pytest.raises(NotADirectoryError):
        export_library(library, target)


def test_export_of_an_empty_library_is_valid(
    library: LibraryService, app_root: Path, tmp_path
) -> None:
    export_dir = tmp_path / "empty-export"

    result = export_library(library, export_dir, base_root=app_root)

    assert result.node_count == 0
    assert result.edge_count == 0
    document = read_json(export_dir / "library.json")
    assert document["nodes"] == []
    assert document["edges"] == []
