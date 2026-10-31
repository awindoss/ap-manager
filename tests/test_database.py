# ==============================================================================
# tests/test_database.py
# Unit testing of the core data layer: verifying multiple parent relationships, cascading deletes, cycle detection and overall consistency
# ==============================================================================
import sqlite3

import pytest
from pathlib import Path
from utils import constants

from models.database import Database
from models.node import Node
from models.edge import Edge

@pytest.fixture
def db(tmp_path):
    """
    Pytest fixture: Provides a separate temporary database instance for each test function.
    """
    db_file = tmp_path / "test_library.db"
    database = Database(db_path=db_file)
    database.init_tables()
    return database


def test_init_tables(db: Database):
    """After testing the initialisation of the table structure, the data table is empty"""
    nodes = db.get_all_nodes()
    edges = db.get_all_edges()
    assert nodes == []
    assert edges == []


def test_node_crud(db: Database):
    """CRUD operations on test nodes and secure parsing of JSON fields"""
    node = Node(
        name="Python Programming", 
        pdf_paths=["/docs/python.pdf"], 
        metadata={"author": "Guido", "year": 1991}
    )
    
    # 1. Create
    node_id = db.add_node(node)
    assert node_id > 0

    # 2. Read
    fetched = db.get_node(node_id)
    assert fetched is not None
    assert fetched.name == "Python Programming"
    assert fetched.pdf_paths == ["/docs/python.pdf"]
    assert fetched.metadata == {"author": "Guido", "year": 1991}
    assert fetched.style_bold is False

    # 3. Update
    db.update_node(node_id, name="Advanced Python", style_bold=True, pdf_paths=["/docs/adv.pdf"])
    updated = db.get_node(node_id)
    assert updated.name == "Advanced Python"
    assert updated.style_bold is True
    assert updated.pdf_paths == ["/docs/adv.pdf"]

    # 4. Delete
    db.delete_node(node_id)
    assert db.get_node(node_id) is None


def test_multi_parent_graph_structure(db: Database):
    """
    Key test: A -> X, B -> X
    Verify that X appears only once in the 'nodes' table, but has two associated edges in the 'edges' table (multiple parents).
    """
    id_a = db.add_node(Node(name="Category A"))
    id_b = db.add_node(Node(name="Category B"))
    id_x = db.add_node(Node(name="Shared Item X"))

    db.add_edge(id_a, id_x)
    db.add_edge(id_b, id_x)

    parents_of_x = db.get_parents(id_x)
    assert sorted(parents_of_x) == sorted([id_a, id_b])

    assert db.get_children(id_a) == [id_x]
    assert db.get_children(id_b) == [id_x]

    all_nodes = db.get_all_nodes()
    assert len(all_nodes) == 3

    all_edges = db.get_all_edges()
    assert len(all_edges) == 2


def test_cycle_detection(db: Database):
    """
    Key test: A -> B -> C -> A
    Verify that would_create_cycle correctly detects potential cycles and returns `True`.
    """
    id_a = db.add_node(Node(name="Node A"))
    id_b = db.add_node(Node(name="Node B"))
    id_c = db.add_node(Node(name="Node C"))

    db.add_edge(id_a, id_b)  # A -> B
    db.add_edge(id_b, id_c)  # B -> C

    assert db.would_create_cycle(id_c, id_a) is True

    assert db.would_create_cycle(id_a, id_a) is True

    id_d = db.add_node(Node(name="Node D"))
    assert db.would_create_cycle(id_c, id_d) is False


def test_get_all_positions(db: Database):
    """Testing full-path backtracking in multi-parent scenarios (get_all_positions)"""
    r1 = db.add_node(Node(name="Root 1"))
    r2 = db.add_node(Node(name="Root 2"))
    x = db.add_node(Node(name="Target X"))

    db.add_edge(r1, x)
    db.add_edge(r2, x)

    positions = db.get_all_positions(x)
    
    assert len(positions) == 2
    assert [r1, x] in positions
    assert [r2, x] in positions

def test_delete_edge(db: Database):
    """Testing the deletion of relationships: A -> C and B -> C exist; after deleting A -> C, B -> C still exists."""
    id_a = db.add_node(Node(name="A"))
    id_b = db.add_node(Node(name="B"))
    id_c = db.add_node(Node(name="C"))

    db.add_edge(id_a, id_c)
    db.add_edge(id_b, id_c)

    db.delete_edge(id_a, id_c)

    assert db.get_parents(id_c) == [id_b]
    assert db.get_children(id_a) == []
    assert db.get_children(id_b) == [id_c]
    assert len(db.get_all_edges()) == 1


def test_complete_deletion_cascade(db: Database):
    """Test for complete deletion: when C is deleted, all edges linking A to C and B to C are automatically removed"""
    id_a = db.add_node(Node(name="A"))
    id_b = db.add_node(Node(name="B"))
    id_c = db.add_node(Node(name="C"))

    db.add_edge(id_a, id_c)
    db.add_edge(id_b, id_c)

    db.delete_node(id_c)

    assert db.get_node(id_c) is None
    assert db.get_children(id_a) == []
    assert db.get_children(id_b) == []
    assert len(db.get_all_edges()) == 0

def test_get_root_nodes(db: Database):
    """Test to determine the root node: When A -> X, A is the root and X is not."""
    id_a = db.add_node(Node(name="Root A"))
    id_x = db.add_node(Node(name="Child X"))

    db.add_edge(id_a, id_x)

    roots = db.get_root_nodes()
    assert id_a in roots
    assert id_x not in roots
    assert len(roots) == 1


def test_get_parent_counts_aggregates_in_one_query(db: Database):
    """Phase 3 badge data: one GROUP BY result for the whole graph."""
    id_a = db.add_node(Node(name="A"))
    id_b = db.add_node(Node(name="B"))
    id_x = db.add_node(Node(name="Shared X"))
    id_y = db.add_node(Node(name="Child Y"))
    db.add_edge(id_a, id_x)
    db.add_edge(id_b, id_x)
    db.add_edge(id_x, id_y)

    counts = db.get_parent_counts()

    assert counts[id_x] == 2
    assert counts[id_y] == 1
    assert counts.get(id_a, 0) == 0
    assert counts.get(id_b, 0) == 0


def test_update_node_bogus_field(db: Database):
    """Test for updating a node with an invalid field: db.update_node(id, bogus="x") should not raise an exception, and valid fields should be updated as normal."""
    id_a = db.add_node(Node(name="Original Name"))
    
    # Passing in parameters containing an unknown bogus field
    db.update_node(id_a, bogus="unexpected_value", name="Updated Name")
    
    node = db.get_node(id_a)
    assert node.name == "Updated Name"


def test_safe_json_loads_fault_tolerance(db: Database):
    """Test the fault tolerance of _safe_json_loads: manually write invalid JSON to the database; get_node should fall back and return [] rather than crash"""
    id_a = db.add_node(Node(name="Corrupt JSON Node"))

    # Manually injecting a JSON string in an invalid format into the underlying database
    with db.connection() as conn:
        conn.execute(
            f"UPDATE {constants.TABLE_NODES} SET {constants.COLUMN_NODE_PDFS} = ? WHERE {constants.COLUMN_NODE_ID} = ?",
            ("NOT_A_VALID_JSON_STRING", id_a)
        )

    # When retrieving nodes normally, security fault tolerance should be triggered; `pdf_paths` returns the default value [] without raising an error
    node = db.get_node(id_a)
    assert node is not None
    assert node.pdf_paths == []

def test_get_all_positions_with_cycle(db: Database):
    """Test get_all_positions does not cause a stack overflow during the loop"""
    a = db.add_node(Node(name="A"))
    b = db.add_node(Node(name="B"))
    db.add_edge(a, b)
    db.add_edge(b, a)
    positions = db.get_all_positions(a)
    # As long as it doesn't crash, that's fine

def test_multi_level_shared_subtree(db: Database):
    """Test A -> X, B -> X, X -> Y"""
    a = db.add_node(Node(name="A"))
    b = db.add_node(Node(name="B"))
    x = db.add_node(Node(name="X"))
    y = db.add_node(Node(name="Y"))
    db.add_edge(a, x)
    db.add_edge(b, x)
    db.add_edge(x, y)

    positions_y = db.get_all_positions(y)
    assert sorted(positions_y) == sorted([[a, x, y], [b, x, y]])


def test_add_node_with_parent_writes_both_rows(db: Database):
    """A child node and the edge attaching it are created by one call."""
    parent = db.add_node(Node(name="Parent"))

    child = db.add_node_with_parent(Node(name="Child"), parent)

    assert db.get_node(child).name == "Child"
    assert db.get_children(parent) == [child]
    assert len(db.get_all_nodes()) == 2
    assert len(db.get_all_edges()) == 1


def test_add_node_with_parent_rolls_back_when_parent_missing(db: Database):
    """A failed edge insert must not leave an orphan node behind."""
    with pytest.raises(sqlite3.IntegrityError):
        db.add_node_with_parent(Node(name="Orphan"), 9999)

    assert db.get_all_nodes() == []
    assert db.get_all_edges() == []


def test_library_create_node_under_parent_is_atomic(db: Database):
    """LibraryService.create_node takes the single-transaction path."""
    from models.library import LibraryService

    service = LibraryService(db_path=db.db_path)
    root = service.create_node("Root")
    child = service.create_node("Child", parent_id=root)

    assert service.db.get_children(root) == [child]
    assert len(service.db.get_all_nodes()) == 2
    assert len(service.db.get_all_edges()) == 1

    with pytest.raises(ValueError):
        service.create_node("Nope", parent_id=9999)
    assert len(service.db.get_all_nodes()) == 2
    assert len(service.db.get_all_edges()) == 1