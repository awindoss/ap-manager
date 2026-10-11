def get_all_nodes(self) -> List[Node]:
        """
        Retrieve all nodes from the database, sorted in ascending order by ID.
        This is primarily intended for use by the Exporter or for global data analysis.
        """
        sql = f"SELECT * FROM {constants.TABLE_NODES} ORDER BY {constants.COLUMN_NODE_ID} ASC"
        nodes = []
        try:
            with self.connection() as conn:
                rows = conn.execute(sql).fetchall()
                for row in rows:
                    nodes.append(Node(
                        id=row[constants.COLUMN_NODE_ID],
                        name=row[constants.COLUMN_NODE_NAME],
                        pdf_paths=json.loads(row[constants.COLUMN_NODE_PDFS]),
                        icon=row[constants.COLUMN_NODE_ICON],
                        style_bold=bool(row[constants.COLUMN_NODE_STYLE_BOLD]),
                        style_color=row[constants.COLUMN_NODE_STYLE_COLOR],
                        metadata=json.loads(row[constants.COLUMN_NODE_METADATA]),
                        created_time=row[constants.COLUMN_NODE_CREATED_TIME],
                        updated_time=row[constants.COLUMN_NODE_UPDATED_TIME]
                    ))
            return nodes
        except sqlite3.Error as e:
            log_error(f"Error retrieving all nodes: {e}")
            return []

    def get_all_edges(self) -> List[Edge]:
        """
        Retrieve all edges from the database and sort them in ascending order by ID.
        This is primarily intended for use in full graph traversal scenarios, such as the Exporter function.
        """
        sql = f"SELECT * FROM {constants.TABLE_EDGES} ORDER BY {constants.COLUMN_EDGE_ID} ASC"
        edges = []
        try:
            with self.connection() as conn:
                rows = conn.execute(sql).fetchall()
                for row in rows:
                    edges.append(Edge(
                        id=row[constants.COLUMN_EDGE_ID],
                        parent_id=row[constants.COLUMN_EDGE_PARENT_ID],
                        child_id=row[constants.COLUMN_EDGE_CHILD_ID],
                        sort_order=row[constants.COLUMN_EDGE_SORT_ORDER]
                    ))
            return edges
        except sqlite3.Error as e:
            log_error(f"Error retrieving all edges: {e}")
            return []