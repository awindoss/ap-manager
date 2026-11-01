# ==============================================================================
# services/pdf_launcher.py
# Launch PDF files in the user's chosen reader or in the platform default
# application (plan.md §20).
#
# The launcher never parses PDFs and never waits for the reader: it only starts
# a process. All failures are surfaced as :class:`PdfLaunchError` with a
# user-readable message, so the UI can show a dialog instead of crashing
# (plan.md §39).
# ==============================================================================
import os
import shlex
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Iterable, List, Optional, Tuple

from utils.logger import log_info, log_warning


class PdfLaunchError(RuntimeError):
    """A PDF could not be opened (missing file, missing reader, spawn failure)."""


@dataclass
class LaunchReport:
    """Outcome of opening several PDFs at once."""

    opened: List[str] = field(default_factory=list)
    failures: List[Tuple[str, str]] = field(default_factory=list)

    @property
    def opened_count(self) -> int:
        return len(self.opened)

    @property
    def failure_count(self) -> int:
        return len(self.failures)

    @property
    def is_success(self) -> bool:
        return not self.failures


def normalize_reader_args(value: object) -> List[str]:
    """
    Parse ``pdf_reader.args`` from config.

    Accepts ``None``, a list/tuple of arguments or a shell-like string such as
    ``-reuse-instance -new-window``. Invalid quoting degrades to "no arguments"
    with a warning instead of blocking PDF opening.
    """
    if value is None:
        return []
    if isinstance(value, (list, tuple)):
        return [str(item) for item in value if str(item).strip()]
    text = str(value).strip()
    if not text:
        return []
    try:
        return shlex.split(text)
    except ValueError as error:
        log_warning(f"Invalid pdf_reader.args {value!r}: {error}; ignoring them.")
        return []


class PdfLauncher:
    """
    Starts the configured reader, or the platform default PDF application.

    ``popen`` / ``startfile`` are injectable so the platform branches can be
    tested without actually starting processes.
    """

    def __init__(
        self,
        reader_path: object = "",
        reader_args: object = None,
        *,
        platform_name: Optional[str] = None,
        popen: Optional[Callable[..., object]] = None,
        startfile: Optional[Callable[[str], object]] = None,
    ) -> None:
        self._reader_path = ""
        self._reader_args: List[str] = []
        self.set_reader_path(reader_path, reader_args)

        self._platform = platform_name or sys.platform
        self._popen = popen or subprocess.Popen
        self._startfile = startfile if startfile is not None else getattr(os, "startfile", None)

    # --------------------------------------------------------------------------
    # Configuration
    # --------------------------------------------------------------------------
    @property
    def reader_path(self) -> str:
        return self._reader_path

    @property
    def reader_args(self) -> List[str]:
        return list(self._reader_args)

    @property
    def uses_system_reader(self) -> bool:
        return not self._reader_path

    def set_reader_path(self, reader_path: object, reader_args: object = None) -> None:
        """Set (or clear) the reader executable and its extra arguments."""
        self._reader_path = "" if reader_path is None else str(reader_path).strip()
        self._reader_args = normalize_reader_args(reader_args)

    # --------------------------------------------------------------------------
    # Launching
    # --------------------------------------------------------------------------
    def build_reader_command(self, pdf_path: str | Path) -> List[str]:
        """Command line for an explicitly configured reader (file path last)."""
        if not self._reader_path:
            raise PdfLaunchError("未指定 PDF 阅读器。")
        return [self._reader_path, *self._reader_args, str(pdf_path)]

    def launch(self, pdf_path: str | Path) -> str:
        """
        Open one PDF; returns the absolute path that was passed to the reader.

        Raises :class:`PdfLaunchError` when the file is missing, the configured
        reader cannot be found, or the operating system refuses the launch.
        """
        candidate = self._absolute_pdf_path(pdf_path)

        if self._reader_path:
            self._check_reader_path(self._reader_path)
            command = self.build_reader_command(candidate)
            try:
                self._popen(command)
            except (OSError, subprocess.SubprocessError) as error:
                raise PdfLaunchError(f"无法启动 PDF 阅读器：{error}") from error
            log_info(f"Opened PDF with configured reader: {candidate}")
            return str(candidate)

        try:
            if self._platform.startswith("win"):
                if self._startfile is None:
                    raise PdfLaunchError("当前系统不支持使用默认阅读器打开 PDF。")
                self._startfile(str(candidate))
            elif self._platform == "darwin":
                self._popen(["open", str(candidate)])
            else:
                self._popen(["xdg-open", str(candidate)])
        except PdfLaunchError:
            raise
        except (OSError, subprocess.SubprocessError) as error:
            raise PdfLaunchError(f"无法使用系统默认阅读器打开 PDF：{error}") from error

        log_info(f"Opened PDF with the system reader: {candidate}")
        return str(candidate)

    def launch_many(self, pdf_paths: Iterable[object]) -> LaunchReport:
        """Open every PDF, collecting failures instead of aborting on the first."""
        report = LaunchReport()
        for path in pdf_paths or ():
            text = "" if path is None else str(path).strip()
            if not text:
                continue
            try:
                self.launch(text)
            except PdfLaunchError as error:
                report.failures.append((text, str(error)))
            else:
                report.opened.append(text)
        return report

    # --------------------------------------------------------------------------
    # Internals
    # --------------------------------------------------------------------------
    @staticmethod
    def _absolute_pdf_path(pdf_path: str | Path) -> Path:
        text = "" if pdf_path is None else str(pdf_path).strip()
        if not text:
            raise PdfLaunchError("PDF 路径为空。")
        candidate = Path(text).expanduser()
        if not candidate.is_absolute():
            candidate = Path(os.path.abspath(candidate))
        if not candidate.is_file():
            raise PdfLaunchError(f"PDF 文件不存在：{candidate}")
        return candidate

    @staticmethod
    def _check_reader_path(reader_path: str) -> None:
        """
        Validate a configured reader without forbidding bare command names.

        A value such as ``sumatrapdf`` (no separators) is left to ``PATH`` lookup
        by the OS. A value that looks like a filesystem path must exist.
        """
        candidate = Path(reader_path).expanduser()
        looks_like_path = (
            candidate.is_absolute()
            or bool(candidate.drive)
            or candidate.parent != Path(".")
        )
        if looks_like_path and not candidate.is_file():
            raise PdfLaunchError(f"PDF 阅读器不存在：{candidate}")


def launch_pdf(
    pdf_abs_path: str | Path,
    reader_path: object = None,
    reader_args: object = None,
    *,
    platform_name: Optional[str] = None,
) -> bool:
    """Module-level convenience wrapper used by simple callers and tests."""
    PdfLauncher(
        reader_path=reader_path or "",
        reader_args=reader_args,
        platform_name=platform_name,
    ).launch(pdf_abs_path)
    return True


# ==============================================================================
# End of pdf_launcher.py
# ==============================================================================
