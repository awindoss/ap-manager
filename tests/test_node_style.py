# ==============================================================================
# tests/test_node_style.py
# Node-level style normalisation and legacy NULL handling (Phase 3).
# ==============================================================================
import logging

import pytest

from models.database import Database
from models.node import Node, normalize_color, normalize_icon
from utils import constants


@pytest.fixture
def db(tmp_path) -> Database:
    database = Database(db_path=tmp_path / "node_style_test.db")
    database.init_tables()
    return database


def test_normalize_icon_and_color_handle_empty_values() -> None:
    assert normalize_icon(None) == ""
    assert normalize_icon("  ⭐  ") == "⭐"
    assert normalize_color(None) == constants.DEFAULT_TEXT_COLOR
    assert normalize_color("") == constants.DEFAULT_TEXT_COLOR
    assert normalize_color("  #AbC  ") == "#aabbcc"
    assert normalize_color("#B22222") == "#b22222"


def test_normalize_color_rejects_invalid_values_with_a_warning(caplog) -> None:
    with caplog.at_level(logging.WARNING, logger="ap_logger"):
        assert normalize_color("not-a-colour") == constants.DEFAULT_TEXT_COLOR
        assert normalize_color("#12345") == constants.DEFAULT_TEXT_COLOR
        assert normalize_color(42) == constants.DEFAULT_TEXT_COLOR

    assert "Invalid node colour" in caplog.text
    assert caplog.text.count("Invalid node colour") == 3


def test_node_post_init_normalises_schema_nulls_and_whitespace() -> None:
    node = Node(name="  Book  ", icon=None, style_bold=1, style_color=None)

    assert node.name == "Book"
    assert node.icon == ""
    assert node.style_bold is True
    assert node.style_color == constants.DEFAULT_TEXT_COLOR
    assert node.pdf_paths == []
    assert node.metadata == {}


def test_get_node_normalises_legacy_null_columns(db: Database) -> None:
    """A row written before Phase 3 may have NULL icon/style_color."""
    node_id = db.add_node(Node(name="Legacy"))
    with db.connection() as conn:
        conn.execute(
            f"UPDATE {constants.TABLE_NODES} "
            f"SET {constants.COLUMN_NODE_ICON} = NULL, "
            f"{constants.COLUMN_NODE_STYLE_COLOR} = NULL "
            f"WHERE {constants.COLUMN_NODE_ID} = ?",
            (node_id,),
        )

    node = db.get_node(node_id)

    assert node is not None
    assert node.icon == ""
    assert node.style_color == constants.DEFAULT_TEXT_COLOR
    assert node.style_bold is False


def test_database_update_normalises_invalid_style(db: Database) -> None:
    """Even a direct database write cannot store an invalid colour."""
    node_id = db.add_node(Node(name="Book"))

    db.update_node(
        node_id,
        name="  Renamed  ",
        icon=None,
        style_color="rgb(1,2,3)",
        style_bold=1,
    )

    node = db.get_node(node_id)
    assert node is not None
    assert node.name == "Renamed"
    assert node.icon == ""
    assert node.style_color == constants.DEFAULT_TEXT_COLOR
    assert node.style_bold is True
