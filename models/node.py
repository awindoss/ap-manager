# ==============================================================================
# models/node.py
# Node Data Model
# ==============================================================================

from dataclasses import dataclass, field
from typing import Optional, List
from utils.constants import DEFAULT_TEXT_COLOR, DEFAULT_BOLD

@dataclass
class Node:
    """
    A core node data class, used to encapsulate the node's own properties and map to the 'nodes' table in the database.
    """
    # NOTE: 'name' is the only required field, so it must be declared before any
    # field carrying a default value. 'id' is optional and therefore declared last;
    # this keeps `Node("Some Book")` valid while still allowing positional-free use.
    name: str

    id: Optional[int] = None

    pdf_paths: List[str] = field(default_factory=list)
    
    icon: str = ""
    
    #Default: False
    style_bold: bool = DEFAULT_BOLD
    
    #Default: "#000000"
    style_color: str = DEFAULT_TEXT_COLOR
    
    metadata: dict = field(default_factory=dict)
    
    created_time: Optional[str] = None
    
    updated_time: Optional[str] = None