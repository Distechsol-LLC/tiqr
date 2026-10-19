import subprocess

import pytest

from tiqr.core import printer
from tiqr.core.printer import PrinterError


def no_sumatra_installed(monkeypatch, tmp_path):
    monkeypatch.setattr(printer.shutil, "which", lambda name: None)
    for variable in ("LOCALAPPDATA", "ProgramFiles", "ProgramFiles(x86)"):
        monkeypatch.setenv(variable, str(tmp_path / "empty" / variable))


def test_send_to_printer_uses_print_verb_on_windows_without_sumatra(monkeypatch, tmp_path):
    path = tmp_path / "ticket.pdf"
    calls = []
    no_sumatra_installed(monkeypatch, tmp_path)
    monkeypatch.setattr(printer.sys, "platform", "win32")
    monkeypatch.setattr(
        printer.os, "startfile", lambda target, verb: calls.append((target, verb)), raising=False
    )

    printer.send_to_printer(path)

    assert calls == [(path, "print")]


def test_send_to_printer_prefers_sumatra_silent_100_percent_on_windows(monkeypatch, tmp_path):
    path = tmp_path / "ticket.pdf"
    sumatra = tmp_path / "SumatraPDF" / "SumatraPDF.exe"
    sumatra.parent.mkdir()
    sumatra.write_bytes(b"")
    runs = []

    def run(args, **kwargs):
        runs.append(args)
        return subprocess.CompletedProcess(args, 0, b"", b"")

    no_sumatra_installed(monkeypatch, tmp_path)
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    monkeypatch.setattr(printer.sys, "platform", "win32")
    monkeypatch.setattr(printer.subprocess, "run", run)
    monkeypatch.setattr(
        printer.os, "startfile", lambda *args: pytest.fail("startfile used"), raising=False
    )

    printer.send_to_printer(path)

    assert runs == [
        [sumatra, "-print-to-default", "-print-settings", "noscale", "-silent", str(path)]
    ]


def test_sumatra_failure_is_reported_on_windows(monkeypatch, tmp_path):
    path = tmp_path / "ticket.pdf"
    no_sumatra_installed(monkeypatch, tmp_path)
    monkeypatch.setattr(printer.shutil, "which", lambda name: "C:/Tools/SumatraPDF.exe")
    monkeypatch.setattr(printer.sys, "platform", "win32")
    monkeypatch.setattr(
        printer.subprocess,
        "run",
        lambda args, **kwargs: subprocess.CompletedProcess(args, 1, b"", b""),
    )

    with pytest.raises(PrinterError, match=r"SumatraPDF could not print ticket\.pdf"):
        printer.send_to_printer(path)


def test_send_to_printer_uses_lp_on_linux(monkeypatch, tmp_path):
    path = tmp_path / "ticket.pdf"
    runs = []

    def run(args, **kwargs):
        runs.append(args)
        return subprocess.CompletedProcess(args, 0, "request id is printer-1", "")

    monkeypatch.setattr(printer.sys, "platform", "linux")
    monkeypatch.setattr(printer.shutil, "which", lambda name: "/usr/bin/lp")
    monkeypatch.setattr(printer.subprocess, "run", run)

    printer.send_to_printer(path)

    assert runs == [["/usr/bin/lp", "-o", "print-scaling=none", str(path)]]


def test_send_to_printer_reports_missing_or_failed_lp(monkeypatch, tmp_path):
    path = tmp_path / "ticket.pdf"
    monkeypatch.setattr(printer.sys, "platform", "linux")
    monkeypatch.setattr(printer.shutil, "which", lambda name: None)
    with pytest.raises(PrinterError, match="CUPS"):
        printer.send_to_printer(path)

    monkeypatch.setattr(printer.shutil, "which", lambda name: "/usr/bin/lp")
    monkeypatch.setattr(
        printer.subprocess,
        "run",
        lambda args, **kwargs: subprocess.CompletedProcess(args, 1, "", "lp: Destination not set"),
    )
    with pytest.raises(PrinterError, match="Destination not set"):
        printer.send_to_printer(path)
