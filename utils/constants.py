# ==============================================================================
# utils/constants.py
# Definition of global constants
# ==============================================================================
"""
Written in accordance with the plans set out in plan.md and stage.md.
Attention: This software operates in portable mode; it is recommended that you place it in a writable directory.
"""
import sys
from pathlib import Path
from typing import Final
import logging

# --------------------------------------------------------------------------
# 1.Application Info
# --------------------------------------------------------------------------
APP_NAME: Final[str] = "AP Library Manager"
APP_VERSION: Final[str] = "0.1"
APP_AUTHOR: Final[str] = "Developer"
APP_DESCRIPTION: Final[str] = "Local PDF Book Collection and Categorisation Manager (Multi-level Hierarchical Structure)"

# --------------------------------------------------------------------------
# 2.Path Constants
# --------------------------------------------------------------------------
"""
Path definition notes:
- By default, these are based on the application installation directory or the current runtime directory.
- DB_PATH points to the relative path of the SQLite database.
- CONFIG_PATH points to the relative path of the JSON configuration file.
- BOOKS_PATH is an optional logical directory for centrally storing PDF files (not mandatory).
Also:
DEFAULT_DB_PATH_RELATIVE is the default configuration value; DB_PATH is the resolved default absolute path;
If library.database_path has a value in config.json, the configuration value should take precedence;
The Database class should ideally accept str | Path
"""

def _get_user_data_root() -> Path:
    """Returns the root directory of writable user data. During development, this is the project root; during packaging, it is the directory adjacent to the executable file."""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent.parent

# Default path (development environment)
BASE_ROOT: Final[Path] = _get_user_data_root()

DATA_DIR_NAME: Final[str] = "data"
CONFIG_FILE_NAME: Final[str] = "config.json"
DB_FILE_NAME: Final[str] = "library.db"
LOGS_DIR_NAME: Final[str] = "logs"
ICONS_DIR_NAME: Final[str] = "icons"
BOOKS_DIR_NAME: Final[str] = "books"

# Creating a path object
DATA_PATH: Final[Path] = BASE_ROOT / DATA_DIR_NAME
CONFIG_PATH: Final[Path] = BASE_ROOT / CONFIG_FILE_NAME
DB_PATH: Final[Path] = DATA_PATH / DB_FILE_NAME
LOGS_PATH: Final[Path] = BASE_ROOT / LOGS_DIR_NAME
ICONS_PATH: Final[Path] = BASE_ROOT / ICONS_DIR_NAME
BOOKS_PATH: Final[Path] = BASE_ROOT / BOOKS_DIR_NAME

# The name of the temporary root directory used during export/import
EXPORT_DIR_PREFIX: Final[str] = "my_library_"


# --------------------------------------------------------------------------
# 3.Config Keys
# --------------------------------------------------------------------------
"""
To avoid errors caused by hard-coded strings, all top-level keys in config.json should be defined here.
According to plan.md"""

# Database-related
SECTION_LIBRARY: Final[str] = "library"
KEY_DB_PATH: Final[str] = "database_path"
DEFAULT_DB_PATH_RELATIVE: Final[str] = DATA_DIR_NAME + "/" + DB_FILE_NAME

# Reader Settings
SECTION_PDF_READER: Final[str] = "pdf_reader"
KEY_PDF_READER_PATH: Final[str] = "path"  # optional
KEY_PDF_READER_ARGS: Final[str] = "args"  # optional

# UI Settings
SECTION_UI: Final[str] = "ui"
KEY_WINDOW_WIDTH: Final[str] = "window_width"
KEY_WINDOW_HEIGHT: Final[str] = "window_height"
KEY_WINDOW_X: Final[str] = "window_x"       # null indicates centre alignment
KEY_WINDOW_Y: Final[str] = "window_y"
KEY_WINDOW_MAXIMIZED: Final[str] = "window_maximized"
# Expanded branches are stored as display paths (lists of node ids), not as a
# flat node-id set: the same node can be expanded under one parent and collapsed
# under another (multi-parent projection, plan.md §10).
KEY_EXPANDED_PATHS: Final[str] = "expanded_paths"
KEY_SEARCH_PANEL_VISIBLE: Final[str] = "search_panel_visible"
DEFAULT_WINDOW_WIDTH: Final[int] = 1200
DEFAULT_WINDOW_HEIGHT: Final[int] = 800
DEFAULT_WINDOW_MAXIMIZED: Final[bool] = False
MIN_WINDOW_WIDTH: Final[int] = 640
MIN_WINDOW_HEIGHT: Final[int] = 480
MAX_WINDOW_WIDTH: Final[int] = 10_000
MAX_WINDOW_HEIGHT: Final[int] = 10_000
# Guard against a config file growing without bound as the tree is expanded.
MAX_SAVED_EXPANDED_PATHS: Final[int] = 500

# Logging settings
SECTION_LOGGING: Final[str] = "logging"
KEY_LOG_LEVEL: Final[str] = "level"
DEFAULT_LOG_LEVEL_NAME: Final[str] = "INFO"
LOG_FILE_MAX_BYTES: Final[int] = 2 * 1024 * 1024
LOG_FILE_BACKUP_COUNT: Final[int] = 3

# --------------------------------------------------------------------------
# 4.Database Schema Constants
# --------------------------------------------------------------------------
"""
According to plan.md
Note: The actual table name may contain _id, but care must be taken with ID mapping when exchanging data in JSON."""

TABLE_NODES: Final[str] = "nodes"
TABLE_EDGES: Final[str] = "edges"

COLUMN_NODE_ID: Final[str] = "id"
COLUMN_NODE_NAME: Final[str] = "name"
COLUMN_NODE_PDFS: Final[str] = "pdf_paths"  # JSON arrays storage
COLUMN_NODE_ICON: Final[str] = "icon"
COLUMN_NODE_STYLE_BOLD: Final[str] = "style_bold"
COLUMN_NODE_STYLE_COLOR: Final[str] = "style_color"
COLUMN_NODE_METADATA: Final[str] = "metadata"
COLUMN_NODE_CREATED_TIME: Final[str] = "created_time"
COLUMN_NODE_UPDATED_TIME: Final[str] = "updated_time"

COLUMN_EDGE_ID: Final[str] = "id"
COLUMN_EDGE_PARENT_ID: Final[str] = "parent_id"
COLUMN_EDGE_CHILD_ID: Final[str] = "child_id"
COLUMN_EDGE_SORT_ORDER: Final[str] = "sort_order"


# --------------------------------------------------------------------------
# 5.Version & Format Constants
# --------------------------------------------------------------------------
"""
According to plan.md
Ensure that JSON structure compatibility can be checked during import and export."""

LIBRARY_FORMAT_VERSION: Final[str] = "0.1"
JSON_FORMAT_KEY: Final[str] = "format"
VERSION_KEY: Final[str] = "version"
LIBRARY_FORMAT_NAME: Final[str] = "ap_manager_library"
# Versions the importer understands. A newer file must be rejected instead of
# being imported with silently missing fields (plan.md §41).
SUPPORTED_LIBRARY_VERSIONS: Final[tuple[str, ...]] = (LIBRARY_FORMAT_VERSION,)


# --------------------------------------------------------------------------
# 6.UI Style Defaults
# --------------------------------------------------------------------------

DEFAULT_ICON_EMOJIS: Final[tuple[str, ...]] = (
    "📚", "📖", "📜", "🏛️", "👤", "🔬", "⭐", "📌"
)
DEFAULT_ICON_CUSTOM_EXTENSION: Final[str] = ".png"
VALID_ICON_EXTENSIONS: Final[tuple[str, ...]] = (".png", ".ico", ".svg")
DEFAULT_TEXT_COLOR: Final[str] = "#000000"
DEFAULT_BOLD: Final[bool] = False

# Tree rendering
TREE_ICON_SIZE: Final[int] = 16
MAX_NODE_NAME_LENGTH: Final[int] = 200


# --------------------------------------------------------------------------
# 7.PDF & File Handling
# --------------------------------------------------------------------------

PDF_EXTENSION: Final[str] = ".pdf"
FDF_EXTENSION: Final[str] = ".fdf" # reserve FDF annotation extensions
VALID_PDF_EXTENSIONS: Final[tuple[str, ...]] = (".pdf",)
VALID_ANNOTATION_EXTENSIONS: Final[tuple[str, ...]] = (".fdf",)
WARNING_ICON_MISSING_FILE: Final[str] = "⚠️"

# File dialog filters (UI strings, kept here so phase 6 import/export can reuse them).
PDF_FILE_FILTER: Final[str] = "PDF 文件 (*.pdf)"
LIBRARY_JSON_FILE_NAME: Final[str] = "library.json"
LIBRARY_FILE_FILTER: Final[str] = "图书馆文件 (*.json);;所有文件 (*)"
MAX_PDF_PATH_LENGTH: Final[int] = 4096
# Streamed hashing/copying of PDF files: books can be large, so never read a
# whole PDF into memory just to compare or duplicate it.
PDF_COPY_CHUNK_SIZE: Final[int] = 1024 * 1024
# Suffix used when a copied PDF's name is already taken by a different file.
PDF_COPY_NAME_SUFFIX_FORMAT: Final[str] = "{stem}_{digest}{suffix}"


# --------------------------------------------------------------------------
# 8.Business Logic Constants
# --------------------------------------------------------------------------
"""
A threshold or pattern used to control certain specific behaviours."""

DEFAULT_SORT_ORDER_INCREMENT: Final[int] = 1

# Import behaviour (Phase 6). "merge" keeps the existing library and appends the
# imported graph; "replace" clears the existing graph in the same transaction.
IMPORT_MODE_MERGE: Final[str] = "merge"
IMPORT_MODE_REPLACE: Final[str] = "replace"
IMPORT_MODES: Final[tuple[str, ...]] = (IMPORT_MODE_MERGE, IMPORT_MODE_REPLACE)

# Library exchange format keys (plan.md §23.2). Keeping them in one place makes
# the exporter and the validator impossible to drift apart.
JSON_NODES_KEY: Final[str] = "nodes"
JSON_EDGES_KEY: Final[str] = "edges"
JSON_NODE_ID_KEY: Final[str] = "id"
JSON_NODE_NAME_KEY: Final[str] = "name"
JSON_NODE_PDFS_KEY: Final[str] = "pdfs"
JSON_NODE_ICON_KEY: Final[str] = "icon"
JSON_NODE_STYLE_KEY: Final[str] = "style"
JSON_STYLE_BOLD_KEY: Final[str] = "bold"
JSON_STYLE_COLOR_KEY: Final[str] = "color"
JSON_NODE_METADATA_KEY: Final[str] = "metadata"
JSON_EDGE_PARENT_KEY: Final[str] = "parent"
JSON_EDGE_CHILD_KEY: Final[str] = "child"
JSON_EDGE_SORT_ORDER_KEY: Final[str] = "sort_order"

# Custom drag-and-drop payload used by LibraryTreeView (Phase 5). The payload is
# JSON: {"paths": [[root_id, ..., node_id], ...]} so a drag keeps the exact
# display instance (important for "move from this parent").
NODE_DRAG_MIME_TYPE: Final[str] = "application/x-ap-manager-node-paths"
DRAG_HIGHLIGHT_ALPHA: Final[int] = 70
DRAG_REORDER_LINE_HEIGHT: Final[int] = 3

# Tree projection guards (Phase 2).
# The graph is projected onto a tree; a corrupted dataset could otherwise make
# the projection grow without bound (a cycle, or a diamond-shaped DAG whose
# display instances multiply exponentially). Both limits abort the build
# gracefully and are reported by the model instead of freezing the GUI.
TREE_MAX_DEPTH: Final[int] = 64
TREE_MAX_ITEMS: Final[int] = 200_000


# --------------------------------------------------------------------------
# 8b.Search & relocation (Phase 7)
# --------------------------------------------------------------------------
# Search is synchronous (SQLite over a local file); a short debounce keeps the
# view responsive while typing without adding an async worker.
SEARCH_DEBOUNCE_MS: Final[int] = 250
SEARCH_DEFAULT_LIMIT: Final[int] = 100
SEARCH_MAX_LIMIT: Final[int] = 500
SEARCH_MAX_QUERY_LENGTH: Final[int] = 200
# Match sources reported by the search service. Kept as strings so the result
# objects stay serialisable and easy to display in the UI.
SEARCH_MATCH_NAME: Final[str] = "name"
SEARCH_MATCH_PDF: Final[str] = "pdf"
SEARCH_MATCH_LABELS: Final[dict[str, str]] = {
    SEARCH_MATCH_NAME: "名称",
    SEARCH_MATCH_PDF: "PDF",
}
# A node inside a cycle may have no root path at all; the result still exists
# but has zero locations (plan.md §28).
SEARCH_NO_LOCATION_TEXT: Final[str] = "（没有可达位置）"

# Batch relocation (plan.md §22 / stage.md 7.2 "批量重新定位").
RELINK_STATUS_MATCHED: Final[str] = "matched"
RELINK_STATUS_AMBIGUOUS: Final[str] = "ambiguous"
RELINK_STATUS_NOT_FOUND: Final[str] = "not_found"
RELINK_STATUS_LABELS: Final[dict[str, str]] = {
    RELINK_STATUS_MATCHED: "已匹配",
    RELINK_STATUS_AMBIGUOUS: "同名文件有多个",
    RELINK_STATUS_NOT_FOUND: "未找到",
}


# --------------------------------------------------------------------------
# 9.Logging Config
# --------------------------------------------------------------------------

LOG_LEVEL_INFO: Final[int] = logging.INFO
LOG_LEVEL_DEBUG: Final[int] = logging.DEBUG
LOG_FILE_NAME: Final[str] = f"{APP_NAME.replace(' ', '_')}_log.txt"


# ==============================================================================
# End of constants.py
# ==============================================================================
