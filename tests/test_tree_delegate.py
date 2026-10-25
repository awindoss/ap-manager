# ==============================================================================
# tests/test_tree_delegate.py
# Multi-parent badge delegate: sizing and a render smoke test (Phase 3).
# ==============================================================================
import pytest

pytest.importorskip("PySide6")

from PySide6.QtCore import QModelIndex, QRect, Qt
from PySide6.QtGui import QPainter, QPixmap
from PySide6.QtWidgets import QApplication, QStyleOptionViewItem

from models.library import LibraryService
from views.delegates.tree_delegate import TreeDelegate
from views.tree_model import TreeModel

pytestmark = pytest.mark.usefixtures("qapp")


@pytest.fixture
def library(tmp_path) -> LibraryService:
    return LibraryService(db_path=tmp_path / "delegate_test.db")


def build_model(library: LibraryService) -> TreeModel:
    model = TreeModel(library)
    model.refresh()
    return model


def base_option() -> QStyleOptionViewItem:
    option = QStyleOptionViewItem()
    option.font = QApplication.font()
    option.rect = QRect(0, 0, 240, 20)
    return option


def test_size_hint_reserves_room_for_the_badge(library: LibraryService) -> None:
    single = library.create_node("X")
    parent_a = library.create_node("A")
    parent_b = library.create_node("B")
    shared = library.create_node("X")
    library.attach_nodes(parent_a, shared)
    library.attach_nodes(parent_b, shared)

    model = build_model(library)
    delegate = TreeDelegate()

    single_index = model.find_index_by_display_path((single,))
    shared_index = model.find_index_by_display_path((parent_a, shared))

    assert model.data(single_index, TreeModel.ParentCountRole) == 0
    assert model.data(shared_index, TreeModel.ParentCountRole) == 2

    option = base_option()
    single_size = delegate.sizeHint(option, single_index)
    shared_size = delegate.sizeHint(option, shared_index)

    assert single_size.height() == shared_size.height()
    assert shared_size.width() > single_size.width()


def test_paint_badge_and_plain_rows_without_error(library: LibraryService) -> None:
    parent_a = library.create_node("A")
    parent_b = library.create_node("B")
    shared = library.create_node("Shared", icon="⭐", style_bold=True)
    library.attach_nodes(parent_a, shared)
    library.attach_nodes(parent_b, shared)

    model = build_model(library)
    delegate = TreeDelegate()
    option = base_option()

    pixmap = QPixmap(option.rect.size())
    pixmap.fill(Qt.GlobalColor.white)
    painter = QPainter(pixmap)
    try:
        delegate.paint(painter, option, model.find_index_by_display_path((parent_a,)))
        delegate.paint(
            painter,
            option,
            model.find_index_by_display_path((parent_a, shared)),
        )
    finally:
        painter.end()

    assert not pixmap.isNull()
    # The badge is drawn in the right-hand margin; compare with an untouched
    # bitmap so a completely blank paint cannot pass silently.
    blank = QPixmap(option.rect.size())
    blank.fill(Qt.GlobalColor.white)
    assert pixmap.toImage() != blank.toImage()


def test_paint_ignores_invalid_index(library: LibraryService) -> None:
    model = build_model(library)
    delegate = TreeDelegate()

    pixmap = QPixmap(100, 20)
    pixmap.fill(Qt.GlobalColor.white)
    painter = QPainter(pixmap)
    try:
        # QTreeView never delegates an invalid index; make sure it cannot crash.
        delegate.paint(painter, base_option(), QModelIndex())
    finally:
        painter.end()

    assert not pixmap.isNull()
