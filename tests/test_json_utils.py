# ==============================================================================
# tests/test_json_utils.py
# Validation of the library exchange format (Phase 6).
# ==============================================================================
import json

import pytest

from utils import constants
from utils.json_utils import (
    LibraryFormatError,
    LibraryVersionError,
    load_library_document,
    parse_library_document,
    validate_json_schema,
)


def make_document(nodes=None, edges=None, **overrides) -> dict:
    document = {
        constants.JSON_FORMAT_KEY: constants.LIBRARY_FORMAT_NAME,
        constants.VERSION_KEY: constants.LIBRARY_FORMAT_VERSION,
        constants.JSON_NODES_KEY: nodes
        if nodes is not None
        else [
            {
                "id": "n1",
                "name": "经济政治",
                "pdfs": [],
                "icon": "🏛️",
                "style": {"bold": False, "color": "#000000"},
                "metadata": {},
            },
            {
                "id": "n2",
                "name": "马克思",
                "pdfs": ["./books/marx.pdf"],
                "icon": "👤",
                "style": {"bold": True, "color": "#B22222"},
                "metadata": {"tags": ["哲学"]},
            },
        ],
        constants.JSON_EDGES_KEY: edges
        if edges is not None
        else [
            {"parent": "n1", "child": "n2", "sort_order": 0},
        ],
    }
    document.update(overrides)
    return document


def test_valid_document_is_parsed_with_typed_records(tmp_path) -> None:
    document = parse_library_document(make_document())

    assert document.version == "0.1"
    assert [node.external_id for node in document.nodes] == ["n1", "n2"]
    assert document.nodes[1].name == "马克思"
    assert document.nodes[1].pdfs == ("./books/marx.pdf",)
    assert document.nodes[1].style_bold is True
    assert document.nodes[1].style_color == "#B22222"
    assert document.nodes[1].metadata == {"tags": ["哲学"]}
    assert document.edges[0].parent == "n1"
    assert document.edges[0].sort_order == 0


def test_validate_json_schema_accepts_a_valid_document() -> None:
    assert validate_json_schema(make_document()) is None


def test_unknown_extra_keys_are_ignored() -> None:
    raw = make_document()
    raw["exported_by"] = "future version"
    raw["nodes"][0]["future_field"] = 1

    document = parse_library_document(raw)

    assert len(document.nodes) == 2


def test_numeric_external_ids_are_normalised_to_strings() -> None:
    raw = make_document(
        nodes=[
            {"id": 1, "name": "A"},
            {"id": 2, "name": "B"},
        ],
        edges=[{"parent": 1, "child": 2, "sort_order": 0}],
    )

    document = parse_library_document(raw)

    assert [node.external_id for node in document.nodes] == ["1", "2"]
    assert document.edges[0].parent == "1"


def test_missing_or_wrong_format_is_rejected() -> None:
    raw = make_document()
    raw.pop(constants.JSON_FORMAT_KEY)
    with pytest.raises(LibraryFormatError, match="format"):
        parse_library_document(raw)

    raw = make_document()
    raw[constants.JSON_FORMAT_KEY] = "some_other_app"
    with pytest.raises(LibraryFormatError, match="AP Library Manager"):
        parse_library_document(raw)


def test_unsupported_version_is_rejected() -> None:
    raw = make_document(version="99.0")

    with pytest.raises(LibraryVersionError, match="99.0"):
        parse_library_document(raw)


def test_missing_version_is_rejected() -> None:
    raw = make_document()
    raw.pop(constants.VERSION_KEY)

    with pytest.raises(LibraryFormatError, match="版本号"):
        parse_library_document(raw)


def test_missing_nodes_or_edges_arrays_are_rejected() -> None:
    raw = make_document()
    raw.pop(constants.JSON_NODES_KEY)
    with pytest.raises(LibraryFormatError, match="nodes"):
        parse_library_document(raw)

    raw = make_document()
    raw.pop(constants.JSON_EDGES_KEY)
    with pytest.raises(LibraryFormatError, match="edges"):
        parse_library_document(raw)


def test_duplicate_node_ids_are_rejected() -> None:
    raw = make_document(
        nodes=[
            {"id": "n1", "name": "A"},
            {"id": "n1", "name": "B"},
        ],
        edges=[],
    )

    with pytest.raises(LibraryFormatError, match="重复"):
        parse_library_document(raw)


def test_node_requires_a_name() -> None:
    for name in ("", "   ", None, 42):
        raw = make_document(nodes=[{"id": "n1", "name": name}], edges=[])
        with pytest.raises(LibraryFormatError, match="名称"):
            parse_library_document(raw)


def test_node_pdfs_must_be_a_list_of_strings() -> None:
    raw = make_document(nodes=[{"id": "n1", "name": "A", "pdfs": "books/a.pdf"}], edges=[])
    with pytest.raises(LibraryFormatError, match="pdfs"):
        parse_library_document(raw)

    raw = make_document(nodes=[{"id": "n1", "name": "A", "pdfs": [1]}], edges=[])
    with pytest.raises(LibraryFormatError, match="pdfs"):
        parse_library_document(raw)


def test_style_and_metadata_types_are_validated() -> None:
    raw = make_document(
        nodes=[{"id": "n1", "name": "A", "style": {"bold": "yes"}}],
        edges=[],
    )
    with pytest.raises(LibraryFormatError, match="bold"):
        parse_library_document(raw)

    raw = make_document(
        nodes=[{"id": "n1", "name": "A", "style": {"color": 12}}],
        edges=[],
    )
    with pytest.raises(LibraryFormatError, match="color"):
        parse_library_document(raw)

    raw = make_document(
        nodes=[{"id": "n1", "name": "A", "metadata": ["tags"]}],
        edges=[],
    )
    with pytest.raises(LibraryFormatError, match="metadata"):
        parse_library_document(raw)


def test_edges_must_reference_known_nodes() -> None:
    raw = make_document(
        nodes=[{"id": "n1", "name": "A"}],
        edges=[{"parent": "n1", "child": "n2", "sort_order": 0}],
    )
    with pytest.raises(LibraryFormatError, match="不存在的子节点"):
        parse_library_document(raw)


def test_duplicate_or_self_edges_are_rejected() -> None:
    nodes = [{"id": "n1", "name": "A"}, {"id": "n2", "name": "B"}]

    with pytest.raises(LibraryFormatError, match="重复"):
        parse_library_document(
            make_document(
                nodes=nodes,
                edges=[
                    {"parent": "n1", "child": "n2"},
                    {"parent": "n1", "child": "n2"},
                ],
            )
        )

    with pytest.raises(LibraryFormatError, match="自身"):
        parse_library_document(
            make_document(
                nodes=nodes,
                edges=[{"parent": "n1", "child": "n1"}],
            )
        )


def test_cycle_is_rejected() -> None:
    raw = make_document(
        nodes=[
            {"id": "a", "name": "A"},
            {"id": "b", "name": "B"},
            {"id": "c", "name": "C"},
        ],
        edges=[
            {"parent": "a", "child": "b"},
            {"parent": "b", "child": "c"},
            {"parent": "c", "child": "a"},
        ],
    )

    with pytest.raises(LibraryFormatError, match="循环"):
        parse_library_document(raw)


def test_multi_parent_diamond_is_not_a_cycle() -> None:
    raw = make_document(
        nodes=[
            {"id": "a", "name": "A"},
            {"id": "b", "name": "B"},
            {"id": "x", "name": "X"},
        ],
        edges=[
            {"parent": "a", "child": "x"},
            {"parent": "b", "child": "x"},
        ],
    )

    document = parse_library_document(raw)
    assert len(document.edges) == 2


def test_load_library_document_accepts_utf8_bom(tmp_path) -> None:
    path = tmp_path / "library.json"
    path.write_text(
        "\ufeff" + json.dumps(make_document(), ensure_ascii=False),
        encoding="utf-8",
    )

    document = load_library_document(path)

    assert document.nodes[0].name == "经济政治"


def test_load_library_document_reports_json_errors(tmp_path) -> None:
    path = tmp_path / "library.json"
    path.write_text("{not json", encoding="utf-8")

    with pytest.raises(LibraryFormatError, match="JSON 格式错误"):
        load_library_document(path)


def test_load_library_document_reports_missing_file(tmp_path) -> None:
    with pytest.raises(LibraryFormatError, match="无法读取"):
        load_library_document(tmp_path / "missing.json")
