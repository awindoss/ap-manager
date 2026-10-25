# ==============================================================================
# models/node.py
# Node data model + node-level value normalisation
# ==============================================================================
import re
from dataclasses import dataclass, field
from typing import Any, Optional, List

from utils.constants import DEFAULT_BOLD, DEFAULT_TEXT_COLOR
from utils.logger import log_warning

# Only hex colours are stored. Accepting the short form keeps hand-written data
# (and the old schema default) usable while writes always normalise to #rrggbb.
_HEX_COLOR_PATTERN = re.compile(r"^#(?:[0-9a-fA-F]{3}|[0-9a-fA-F]{6})$")


def normalize_icon(value: Any) -> str:
    """Normalise a node icon: ``None`` becomes an empty string, values are stripped."""
    if value is None:
        return ""
    return str(value).strip()


def normalize_color(value: Any) -> str:
    """
    Normalise a text colour to ``#rrggbb``.

    ``None`` / empty / invalid values fall back to the schema default. A warning
    is logged for non-empty invalid values so a broken config does not fail
    silently, but node creation must never raise because of a bad colour.
    """
    if value is None:
        return DEFAULT_TEXT_COLOR
    if not isinstance(value, str):
        log_warning(f"Invalid node colour {value!r}; falling back to {DEFAULT_TEXT_COLOR}.")
        return DEFAULT_TEXT_COLOR

    raw = value.strip()
    if not raw:
        return DEFAULT_TEXT_COLOR
    if not _HEX_COLOR_PATTERN.fullmatch(raw):
        log_warning(f"Invalid node colour {value!r}; falling back to {DEFAULT_TEXT_COLOR}.")
        return DEFAULT_TEXT_COLOR

    if len(raw) == 4:  # #abc -> #aabbcc
        raw = "#" + "".join(char * 2 for char in raw[1:])
    return raw.lower()


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

    # Default: False
    style_bold: bool = DEFAULT_BOLD

    # Default: "#000000"
    style_color: str = DEFAULT_TEXT_COLOR

    metadata: dict = field(default_factory=dict)

    created_time: Optional[str] = None

    updated_time: Optional[str] = None

    def __post_init__(self) -> None:
        """
        Enforce the node invariants in one place.

        The SQLite schema allows NULL for ``icon`` / ``style_color``, and callers
        may hand in ``None``; normalising here means the view layer never has to
        guard against ``QIcon(None)`` / ``QColor(None)``.
        """
        self.name = "" if self.name is None else str(self.name).strip()
        self.pdf_paths = [str(path) for path in (self.pdf_paths or [])]
        self.icon = normalize_icon(self.icon)
        self.style_bold = bool(self.style_bold)
        self.style_color = normalize_color(self.style_color)
        self.metadata = self.metadata if isinstance(self.metadata, dict) else {}


# ==============================================================================
# End of node.py
# ==============================================================================
