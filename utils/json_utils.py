# ==============================================================================
# utils/json_utils.py
# Reading and validating the library exchange format (plan.md §23.2, §24, §41).
#
# The importer must never leave half a library behind, so every structural
# problem is detected here before the database is touched. Errors are raised as
# LibraryFormatError (a ValueError subclass) with a user-readable message, and
# the importer/UI only need to display it.
# ==============================================================================
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Sequence, Tuple

from utils import constants
from utils.logger import log_debug


class LibraryFormatError(ValueError):
    """The selected file is not a valid AP Library Manager library document."""


class LibraryVersionError(LibraryFormatError):
    """The document uses a format version this build cannot import."""


@dataclass(frozen=True)
class LibraryNodeRecord:
    """One validated node entry of an exchange document."""

    external_id: str
    name: str
    pdfs: Tuple[str, ...]
    icon: str
    style_bold: bool
    style_color: str
    metadata: Dict[str, Any]


@dataclass(frozen=True)
class LibraryEdgeRecord:
    """One validated edge entry of an exchange document."""

    parent: str
    child: str
    sort_order: int


@dataclass(frozen=True)
class LibraryDocument:
    """A fully validated library document, ready to be imported."""

    version: str
    nodes: Tuple[LibraryNodeRecord, ...]
    edges: Tuple[LibraryEdgeRecord, ...]


# ------------------------------------------------------------------------------
# Public API
# ------------------------------------------------------------------------------
def validate_json_schema(data: Any) -> None:
    """
    Validate an already-decoded library document.

    Raises :class:`LibraryFormatError` / :class:`LibraryVersionError` with a
    message intended for the user. Extra unknown keys are ignored so a future
    exporter can add fields without breaking older importers.
    """
    _parse_document(data)


def parse_library_document(data: Any) -> LibraryDocument:
    """Validate ``data`` and return it as typed records."""
    return _parse_document(data)


def load_library_document(path: str | Path) -> LibraryDocument:
    """
    Read and validate a ``library.json`` file.

    ``utf-8-sig`` accepts files written by Windows editors that add a BOM,
    which would otherwise make ``json.loads`` fail on the first character.
    """
    file_path = Path(path)
    try:
        raw_text = file_path.read_text(encoding="utf-8-sig")
    except OSError as error:
        raise LibraryFormatError(f"无法读取文件：{file_path}\n{error}") from error

    try:
        data = json.loads(raw_text)
    except json.JSONDecodeError as error:
        raise LibraryFormatError(
            f"JSON 格式错误（第 {error.lineno} 行第 {error.colno} 列）：{error.msg}"
        ) from error

    document = _parse_document(data)
    log_debug(
        f"Validated library document {file_path}: version {document.version}, "
        f"{len(document.nodes)} node(s), {len(document.edges)} edge(s)."
    )
    return document


# ------------------------------------------------------------------------------
# Parsing / validation internals
# ------------------------------------------------------------------------------
def _parse_document(data: Any) -> LibraryDocument:
    if not isinstance(data, dict):
        raise LibraryFormatError("图书馆文件的顶层必须是一个 JSON 对象。")

    format_name = data.get(constants.JSON_FORMAT_KEY)
    if format_name != constants.LIBRARY_FORMAT_NAME:
        raise LibraryFormatError(
            "这不是 AP Library Manager 导出的图书馆文件"
            f"（format = {format_name!r}，应为 {constants.LIBRARY_FORMAT_NAME!r}）。"
        )

    version = data.get(constants.VERSION_KEY)
    if not isinstance(version, str) or not version.strip():
        raise LibraryFormatError("图书馆文件缺少有效的版本号（version）。")
    version = version.strip()
    if version not in constants.SUPPORTED_LIBRARY_VERSIONS:
        supported = "、".join(constants.SUPPORTED_LIBRARY_VERSIONS)
        raise LibraryVersionError(
            f"不支持的图书馆文件版本：{version}（当前支持 {supported}）。"
            "请使用兼容版本的软件导入。"
        )

    raw_nodes = data.get(constants.JSON_NODES_KEY)
    if not isinstance(raw_nodes, list):
        raise LibraryFormatError("图书馆文件缺少 nodes 数组。")
    raw_edges = data.get(constants.JSON_EDGES_KEY)
    if not isinstance(raw_edges, list):
        raise LibraryFormatError("图书馆文件缺少 edges 数组。")

    nodes: List[LibraryNodeRecord] = []
    known_ids: Dict[str, int] = {}
    for index, raw_node in enumerate(raw_nodes):
        record = _parse_node(raw_node, index)
        if record.external_id in known_ids:
            raise LibraryFormatError(
                f"节点 ID 重复：{record.external_id}（第 {known_ids[record.external_id] + 1} "
                f"个和第 {index + 1} 个节点）。"
            )
        known_ids[record.external_id] = index
        nodes.append(record)

    edges: List[LibraryEdgeRecord] = []
    seen_pairs: set[Tuple[str, str]] = set()
    for index, raw_edge in enumerate(raw_edges):
        record = _parse_edge(raw_edge, index)
        if record.parent not in known_ids:
            raise LibraryFormatError(
                f"第 {index + 1} 条关系引用了不存在的父节点：{record.parent}"
            )
        if record.child not in known_ids:
            raise LibraryFormatError(
                f"第 {index + 1} 条关系引用了不存在的子节点：{record.child}"
            )
        pair = (record.parent, record.child)
        if pair in seen_pairs:
            raise LibraryFormatError(
                f"关系重复：{record.parent} -> {record.child}"
            )
        seen_pairs.add(pair)
        if record.parent == record.child:
            raise LibraryFormatError(
                f"关系不能指向自身：{record.parent} -> {record.child}"
            )
        edges.append(record)

    _assert_acyclic(nodes, edges)
    return LibraryDocument(version=version, nodes=tuple(nodes), edges=tuple(edges))


def _parse_node(raw_node: Any, index: int) -> LibraryNodeRecord:
    label = f"第 {index + 1} 个节点"
    if not isinstance(raw_node, dict):
        raise LibraryFormatError(f"{label}必须是一个 JSON 对象。")

    external_id = _normalise_external_id(
        raw_node.get(constants.JSON_NODE_ID_KEY), f"{label}的 id"
    )
    label = f"节点 {external_id}"

    raw_name = raw_node.get(constants.JSON_NODE_NAME_KEY)
    if not isinstance(raw_name, str) or not raw_name.strip():
        raise LibraryFormatError(f"{label}缺少有效的名称（name）。")
    name = raw_name.strip()

    raw_pdfs = raw_node.get(constants.JSON_NODE_PDFS_KEY, [])
    if raw_pdfs is None:
        raw_pdfs = []
    if not isinstance(raw_pdfs, list):
        raise LibraryFormatError(f"{label}的 pdfs 必须是数组。")

    pdfs: List[str] = []
    for entry in raw_pdfs:
        if not isinstance(entry, str):
            raise LibraryFormatError(f"{label}的 pdfs 中含有非字符串路径：{entry!r}")
        text = entry.strip()
        if text:
            pdfs.append(text)

    raw_icon = raw_node.get(constants.JSON_NODE_ICON_KEY, "")
    if raw_icon is None:
        icon = ""
    elif isinstance(raw_icon, str):
        icon = raw_icon.strip()
    else:
        raise LibraryFormatError(f"{label}的 icon 必须是字符串。")

    raw_style = raw_node.get(constants.JSON_NODE_STYLE_KEY, {})
    if raw_style is None:
        raw_style = {}
    if not isinstance(raw_style, dict):
        raise LibraryFormatError(f"{label}的 style 必须是对象。")

    bold = _as_bool(
        raw_style.get(constants.JSON_STYLE_BOLD_KEY, False), f"{label}的 style.bold"
    )
    raw_color = raw_style.get(constants.JSON_STYLE_COLOR_KEY, constants.DEFAULT_TEXT_COLOR)
    if raw_color is None:
        color = constants.DEFAULT_TEXT_COLOR
    elif isinstance(raw_color, str):
        color = raw_color.strip() or constants.DEFAULT_TEXT_COLOR
    else:
        raise LibraryFormatError(f"{label}的 style.color 必须是字符串。")

    raw_metadata = raw_node.get(constants.JSON_NODE_METADATA_KEY, {})
    if raw_metadata is None:
        raw_metadata = {}
    if not isinstance(raw_metadata, dict):
        raise LibraryFormatError(f"{label}的 metadata 必须是对象。")

    return LibraryNodeRecord(
        external_id=external_id,
        name=name,
        pdfs=tuple(pdfs),
        icon=icon,
        style_bold=bold,
        style_color=color,
        metadata=dict(raw_metadata),
    )


def _parse_edge(raw_edge: Any, index: int) -> LibraryEdgeRecord:
    label = f"第 {index + 1} 条关系"
    if not isinstance(raw_edge, dict):
        raise LibraryFormatError(f"{label}必须是一个 JSON 对象。")

    parent = _normalise_external_id(
        raw_edge.get(constants.JSON_EDGE_PARENT_KEY), f"{label}的 parent"
    )
    child = _normalise_external_id(
        raw_edge.get(constants.JSON_EDGE_CHILD_KEY), f"{label}的 child"
    )
    raw_sort_order = raw_edge.get(constants.JSON_EDGE_SORT_ORDER_KEY, 0)
    if raw_sort_order is None:
        raw_sort_order = 0
    if isinstance(raw_sort_order, bool) or not isinstance(raw_sort_order, int):
        raise LibraryFormatError(f"{label}的 sort_order 必须是整数。")

    return LibraryEdgeRecord(parent=parent, child=child, sort_order=raw_sort_order)


def _assert_acyclic(
    nodes: Sequence[LibraryNodeRecord],
    edges: Sequence[LibraryEdgeRecord],
) -> None:
    """
    Reject a document whose edges form a cycle (plan.md §7.2 and §24).

    Kahn's algorithm is used instead of a recursive DFS so a very deep document
    cannot hit Python's recursion limit. The remaining nodes are reported by id
    so the user can repair the file.
    """
    order = [node.external_id for node in nodes]
    adjacency: Dict[str, List[str]] = {node_id: [] for node_id in order}
    indegree: Dict[str, int] = {node_id: 0 for node_id in order}

    for edge in edges:
        adjacency[edge.parent].append(edge.child)
        indegree[edge.child] += 1

    queue = [node_id for node_id in order if indegree[node_id] == 0]
    visited = 0
    position = 0
    while position < len(queue):
        current = queue[position]
        position += 1
        visited += 1
        for child in adjacency[current]:
            indegree[child] -= 1
            if indegree[child] == 0:
                queue.append(child)

    if visited == len(order):
        return

    remaining = [node_id for node_id in order if indegree[node_id] > 0]
    preview = "、".join(remaining[:5])
    if len(remaining) > 5:
        preview += "…"
    raise LibraryFormatError(
        f"关系数据包含循环引用（涉及节点：{preview}），无法导入。"
    )


def _normalise_external_id(value: Any, what: str) -> str:
    """External node ids are strings in the schema but integers are accepted."""
    if isinstance(value, bool) or value is None:
        raise LibraryFormatError(f"{what} 缺失或不是有效的节点 ID。")
    if isinstance(value, int):
        return str(value)
    if isinstance(value, str):
        text = value.strip()
        if text:
            return text
    raise LibraryFormatError(f"{what} 缺失或不是有效的节点 ID。")


def _as_bool(value: Any, what: str) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, int) and value in (0, 1):
        return bool(value)
    raise LibraryFormatError(f"{what} 必须是 true 或 false。")


# ==============================================================================
# End of json_utils.py
# ==============================================================================
