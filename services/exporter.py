# ==============================================================================
# services/exporter.py
# Whole-library JSON export (plan.md §23, stage.md Phase 6).
#
# The exporter writes a flat ``nodes`` + ``edges`` document, never a nested
# ``children`` tree: only the flat form can represent multi-parent relations
# losslessly (plan.md §23.2). PDF references are rewritten relative to the
# export directory; custom icons are copied into ``<export_dir>/icons/`` so the
# exported folder does not depend on the application's own ``icons/`` folder.
#
# Optionally (``copy_pdfs=True``) the PDF files themselves are copied into
# ``<export_dir>/books/``, which makes the exported folder self-contained and
# shippable to another computer.
# ==============================================================================
import json
import os
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Set

from models.library import LibraryService
from models.node import Node, normalize_icon
from services import path_manager
from utils import constants
from utils import icon_utils
from utils.logger import log_debug, log_error, log_info, log_warning


@dataclass(frozen=True)
class ExportResult:
    """Summary of one successful export."""

    export_dir: Path
    json_path: Path
    node_count: int
    edge_count: int
    pdf_copies: int = 0
    icon_copies: int = 0
    warnings: List[str] = field(default_factory=list)

    @property
    def has_warnings(self) -> bool:
        return bool(self.warnings)


def export_library(
    library: LibraryService,
    export_dir: str | Path,
    *,
    copy_pdfs: bool = False,
    overwrite: bool = True,
    base_root: Optional[Path] = None,
    icons_dir: Optional[Path] = None,
) -> ExportResult:
    """
    Export the whole library into ``export_dir`` as ``library.json``.

    Parameters
    ----------
    library:
        Business-layer service that owns the database.
    export_dir:
        Target directory. It is created when missing.
    copy_pdfs:
        Copy every existing PDF into ``<export_dir>/books/`` and reference it as
        ``./books/<name>``. When False only the (relative) path reference is
        exported.
    overwrite:
        Replace an existing ``library.json``. When False a ``FileExistsError``
        is raised so the caller can ask the user first.
    base_root / icons_dir:
        Overrides for tests and for callers with a non-default portable root.

    Raises ``OSError`` for filesystem failures and ``ValueError`` for an
    inconsistent database (for example an edge whose endpoint disappeared).
    """
    directory = Path(export_dir).expanduser()
    if directory.exists() and not directory.is_dir():
        raise NotADirectoryError(f"导出目标不是文件夹：{directory}")
    directory.mkdir(parents=True, exist_ok=True)
    export_root = Path(os.path.abspath(directory))

    json_path = directory / constants.LIBRARY_JSON_FILE_NAME
    if json_path.exists() and not overwrite:
        raise FileExistsError(
            f"导出目录中已经存在 {constants.LIBRARY_JSON_FILE_NAME}：{json_path}"
        )

    nodes = library.get_all_nodes()
    edges = library.get_all_edges()

    warnings: List[str] = []
    external_by_id = _build_external_ids(nodes)

    pdf_reference_cache: Dict[str, str] = {}
    copied_pdfs: Set[str] = set()
    exported_icons: Set[str] = set()
    icon_reference_cache: Dict[str, str] = {}

    exported_nodes: List[dict] = []
    for node in nodes:
        assert node.id is not None
        pdfs: List[str] = []
        seen_pdf_keys: Set[str] = set()
        for stored_path in node.pdf_paths:
            reference = _export_pdf_reference(
                stored_path,
                export_root=export_root,
                copy_pdfs=copy_pdfs,
                base_root=base_root,
                warnings=warnings,
                reference_cache=pdf_reference_cache,
                copied_pdfs=copied_pdfs,
            )
            if not reference:
                continue
            key = path_manager.pdf_path_key(reference)
            if key in seen_pdf_keys:
                continue
            seen_pdf_keys.add(key)
            pdfs.append(reference)

        icon = _export_icon_reference(
            node.icon,
            export_root=export_root,
            base_root=base_root,
            icons_dir=icons_dir,
            warnings=warnings,
            reference_cache=icon_reference_cache,
            exported_icons=exported_icons,
        )

        exported_nodes.append(
            {
                constants.JSON_NODE_ID_KEY: external_by_id[node.id],
                constants.JSON_NODE_NAME_KEY: node.name,
                constants.JSON_NODE_PDFS_KEY: pdfs,
                constants.JSON_NODE_ICON_KEY: icon,
                constants.JSON_NODE_STYLE_KEY: {
                    constants.JSON_STYLE_BOLD_KEY: bool(node.style_bold),
                    constants.JSON_STYLE_COLOR_KEY: node.style_color,
                },
                constants.JSON_NODE_METADATA_KEY: dict(node.metadata or {}),
            }
        )

    exported_edges: List[dict] = []
    for edge in edges:
        if edge.parent_id not in external_by_id or edge.child_id not in external_by_id:
            raise ValueError(
                f"数据库中的关系 {edge.parent_id} -> {edge.child_id} "
                "引用了不存在的节点，无法导出。"
            )
        exported_edges.append(
            {
                constants.JSON_EDGE_PARENT_KEY: external_by_id[edge.parent_id],
                constants.JSON_EDGE_CHILD_KEY: external_by_id[edge.child_id],
                constants.JSON_EDGE_SORT_ORDER_KEY: int(edge.sort_order),
            }
        )

    document = {
        constants.JSON_FORMAT_KEY: constants.LIBRARY_FORMAT_NAME,
        constants.VERSION_KEY: constants.LIBRARY_FORMAT_VERSION,
        constants.JSON_NODES_KEY: exported_nodes,
        constants.JSON_EDGES_KEY: exported_edges,
    }
    _write_document(json_path, document)

    result = ExportResult(
        export_dir=directory,
        json_path=json_path,
        node_count=len(exported_nodes),
        edge_count=len(exported_edges),
        pdf_copies=len(copied_pdfs),
        icon_copies=len(exported_icons),
        warnings=warnings,
    )
    log_info(
        f"Exported library to {json_path}: {result.node_count} node(s), "
        f"{result.edge_count} edge(s), {result.pdf_copies} PDF(s), "
        f"{result.icon_copies} icon(s), {len(warnings)} warning(s)."
    )
    return result


# ------------------------------------------------------------------------------
# Internals
# ------------------------------------------------------------------------------
def _build_external_ids(nodes: List[Node]) -> Dict[int, str]:
    """Map local node ids to stable, database-independent ``n1``-style ids."""
    external: Dict[int, str] = {}
    for index, node in enumerate(nodes, start=1):
        if node.id is None:
            raise ValueError("数据库中有一个节点没有 ID，无法导出。")
        if node.id in external:
            raise ValueError(f"数据库中节点 ID 重复：{node.id}")
        external[node.id] = f"n{index}"
    return external


def _export_pdf_reference(
    stored_path: object,
    *,
    export_root: Path,
    copy_pdfs: bool,
    base_root: Optional[Path],
    warnings: List[str],
    reference_cache: Dict[str, str],
    copied_pdfs: Set[str],
) -> str:
    """Return the ``pdfs`` entry for one stored reference (or ``""``)."""
    reference, absolute, exists = path_manager.make_export_reference(
        stored_path, export_root, base_root=base_root
    )
    if not reference:
        return ""

    if not exists:
        warnings.append(f"PDF 文件缺失，仅导出路径引用：{stored_path}")
        return reference

    if not copy_pdfs or absolute is None:
        return reference

    try:
        source_key = os.path.normcase(str(absolute.resolve()))
    except OSError:
        source_key = os.path.normcase(str(absolute))
    cached = reference_cache.get(source_key)
    if cached is not None:
        return cached

    try:
        destination = path_manager.copy_into_books(
            absolute, export_root / constants.BOOKS_DIR_NAME
        )
    except OSError as error:
        log_warning(f"Could not copy PDF {stored_path!r} into the export: {error}")
        warnings.append(f"无法复制 PDF「{stored_path}」：{error}")
        return reference

    try:
        relative = destination.resolve().relative_to(export_root.resolve()).as_posix()
        reference = "./" + relative
    except (OSError, ValueError):
        # Should not happen because copy_into_books always targets export_root/books.
        reference = destination.as_posix()

    reference_cache[source_key] = reference
    copied_pdfs.add(source_key)
    return reference


def _export_icon_reference(
    icon: object,
    *,
    export_root: Path,
    base_root: Optional[Path],
    icons_dir: Optional[Path],
    warnings: List[str],
    reference_cache: Dict[str, str],
    exported_icons: Set[str],
) -> str:
    """Copy one custom icon into the export and return its portable reference."""
    text = normalize_icon(icon)
    if not text:
        return ""
    if not icon_utils.is_custom_icon(text):
        # Built-in emoji / plain text icon: nothing to copy.
        return text

    source = icon_utils.get_icon_path(
        text, base_root=base_root, icons_dir=icons_dir
    )
    if source is None:
        warnings.append(f"自定义图标文件缺失，仅保留原值：{text}")
        return text

    try:
        cache_key = str(source.resolve())
    except OSError:
        cache_key = str(source)
    cached = reference_cache.get(cache_key)
    if cached is not None:
        return cached

    icons_root = export_root / constants.ICONS_DIR_NAME
    icons_root.mkdir(parents=True, exist_ok=True)
    destination = icons_root / source.name
    if not destination.exists():
        try:
            shutil.copy2(source, destination)
        except OSError as error:
            log_warning(f"Could not copy icon {source} into the export: {error}")
            warnings.append(f"无法复制图标文件「{text}」：{error}")
            return text
        exported_icons.add(destination.name)

    reference = f"{constants.ICONS_DIR_NAME}/{source.name}"
    reference_cache[cache_key] = reference
    return reference


def _write_document(json_path: Path, document: dict) -> None:
    """Write the JSON atomically so a failed export never truncates the old file."""
    text = json.dumps(document, ensure_ascii=False, indent=2) + "\n"
    temporary = json_path.with_name(json_path.name + ".tmp")
    try:
        temporary.write_text(text, encoding="utf-8")
        os.replace(temporary, json_path)
    except OSError as error:
        log_error(f"Could not write export file {json_path}: {error}")
        try:
            temporary.unlink(missing_ok=True)
        except OSError:
            pass
        raise
    log_debug(f"Wrote {len(text)} characters to {json_path}.")


# ==============================================================================
# End of exporter.py
# ==============================================================================
