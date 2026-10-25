# ==============================================================================
# tests/test_tree_model.py
# Tests for the graph -> QTreeView projection (Phase 2).
#
# The critical properties under test:
#   * a node reachable through several parents is displayed once per path;
#   * both display instances keep the same database node id;
#   * cycles on the current path are skipped and reported, never rendered.
# ==============================================================================
import logging

import pytest

pytest.importorskip("PySide6")

from PySide6.QtCore import QModelIndex, Qt
from PySide6.QtGui import QColor, QFont, QIcon

from models.library import LibraryService
from utils import constants
from views.tree_model import TreeItem, TreeModel

pytestmark = pytest.mark.usefixtures("qapp")


# ------------------------------------------------------------------------------
# Fixtures and helpers
# ------------------------------------------------------------------------------
@pytest.fixture
def library(tmp_path) -> LibraryService:
    """A LibraryService backed by an empty throw-away database."""
    return LibraryService(db_path=tmp_path / "tree_model_test.db")


def build_model(library: LibraryService) -> TreeModel:
    model = TreeModel(library)
    model.refresh()
    return model


def top(model: TreeModel, row: int) -> QModelIndex:
    return model.index(row, 0, QModelIndex())


def child(model: TreeModel, parent_index: QModelIndex, row: int) -> QModelIndex:
    return model.index(row, 0, parent_index)


def name_at(model: TreeModel, index: QModelIndex) -> str:
    return model.data(index, Qt.ItemDataRole.DisplayRole)


# ------------------------------------------------------------------------------
# Basic projection
# ------------------------------------------------------------------------------
def test_empty_library(library: LibraryService) -> None:
    model = build_model(library)

    assert model.root_count == 0
    assert model.rowCount(QModelIndex()) == 0
    assert model.columnCount() == 1
    assert model.displayed_node_count == 0
    assert model.displayed_item_count == 0
    assert model.is_loaded is True
    assert model.unreachable_node_ids == ()
    assert model.cycle_warnings == ()


def test_single_tree_structure(library: LibraryService) -> None:
    """A -> B -> C is projected with correct rows and parent links."""
    id_a = library.create_node("A")
    id_b = library.create_node("B", parent_id=id_a)
    id_c = library.create_node("C", parent_id=id_b)

    model = build_model(library)

    assert model.root_count == 1
    index_a = top(model, 0)
    assert name_at(model, index_a) == "A"
    assert model.node_id_from_index(index_a) == id_a
    assert model.rowCount(index_a) == 1

    index_b = child(model, index_a, 0)
    assert name_at(model, index_b) == "B"
    assert model.node_id_from_index(index_b) == id_b
    assert model.rowCount(index_b) == 1

    index_c = child(model, index_b, 0)
    assert name_at(model, index_c) == "C"
    assert model.node_id_from_index(index_c) == id_c
    assert model.rowCount(index_c) == 0

    # parent() must walk back up the projected tree, not the database graph.
    parent_b = model.parent(index_b)
    parent_c = model.parent(index_c)
    assert parent_b.isValid() and model.node_id_from_index(parent_b) == id_a
    assert parent_c.isValid() and model.node_id_from_index(parent_c) == id_b
    assert not model.parent(index_a).isValid()
    assert not model.parent(QModelIndex()).isValid()


def test_multi_parent_node_is_displayed_twice(library: LibraryService) -> None:
    """The Phase 2 acceptance case: A -> X and B -> X must show X twice."""
    id_a = library.create_node("A")
    id_b = library.create_node("B")
    id_x = library.create_node("X")
    library.attach_nodes(id_a, id_x)
    library.attach_nodes(id_b, id_x)

    model = build_model(library)

    assert model.root_count == 2
    instances = []
    for row in range(2):
        root_index = top(model, row)
        assert model.rowCount(root_index) == 1
        x_index = child(model, root_index, 0)
        assert name_at(model, x_index) == "X"
        # Same database node ...
        assert model.node_id_from_index(x_index) == id_x
        instances.append(x_index)

    # ... but two distinct display instances with distinct paths.
    paths = [model.data(index, TreeModel.DisplayPathRole) for index in instances]
    assert paths == [(id_a, id_x), (id_b, id_x)]
    assert len(model.find_items_by_node_id(id_x)) == 2

    assert model.displayed_node_count == 3
    assert model.displayed_item_count == 4


def test_shared_subtree_appears_under_each_parent(library: LibraryService) -> None:
    """A -> X, B -> X, X -> Y: Y is projected below both X instances."""
    id_a = library.create_node("A")
    id_b = library.create_node("B")
    id_x = library.create_node("X")
    id_y = library.create_node("Y")
    library.attach_nodes(id_a, id_x)
    library.attach_nodes(id_b, id_x)
    library.attach_nodes(id_x, id_y)

    model = build_model(library)

    y_paths = []
    for row in range(2):
        x_index = child(model, top(model, row), 0)
        assert model.rowCount(x_index) == 1
        y_index = child(model, x_index, 0)
        assert name_at(model, y_index) == "Y"
        assert model.node_id_from_index(y_index) == id_y
        y_paths.append(model.data(y_index, TreeModel.DisplayPathRole))

    assert y_paths == [(id_a, id_x, id_y), (id_b, id_x, id_y)]
    assert model.displayed_item_count == 6


# ------------------------------------------------------------------------------
# Ordering
# ------------------------------------------------------------------------------
def test_children_follow_sort_order(library: LibraryService) -> None:
    """get_node_children() and the model must honour edges.sort_order."""
    id_p = library.create_node("P")
    id_x = library.create_node("X")
    id_y = library.create_node("Y")
    id_z = library.create_node("Z")
    library.attach_nodes(id_p, id_z, sort_order=0)
    library.attach_nodes(id_p, id_y, sort_order=1)
    library.attach_nodes(id_p, id_x, sort_order=2)

    assert [node.name for node in library.get_node_children(id_p)] == ["Z", "Y", "X"]

    model = build_model(library)
    p_index = top(model, 0)
    assert [name_at(model, child(model, p_index, row)) for row in range(3)] == ["Z", "Y", "X"]


# ------------------------------------------------------------------------------
# Cycle protection
# ------------------------------------------------------------------------------
def test_cycle_is_skipped_and_reported(library: LibraryService, caplog) -> None:
    """Root -> A -> B -> A (forced) must not recurse; the repeated A is skipped."""
    id_root = library.create_node("Root")
    id_a = library.create_node("A", parent_id=id_root)
    id_b = library.create_node("B", parent_id=id_a)
    # Bypass the business-layer guard to simulate a corrupted database.
    library.db.add_edge(id_b, id_a)
    assert library.db.would_create_cycle(id_a, id_b) is True

    with caplog.at_level(logging.WARNING, logger="ap_logger"):
        model = build_model(library)

    # Root -> A -> B only; A is *not* re-rendered below B.
    index_root = top(model, 0)
    index_a = child(model, index_root, 0)
    index_b = child(model, index_a, 0)
    assert model.rowCount(index_b) == 0
    assert model.displayed_item_count == 3
    assert model.displayed_node_count == 3

    assert len(model.cycle_warnings) == 1
    repeated_id, path = model.cycle_warnings[0]
    assert repeated_id == id_a
    assert path == (id_root, id_a, id_b, id_a)
    assert "Cycle detected" in caplog.text


def test_cycle_only_component_is_not_displayed(library: LibraryService) -> None:
    """A component that only exists inside a cycle has no root and is reported."""
    id_a = library.create_node("Cycle A")
    id_b = library.create_node("Cycle B")
    library.db.add_edge(id_a, id_b)
    library.db.add_edge(id_b, id_a)
    id_root = library.create_node("Root")

    model = build_model(library)

    assert model.root_count == 1
    assert model.node_id_from_index(top(model, 0)) == id_root
    assert model.displayed_node_count == 1
    assert set(model.unreachable_node_ids) == {id_a, id_b}


# ------------------------------------------------------------------------------
# Refresh and roles
# ------------------------------------------------------------------------------
def test_refresh_rebuilds_from_database(library: LibraryService) -> None:
    id_root = library.create_node("Root")
    model = build_model(library)
    root_index = top(model, 0)
    assert model.rowCount(root_index) == 0

    id_child = library.create_node("Child", parent_id=id_root)
    model.refresh()

    root_index = top(model, 0)
    assert model.rowCount(root_index) == 1
    assert name_at(model, child(model, root_index, 0)) == "Child"
    assert model.node_id_from_index(child(model, root_index, 0)) == id_child


def test_flags_and_custom_roles(library: LibraryService) -> None:
    id_root = library.create_node("Root")
    model = build_model(library)
    index = top(model, 0)

    flags = model.flags(index)
    assert bool(flags & Qt.ItemFlag.ItemIsEnabled)
    assert bool(flags & Qt.ItemFlag.ItemIsSelectable)
    assert not bool(flags & Qt.ItemFlag.ItemIsEditable)
    assert model.flags(QModelIndex()) == Qt.ItemFlag.NoItemFlags

    assert model.data(index, TreeModel.NodeIdRole) == id_root
    assert model.data(index, TreeModel.DisplayPathRole) == (id_root,)
    assert model.columnCount() == 1
    assert model.headerData(0, Qt.Orientation.Horizontal, Qt.ItemDataRole.DisplayRole) == "名称"
    assert model.item_from_index(QModelIndex()) is None
    assert model.node_id_from_index(QModelIndex()) is None
    assert isinstance(model.item_from_index(index), TreeItem)


def test_leaf_node_roles_for_default_style(
    library: LibraryService,
    tmp_path,
    monkeypatch,
) -> None:
    """A plain node keeps the view's defaults instead of forcing a style."""
    books = tmp_path / constants.BOOKS_DIR_NAME
    books.mkdir()
    (books / "book.pdf").write_bytes(b"%PDF-1.4\n")
    monkeypatch.setattr(constants, "BASE_ROOT", tmp_path)
    library.create_node("Book", pdf_paths=["books/book.pdf"])
    model = build_model(library)
    index = top(model, 0)

    for role in (
        Qt.ItemDataRole.DecorationRole,
        Qt.ItemDataRole.FontRole,
        Qt.ItemDataRole.ForegroundRole,
    ):
        assert model.data(index, role) is None

    assert model.data(index, TreeModel.ParentCountRole) == 0

    tooltip = model.data(index, Qt.ItemDataRole.ToolTipRole)
    assert "Book" in tooltip
    assert "PDF: 1" in tooltip


# ------------------------------------------------------------------------------
# Phase 3: visual roles, parent badge data and in-place updates
# ------------------------------------------------------------------------------
def test_visual_roles_reflect_node_style(library: LibraryService) -> None:
    library.create_node(
        "Styled",
        icon="⭐",
        style_bold=True,
        style_color="#B22222",
    )
    model = build_model(library)
    index = top(model, 0)

    decoration = model.data(index, Qt.ItemDataRole.DecorationRole)
    font = model.data(index, Qt.ItemDataRole.FontRole)
    foreground = model.data(index, Qt.ItemDataRole.ForegroundRole)

    assert isinstance(decoration, QIcon) and not decoration.isNull()
    assert isinstance(font, QFont) and font.bold() is True
    assert isinstance(foreground, QColor)
    assert foreground.name() == "#b22222"


def test_default_colour_is_left_to_the_palette(library: LibraryService) -> None:
    library.create_node("Plain", style_color="#000000")
    model = build_model(library)

    assert model.data(top(model, 0), Qt.ItemDataRole.ForegroundRole) is None


def test_parent_count_role_marks_shared_nodes(library: LibraryService) -> None:
    id_a = library.create_node("A")
    id_b = library.create_node("B")
    id_x = library.create_node("X")
    library.attach_nodes(id_a, id_x)
    library.attach_nodes(id_b, id_x)
    id_y = library.create_node("Y", parent_id=id_x)

    model = build_model(library)

    for row in range(2):
        root_index = top(model, row)
        x_index = child(model, root_index, 0)
        assert model.data(root_index, TreeModel.ParentCountRole) == 0
        assert model.data(x_index, TreeModel.ParentCountRole) == 2
        y_index = child(model, x_index, 0)
        assert model.data(y_index, TreeModel.ParentCountRole) == 1

    assert model.parent_count(id_x) == 2
    assert model.parent_count(id_y) == 1
    assert model.parent_count(999999) == 0


def test_tooltip_reports_multiple_positions(library: LibraryService) -> None:
    id_a = library.create_node("A")
    id_b = library.create_node("B")
    id_x = library.create_node("X")
    library.attach_nodes(id_a, id_x)
    library.attach_nodes(id_b, id_x)

    model = build_model(library)
    x_index = child(model, top(model, 0), 0)

    tooltip = model.data(x_index, Qt.ItemDataRole.ToolTipRole)
    assert "位置: 2 个" in tooltip


def test_notify_node_changed_updates_every_instance_without_reset(library: LibraryService) -> None:
    id_a = library.create_node("A")
    id_b = library.create_node("B")
    id_x = library.create_node("X")
    library.attach_nodes(id_a, id_x)
    library.attach_nodes(id_b, id_x)

    model = build_model(library)
    resets = []
    model.modelReset.connect(lambda: resets.append(True))

    library.update_node(
        id_x,
        name="Renamed",
        icon="⭐",
        style_bold=True,
        style_color="#123456",
    )
    assert model.notify_node_changed(id_x) is True

    assert resets == []
    for row in range(2):
        x_index = child(model, top(model, row), 0)
        assert name_at(model, x_index) == "Renamed"
        assert model.data(x_index, Qt.ItemDataRole.FontRole).bold() is True
        assert model.data(x_index, Qt.ItemDataRole.ForegroundRole).name() == "#123456"
        assert model.data(x_index, Qt.ItemDataRole.DecorationRole) is not None
        assert model.data(x_index, TreeModel.ParentCountRole) == 2


def test_notify_node_changed_unknown_node_returns_false(library: LibraryService) -> None:
    model = build_model(library)

    assert model.notify_node_changed(999999) is False


def test_find_index_by_display_path(library: LibraryService) -> None:
    id_a = library.create_node("A")
    id_b = library.create_node("B")
    id_x = library.create_node("X")
    library.attach_nodes(id_a, id_x)
    library.attach_nodes(id_b, id_x)

    model = build_model(library)

    index_a_x = model.find_index_by_display_path((id_a, id_x))
    index_b_x = model.find_index_by_display_path((id_b, id_x))

    assert index_a_x.isValid() and index_b_x.isValid()
    assert index_a_x != index_b_x
    assert model.node_id_from_index(index_a_x) == id_x
    assert model.data(index_a_x, TreeModel.DisplayPathRole) == (id_a, id_x)

    assert not model.find_index_by_display_path(()).isValid()
    assert not model.find_index_by_display_path((id_a, 999999)).isValid()
    assert not model.find_index_by_display_path((999999,)).isValid()


# ------------------------------------------------------------------------------
# Phase 3: missing PDF marker
# ------------------------------------------------------------------------------
def test_missing_pdf_gets_a_warning_icon_and_tooltip(
    library: LibraryService,
    tmp_path,
    monkeypatch,
) -> None:
    books = tmp_path / constants.BOOKS_DIR_NAME
    books.mkdir()
    (books / "present.pdf").write_bytes(b"%PDF-1.4\n")
    monkeypatch.setattr(constants, "BASE_ROOT", tmp_path)

    id_ok = library.create_node(
        "Present", pdf_paths=["books/present.pdf"], icon="📚"
    )
    id_missing = library.create_node("Missing", pdf_paths=["books/gone.pdf"])

    model = build_model(library)

    assert model.missing_pdf_node_ids == (id_missing,)
    assert model.missing_pdf_paths(id_missing) == ("books/gone.pdf",)
    assert model.missing_pdf_paths(id_ok) == ()

    ok_index = model.find_index_by_display_path((id_ok,))
    missing_index = model.find_index_by_display_path((id_missing,))

    # A node without its own icon still gets a warning icon.
    assert isinstance(model.data(ok_index, Qt.ItemDataRole.DecorationRole), QIcon)
    assert isinstance(model.data(missing_index, Qt.ItemDataRole.DecorationRole), QIcon)

    tooltip = model.data(missing_index, Qt.ItemDataRole.ToolTipRole)
    assert "缺失 PDF: 1" in tooltip
    assert "books/gone.pdf" in tooltip
    assert "缺失" not in (model.data(ok_index, Qt.ItemDataRole.ToolTipRole) or "")


def test_partially_missing_pdf_is_flagged(
    library: LibraryService,
    tmp_path,
    monkeypatch,
) -> None:
    books = tmp_path / constants.BOOKS_DIR_NAME
    books.mkdir()
    (books / "present.pdf").write_bytes(b"%PDF-1.4\n")
    monkeypatch.setattr(constants, "BASE_ROOT", tmp_path)

    node_id = library.create_node(
        "Mixed",
        pdf_paths=["books/present.pdf", "books/gone.pdf"],
    )

    model = build_model(library)

    assert model.missing_pdf_node_ids == (node_id,)
    assert model.missing_pdf_paths(node_id) == ("books/gone.pdf",)


def test_notify_node_changed_refreshes_the_missing_pdf_cache(
    library: LibraryService,
    tmp_path,
    monkeypatch,
) -> None:
    monkeypatch.setattr(constants, "BASE_ROOT", tmp_path)
    node_id = library.create_node("Book", pdf_paths=["books/gone.pdf"])
    model = build_model(library)
    assert model.missing_pdf_node_ids == (node_id,)

    (tmp_path / constants.BOOKS_DIR_NAME).mkdir()
    (tmp_path / constants.BOOKS_DIR_NAME / "gone.pdf").write_bytes(b"%PDF-1.4\n")
    library.update_node(node_id, pdf_paths=["books/gone.pdf"])
    assert model.notify_node_changed(node_id) is True

    assert model.missing_pdf_node_ids == ()

