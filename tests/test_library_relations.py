# ==============================================================================
# tests/test_library_relations.py
# Business-layer tests for the Phase 5 graph operations: attach/detach/move,
# descendant discovery, sibling ordering and multi-position queries.
# ==============================================================================
import pytest

from models.library import GraphCycleError, LibraryService


@pytest.fixture
def library(tmp_path) -> LibraryService:
    return LibraryService(db_path=tmp_path / "relations_test.db")


def names(library: LibraryService, parent_id: int) -> list[str]:
    return [node.name for node in library.get_node_children(parent_id)]


def test_attach_appends_and_keeps_existing_positions(library: LibraryService) -> None:
    id_library = library.create_node("经济政治")
    id_shelf = library.create_node("西欧哲学家")
    id_marx = library.create_node("马克思")

    library.attach_nodes(id_library, id_marx)
    library.attach_nodes(id_shelf, id_marx)

    assert [parent.id for parent in library.get_node_parents(id_marx)] == [
        id_library,
        id_shelf,
    ]
    assert library.get_parent_ids(id_marx) == [id_library, id_shelf]
    assert names(library, id_library) == ["马克思"]
    assert names(library, id_shelf) == ["马克思"]


def test_attach_rejects_a_duplicate_edge(library: LibraryService) -> None:
    parent = library.create_node("P")
    child = library.create_node("C")
    library.attach_nodes(parent, child)

    with pytest.raises(ValueError):
        library.attach_nodes(parent, child)


def test_attach_rejects_cycle_and_self_link(library: LibraryService) -> None:
    a = library.create_node("A")
    b = library.create_node("B")
    c = library.create_node("C")
    library.attach_nodes(a, b)
    library.attach_nodes(b, c)

    with pytest.raises(GraphCycleError):
        library.attach_nodes(c, a)
    with pytest.raises(ValueError):
        library.attach_nodes(a, a)

    # The rejected operation must not have written anything.
    assert library.get_node_parents(a) == []
    assert library.get_parent_ids(c) == [b]


def test_detach_removes_only_one_edge(library: LibraryService) -> None:
    a = library.create_node("A")
    b = library.create_node("B")
    x = library.create_node("X")
    library.attach_nodes(a, x)
    library.attach_nodes(b, x)

    assert library.detach_nodes(a, x) is True

    assert library.get_parent_ids(x) == [b]
    assert library.get_node(a).id == a
    assert library.get_node(x).id == x
    # Detaching a non-existent edge is a harmless no-op.
    assert library.detach_nodes(a, x) is False


def test_delete_node_completely_removes_all_edges(library: LibraryService) -> None:
    a = library.create_node("A")
    b = library.create_node("B")
    x = library.create_node("X")
    y = library.create_node("Y", parent_id=x)
    library.attach_nodes(a, x)
    library.attach_nodes(b, x)

    library.delete_node_completely(x)

    assert library.get_node(x) is None
    assert library.get_parent_ids(y) == []
    assert library.db.get_edge(a, x) is None
    assert library.db.get_edge(b, x) is None
    assert library.db.get_edge(x, y) is None
    assert library.get_node(y).name == "Y"


def test_get_descendant_ids_is_transitive(library: LibraryService) -> None:
    a = library.create_node("A")
    b = library.create_node("B", parent_id=a)
    c = library.create_node("C", parent_id=b)
    d = library.create_node("D", parent_id=a)
    other = library.create_node("other")

    descendants = set(library.get_descendant_ids(a))
    assert descendants == {b, c, d}
    assert other not in descendants
    assert library.get_descendant_ids(c) == []


def test_reorder_children_changes_display_order(library: LibraryService) -> None:
    parent = library.create_node("P")
    x = library.create_node("X", parent_id=parent)
    y = library.create_node("Y", parent_id=parent)
    z = library.create_node("Z", parent_id=parent)
    assert names(library, parent) == ["X", "Y", "Z"]

    assert library.reorder_children(parent, [z, x, y]) is True
    assert names(library, parent) == ["Z", "X", "Y"]
    assert [library.db.get_edge_sort_order(parent, cid) for cid in (z, x, y)] == [
        0,
        1,
        2,
    ]

    # The same order is a no-op.
    assert library.reorder_children(parent, [z, x, y]) is False


def test_reorder_children_rejects_foreign_or_incomplete_lists(
    library: LibraryService,
) -> None:
    parent = library.create_node("P")
    x = library.create_node("X", parent_id=parent)
    y = library.create_node("Y", parent_id=parent)
    foreign = library.create_node("Foreign")

    with pytest.raises(ValueError):
        library.reorder_children(parent, [x, foreign])
    with pytest.raises(ValueError):
        library.reorder_children(parent, [x, x, y])
    with pytest.raises(ValueError):
        library.reorder_children(parent, [x])


def test_reorder_relative_before_and_after(library: LibraryService) -> None:
    parent = library.create_node("P")
    x = library.create_node("X", parent_id=parent)
    y = library.create_node("Y", parent_id=parent)
    z = library.create_node("Z", parent_id=parent)

    assert library.reorder_relative(parent, z, x, before=True) is True
    assert names(library, parent) == ["Z", "X", "Y"]

    assert library.reorder_relative(parent, z, y, before=False) is True
    assert names(library, parent) == ["X", "Y", "Z"]

    # The node is already there: no write.
    assert library.reorder_relative(parent, x, y, before=True) is False


def test_new_edges_use_max_plus_one_after_detach(library: LibraryService) -> None:
    parent = library.create_node("P")
    x = library.create_node("X", parent_id=parent)
    y = library.create_node("Y", parent_id=parent)
    library.detach_nodes(parent, x)
    z = library.create_node("Z")
    library.attach_nodes(parent, z)

    assert names(library, parent) == ["Y", "Z"]
    assert library.db.get_edge_sort_order(parent, y) == 1
    assert library.db.get_edge_sort_order(parent, z) == 2


def test_move_node_moves_the_edge_and_appends(library: LibraryService) -> None:
    old_parent = library.create_node("Old")
    new_parent = library.create_node("New")
    sibling = library.create_node("Sibling", parent_id=new_parent)
    child = library.create_node("Child", parent_id=old_parent)

    assert library.move_node(old_parent, child, new_parent) is True

    assert library.get_parent_ids(child) == [new_parent]
    assert names(library, old_parent) == []
    assert names(library, new_parent) == ["Sibling", "Child"]


def test_get_node_paths_lists_every_root_path(library: LibraryService) -> None:
    a = library.create_node("A")
    b = library.create_node("B")
    x = library.create_node("X")
    library.attach_nodes(a, x)
    library.attach_nodes(b, x)

    assert library.get_node_paths(x) == [[a, x], [b, x]]
    assert library.get_node_paths(a) == [[a]]


def test_cycle_only_node_has_no_position(library: LibraryService) -> None:
    a = library.create_node("Cycle A")
    b = library.create_node("Cycle B")
    library.db.add_edge(a, b)
    library.db.add_edge(b, a)

    assert library.get_node_paths(a) == []
