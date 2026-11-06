# ==============================================================================
# tests/test_path_manager.py
# Portable PDF path resolution behind the missing-file marker (Phase 3) and the
# storage/copy/re-location helpers used by PDF management (Phase 4).
# ==============================================================================
import os
from pathlib import Path

import pytest

from services import path_manager


def make_pdf(path: Path, content: bytes = b"%PDF-1.4\n% test fixture\n") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
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


# ------------------------------------------------------------------------------
# Phase 4: storage representation
# ------------------------------------------------------------------------------
def test_normalize_stored_path_keeps_absolute_and_normalises_relative() -> None:
    assert path_manager.normalize_stored_path(None) == ""
    assert path_manager.normalize_stored_path("  ") == ""
    assert path_manager.normalize_stored_path("  books\\a.pdf  ") == "books/a.pdf"

    absolute = Path.cwd().resolve() / "books" / "a.pdf"
    assert path_manager.normalize_stored_path(str(absolute)) == str(absolute)


def test_pdf_path_key_detects_equivalent_spellings() -> None:
    assert path_manager.pdf_path_key("books/a.pdf") == path_manager.pdf_path_key("books/a.pdf")
    assert path_manager.pdf_path_key("books/a.pdf") != path_manager.pdf_path_key("books/b.pdf")
    assert path_manager.pdf_path_key("") == ""

    if os.name == "nt":
        assert path_manager.pdf_path_key("books/a.pdf") == path_manager.pdf_path_key(
            "BOOKS/A.PDF"
        )


def test_is_within_root_and_relative_to_root(tmp_path) -> None:
    root = tmp_path / "app"
    inside = root / "books" / "a.pdf"
    outside = tmp_path / "elsewhere" / "a.pdf"
    inside.parent.mkdir(parents=True)
    inside.write_bytes(b"x")

    assert path_manager.is_within_root(inside, root) is True
    assert path_manager.is_within_root(outside, root) is False
    assert path_manager.relative_to_root(inside, root) == "books/a.pdf"
    assert path_manager.relative_to_root(outside, root) is None


def test_make_stored_path_relative_for_file_inside_root(tmp_path) -> None:
    root = tmp_path / "app"
    pdf = make_pdf(root / "books" / "a.pdf")

    assert path_manager.make_stored_path(pdf, base_root=root) == "books/a.pdf"


def test_make_stored_path_absolute_for_file_outside_root(tmp_path) -> None:
    root = tmp_path / "app"
    root.mkdir()
    pdf = make_pdf(tmp_path / "elsewhere" / "a.pdf")

    stored = path_manager.make_stored_path(pdf, base_root=root)

    assert Path(stored).is_absolute()
    assert stored == pdf.as_posix()


def test_make_stored_path_rejects_missing_and_non_pdf(tmp_path) -> None:
    root = tmp_path / "app"
    root.mkdir()

    with pytest.raises(FileNotFoundError):
        path_manager.make_stored_path("gone.pdf", base_root=root)

    text_file = root / "notes.txt"
    text_file.write_text("not a pdf", encoding="utf-8")
    with pytest.raises(ValueError):
        path_manager.make_stored_path(text_file, base_root=root)


def test_make_stored_path_copies_to_books(tmp_path) -> None:
    root = tmp_path / "app"
    root.mkdir()
    pdf = make_pdf(tmp_path / "downloads" / "capital.pdf")

    stored = path_manager.make_stored_path(pdf, base_root=root, copy_to_books=True)

    assert stored == "books/capital.pdf"
    copied = root / "books" / "capital.pdf"
    assert copied.is_file()
    assert copied.read_bytes() == pdf.read_bytes()


def test_copy_to_books_reuses_identical_files(tmp_path) -> None:
    root = tmp_path / "app"
    root.mkdir()
    first = make_pdf(tmp_path / "one" / "book.pdf", b"same")
    second = make_pdf(tmp_path / "two" / "book.pdf", b"same")

    first_stored = path_manager.make_stored_path(first, base_root=root, copy_to_books=True)
    second_stored = path_manager.make_stored_path(second, base_root=root, copy_to_books=True)

    assert first_stored == second_stored == "books/book.pdf"
    assert len(list((root / "books").glob("*.pdf"))) == 1


def test_copy_to_books_disambiguates_different_files_with_the_same_name(tmp_path) -> None:
    root = tmp_path / "app"
    root.mkdir()
    first = make_pdf(tmp_path / "one" / "book.pdf", b"first")
    second = make_pdf(tmp_path / "two" / "book.pdf", b"second")

    first_stored = path_manager.make_stored_path(first, base_root=root, copy_to_books=True)
    second_stored = path_manager.make_stored_path(second, base_root=root, copy_to_books=True)

    assert first_stored == "books/book.pdf"
    assert second_stored != first_stored
    assert second_stored.startswith("books/book_")
    assert (root / second_stored).read_bytes() == b"second"


def test_describe_pdf_reports_presence_and_paths(tmp_path) -> None:
    existing = make_pdf(tmp_path / "app" / "books" / "a.pdf")
    root = tmp_path / "app"

    described = path_manager.describe_pdf("books/a.pdf", base_root=root)
    assert described.exists is True
    assert described.missing is False
    assert described.file_name == "a.pdf"
    assert described.absolute_path is not None
    assert described.absolute_path.resolve() == existing.resolve()

    missing = path_manager.describe_pdf("books/gone.pdf", base_root=root)
    assert missing.exists is False
    assert missing.missing is True
    assert missing.display_path.endswith("gone.pdf")

    described_many = path_manager.describe_pdfs(["books/a.pdf", "books/gone.pdf"], base_root=root)
    assert [entry.missing for entry in described_many] == [False, True]


# ------------------------------------------------------------------------------
# Phase 6: export / import reference conversion
# ------------------------------------------------------------------------------
def test_make_export_reference_uses_dot_slash_for_relative_paths(tmp_path) -> None:
    root = tmp_path / "app"
    pdf = make_pdf(root / "books" / "a.pdf")
    export_dir = root / "exports" / "lib"

    reference, absolute, exists = path_manager.make_export_reference(
        "books/a.pdf", export_dir, base_root=root
    )

    assert reference == "../../books/a.pdf"
    assert absolute is not None and absolute.resolve() == pdf.resolve()
    assert exists is True


def test_make_export_reference_prefixes_a_path_inside_the_export_dir(tmp_path) -> None:
    root = tmp_path / "app"
    make_pdf(root / "exports" / "books" / "a.pdf")
    export_dir = root / "exports"

    reference, _absolute, exists = path_manager.make_export_reference(
        "exports/books/a.pdf", export_dir, base_root=root
    )

    assert reference == "./books/a.pdf"
    assert exists is True


def test_make_export_reference_reports_missing_files(tmp_path) -> None:
    root = tmp_path / "app"
    reference, absolute, exists = path_manager.make_export_reference(
        "books/gone.pdf", root / "export", base_root=root
    )

    assert reference.endswith("books/gone.pdf")
    assert absolute is not None
    assert exists is False


def test_resolve_imported_reference_rebases_onto_the_target_root(tmp_path) -> None:
    target_root = tmp_path / "target"
    source_dir = target_root / "portable"
    pdf = make_pdf(source_dir / "books" / "a.pdf")

    stored, absolute, exists = path_manager.resolve_imported_reference(
        "./books/a.pdf", source_dir, base_root=target_root
    )

    assert stored == "portable/books/a.pdf"
    assert absolute is not None and absolute.resolve() == pdf.resolve()
    assert exists is True


def test_resolve_imported_reference_keeps_paths_outside_the_root_absolute(tmp_path) -> None:
    source_dir = tmp_path / "exported"
    target_root = tmp_path / "target"
    pdf = make_pdf(source_dir / "books" / "a.pdf")

    stored, _absolute, exists = path_manager.resolve_imported_reference(
        "./books/a.pdf", source_dir, base_root=target_root
    )

    assert stored == pdf.as_posix()
    assert exists is True


def test_resolve_imported_reference_does_not_require_the_file(tmp_path) -> None:
    stored, absolute, exists = path_manager.resolve_imported_reference(
        "./books/gone.pdf", tmp_path / "exported", base_root=tmp_path
    )

    assert stored == "exported/books/gone.pdf"
    assert absolute is not None
    assert exists is False
