# ==============================================================================
# tests/test_relocator.py
# Phase 7: batch matching of missing PDFs against a folder.
# ==============================================================================
from pathlib import Path

import pytest

from controllers.app_controller import AppController
from services.relocator import (
    RelinkRequest,
    build_filename_index,
    plan_batch_relink,
)
from utils import constants


def make_pdf(path: Path, content: bytes = b"%PDF-1.4\n") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    return path


def request(stored_path: str, node_id: int = 1) -> RelinkRequest:
    return RelinkRequest(node_id=node_id, stored_path=stored_path)


def test_single_same_named_pdf_is_matched_recursively(tmp_path) -> None:
    target = make_pdf(tmp_path / "recovered" / "deep" / "capital.pdf")

    plan = plan_batch_relink([request("books/capital.pdf")], tmp_path)

    assert len(plan.matched) == 1
    assert plan.matched[0].new_path == target
    assert plan.matched[0].status == constants.RELINK_STATUS_MATCHED


def test_non_recursive_scan_ignores_subfolders(tmp_path) -> None:
    make_pdf(tmp_path / "sub" / "capital.pdf")
    direct = make_pdf(tmp_path / "capital.pdf")

    plan = plan_batch_relink(
        [request("books/capital.pdf")], tmp_path, recursive=False
    )

    assert len(plan.matched) == 1
    assert plan.matched[0].new_path == direct


def test_missing_file_is_reported_not_guessed(tmp_path) -> None:
    make_pdf(tmp_path / "other.pdf")

    plan = plan_batch_relink([request("books/capital.pdf")], tmp_path)

    assert not plan.matched
    assert len(plan.not_found) == 1
    assert plan.not_found[0].status_label == "未找到"


def test_same_name_in_two_directories_is_ambiguous(tmp_path) -> None:
    make_pdf(tmp_path / "a" / "capital.pdf")
    make_pdf(tmp_path / "b" / "capital.pdf")

    plan = plan_batch_relink([request("books/capital.pdf")], tmp_path)

    assert not plan.matched
    assert len(plan.ambiguous) == 1
    assert "同名" in plan.ambiguous[0].detail


def test_path_suffix_breaks_the_tie(tmp_path) -> None:
    expected = make_pdf(tmp_path / "marx" / "books" / "capital.pdf")
    make_pdf(tmp_path / "other" / "capital.pdf")

    plan = plan_batch_relink([request("marx/books/capital.pdf")], tmp_path)

    assert len(plan.matched) == 1
    assert plan.matched[0].new_path == expected
    assert "最接近" in plan.matched[0].detail


def test_invalid_search_root_raises(tmp_path) -> None:
    with pytest.raises(ValueError, match="文件夹不存在"):
        plan_batch_relink([request("a.pdf")], tmp_path / "missing")

    with pytest.raises(ValueError, match="请选择"):
        plan_batch_relink([request("a.pdf")], "")


def test_filename_index_contains_only_pdfs(tmp_path) -> None:
    make_pdf(tmp_path / "a.pdf")
    (tmp_path / "notes.txt").write_text("not a pdf", encoding="utf-8")

    index = build_filename_index(tmp_path)

    assert list(index) == ["a.pdf"]


def test_windows_separators_are_supported(tmp_path) -> None:
    target = make_pdf(tmp_path / "books" / "capital.pdf")

    plan = plan_batch_relink([request(r"books\capital.pdf")], tmp_path)

    assert len(plan.matched) == 1
    assert plan.matched[0].new_path == target


def test_controller_batch_relinks_every_matched_reference(tmp_path) -> None:
    controller = AppController(db_path=tmp_path / "library.db")
    node_id = controller.library.create_node(
        "资本论",
        pdf_paths=["books/capital_1.pdf", "books/capital_2.pdf"],
    )
    make_pdf(tmp_path / "recovered" / "capital_1.pdf")
    make_pdf(tmp_path / "recovered" / "capital_2.pdf")

    outcome = controller.relink_missing_from_folder(tmp_path / "recovered")

    assert outcome.requested == 2
    assert outcome.relinked == 2
    assert outcome.has_changes is True
    stored = controller.list_pdfs(node_id)
    assert [Path(path).name for path in stored] == ["capital_1.pdf", "capital_2.pdf"]
    assert all(Path(path).is_file() for path in stored)


def test_controller_batch_reports_unmatched_entries(tmp_path) -> None:
    controller = AppController(db_path=tmp_path / "library.db")
    controller.library.create_node("A", pdf_paths=["books/missing.pdf"])
    make_pdf(tmp_path / "recovered" / "unrelated.pdf")

    outcome = controller.relink_missing_from_folder(tmp_path / "recovered")

    assert outcome.relinked == 0
    assert outcome.has_changes is False
    assert len(outcome.not_found) == 1
    assert outcome.not_found[0].node_name == "A"


def test_controller_batch_keeps_going_after_one_write_failure(
    tmp_path, monkeypatch
) -> None:
    controller = AppController(db_path=tmp_path / "library.db")
    controller.library.create_node(
        "A", pdf_paths=["books/a.pdf", "books/b.pdf"]
    )
    make_pdf(tmp_path / "recovered" / "a.pdf")
    make_pdf(tmp_path / "recovered" / "b.pdf")

    original = controller.relink_pdf
    calls = []

    def flaky(node_id, stored_path, new_source, **kwargs):
        calls.append(stored_path)
        if stored_path.endswith("a.pdf"):
            raise ValueError("模拟写入失败")
        return original(node_id, stored_path, new_source, **kwargs)

    monkeypatch.setattr(controller, "relink_pdf", flaky)

    outcome = controller.relink_missing_from_folder(tmp_path / "recovered")

    assert len(calls) == 2
    assert outcome.relinked == 1
    assert len(outcome.errors) == 1
