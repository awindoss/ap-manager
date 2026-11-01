# ==============================================================================
# tests/test_library_pdfs.py
# PDF reference management in the business layer (Phase 4).
# ==============================================================================
import os

import pytest

from models.library import LibraryService


@pytest.fixture
def library(tmp_path) -> LibraryService:
    return LibraryService(db_path=tmp_path / "library.db")


def test_add_pdf_persists_and_deduplicates(library: LibraryService) -> None:
    node_id = library.create_node("资本论")

    assert library.add_pdf(node_id, "books/capital_1.pdf") is True
    assert library.add_pdf(node_id, "books/capital_2.pdf") is True
    assert library.add_pdf(node_id, "books/capital_1.pdf") is False
    assert library.add_pdf(node_id, "  books/capital_2.pdf  ") is False
    assert library.get_pdf_list(node_id) == [
        "books/capital_1.pdf",
        "books/capital_2.pdf",
    ]

    reopened = LibraryService(db_path=library.db.db_path)
    assert reopened.get_pdf_list(node_id) == [
        "books/capital_1.pdf",
        "books/capital_2.pdf",
    ]


def test_pdf_dedupe_is_case_insensitive_on_windows(library: LibraryService) -> None:
    node_id = library.create_node("Book")
    library.add_pdf(node_id, "books/a.pdf")

    duplicate = library.add_pdf(node_id, "BOOKS/A.PDF")

    if os.name == "nt":
        assert duplicate is False
        assert library.get_pdf_list(node_id) == ["books/a.pdf"]
    else:
        assert duplicate is True


def test_add_pdfs_returns_only_new_paths(library: LibraryService) -> None:
    node_id = library.create_node("Book")
    library.add_pdf(node_id, "books/a.pdf")

    added = library.add_pdfs(
        node_id,
        ["books/a.pdf", "books/b.pdf", "books/c.pdf", "books/b.pdf"],
    )

    assert added == ["books/b.pdf", "books/c.pdf"]
    assert library.get_pdf_list(node_id) == [
        "books/a.pdf",
        "books/b.pdf",
        "books/c.pdf",
    ]


def test_add_pdfs_ignores_empty_entries(library: LibraryService) -> None:
    node_id = library.create_node("Book")

    added = library.add_pdfs(node_id, ["", "   ", None, "books/a.pdf"])

    assert added == ["books/a.pdf"]


def test_add_pdf_rejects_an_empty_path(library: LibraryService) -> None:
    node_id = library.create_node("Book")

    with pytest.raises(ValueError):
        library.add_pdf(node_id, "   ")


def test_set_pdf_list_replaces_and_deduplicates(library: LibraryService) -> None:
    node_id = library.create_node("Book")
    library.add_pdf(node_id, "books/old.pdf")

    library.set_pdf_list(
        node_id,
        ["books/a.pdf", "", "books/b.pdf", "books/a.pdf", None],
    )

    assert library.get_pdf_list(node_id) == ["books/a.pdf", "books/b.pdf"]

    library.set_pdf_list(node_id, [])
    assert library.get_pdf_list(node_id) == []


def test_get_pdf_list_returns_a_copy(library: LibraryService) -> None:
    node_id = library.create_node("Book")
    library.add_pdf(node_id, "books/a.pdf")

    returned = library.get_pdf_list(node_id)
    returned.append("books/injected.pdf")

    assert library.get_pdf_list(node_id) == ["books/a.pdf"]


def test_remove_pdf_and_remove_pdfs(library: LibraryService) -> None:
    node_id = library.create_node("Book")
    library.add_pdfs(node_id, ["books/a.pdf", "books/b.pdf", "books/c.pdf"])

    assert library.remove_pdf(node_id, "books/a.pdf") is True
    assert library.remove_pdf(node_id, "books/a.pdf") is False
    assert library.remove_pdfs(node_id, ["books/b.pdf", "books/c.pdf", "books/x.pdf"]) == 2
    assert library.get_pdf_list(node_id) == []


def test_relink_pdf_keeps_the_position(library: LibraryService) -> None:
    node_id = library.create_node("Book")
    library.add_pdfs(node_id, ["books/a.pdf", "books/b.pdf", "books/c.pdf"])

    assert library.relink_pdf(node_id, "books/b.pdf", "books/new-b.pdf") is True

    assert library.get_pdf_list(node_id) == [
        "books/a.pdf",
        "books/new-b.pdf",
        "books/c.pdf",
    ]


def test_relink_pdf_rejects_unknown_old_path_and_empty_values(library: LibraryService) -> None:
    node_id = library.create_node("Book")
    library.add_pdf(node_id, "books/a.pdf")

    assert library.relink_pdf(node_id, "books/other.pdf", "books/new.pdf") is False
    with pytest.raises(ValueError):
        library.relink_pdf(node_id, "books/a.pdf", "   ")


def test_relink_pdf_collapses_an_existing_duplicate(library: LibraryService) -> None:
    node_id = library.create_node("Book")
    library.add_pdfs(node_id, ["books/a.pdf", "books/b.pdf"])

    changed = library.relink_pdf(node_id, "books/a.pdf", "books/b.pdf")

    assert changed is False
    assert library.get_pdf_list(node_id) == ["books/a.pdf", "books/b.pdf"]


def test_pdf_operations_require_an_existing_node(library: LibraryService) -> None:
    for operation in (
        lambda: library.get_pdf_list(999),
        lambda: library.set_pdf_list(999, []),
        lambda: library.add_pdf(999, "books/a.pdf"),
        lambda: library.add_pdfs(999, ["books/a.pdf"]),
        lambda: library.remove_pdfs(999, ["books/a.pdf"]),
        lambda: library.relink_pdf(999, "books/a.pdf", "books/b.pdf"),
    ):
        with pytest.raises(ValueError):
            operation()


def test_pdf_list_is_shared_by_every_display_instance(library: LibraryService) -> None:
    shelf_a = library.create_node("Shelf A")
    shelf_b = library.create_node("Shelf B")
    book_id = library.create_node("Capital", parent_id=shelf_a)
    library.attach_nodes(shelf_b, book_id)
    library.add_pdf(book_id, "books/capital.pdf")

    instance_a = library.get_node_children(shelf_a)[0]
    instance_b = library.get_node_children(shelf_b)[0]

    assert instance_a.id == instance_b.id == book_id
    assert instance_a.pdf_paths == ["books/capital.pdf"]
    assert instance_b.pdf_paths == ["books/capital.pdf"]
