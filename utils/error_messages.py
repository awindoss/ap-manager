# ==============================================================================
# utils/error_messages.py
# Turn technical exceptions into short, actionable messages for the UI
# (plan.md §39: the user sees an understandable text, the log keeps details).
#
# The helpers never hide the original error: callers log the exception with
# ``log_exception()`` while showing ``describe_error(error)`` in a QMessageBox.
# ==============================================================================
import json
import sqlite3
import traceback
from typing import Optional


def describe_error(error: BaseException) -> str:
    """
    Return a user-facing description for ``error``.

    ``ValueError`` (including :class:`models.library.GraphCycleError`) already
    carries a Chinese, user-oriented message and is passed through unchanged.
    """
    if isinstance(error, json.JSONDecodeError):
        line = getattr(error, "lineno", 0)
        column = getattr(error, "colno", 0)
        return (
            "文件内容不是有效的 JSON，无法读取。\n"
            f"请检查第 {line} 行第 {column} 列附近的内容。"
        )

    if isinstance(error, ValueError):
        text = str(error).strip()
        return text or "操作未能完成，请检查输入后重试。"

    if isinstance(error, sqlite3.OperationalError):
        raw = str(error)
        lowered = raw.lower()
        if "locked" in lowered or "busy" in lowered:
            return (
                "数据库正被占用，暂时无法写入。\n"
                "请关闭其他正在使用书库的窗口或程序，稍后重试。"
                f"\n\n技术信息：{raw}"
            )
        if "readonly" in lowered or "read-only" in lowered:
            return (
                "书库数据库是只读的，无法保存修改。\n"
                "请检查文件权限，或把程序放到可写目录后重试。"
                f"\n\n技术信息：{raw}"
            )
        if "no such table" in lowered:
            return (
                "书库数据库结构不完整，无法完成操作。\n"
                "请检查 data/library.db 是否被替换或损坏。"
                f"\n\n技术信息：{raw}"
            )
        if "disk i/o error" in lowered or "unable to open database" in lowered:
            return (
                "无法读写书库数据库文件。\n"
                "请确认磁盘可用空间充足、文件没有被其他程序占用。"
                f"\n\n技术信息：{raw}"
            )
        return f"数据库操作失败：{raw}"

    if isinstance(error, sqlite3.IntegrityError):
        return (
            "数据约束冲突，操作没有写入数据库。\n"
            "可能该位置已经存在，请刷新后重试。"
            f"\n\n技术信息：{error}"
        )
    if isinstance(error, sqlite3.Error):
        return f"数据库操作失败：{error}"

    if isinstance(error, PermissionError):
        return (
            "没有访问权限，操作未能完成。\n"
            "请检查文件或目录的权限设置，或换一个可写的目录。"
            f"\n\n技术信息：{error}"
        )
    if isinstance(error, FileNotFoundError):
        return f"找不到文件或目录：{getattr(error, 'filename', None) or error}"
    if isinstance(error, IsADirectoryError):
        return "选择的是一个文件夹，请选择具体文件。"
    if isinstance(error, FileExistsError):
        return "目标文件已存在，请换一个名称或选择覆盖。"
    if isinstance(error, MemoryError):
        return "内存不足，操作未能完成。请关闭部分程序后重试。"
    if isinstance(error, OSError):
        return f"文件操作失败：{error}"

    text = str(error).strip()
    if text:
        return f"操作失败：{text}"
    return f"操作失败：{type(error).__name__}"


def describe_operation(operation: str, error: BaseException) -> str:
    """Prefix a friendly message with the action that failed."""
    return f"{operation}失败。\n\n{describe_error(error)}"


def technical_details(error: Optional[BaseException] = None) -> str:
    """
    Return a traceback for the "details" area of an error dialog.

    When an exception is being handled, the active traceback is used; otherwise
    the exception type/message is returned on its own.
    """
    active = traceback.format_exc()
    if active and active.strip() != "NoneType: None":
        return active
    if error is None:
        return ""
    return "".join(traceback.format_exception_only(type(error), error)).strip()


# ==============================================================================
# End of error_messages.py
# ==============================================================================
