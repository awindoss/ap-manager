# ==============================================================================
# tests/test_controller_editing.py
# Phase 3 controller write interface: validation, normalisation, parent queries.
# ==============================================================================
import pytest

from controllers.app_controller import AppController
from utils import constants


@pytest.fixture
def controller(tmp_path) -> AppController:
    return AppController(db_path=tmp_path / "controller_editing.db")


def test_create_node_persists_style(controller: AppController) -> None:
    node_id = controller.create_node(
        "  马克思  ",
        icon="👤",
        style_bold=True,
        style_color="#1E5AA8",
    )

    node = controller.get_node(node_id)
    assert node is not None
    assert node.name == "马克思"
    assert node.icon == "👤"
    assert node.style_bold is True
    assert node.style_color == "#1e5aa8"


def test_create_node_normalises_invalid_style(controller: AppController) -> None:
    node_id = controller.create_node("Book", icon=None, style_color="red")
    node = controller.get_node(node_id)

    assert node.icon == ""
    assert node.style_color == constants.DEFAULT_TEXT_COLOR


def test_create_node_rejects_empty_name(controller: AppController) -> None:
    with pytest.raises(ValueError, match="不能为空"):
        controller.create_node("   ")
    with pytest.raises(ValueError, match="不能为空"):
        controller.create_node(None)


def test_create_node_rejects_overlong_name(controller: AppController) -> None:
    with pytest.raises(ValueError, match="不能超过"):
        controller.create_node("x" * (constants.MAX_NODE_NAME_LENGTH + 1))


def test_create_child_node_creates_edge(controller: AppController) -> None:
    parent_id = controller.create_node("马列")
    child_id = controller.create_node("马克思", parent_id=parent_id)

    assert [node.id for node in controller.get_node_children(parent_id)] == [child_id]
    assert [node.id for node in controller.get_node_parents(child_id)] == [parent_id]


def test_create_node_with_unknown_parent_is_rejected(controller: AppController) -> None:
    with pytest.raises(ValueError):
        controller.create_node("Orphan", parent_id=999999)


def test_update_node_writes_only_given_fields(controller: AppController) -> None:
    node_id = controller.create_node("Old", icon="📚", style_bold=False, style_color="#000000")

    assert controller.update_node(node_id, name="New") is True
    node = controller.get_node(node_id)
    assert node.name == "New"
    assert node.icon == "📚"

    assert controller.update_node(node_id, icon="", style_bold=True, style_color="#B22222") is True
    node = controller.get_node(node_id)
    assert node.icon == ""
    assert node.style_bold is True
    assert node.style_color == "#b22222"


def test_update_node_with_no_changes_is_a_noop(controller: AppController) -> None:
    node_id = controller.create_node("Same")

    assert controller.update_node(node_id) is False


def test_update_node_rejects_empty_name(controller: AppController) -> None:
    node_id = controller.create_node("Old")

    with pytest.raises(ValueError, match="不能为空"):
        controller.update_node(node_id, name="   ")


def test_update_unknown_node_is_rejected(controller: AppController) -> None:
    with pytest.raises(ValueError, match="不存在"):
        controller.update_node(999999, name="Ghost")


def test_parent_count_map_and_parents(controller: AppController) -> None:
    parent_a = controller.create_node("A")
    parent_b = controller.create_node("B")
    shared = controller.create_node("X")
    controller.library.attach_nodes(parent_a, shared)
    controller.library.attach_nodes(parent_b, shared)

    assert controller.get_parent_count_map()[shared] == 2
    assert {node.id for node in controller.get_node_parents(shared)} == {parent_a, parent_b}
