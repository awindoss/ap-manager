# ==============================================================================
# tests/test_search_service.py
# Phase 7: node/PDF search, multi-parent locations and result limits.
# ==============================================================================
import json

import pytest

from controllers.app_controller import AppController
from utils import constants


@pytest.fixture
def controller(tmp_path) -> AppController:
    return AppController(db_path=tmp_path / "search.db")


def test_search_matches_node_names_case_insensitively(controller: AppController) -> None:
    controller.create_node("Capital")
    controller.create_node("马克思")

    latin = controller.search_library("cApItAl")
    chinese = controller.search_library("马克思")

    assert [hit.name for hit in latin.hits] == ["Capital"]
    assert [hit.name for hit in chinese.hits] == ["马克思"]
    assert latin.hits[0].name_matched is True
    assert latin.hits[0].pdf_matched is False


def test_search_matches_pdf_file_names(controller: AppController) -> None:
    controller.library.create_node(
        "第一卷",
        pdf_paths=["books/capital_vol1.pdf", "books/notes.pdf"],
    )
    controller.library.create_node("无关节点", pdf_paths=["books/other.pdf"])

    result = controller.search_library("capital")

    assert result.hit_count == 1
    hit = result.hits[0]
    assert hit.name == "第一卷"
    assert hit.pdf_matched is True
    assert hit.name_matched is False
    assert hit.matched_pdf_names == ("capital_vol1.pdf",)
    assert "PDF" in hit.match_label


def test_search_returns_every_multi_parent_location(controller: AppController) -> None:
    root_a = controller.create_node("A")
    root_b = controller.create_node("B")
    child = controller.create_node("X", parent_id=root_a)
    controller.attach_node_to_parents(child, [root_b])

    result = controller.search_library("X")

    assert result.hit_count == 1
    hit = result.hits[0]
    assert {location.label for location in hit.locations} == {"A > X", "B > X"}
    assert len({location.path for location in hit.locations}) == 2


def test_search_ands_tokens_across_name_and_pdf(controller: AppController) -> None:
    controller.library.create_node("马克思", pdf_paths=["books/资本.pdf"])
    controller.library.create_node("马克思", pdf_paths=["books/manifesto.pdf"])

    combined = controller.search_library("马克思 资本")
    impossible = controller.search_library("马克思 不存在")

    assert combined.hit_count == 1
    assert combined.hits[0].name_matched is True
    assert combined.hits[0].pdf_matched is True
    assert impossible.is_empty


def test_search_limit_and_truncation(controller: AppController) -> None:
    for index in range(5):
        controller.create_node(f"匹配节点 {index}")

    result = controller.search_library("匹配节点", limit=2)

    assert result.hit_count == 2
    assert result.limit == 2
    assert result.truncated is True


def test_search_limit_is_clamped_to_the_supported_maximum(controller: AppController) -> None:
    controller.create_node("节点")

    result = controller.search_library("节点", limit=10_000)

    assert result.limit == constants.SEARCH_MAX_LIMIT


def test_search_escapes_like_wildcards(controller: AppController) -> None:
    controller.create_node("100% done")
    controller.create_node("100x done")
    controller.create_node("under_score")
    controller.create_node("underXscore")

    percent = controller.search_library("100%")
    underscore = controller.search_library("under_score")

    assert [hit.name for hit in percent.hits] == ["100% done"]
    assert [hit.name for hit in underscore.hits] == ["under_score"]


def test_empty_query_returns_no_results(controller: AppController) -> None:
    controller.create_node("节点")

    empty_result = controller.search_library("   ")

    assert empty_result.is_empty
    assert empty_result.query == ""


def test_name_match_sorts_before_pdf_only_match(controller: AppController) -> None:
    controller.library.create_node("zzz pdf carrier", pdf_paths=["books/target.pdf"])
    controller.library.create_node("target", pdf_paths=["books/other.pdf"])

    result = controller.search_library("target")

    assert [hit.name for hit in result.hits] == ["target", "zzz pdf carrier"]
    assert result.hits[0].name_matched is True
    assert result.hits[1].pdf_matched is True


def test_node_without_reachable_root_has_no_locations(controller: AppController) -> None:
    node_a = controller.create_node("Cycle A")
    node_b = controller.create_node("Cycle B")
    # Bypass the business-layer cycle guard to simulate a corrupted database.
    controller.library.db.add_edge(node_a, node_b)
    controller.library.db.add_edge(node_b, node_a)

    result = controller.search_library("Cycle A")

    assert result.hit_count == 1
    assert result.hits[0].locations == ()


def test_search_handles_legacy_ascii_escaped_json_paths(
    controller: AppController,
) -> None:
    """Older databases stored non-ASCII paths as ``\\u8d44\\u672c``."""
    node_id = controller.library.create_node("Legacy", pdf_paths=["books/资本.pdf"])
    legacy_json = json.dumps(["books/资本.pdf"], ensure_ascii=True)
    with controller.library.db.connection() as conn:
        conn.execute(
            "UPDATE nodes SET pdf_paths = ? WHERE id = ?",
            (legacy_json, node_id),
        )

    result = controller.search_library("资本")

    assert result.hit_count == 1
    assert result.hits[0].pdf_matched is True


def test_query_length_is_bounded(controller: AppController) -> None:
    controller.create_node("节点")
    long_query = "节" * (constants.SEARCH_MAX_QUERY_LENGTH + 20)

    result = controller.search_library(long_query)

    assert len(result.query) <= constants.SEARCH_MAX_QUERY_LENGTH
