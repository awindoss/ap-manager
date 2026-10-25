# ==============================================================================
# models/database.py
# A core database class that handles SQLite interactions and CRUD operations on graph structures
# ==============================================================================
import sqlite3
import json
from pathlib import Path
from typing import Optional, List, Dict, Any
from contextlib import contextmanager
from collections import deque

from models.node import Node, normalize_color, normalize_icon
from models.edge import Edge
from utils import constants
from utils.logger import log_info, log_error, log_debug, log_warning

class Database:
    """
    Responsible for interactions with the local SQLite database.
    As planned, a directed graph structure based on 'nodes' and 'edges' tables is used.
    """
    def __init__(self, db_path: str | Path = constants.DB_PATH):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        log_debug(f"Initialized Database with path: {self.db_path}")

    def connect(self) -> sqlite3.Connection:
        """
        Creates and returns a connection to the underlying database.
        """
        conn = sqlite3.connect(str(self.db_path))
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON;")
        return conn

    @contextmanager
    def connection(self):
        """
        A context manager for database connections.
        Ensures that connections are closed correctly after use, prevents connection leaks, and provides centralised management of transactions.
        """
        conn = self.connect()
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def init_tables(self) -> None:
        """Initialise the database table structures and indexes."""
        try:
            with self.connection() as conn:
                # 1. Create the 'nodes' table
                conn.execute(f"""
                    CREATE TABLE IF NOT EXISTS {constants.TABLE_NODES} (
                        {constants.COLUMN_NODE_ID} INTEGER PRIMARY KEY AUTOINCREMENT,
                        {constants.COLUMN_NODE_NAME} TEXT NOT NULL,
                        {constants.COLUMN_NODE_PDFS} TEXT DEFAULT '[]',
                        {constants.COLUMN_NODE_ICON} TEXT,
                        {constants.COLUMN_NODE_STYLE_BOLD} INTEGER NOT NULL DEFAULT 0,
                        {constants.COLUMN_NODE_STYLE_COLOR} TEXT DEFAULT '{constants.DEFAULT_TEXT_COLOR}',
                        {constants.COLUMN_NODE_METADATA} TEXT DEFAULT '{{}}',
                        {constants.COLUMN_NODE_CREATED_TIME} TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        {constants.COLUMN_NODE_UPDATED_TIME} TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    );
                """)

                # 2. Create the 'edges' table
                conn.execute(f"""
                    CREATE TABLE IF NOT EXISTS {constants.TABLE_EDGES} (
                        {constants.COLUMN_EDGE_ID} INTEGER PRIMARY KEY AUTOINCREMENT,
                        {constants.COLUMN_EDGE_PARENT_ID} INTEGER NOT NULL,
                        {constants.COLUMN_EDGE_CHILD_ID} INTEGER NOT NULL,
                        {constants.COLUMN_EDGE_SORT_ORDER} INTEGER NOT NULL DEFAULT 0,
                        
                        FOREIGN KEY ({constants.COLUMN_EDGE_PARENT_ID})
                            REFERENCES {constants.TABLE_NODES}({constants.COLUMN_NODE_ID})
                            ON DELETE CASCADE,
                            
                        FOREIGN KEY ({constants.COLUMN_EDGE_CHILD_ID})
                            REFERENCES {constants.TABLE_NODES}({constants.COLUMN_NODE_ID})
                            ON DELETE CASCADE,
                            
                        UNIQUE({constants.COLUMN_EDGE_PARENT_ID}, {constants.COLUMN_EDGE_CHILD_ID})
                    );
                """)

                # 3. Creating indexes to optimise queries
                conn.execute(f"CREATE INDEX IF NOT EXISTS idx_edges_parent ON {constants.TABLE_EDGES}({constants.COLUMN_EDGE_PARENT_ID});")
                conn.execute(f"CREATE INDEX IF NOT EXISTS idx_edges_child ON {constants.TABLE_EDGES}({constants.COLUMN_EDGE_CHILD_ID});")
                conn.execute(f"CREATE INDEX IF NOT EXISTS idx_edges_parent_sort ON {constants.TABLE_EDGES}({constants.COLUMN_EDGE_PARENT_ID}, {constants.COLUMN_EDGE_SORT_ORDER});")

                log_info("Database tables and indexes initialized successfully.")
        except sqlite3.Error as e:
            log_error(f"Failed to initialize database tables: {e}")
            raise
    
    @staticmethod
    def _safe_json_loads(raw: Any, fallback: Any, context: str = "") -> Any:
        """
        Parse a JSON text field from the database.
        Returns fallback on empty or invalid input, and logs a warning.
        """
        if raw is None or raw == "":
            return fallback
        try:
            return json.loads(raw)
        except (TypeError, json.JSONDecodeError) as e:
            log_warning(f"Invalid JSON in DB ({context}): {raw!r} ({e})")
            return fallback
    
    @staticmethod
    def _row_to_node(row: sqlite3.Row) -> Node:
        """
        Internal helper method: Converts a sqlite3.Row into a Node object.
        Centralizes the parsing logic to avoid duplication across CRUD methods.
        """
        return Node(
            id=row[constants.COLUMN_NODE_ID],
            name=row[constants.COLUMN_NODE_NAME],
            pdf_paths=Database._safe_json_loads(row[constants.COLUMN_NODE_PDFS], [], "pdf_paths"),
            icon=row[constants.COLUMN_NODE_ICON],
            style_bold=bool(row[constants.COLUMN_NODE_STYLE_BOLD]),
            style_color=row[constants.COLUMN_NODE_STYLE_COLOR],
            metadata=Database._safe_json_loads(row[constants.COLUMN_NODE_METADATA], {}, "metadata"),
            created_time=row[constants.COLUMN_NODE_CREATED_TIME],
            updated_time=row[constants.COLUMN_NODE_UPDATED_TIME]
        )

    @staticmethod
    def _row_to_edge(row: sqlite3.Row) -> Edge:
        """
        Internal helper method: Converts a sqlite3.Row into an Edge object.
        Centralizes the parsing logic to avoid duplication.
        """
        return Edge(
            id=row[constants.COLUMN_EDGE_ID],
            parent_id=row[constants.COLUMN_EDGE_PARENT_ID],
            child_id=row[constants.COLUMN_EDGE_CHILD_ID],
            sort_order=row[constants.COLUMN_EDGE_SORT_ORDER]
        )
        
    # --------------------------------------------------------------------------
    # Node CRUD
    # --------------------------------------------------------------------------

    def add_node(self, node: Node) -> int:
        sql = f"""
            INSERT INTO {constants.TABLE_NODES} (
                {constants.COLUMN_NODE_NAME}, 
                {constants.COLUMN_NODE_PDFS}, 
                {constants.COLUMN_NODE_ICON}, 
                {constants.COLUMN_NODE_STYLE_BOLD}, 
                {constants.COLUMN_NODE_STYLE_COLOR}, 
                {constants.COLUMN_NODE_METADATA}
            ) VALUES (?, ?, ?, ?, ?, ?)
        """
        try:
            with self.connection() as conn:
                cursor = conn.execute(sql, (
                    node.name,
                    json.dumps(node.pdf_paths),
                    node.icon,
                    1 if node.style_bold else 0,
                    node.style_color,
                    json.dumps(node.metadata)
                ))
                new_id = cursor.lastrowid
                if new_id is None:
                    raise sqlite3.Error("Failed to retrieve new node ID")
                log_debug(f"Added node '{node.name}' with ID: {new_id}")
                return new_id
        except sqlite3.Error as e:
            log_error(f"Error adding node '{node.name}': {e}")
            raise

    def get_node(self, node_id: int) -> Optional[Node]:
        sql = f"SELECT * FROM {constants.TABLE_NODES} WHERE {constants.COLUMN_NODE_ID} = ?"
        try:
            with self.connection() as conn:
                row = conn.execute(sql, (node_id,)).fetchone()
                return self._row_to_node(row) if row else None
        except (sqlite3.Error, json.JSONDecodeError) as e:
            log_error(f"Error retrieving node {node_id}: {e}")
            return None

    def update_node(self, node_id: int, **kwargs: Any) -> None:
        if not kwargs:
            return

        valid_fields = {
            "name": constants.COLUMN_NODE_NAME,
            "pdf_paths": constants.COLUMN_NODE_PDFS,
            "icon": constants.COLUMN_NODE_ICON,
            "style_bold": constants.COLUMN_NODE_STYLE_BOLD,
            "style_color": constants.COLUMN_NODE_STYLE_COLOR,
            "metadata": constants.COLUMN_NODE_METADATA
        }

        set_clauses = []
        values = []

        for key, val in kwargs.items():
            if key in valid_fields:
                db_column = valid_fields[key]
                set_clauses.append(f"{db_column} = ?")
                if key in ("pdf_paths", "metadata"):
                    values.append(json.dumps(val))
                elif key == "style_bold":
                    values.append(1 if val else 0)
                elif key == "style_color":
                    # Keep the database canonical even when a caller bypasses the
                    # controller/dialog validation.
                    values.append(normalize_color(val))
                elif key == "icon":
                    values.append(normalize_icon(val))
                elif key == "name":
                    values.append("" if val is None else str(val).strip())
                else:
                    values.append(val)
            else:
                log_warning(f"Invalid field '{key}' provided for update_node on node {node_id}, ignored.")

        if not set_clauses:
            return

        set_clauses.append(f"{constants.COLUMN_NODE_UPDATED_TIME} = CURRENT_TIMESTAMP")
        sql = f"UPDATE {constants.TABLE_NODES} SET {', '.join(set_clauses)} WHERE {constants.COLUMN_NODE_ID} = ?"
        values.append(node_id)

        try:
            with self.connection() as conn:
                conn.execute(sql, values)
                log_debug(f"Updated node {node_id} with args: {list(kwargs.keys())}")
        except sqlite3.Error as e:
            log_error(f"Error updating node {node_id}: {e}")
            raise

    def delete_node(self, node_id: int) -> None:
        try:
            with self.connection() as conn:
                conn.execute(
                    f"DELETE FROM {constants.TABLE_EDGES} "
                    f"WHERE {constants.COLUMN_EDGE_PARENT_ID} = ? "
                    f"OR {constants.COLUMN_EDGE_CHILD_ID} = ?",
                    (node_id, node_id),
                )
                conn.execute(
                f"DELETE FROM {constants.TABLE_NODES} WHERE {constants.COLUMN_NODE_ID} = ?",
                (node_id,),
                )
                log_info(f"Completely deleted node {node_id} and its associated edges.")
        except sqlite3.Error as e:
            log_error(f"Error deleting node {node_id}: {e}")
            raise


    # --------------------------------------------------------------------------
    # Edge CRUD and Multi-Parent Graph Operations
    # --------------------------------------------------------------------------

    def add_edge(self, parent_id: int, child_id: int, sort_order: int = 0) -> int:
        sql = f"""
            INSERT INTO {constants.TABLE_EDGES} (
                {constants.COLUMN_EDGE_PARENT_ID}, 
                {constants.COLUMN_EDGE_CHILD_ID}, 
                {constants.COLUMN_EDGE_SORT_ORDER}
            ) VALUES (?, ?, ?)
        """
        try:
            with self.connection() as conn:
                cursor = conn.execute(sql, (parent_id, child_id, sort_order))
                new_id = cursor.lastrowid
                if new_id is None:
                    raise sqlite3.Error("Failed to retrieve new edge ID")
                log_debug(f"Edge added: {parent_id} -> {child_id} (order: {sort_order})")
                return new_id
        except sqlite3.IntegrityError as e:
            name = getattr(e, "sqlite_errorname", "") or ""
            if name == "SQLITE_CONSTRAINT_UNIQUE":
                log_error(f"Edge {parent_id} -> {child_id} already exists.")
            elif name == "SQLITE_CONSTRAINT_FOREIGNKEY":
                log_error(f"Edge {parent_id} -> {child_id} references non-existent node.")
            else:
                log_error(f"IntegrityError on edge {parent_id} -> {child_id}: {e}")
            raise
        except sqlite3.Error as e:
            log_error(f"Error adding edge {parent_id} -> {child_id}: {e}")
            raise

    def delete_edge(self, parent_id: int, child_id: int) -> None:
        sql = f"""
            DELETE FROM {constants.TABLE_EDGES} 
            WHERE {constants.COLUMN_EDGE_PARENT_ID} = ? 
            AND {constants.COLUMN_EDGE_CHILD_ID} = ?
        """
        try:
            with self.connection() as conn:
                conn.execute(sql, (parent_id, child_id))
                log_debug(f"Edge deleted: {parent_id} -> {child_id}")
        except sqlite3.Error as e:
            log_error(f"Error deleting edge {parent_id} -> {child_id}: {e}")
            raise

    def move_edge(self, old_parent_id: int, child_id: int, new_parent_id: int, sort_order: int = 0) -> None:
        """
        Move edges atomically within the same database transaction (deleting the old edge and inserting the new one),
        ensuring that the operation either succeeds in its entirety or is rolled back in its entirety, thereby preventing nodes from becoming orphaned.
        """
        try:
            with self.connection() as conn:
                conn.execute(
                    f"DELETE FROM {constants.TABLE_EDGES} "
                    f"WHERE {constants.COLUMN_EDGE_PARENT_ID} = ? "
                    f"AND {constants.COLUMN_EDGE_CHILD_ID} = ?",
                    (old_parent_id, child_id),
                )
                conn.execute(
                    f"INSERT INTO {constants.TABLE_EDGES} "
                    f"({constants.COLUMN_EDGE_PARENT_ID}, {constants.COLUMN_EDGE_CHILD_ID}, "
                    f"{constants.COLUMN_EDGE_SORT_ORDER}) VALUES (?, ?, ?)",
                    (new_parent_id, child_id, sort_order),
                )
                log_debug(f"Atomically moved edge for child {child_id}: {old_parent_id} -> {new_parent_id}")
        except sqlite3.Error as e:
            log_error(f"Failed to atomically move edge for child {child_id} from {old_parent_id} to {new_parent_id}: {e}")
            raise

    def _get_children_with_conn(self, conn: sqlite3.Connection, parent_id: int) -> List[int]:
        """Internal helper method: Reusing existing connections to retrieve child nodes"""
        sql = f"""
            SELECT {constants.COLUMN_EDGE_CHILD_ID} FROM {constants.TABLE_EDGES} 
            WHERE {constants.COLUMN_EDGE_PARENT_ID} = ? 
            ORDER BY {constants.COLUMN_EDGE_SORT_ORDER} ASC, {constants.COLUMN_EDGE_ID} ASC
        """
        rows = conn.execute(sql, (parent_id,)).fetchall()
        return [row[0] for row in rows]

    def get_children(self, parent_id: int) -> List[int]:
        try:
            with self.connection() as conn:
                return self._get_children_with_conn(conn, parent_id)
        except sqlite3.Error as e:
            log_error(f"Error getting children for {parent_id}: {e}")
            return []

    def _get_parents_with_conn(self, conn: sqlite3.Connection, child_id: int) -> List[int]:
        """Internal helper method: Reusing an existing connection to retrieve the parent node"""
        sql = f"""
            SELECT {constants.COLUMN_EDGE_PARENT_ID} FROM {constants.TABLE_EDGES} 
            WHERE {constants.COLUMN_EDGE_CHILD_ID} = ?
            ORDER BY {constants.COLUMN_EDGE_PARENT_ID} ASC
        """
        rows = conn.execute(sql, (child_id,)).fetchall()
        return [row[0] for row in rows]

    def get_parents(self, child_id: int) -> List[int]:
        try:
            with self.connection() as conn:
                return self._get_parents_with_conn(conn, child_id)
        except sqlite3.Error as e:
            log_error(f"Error getting parents for {child_id}: {e}")
            return []

    def get_parent_counts(self) -> Dict[int, int]:
        """
        Return ``{child_id: number_of_parents}`` for every node that has edges.

        One aggregate query instead of one connection per node. The tree model
        caches this map when it builds the projection, so the delegate can draw
        the multi-parent badge without touching SQLite per painted row.
        """
        sql = (
            f"SELECT {constants.COLUMN_EDGE_CHILD_ID}, COUNT(*) "
            f"FROM {constants.TABLE_EDGES} "
            f"GROUP BY {constants.COLUMN_EDGE_CHILD_ID}"
        )
        try:
            with self.connection() as conn:
                rows = conn.execute(sql).fetchall()
                return {int(row[0]): int(row[1]) for row in rows}
        except sqlite3.Error as e:
            log_error(f"Error getting parent counts: {e}")
            return {}

    def get_root_nodes(self) -> List[int]:
        sql = f"""
            SELECT {constants.COLUMN_NODE_ID} 
            FROM {constants.TABLE_NODES} WHERE {constants.COLUMN_NODE_ID} NOT IN (
                SELECT {constants.COLUMN_EDGE_CHILD_ID} FROM {constants.TABLE_EDGES}
            )
            ORDER BY {constants.COLUMN_NODE_ID} ASC
        """
        try:
            with self.connection() as conn:
                rows = conn.execute(sql).fetchall()
                return [row[0] for row in rows]
        except sqlite3.Error as e:
            log_error(f"Error getting root nodes: {e}")
            return []

    # --------------------------------------------------------------------------
    # Graph Algorithms (Cycle Detection and Localisation)
    # --------------------------------------------------------------------------

    def would_create_cycle(self, parent_id: int, child_id: int) -> bool:
        if parent_id == child_id:
            return True
            
        try:
            with self.connection() as conn:
                visited = set()
                queue = deque([child_id])
                
                while queue:
                    current = queue.popleft()
                    if current == parent_id:
                        return True
                    if current not in visited:
                        visited.add(current)
                        queue.extend(self._get_children_with_conn(conn, current))
        except sqlite3.Error as e:
            log_error(f"Error during cycle detection: {e}")
            return True
                
        return False

    def get_all_positions(self, node_id: int) -> List[List[int]]:
        paths = []
        
        try:
            with self.connection() as conn:
                def backtrack(current_id: int, current_path: List[int]) -> None:
                    if current_id in current_path:
                        log_warning(
                            f"Loop detected during path generation: "
                            f"node={node_id} current={current_id} path={current_path}"
                            )
                        return
                    parents = self._get_parents_with_conn(conn, current_id)
                    if not parents:
                        paths.append([current_id] + current_path)
                    else:
                        for p_id in parents:
                            backtrack(p_id, [current_id] + current_path)
                
                backtrack(node_id, [])
        except sqlite3.Error as e:
            log_error(f"Error generating all positions for node {node_id}: {e}")
            
        return paths

    # --------------------------------------------------------------------------
    # Addition
    # --------------------------------------------------------------------------

    def get_all_nodes(self) -> List[Node]:
        """
        Retrieve all nodes from the database, sorted in ascending order by ID.
        This is primarily intended for use by the Exporter or for global data analysis.
        """
        sql = f"SELECT * FROM {constants.TABLE_NODES} ORDER BY {constants.COLUMN_NODE_ID} ASC"
        try:
            with self.connection() as conn:
                rows = conn.execute(sql).fetchall()
                return [self._row_to_node(row) for row in rows]
        except sqlite3.Error as e:
            log_error(f"Error retrieving all nodes: {e}")
            return []

    def get_all_edges(self) -> List[Edge]:
        """
        Retrieve all edges from the database and sort them in ascending order by ID.
        This is primarily intended for use in full graph traversal scenarios, such as the Exporter function.
        """
        sql = f"SELECT * FROM {constants.TABLE_EDGES} ORDER BY {constants.COLUMN_EDGE_ID} ASC"
        try:
            with self.connection() as conn:
                rows = conn.execute(sql).fetchall()
                return [self._row_to_edge(row) for row in rows]
        except sqlite3.Error as e:
            log_error(f"Error retrieving all edges: {e}")
            return []