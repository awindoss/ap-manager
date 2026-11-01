# ==============================================================================
# models/library.py
# Business logic layer: encapsulates database operations and handles core business rules (such as cyclic checks and node hierarchy navigation)
# ==============================================================================
from pathlib import Path
from typing import Iterable, Optional, List, Dict
import os
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
        Create a new node. When `parent_id` is given, the node and the edge that
        attaches it to that parent are written in a single transaction.
        """        
        if parent_id is not None and self.db.get_node(parent_id) is None:
            log_error(f"Parent node {parent_id} does not exist.")
            raise ValueError(f"Parent node {parent_id} does not exist.")
            
        new_node = Node(name=name, **kwargs)

        if parent_id is not None:
            # Node + edge in one transaction: no orphan node if the edge fails.
            return self.db.add_node_with_parent(new_node, parent_id)

        node_id = self.db.add_node(new_node)
            
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

    # --------------------------------------------------------------------------
    # PDF references (Phase 4)
    # --------------------------------------------------------------------------
    def get_pdf_list(self, node_id: int) -> List[str]:
        """Return the stored PDF paths of a node, in display order."""
        return list(self._require_node(node_id).pdf_paths)

    def set_pdf_list(self, node_id: int, pdf_paths: Iterable[object]) -> None:
        """
        Replace the whole PDF list of a node.

        Empty entries are dropped and duplicates are removed while preserving
        the first occurrence, so a hand-edited or imported list cannot leave the
        node with two references to the same file.
        """
        self._require_node(node_id)
        cleaned = self._dedupe_pdf_paths(pdf_paths)
        self.db.update_node(node_id, pdf_paths=cleaned)
        log_info(f"Node {node_id} PDF list set to {len(cleaned)} reference(s).")

    def add_pdf(self, node_id: int, pdf_path: object) -> bool:
        """Attach one PDF reference; returns False when it was already present."""
        if not self._clean_pdf_path(pdf_path):
            raise ValueError("PDF 路径不能为空。")
        return bool(self.add_pdfs(node_id, [pdf_path]))

    def add_pdfs(self, node_id: int, pdf_paths: Iterable[object]) -> List[str]:
        """
        Attach several PDF references in one database write.

        Returns the paths that were actually added. Duplicates (same file,
        case-insensitively on Windows) are skipped instead of being an error,
        which keeps "add a folder of PDFs twice" harmless.
        """
        node = self._require_node(node_id)
        # Hand-edited or imported data may contain duplicate spellings; clean
        # them while writing so the stored list stays canonical.
        current = self._dedupe_pdf_paths(node.pdf_paths)
        keys = {self._pdf_key(path) for path in current if path}

        added: List[str] = []
        for raw in pdf_paths or ():
            path = self._clean_pdf_path(raw)
            if not path:
                continue
            key = self._pdf_key(path)
            if key in keys:
                continue
            keys.add(key)
            current.append(path)
            added.append(path)

        if added:
            self.db.update_node(node_id, pdf_paths=current)
            log_info(f"Node {node_id} gained {len(added)} PDF reference(s).")
        return added

    def remove_pdf(self, node_id: int, pdf_path: object) -> bool:
        """Detach one PDF reference; returns False when it was not attached."""
        return self.remove_pdfs(node_id, [pdf_path]) > 0

    def remove_pdfs(self, node_id: int, pdf_paths: Iterable[object]) -> int:
        """
        Detach several PDF references in one database write.

        Only the database reference is removed; the file on disk is never
        touched (plan.md §40: classification deletion != file deletion).
        """
        node = self._require_node(node_id)
        keys = {
            self._pdf_key(path)
            for path in pdf_paths or ()
            if self._clean_pdf_path(path)
        }
        if not keys:
            return 0

        remaining = [path for path in node.pdf_paths if self._pdf_key(path) not in keys]
        removed = len(node.pdf_paths) - len(remaining)
        if removed:
            self.db.update_node(node_id, pdf_paths=remaining)
            log_info(f"Node {node_id} lost {removed} PDF reference(s).")
        return removed

    def relink_pdf(
        self,
        node_id: int,
        old_pdf_path: object,
        new_pdf_path: object,
    ) -> bool:
        """
        Point an existing reference at a different file, keeping its position.

        Used by "re-locate missing PDF" (plan.md §22): the classification stays
        exactly where it was, only the path changes. Returns False when the old
        path is not attached or the new path equals it.
        """
        node = self._require_node(node_id)
        old_clean = self._clean_pdf_path(old_pdf_path)
        new_clean = self._clean_pdf_path(new_pdf_path)
        if not old_clean or not new_clean:
            raise ValueError("PDF 路径不能为空。")

        old_key = self._pdf_key(old_clean)
        current = list(node.pdf_paths)
        current_keys = {self._pdf_key(path) for path in current}
        if old_key not in current_keys:
            return False

        new_key = self._pdf_key(new_clean)
        if new_key != old_key and new_key in current_keys:
            # The replacement is already attached: leave the list untouched so
            # the caller can report a duplicate instead of silently merging.
            return False

        updated = [new_clean if self._pdf_key(path) == old_key else path for path in current]
        updated = self._dedupe_pdf_paths(updated)

        if updated == current:
            return False
        if new_key == old_key:
            return False

        self.db.update_node(node_id, pdf_paths=updated)
        log_info(f"Node {node_id} re-linked a PDF reference.")
        return True

    # --------------------------------------------------------------------------
    # PDF helpers
    # --------------------------------------------------------------------------
    def _require_node(self, node_id: int) -> Node:
        node = self.db.get_node(node_id)
        if node is None:
            log_error(f"Node {node_id} does not exist.")
            raise ValueError(f"节点 {node_id} 不存在。")
        return node

    @staticmethod
    def _clean_pdf_path(pdf_path: object) -> str:
        return "" if pdf_path is None else str(pdf_path).strip()

    @staticmethod
    def _pdf_key(pdf_path: object) -> str:
        """Comparison key: normalised, case-insensitive on Windows."""
        text = "" if pdf_path is None else str(pdf_path).strip()
        if not text:
            return ""
        return os.path.normcase(os.path.normpath(text))

    @classmethod
    def _dedupe_pdf_paths(cls, pdf_paths: Iterable[object]) -> List[str]:
        cleaned: List[str] = []
        seen = set()
        for raw in pdf_paths or ():
            path = cls._clean_pdf_path(raw)
            if not path:
                continue
            key = cls._pdf_key(path)
            if key in seen:
                continue
            seen.add(key)
            cleaned.append(path)
        return cleaned
