# ==============================================================================
# models/library.py
# Business logic layer: encapsulates database operations and handles core business rules (such as cyclic checks and node hierarchy navigation)
# ==============================================================================
from pathlib import Path
from typing import Optional, List, Dict
import sqlite3

from models.database import Database
from models.node import Node
from models.edge import Edge
from utils.logger import log_info, log_error, log_warning

class LibraryService:
    """
    The Library class provides core graph management functionality.
    All interface operations (such as adding, moving and deleting nodes) should be carried out via this class to ensure the integrity of the business logic.
    """
    def __init__(self, db_path: Optional[str | Path] = None):
        if db_path:
            self.db = Database(db_path=db_path)
        else:
            self.db = Database()
        self.db.init_tables()
        log_info("Library business layer initialized.")

    # --------------------------------------------------------------------------
    # Node Management
    # --------------------------------------------------------------------------
    def create_node(self, name: str, parent_id: Optional[int] = None, **kwargs) -> Optional[int]:
        """
        Create a new node. If a parent_id is provided, the associated edge will be created automatically.
        """        
        if parent_id is not None:
            if self.db.get_node(parent_id) is None:
                log_error(f"Parent node {parent_id} does not exist.")
                raise ValueError(f"Parent node {parent_id} does not exist.")
            
        new_node = Node(name=name, **kwargs)
        node_id = self.db.add_node(new_node)

        if parent_id is not None:
            self.db.add_edge(parent_id, node_id)
            
        return node_id

    def update_node(self, node_id: int, **kwargs) -> None:
        """Update node properties"""
        self.db.update_node(node_id, **kwargs)

    def delete_node_completely(self, node_id: int) -> None:
        """Permanently delete the node and all of its associated edges."""
        self.db.delete_node(node_id)

    def get_node(self, node_id: int) -> Optional[Node]:
        """Retrieve node details"""
        return self.db.get_node(node_id)

    def move_node(self, old_parent_id: int, child_id: int, new_parent_id: int, sort_order: Optional[int] = None) -> bool:
        """
        Moves child nodes from the old parent to the new parent (supports node redirection in multi-parent graph structures).
        Includes loop prevention checks.
        """
        if old_parent_id == new_parent_id:
            log_warning(f"Move node ignored: old parent and new parent are the same ({old_parent_id}).")
            return True

        if new_parent_id == child_id:
            raise ValueError("A node cannot be moved under itself.")

        if self.db.would_create_cycle(new_parent_id, child_id):
            log_error(f"Cycle detected! Cannot move child {child_id} under new parent {new_parent_id}.")
            raise ValueError("Operation rejected: moving this node would create a cycle in the graph.")

        if sort_order is None:
            siblings = self.db.get_children(new_parent_id)
            sort_order = len(siblings)

        try:
            self.db.move_edge(old_parent_id, child_id, new_parent_id, sort_order)
            log_info(f"Successfully moved node {child_id} from parent {old_parent_id} to {new_parent_id}.")
            return True
        except sqlite3.Error as e:
            log_error(f"Error executing move_node for child {child_id}: {e}")
            return False

    # --------------------------------------------------------------------------
    # Edges and Graph Management
    # --------------------------------------------------------------------------
    def attach_nodes(self, parent_id: int, child_id: int, sort_order: Optional[int] = None) -> int:
        """
        Link two nodes (parent -> child).
        [Core business logic]: A cycle check must be performed before execution to prevent dead loops in the graph structure.
        Returns True to indicate success, and False to indicate rejection due to the presence of a cycle.
        """
        if parent_id == child_id:
            raise ValueError("A node cannot be a parent of itself.")

        parent = self.db.get_node(parent_id)
        child = self.db.get_node(child_id)
        if not parent or not child:
            log_error(f"Link rejected: node {parent_id} or {child_id} does not exist.")
            raise ValueError(f"Parent ({parent_id}) or Child ({child_id}) node does not exist.")

        if self.db.would_create_cycle(parent_id, child_id):
            log_error(f"Cycle detected! Cannot link parent {parent_id} to child {child_id}.")
            raise ValueError("Operation rejected: linking these nodes would create a cycle in the graph.")

        if sort_order is None:
            siblings = self.db.get_children(parent_id)
            sort_order = len(siblings)

        edge_id = self.db.add_edge(parent_id, child_id, sort_order)
        log_info(f"Successfully linked node {parent_id} -> {child_id} (Edge ID: {edge_id})")
        return edge_id

    def detach_nodes(self, parent_id: int, child_id: int) -> None:
        """Remove the link between two nodes"""
        self.db.delete_edge(parent_id, child_id)

    # --------------------------------------------------------------------------
    # Queries on tree structures
    # --------------------------------------------------------------------------
    def get_node_children(self, parent_id: int) -> List[Node]:
        """
        Retrieve the child nodes of `parent_id`, ordered by the edge `sort_order`
        (ties broken by edge id, i.e. insertion order). The ordering guarantee is
        what the QTreeView projection relies on, so it must stay stable.
        """
        child_ids = self.db.get_children(parent_id)
        children = []
        for cid in child_ids:
            node = self.db.get_node(cid)
            if node:
                children.append(node)
        return children

    def get_node_parents(self, child_id: int) -> List[Node]:
        """Retrieve a list of details for all parent nodes of a specified node (supports multiple parents)"""
        parent_ids = self.db.get_parents(child_id)
        parents = []
        for pid in parent_ids:
            node = self.db.get_node(pid)
            if node:
                parents.append(node)
        return parents

    def get_all_roots(self) -> List[Node]:
        """Retrieve all root nodes (top-level nodes with no parent)"""
        root_ids = self.db.get_root_nodes()
        roots = []
        for rid in root_ids:
            node = self.db.get_node(rid)
            if node:
                roots.append(node)
        return roots

    def get_all_nodes(self) -> List[Node]:
        """
        Retrieve every node stored in the library (ordered by node id).

        Used by the tree view to detect nodes that cannot be reached from any
        root (for example a component that only exists inside a cycle), and by
        later phases for search and export.
        """
        return self.db.get_all_nodes()

    def get_parent_count_map(self) -> Dict[int, int]:
        """
        Return ``{node_id: parent_count}`` for the whole library in one query.

        The tree model caches this when building, so presentation code can show
        the multi-parent badge without a database round-trip per row.
        """
        return self.db.get_parent_counts()

    def get_node_paths(self, node_id: int) -> List[List[int]]:
        """Retrieve all paths leading to this node from any root node (for UI expansion and positioning)"""
        return self.db.get_all_positions(node_id)