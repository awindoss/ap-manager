# ==============================================================================
# services/importer.py
# Whole-library JSON import (plan.md §24, §25, §38, stage.md Phase 6).
#
# Import is additive by default ("merge") and can optionally replace the current
# graph ("replace"). Both modes write every node and edge in ONE database
# transaction, so a validation or SQLite failure leaves the existing library
# untouched instead of producing half a library.
#
# External ids (``n1``, ``n2`` ...) are mapped to freshly generated local ids;
# the importer never assumes that the file ids match this machine's database
# (plan.md §25). PDF/icon references are rebased from the JSON file's directory
# onto the application's portable root, and a missing file only produces a
# warning (plan.md §22, §24).
# ==============================================================================
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple, Union

from models.database import Database
from models.library import LibraryService
from models.node import Node, normalize_icon
from services import path_manager
from utils import constants
from utils import icon_utils
from utils import json_utils
from utils.logger import log_info, log_warning, log_debug


@dataclass(frozen=True)
class ImportResult:
    """Summary of one successful import."""

    json_path: Path
    version: str
    mode: str
    node_count: int
    edge_count: int
    id_map: Dict[str, int] = field(default_factory=dict)
    warnings: List[str] = field(default_factory=list)
    missing_pdfs: List[str] = field(default_factory=list)

    @property
    def has_warnings(self) -> bool:
        return bool(self.warnings)


ImportTarget = Union[LibraryService, Database]


def import_library(
    target: ImportTarget,
    json_path: str | Path,
    *,
    mode: str = constants.IMPORT_MODE_MERGE,
    base_root: Optional[Path] = None,
    icons_dir: Optional[Path] = None,
) -> ImportResult:
    """
    Import ``json_path`` into ``target`` (a LibraryService or a Database).

    ``mode`` is ``"merge"`` (append to the existing graph) or ``"replace"``
    (clear the existing graph in the same transaction). Returns an
    :class:`ImportResult` with the external -> local id map and all non-fatal
    warnings (missing PDFs / icons).

    Raises :class:`json_utils.LibraryFormatError` for an invalid document,
    ``FileNotFoundError`` for a missing input file, and ``sqlite3.Error`` for a
    database failure. In every error case the database is left unchanged.
    """
    if mode not in constants.IMPORT_MODES:
        raise ValueError(
            f"未知的导入方式：{mode!r}（可用：{'、'.join(constants.IMPORT_MODES)}）。"
        )

    source_path = Path(json_path).expanduser()
    if not source_path.is_file():
        raise FileNotFoundError(f"图书馆文件不存在：{source_path}")

    document = json_utils.load_library_document(source_path)
    try:
        source_dir = source_path.resolve().parent
    except OSError:
        source_dir = source_path.absolute().parent

    warnings: List[str] = []
    missing_pdfs: List[str] = []
    missing_keys: Set[str] = set()

    nodes: List[Node] = []
    for record in document.nodes:
        pdfs = _import_pdfs(
            record.pdfs,
            source_dir=source_dir,
            base_root=base_root,
            warnings=warnings,
            missing_pdfs=missing_pdfs,
            missing_keys=missing_keys,
        )
        icon = _import_icon(
            record.icon,
            source_dir=source_dir,
            base_root=base_root,
            icons_dir=icons_dir,
            warnings=warnings,
        )
        nodes.append(
            Node(
                name=record.name,
                pdf_paths=pdfs,
                icon=icon,
                style_bold=record.style_bold,
                style_color=record.style_color,
                metadata=dict(record.metadata),
            )
        )

    index_by_external = {
        record.external_id: index for index, record in enumerate(document.nodes)
    }
    edges: List[Tuple[int, int, int]] = []
    for record in document.edges:
        edges.append(
            (
                index_by_external[record.parent],
                index_by_external[record.child],
                record.sort_order,
            )
        )

    database = _database_for(target)
    local_ids = database.insert_graph(
        nodes, edges, replace=(mode == constants.IMPORT_MODE_REPLACE)
    )

    id_map = {
        record.external_id: local_ids[index]
        for index, record in enumerate(document.nodes)
    }
    result = ImportResult(
        json_path=source_path,
        version=document.version,
        mode=mode,
        node_count=len(nodes),
        edge_count=len(edges),
        id_map=id_map,
        warnings=warnings,
        missing_pdfs=missing_pdfs,
    )
    log_info(
        f"Imported library from {source_path} (version {document.version}, "
        f"mode {mode}): {result.node_count} node(s), {result.edge_count} edge(s), "
        f"{len(missing_pdfs)} missing PDF(s), {len(warnings)} warning(s)."
    )
    if warnings:
        log_warning(
            f"Import completed with {len(warnings)} warning(s); "
            "the library itself was imported successfully."
        )
    return result


# ------------------------------------------------------------------------------
# Reference resolution
# ------------------------------------------------------------------------------
def _import_pdfs(
    references: Tuple[str, ...],
    *,
    source_dir: Path,
    base_root: Optional[Path],
    warnings: List[str],
    missing_pdfs: List[str],
    missing_keys: Set[str],
) -> List[str]:
    """Rebase PDF references and keep the first spelling of every file."""
    pdfs: List[str] = []
    seen: Set[str] = set()

    for reference in references:
        stored, absolute, exists = path_manager.resolve_imported_reference(
            reference, source_dir, base_root=base_root
        )
        if not stored:
            continue

        key = path_manager.pdf_path_key(stored)
        if key in seen:
            continue
        seen.add(key)
        pdfs.append(stored)

        if exists:
            continue

        warnings.append(f"PDF 文件缺失：{reference}")
        if key not in missing_keys:
            missing_keys.add(key)
            missing_pdfs.append(stored)

    return pdfs


def _import_icon(
    icon: object,
    *,
    source_dir: Path,
    base_root: Optional[Path],
    icons_dir: Optional[Path],
    warnings: List[str],
) -> str:
    """
    Copy a custom icon from the import directory into the local ``icons/``.

    Only files inside the import directory are accepted: a hand-edited JSON
    must not be able to copy an arbitrary file from the machine into the
    library. Missing or invalid icons are dropped with a warning; the node
    itself is still imported.
    """
    text = normalize_icon(icon)
    if not text:
        return ""
    if not icon_utils.is_custom_icon(text):
        return text

    candidate = Path(text).expanduser()
    if not candidate.is_absolute():
        candidate = source_dir / candidate

    try:
        resolved = Path(os.path.abspath(candidate))
    except (OSError, ValueError):
        warnings.append(f"图标路径无效，已忽略：{text}")
        return ""

    if not path_manager.is_within_root(resolved, source_dir):
        warnings.append(f"图标不在导入目录内，已忽略：{text}")
        return ""
    if not resolved.is_file():
        warnings.append(f"图标文件缺失，已忽略：{text}")
        return ""

    # A round trip (export -> import) commonly points the icon at the target's
    # own ``icons/`` folder. Reuse it as-is: running the content-addressed
    # import again would append a second hash to the file name and make the
    # exported document change on every cycle.
    root = Path(base_root) if base_root is not None else Path(constants.BASE_ROOT)
    icons_root = (
        Path(icons_dir) if icons_dir is not None else Path(constants.ICONS_PATH)
    )
    if path_manager.is_within_root(resolved, icons_root):
        relative = path_manager.relative_to_root(resolved, root)
        if relative is not None:
            log_debug(f"Reusing existing local icon {relative!r} for {text!r}.")
            return path_manager.normalize_stored_path(relative)
        return f"{constants.ICONS_DIR_NAME}/{resolved.name}"

    try:
        stored = icon_utils.import_custom_icon(
            resolved, base_root=base_root, icons_dir=icons_dir
        )
    except (OSError, ValueError) as error:
        log_warning(f"Could not import icon {resolved}: {error}")
        warnings.append(f"无法导入图标「{text}」：{error}")
        return ""

    log_debug(f"Imported icon reference {text!r} as {stored!r}.")
    return stored


def _database_for(target: ImportTarget) -> Database:
    """Accept either the business service or the data layer (stage.md 6.2)."""
    database: Any = getattr(target, "db", target)
    if not isinstance(database, Database):
        raise TypeError("import_library() 需要 LibraryService 或 Database 实例。")
    return database


# ==============================================================================
# End of importer.py
# ==============================================================================
