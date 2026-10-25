# ==============================================================================
# tests/test_path_manager.py
# Portable PDF path resolution behind the missing-file marker (Phase 3).
# ==============================================================================
from pathlib import Path

from services import path_manager


def make_pdf(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"%PDF-1.4\n% test fixture\n")
    return path


def test_normalize_path_resolves_relative_against_base_root(tmp_path) -> None:
    assert path_manager.normalize_path("books/a.pdf", base_root=tmp_path) == (
        tmp_path / "books" / "a.pdf"
    )


def test_normalize_path_keeps_absolute_paths(tmp_path) -> None:
    absolute = tmp_path / "elsewhere" / "a.pdf"
    assert path_manager.normalize_path(absolute, base_root=tmp_path / "root") == absolute


def test_resolve_pdf_path_returns_existing_file(tmp_path) -> None:
    pdf = make_pdf(tmp_path / "books" / "a.pdf")

    resolved = path_manager.resolve_pdf_path("books/a.pdf", base_root=tmp_path)

    assert resolved is not None
    assert resolved.resolve() == pdf.resolve()
    assert path_manager.is_pdf_exists("books/a.pdf", base_root=tmp_path) is True


def test_resolve_pdf_path_returns_none_for_missing_file(tmp_path) -> None:
    assert path_manager.resolve_pdf_path("books/gone.pdf", base_root=tmp_path) is None
    assert path_manager.is_pdf_exists("books/gone.pdf", base_root=tmp_path) is False
    assert path_manager.resolve_pdf_path("", base_root=tmp_path) is None


def test_missing_pdf_paths_keeps_original_order(tmp_path) -> None:
    make_pdf(tmp_path / "books" / "present.pdf")

    missing = path_manager.missing_pdf_paths(
        ["books/gone-2.pdf", "books/present.pdf", "books/gone-1.pdf"],
        base_root=tmp_path,
    )

    assert missing == ["books/gone-2.pdf", "books/gone-1.pdf"]


def test_missing_pdf_paths_accepts_empty_input(tmp_path) -> None:
    assert path_manager.missing_pdf_paths([], base_root=tmp_path) == []
    assert path_manager.missing_pdf_paths(None, base_root=tmp_path) == []
