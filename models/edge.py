# ==============================================================================
# models/edge.py
# Definition of the Edge data model
# ==============================================================================
from dataclasses import dataclass
from typing import Optional

@dataclass
class Edge:
    """
    Edge data model.
    Used to record multi-parent directed graph relationships between nodes.
    """
    # NOTE: required fields must precede defaulted ones, so 'id' is declared after
    # 'parent_id' / 'child_id' rather than first (see models/node.py for the same fix).
    parent_id: int

    child_id: int

    id: Optional[int] = None

    sort_order: int = 0