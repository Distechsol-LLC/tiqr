"""Hand a rendered PDF to this machine's default printer through the operating system.

There is no queue or driver here. The CLI and the API call this from a print renderer, so the
service only counts a print once the system has accepted the job.
"""

import os
import shutil
import subprocess
import sys
from pathlib import Path


class PrinterError(RuntimeError):
    """The operating system refused the job, or has no way to print."""


def sumatra_pdf() -> Path | None:
    """Find SumatraPDF, which prints silently at 100%."""
    found = shutil.which("SumatraPDF")
    if found is not None:
        return Path(found)
    for variable in ("LOCALAPPDATA", "ProgramFiles", "ProgramFiles(x86)"):
        base = os.environ.get(variable)
        if base and (candidate := Path(base, "SumatraPDF", "SumatraPDF.exe")).is_file():
            return candidate
    return None


def send_to_printer(path: Path) -> None:
    """Queue a PDF on the default printer."""
    if sys.platform == "win32":
        sumatra = sumatra_pdf()
        if sumatra is None:
            # Returns once the job is queued, so later printer failures go unreported.
            os.startfile(path, "print")  # noqa: S606 - the path is the PDF just rendered
            return
        result = subprocess.run(  # noqa: S603 - the executable and PDF are ours
            [sumatra, "-print-to-default", "-print-settings", "noscale", "-silent", str(path)],
            capture_output=True,
            check=False,
        )
        if result.returncode != 0:
            raise PrinterError(f"SumatraPDF could not print {path.name} (exit {result.returncode})")
        return
    lp = shutil.which("lp")
    if lp is None:
        raise PrinterError(
            "Printing needs the CUPS lp command; install CUPS or print the saved PDF"
        )
    # print-scaling=none keeps the page at 100%, which the QR code size depends on.
    result = subprocess.run(  # noqa: S603 - lp is resolved above and the PDF is ours
        [lp, "-o", "print-scaling=none", str(path)], capture_output=True, text=True, check=False
    )
    if result.returncode != 0:
        detail = result.stderr.strip() or f"lp exited with status {result.returncode}"
        raise PrinterError(f"Printing failed: {detail}")
