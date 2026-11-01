# ==============================================================================
# tests/test_library_tree_view.py
# Pure-logic tests for Phase 5 drag and drop (drop decisions + MIME payload).
# ==============================================================================
import pytest

pytest.importorskip("PySide6")

from PySide6.QtCore import QMimeData, QModelIndex, QPointF, Qt
from PySide6.QtGui import QDropEvent

from controllers.app_controller import AppController
from views.library_tree_view import (
    LibraryTreeView,
    decode_drag_payload,
    encode_drag_payload,
)
from views.tree_model import TreeModel

pytestmark = pytest.mark.usefixtures("qapp")


@pytest.fixture
def controller(tmp_path) -> AppController:
    return AppController(db_path=tmp_path / "tree_view_dnd.db")


def make_view(controller: AppController) -> tuple[TreeModel, LibraryTreeView]:
    model = TreeModel(controller.library)
    model.refresh()
    view = LibraryTreeView(model, controller)
    return model, view


def index_of(model: TreeModel, path) -> QModelIndex:
    return model.find_index_by_display_path(tuple(path))


def test_payload_round_trip() -> None:
    mime = QMimeData()
    mime.setData("application/x-ap-manager-node-paths", encode_drag_payload([(1, 2), (1, 3)]))

    assert decode_drag_payload(mime) == ((1, 2), (1, 3))


def test_payload_rejects_foreign_or_broken_data() -> None:
    assert decode_drag_payload(None) == ()
    assert decode_drag_payload(QMimeData()) == ()

    broken = QMimeData()
    broken.setData("application/x-ap-manager-node-paths", b"not json")
    assert decode_drag_payload(broken) == ()

    wrong_shape = QMimeData()
    wrong_shape.setData("application/x-ap-manager-node-paths", b'{"paths": "nope"}')
    assert decode_drag_payload(wrong_shape) == ()


def test_drop_on_a_node_associates(controller: AppController) -> None:
    source = controller.create_node("Source")
    target = controller.create_node("Target")
    model, view = make_view(controller)

    decision = view.evaluate_drop([(source,)], index_of(model, (target,)), zone="on")

    assert decision.accepted is True
    assert decision.kind == "associate"
    assert decision.target_node_id == target
    assert decision.target_path == (target,)


def test_drop_on_self_is_rejected(controller: AppController) -> None:
    root = controller.create_node("Root")
    child = controller.create_node("Child", parent_id=root)
    model, view = make_view(controller)

    decision = view.evaluate_drop(
        [(root, child)], index_of(model, (root, child)), zone="on"
    )

    assert decision.accepted is False
    assert "自己" in decision.reason


def test_drop_that_would_cycle_is_rejected(controller: AppController) -> None:
    root = controller.create_node("Root")
    child = controller.create_node("Child", parent_id=root)
    model, view = make_view(controller)

    decision = view.evaluate_drop([(root,)], index_of(model, (root, child)), zone="on")

    assert decision.accepted is False
    assert "循环" in decision.reason
    assert "Root" in decision.reason and "Child" in decision.reason


def test_drop_onto_blank_area_is_rejected(controller: AppController) -> None:
    controller.create_node("Root")
    model, view = make_view(controller)

    decision = view.evaluate_drop([(1,)], QModelIndex(), zone="on")

    assert decision.accepted is False
    assert "空白" in decision.reason


def test_drop_between_siblings_reorders(controller: AppController) -> None:
    parent = controller.create_node("Parent")
    x = controller.create_node("X", parent_id=parent)
    y = controller.create_node("Y", parent_id=parent)
    z = controller.create_node("Z", parent_id=parent)
    model, view = make_view(controller)

    before = view.evaluate_drop(
        [(parent, x)], index_of(model, (parent, z)), zone="before"
    )
    after = view.evaluate_drop(
        [(parent, x)], index_of(model, (parent, z)), zone="after"
    )

    assert before.accepted is True and before.kind == "reorder"
    assert before.before is True
    assert after.accepted is True and after.before is False
    assert before.target_path == (parent, z)


def test_reorder_requires_exactly_one_source(controller: AppController) -> None:
    parent = controller.create_node("Parent")
    x = controller.create_node("X", parent_id=parent)
    y = controller.create_node("Y", parent_id=parent)
    model, view = make_view(controller)

    decision = view.evaluate_drop(
        [(parent, x), (parent, y)], index_of(model, (parent, y)), zone="before"
    )

    assert decision.accepted is False
    assert "一个节点" in decision.reason


def test_reorder_across_parents_is_rejected(controller: AppController) -> None:
    p1 = controller.create_node("P1")
    p2 = controller.create_node("P2")
    x = controller.create_node("X", parent_id=p1)
    z = controller.create_node("Z", parent_id=p2)
    model, view = make_view(controller)

    decision = view.evaluate_drop(
        [(p1, x)], index_of(model, (p2, z)), zone="before"
    )

    assert decision.accepted is False
    assert "同一个父级" in decision.reason


def test_root_level_sorting_is_rejected(controller: AppController) -> None:
    a = controller.create_node("A")
    b = controller.create_node("B")
    model, view = make_view(controller)

    decision = view.evaluate_drop([(a,)], index_of(model, (b,)), zone="before")

    assert decision.accepted is False
    assert "顶层" in decision.reason


def test_selected_display_paths_contains_current_instance(
    controller: AppController,
) -> None:
    root = controller.create_node("Root")
    child = controller.create_node("Child", parent_id=root)
    model, view = make_view(controller)

    view.setCurrentIndex(index_of(model, (root, child)))

    assert view.selected_display_paths() == [(root, child)]


def test_drop_event_emits_associate_signal(
    controller: AppController, qapp
) -> None:
    source = controller.create_node("Source")
    target = controller.create_node("Target")
    model, view = make_view(controller)
    view.resize(400, 300)
    view.show()
    qapp.processEvents()

    received = []
    view.associateDropped.connect(lambda paths, target_id: received.append((paths, target_id)))

    mime = QMimeData()
    mime.setData("application/x-ap-manager-node-paths", encode_drag_payload([(source,)]))
    target_rect = view.visualRect(index_of(model, (target,)))
    event = QDropEvent(
        QPointF(target_rect.center()),
        Qt.DropAction.MoveAction,
        mime,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
    )

    view.dropEvent(event)

    assert received == [([(source,)], target)]
    view.close()


def test_drop_event_emits_reorder_signal(
    controller: AppController, qapp
) -> None:
    parent = controller.create_node("Parent")
    x = controller.create_node("X", parent_id=parent)
    z = controller.create_node("Z", parent_id=parent)
    model, view = make_view(controller)
    view.resize(400, 300)
    view.show()
    view.expandAll()
    qapp.processEvents()

    received = []
    view.reorderDropped.connect(
        lambda source, target, before: received.append((source, target, before))
    )

    mime = QMimeData()
    mime.setData(
        "application/x-ap-manager-node-paths", encode_drag_payload([(parent, x)])
    )
    target_rect = view.visualRect(index_of(model, (parent, z)))
    event = QDropEvent(
        QPointF(target_rect.left() + 5, target_rect.top() + 1),
        Qt.DropAction.MoveAction,
        mime,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
    )

    view.dropEvent(event)

    assert received == [((parent, x), (parent, z), True)]
    view.close()
