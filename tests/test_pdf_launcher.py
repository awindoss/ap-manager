# ==============================================================================
# tests/test_pdf_launcher.py
# Reader/command selection and failure handling for opening PDFs (Phase 4).
# ==============================================================================
from pathlib import Path

import pytest

from services import pdf_launcher
from services.pdf_launcher import (
    PdfLaunchError,
    PdfLauncher,
    launch_pdf,
    normalize_reader_args,
)


def make_pdf(tmp_path, name: str = "book.pdf") -> Path:
    path = tmp_path / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"%PDF-1.4\n")
    return path


class RecordingPopen:
    def __init__(self) -> None:
        self.commands = []

    def __call__(self, command):
        self.commands.append(list(command))
        return object()


class FailingPopen:
    def __call__(self, command):
        raise OSError("spawn failed")


# ------------------------------------------------------------------------------
# Argument parsing
# ------------------------------------------------------------------------------
def test_normalize_reader_args_accepts_none_list_and_string() -> None:
    assert normalize_reader_args(None) == []
    assert normalize_reader_args("") == []
    assert normalize_reader_args("  ") == []
    assert normalize_reader_args(["-a", " ", "-b"]) == ["-a", "-b"]
    assert normalize_reader_args(("-a", "-b")) == ["-a", "-b"]
    assert normalize_reader_args('-reuse-instance -title "My PDF"') == [
        "-reuse-instance",
        "-title",
        "My PDF",
    ]


def test_normalize_reader_args_ignores_broken_quoting() -> None:
    assert normalize_reader_args('"unterminated') == []


# ------------------------------------------------------------------------------
# Explicit reader
# ------------------------------------------------------------------------------
def test_launch_with_explicit_reader_builds_command(tmp_path) -> None:
    pdf = make_pdf(tmp_path)
    reader = tmp_path / "viewer.exe"
    reader.write_bytes(b"")
    popen = RecordingPopen()

    launcher = PdfLauncher(
        reader_path=str(reader),
        reader_args=["-reuse-instance"],
        platform_name="win32",
        popen=popen,
    )

    opened = launcher.launch(pdf)

    assert opened == str(pdf)
    assert popen.commands == [[str(reader), "-reuse-instance", str(pdf)]]
    assert launcher.uses_system_reader is False
    assert launcher.reader_args == ["-reuse-instance"]


def test_launch_accepts_a_bare_command_name(tmp_path) -> None:
    pdf = make_pdf(tmp_path)
    popen = RecordingPopen()
    launcher = PdfLauncher(reader_path="sumatrapdf", popen=popen)

    launcher.launch(pdf)

    assert popen.commands == [["sumatrapdf", str(pdf)]]


def test_missing_reader_path_is_reported_before_spawning(tmp_path) -> None:
    pdf = make_pdf(tmp_path)
    popen = RecordingPopen()
    launcher = PdfLauncher(reader_path=str(tmp_path / "missing.exe"), popen=popen)

    with pytest.raises(PdfLaunchError):
        launcher.launch(pdf)

    assert popen.commands == []


def test_spawn_failure_is_wrapped(tmp_path) -> None:
    pdf = make_pdf(tmp_path)
    reader = tmp_path / "viewer.exe"
    reader.write_bytes(b"")
    launcher = PdfLauncher(reader_path=str(reader), popen=FailingPopen())

    with pytest.raises(PdfLaunchError):
        launcher.launch(pdf)


def test_build_reader_command_requires_a_reader(tmp_path) -> None:
    launcher = PdfLauncher(platform_name="linux")

    with pytest.raises(PdfLaunchError):
        launcher.build_reader_command(tmp_path / "a.pdf")


def test_set_reader_path_can_restore_the_system_reader() -> None:
    launcher = PdfLauncher(reader_path="viewer", reader_args=["-a"])

    launcher.set_reader_path("", None)

    assert launcher.reader_path == ""
    assert launcher.reader_args == []
    assert launcher.uses_system_reader is True


# ------------------------------------------------------------------------------
# System default reader
# ------------------------------------------------------------------------------
@pytest.mark.parametrize("platform_name", ["win32", "win", "windows"])
def test_windows_system_reader_uses_startfile(tmp_path, platform_name) -> None:
    pdf = make_pdf(tmp_path)
    started = []
    popen = RecordingPopen()

    launcher = PdfLauncher(
        platform_name=platform_name,
        popen=popen,
        startfile=started.append,
    )

    launcher.launch(pdf)

    assert started == [str(pdf)]
    assert popen.commands == []


def test_macos_system_reader_uses_open(tmp_path) -> None:
    pdf = make_pdf(tmp_path)
    popen = RecordingPopen()
    launcher = PdfLauncher(platform_name="darwin", popen=popen)

    launcher.launch(pdf)

    assert popen.commands == [["open", str(pdf)]]


def test_linux_system_reader_uses_xdg_open(tmp_path) -> None:
    pdf = make_pdf(tmp_path)
    popen = RecordingPopen()
    launcher = PdfLauncher(platform_name="linux", popen=popen)

    launcher.launch(pdf)

    assert popen.commands == [["xdg-open", str(pdf)]]


def test_windows_system_reader_reports_startfile_failure(tmp_path) -> None:
    pdf = make_pdf(tmp_path)

    def failing_startfile(_path: str) -> None:
        raise OSError("no association")

    launcher = PdfLauncher(platform_name="win32", startfile=failing_startfile)

    with pytest.raises(PdfLaunchError):
        launcher.launch(pdf)


# ------------------------------------------------------------------------------
# Input validation / batch launch
# ------------------------------------------------------------------------------
def test_missing_pdf_is_rejected(tmp_path) -> None:
    launcher = PdfLauncher(platform_name="linux", popen=RecordingPopen())

    with pytest.raises(PdfLaunchError):
        launcher.launch(tmp_path / "gone.pdf")
    with pytest.raises(PdfLaunchError):
        launcher.launch("")


def test_launch_many_collects_opened_and_failures(tmp_path) -> None:
    first = make_pdf(tmp_path, "first.pdf")
    missing = tmp_path / "missing.pdf"
    popen = RecordingPopen()
    launcher = PdfLauncher(platform_name="linux", popen=popen)

    report = launcher.launch_many([first, missing, None, ""])

    assert report.opened == [str(first)]
    assert report.failure_count == 1
    assert report.opened_count == 1
    assert report.is_success is False
    assert len(popen.commands) == 1


def test_module_level_launch_pdf_uses_the_reader(tmp_path, monkeypatch) -> None:
    pdf = make_pdf(tmp_path)
    reader = tmp_path / "viewer.exe"
    reader.write_bytes(b"")
    popen = RecordingPopen()
    monkeypatch.setattr(pdf_launcher.subprocess, "Popen", popen)

    assert launch_pdf(pdf, reader_path=reader) is True
    assert popen.commands == [[str(reader), str(pdf)]]
