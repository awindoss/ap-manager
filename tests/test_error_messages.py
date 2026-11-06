# ==============================================================================
# tests/test_error_messages.py
# Phase 7: user-facing messages for technical exceptions (plan.md §39).
# ==============================================================================
import json
import sqlite3

from utils.error_messages import (
    describe_error,
    describe_operation,
    technical_details,
)


def test_value_error_keeps_its_user_oriented_text() -> None:
    assert describe_error(ValueError("节点名称不能为空。")) == "节点名称不能为空。"


def test_empty_value_error_gets_a_fallback() -> None:
    assert "请检查输入" in describe_error(ValueError("   "))


def test_locked_database_suggests_closing_other_programs() -> None:
    message = describe_error(sqlite3.OperationalError("database is locked"))

    assert "占用" in message
    assert "database is locked" in message


def test_read_only_database_is_explained() -> None:
    message = describe_error(sqlite3.OperationalError("attempt to write a readonly database"))

    assert "只读" in message
    assert "权限" in message


def test_missing_table_is_explained() -> None:
    message = describe_error(sqlite3.OperationalError("no such table: nodes"))

    assert "结构不完整" in message


def test_permission_error_is_explained() -> None:
    message = describe_error(PermissionError("denied"))

    assert "权限" in message


def test_file_not_found_lists_the_name() -> None:
    message = describe_error(FileNotFoundError(2, "missing", "books/a.pdf"))

    assert "找不到文件" in message
    assert "books/a.pdf" in message


def test_json_error_points_at_the_line() -> None:
    try:
        json.loads("{not json")
    except json.JSONDecodeError as error:
        message = describe_error(error)

    assert "JSON" in message
    assert "行" in message


def test_unknown_error_is_prefixed() -> None:
    assert describe_error(RuntimeError("boom")).startswith("操作失败")


def test_operation_prefix() -> None:
    message = describe_operation("导入图书馆", ValueError("版本不支持"))

    assert message.startswith("导入图书馆失败")
    assert "版本不支持" in message


def test_technical_details_contains_the_traceback() -> None:
    try:
        1 / 0
    except ZeroDivisionError as error:
        details = technical_details(error)

    assert "Traceback" in details
    assert "ZeroDivisionError" in details
