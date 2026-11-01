# ==============================================================================
# tests/test_controller_relations.py
# Controller-level tests for Phase 5 multi-parent operations.
# ==============================================================================
import pytest

from controllers.app_controller import AppController
from models.library import GraphCycleError


@pytest.fixture
def controller(tmp_path) -> AppController:
    return AppController(db_path=tmp_path / "controller_relations.db")


def test_attach_node_to_several_parents(controller: AppController) -> None:
    shelf_a = controller.create_node("A")
    shelf_b = controller.create_node("B")
    book = controller.create_node("Book")

    result = controller.attach_node_to_parents(book, [shelf_a, shelf_b])

    assert result.attached == [(shelf_a, book), (shelf_b, book)]
    assert result.already == []
    assert result.errors == []
    assert result.has_changes is True
    assert controller.get_parent_ids(book) == [shelf_a, shelf_b]


def test_attach_reports_duplicates_and_cycle_without_aborting(
    controller: AppController,
) -> None:
    root = controller.create_node("Root")
    middle = controller.create_node("Middle", parent_id=root)
    leaf = controller.create_node("Leaf", parent_id=middle)
    other = controller.create_node("Other")

    result = controller.attach_node_to_parents(leaf, [middle, other, root, other])

    # `middle -> leaf` already exists; `root -> leaf` is legal; the duplicate of
    # `other` is only processed once.
    assert result.attached == [(other, leaf), (root, leaf)]
    assert result.already == [(middle, leaf)]
    assert result.errors == []

    # Attaching the root below its own descendant would create a cycle.
    cycle_result = controller.attach_node_to_parents(root, [leaf])
    assert cycle_result.attached == []
    assert len(cycle_result.errors) == 1
    (pair, message) = cycle_result.errors[0]
    assert pair == (leaf, root)
    assert "循环" in message
    assert "Root" in message and "Leaf" in message


def test_attach_reports_a_missing_parent(controller: AppController) -> None:
    child = controller.create_node("Child")

    result = controller.attach_node_to_parents(child, [999999])

    assert result.attached == []
    assert result.errors
    assert "不存在" in result.errors[0][1]


def test_attach_nodes_to_one_parent(controller: AppController) -> None:
    parent = controller.create_node("Parent")
    a = controller.create_node("A")
    b = controller.create_node("B")

    result = controller.attach_nodes_to_parent([a, b], parent)

    assert result.attached == [(parent, a), (parent, b)]
    assert [node.name for node in controller.get_node_children(parent)] == ["A", "B"]


def test_detach_node_removes_one_position_only(controller: AppController) -> None:
    a = controller.create_node("A")
    b = controller.create_node("B")
    book = controller.create_node("Book")
    controller.attach_node_to_parents(book, [a, b])

    assert controller.detach_node(a, book) is True
    assert controller.get_parent_ids(book) == [b]
    assert controller.get_node(book) is not None
    assert controller.detach_node(a, book) is False


def test_move_node_outcomes(controller: AppController) -> None:
    old_parent = controller.create_node("Old")
    new_parent = controller.create_node("New")
    child = controller.create_node("Child", parent_id=old_parent)

    outcome = controller.move_node(old_parent, child, new_parent)
    assert outcome.kind == "moved"
    assert outcome.moved is True
    assert controller.get_parent_ids(child) == [new_parent]

    # Same parent: nothing to do.
    assert controller.move_node(new_parent, child, new_parent).kind == "same"

    # Target already contains the node: the old edge is removed (merge).
    third = controller.create_node("Third")
    controller.attach_node_to_parents(child, [third])
    merged = controller.move_node(new_parent, child, third)
    assert merged.kind == "merged"
    assert controller.get_parent_ids(child) == [third]


def test_move_root_node_attaches_and_then_reports_already(
    controller: AppController,
) -> None:
    root = controller.create_node("Root")
    parent = controller.create_node("Parent")

    outcome = controller.move_node(None, root, parent)
    assert outcome.kind == "attached"
    assert controller.get_parent_ids(root) == [parent]

    # A root instance that is already at the target cannot be attached twice.
    assert controller.move_node(None, root, parent).kind == "already"


def test_move_node_rejects_cycles_and_stale_sources(
    controller: AppController,
) -> None:
    root = controller.create_node("Root")
    middle = controller.create_node("Middle", parent_id=root)
    leaf = controller.create_node("Leaf", parent_id=middle)

    with pytest.raises(GraphCycleError):
        controller.move_node(None, root, leaf)
    with pytest.raises(GraphCycleError):
        controller.move_node(root, middle, middle)
    with pytest.raises(ValueError):
        controller.move_node(999999, leaf, root)


def test_get_node_positions_resolves_names_and_paths(
    controller: AppController,
) -> None:
    a = controller.create_node("A")
    b = controller.create_node("B")
    x = controller.create_node("X")
    controller.attach_node_to_parents(x, [a, b])

    positions = controller.get_node_positions(x)

    assert [position.path for position in positions] == [(a, x), (b, x)]
    assert [position.label for position in positions] == ["A > X", "B > X"]
    assert all(position.node_id == x for position in positions)

    single = controller.get_node_positions(a)
    assert [position.label for position in single] == ["A"]

    with pytest.raises(ValueError):
        controller.get_node_positions(999999)


def test_get_node_positions_for_cycle_only_node(controller: AppController) -> None:
    a = controller.create_node("Cycle A")
    b = controller.create_node("Cycle B")
    controller.library.db.add_edge(a, b)
    controller.library.db.add_edge(b, a)

    assert controller.get_node_positions(a) == []


def test_reorder_and_descendant_helpers(controller: AppController) -> None:
    parent = controller.create_node("Parent")
    x = controller.create_node("X", parent_id=parent)
    y = controller.create_node("Y", parent_id=parent)
    z = controller.create_node("Grandchild", parent_id=x)

    assert set(controller.get_descendant_ids(parent)) == {x, y, z}
    assert controller.reorder_relative(parent, y, x, before=True) is True
    assert [node.name for node in controller.get_node_children(parent)] == [
        "Y",
        "X",
    ]


def test_delete_node_completely_through_controller(
    controller: AppController,
) -> None:
    a = controller.create_node("A")
    b = controller.create_node("B")
    book = controller.create_node("Book")
    controller.attach_node_to_parents(book, [a, b])

    controller.delete_node_completely(book)

    assert controller.get_node(book) is None
    assert controller.get_node_children(a) == []
    assert controller.get_node_children(b) == []

    with pytest.raises(ValueError):
        controller.delete_node_completely(book)
