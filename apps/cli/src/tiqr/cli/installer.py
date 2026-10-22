"""Platform steps of `tiqr install`: administrator check, firewall, service and health check.

Each step runs the operating system's own tool (netsh, ufw, firewall-cmd, systemctl, useradd,
icacls, WinSW) with a fixed argument list, so every command can be read where it is built.
"""

import ctypes
import json
import os
import shutil
import socket
import subprocess
import sys
import time
import urllib.request
from pathlib import Path
from xml.sax.saxutils import escape

from tiqr.core.settings import BRANDING_FILE

SERVICE_NAME = "TiQR"
SERVICE_USER = "tiqr"
UNIT_PATH = Path("/etc/systemd/system/tiqr.service")
# WinSW reads its configuration from the wrapper's base name, so the two sit side by side.
WINSW_NAME = "tiqr-service.exe"
WINSW_CONFIG = "tiqr-service.xml"


def is_administrator() -> bool:
    if sys.platform == "win32":
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    return os.geteuid() == 0


def lan_address() -> str:
    """The address this machine routes outward from; a UDP connect sends nothing."""
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as probe:
        try:
            probe.connect(("10.255.255.255", 1))
        except OSError:
            return "127.0.0.1"
        return str(probe.getsockname()[0])


def _run(argv: list[str]) -> str:
    result = subprocess.run(argv, capture_output=True, text=True, check=False)  # noqa: S603 - fixed tools
    if result.returncode:
        raise RuntimeError(f"{argv[0]} failed: {(result.stderr or result.stdout).strip()}")
    return result.stdout


def _succeeds(argv: list[str]) -> bool:
    return subprocess.run(argv, capture_output=True, check=False).returncode == 0  # noqa: S603 - fixed tools


def _output(argv: list[str]) -> str:
    """A status query: its output, or nothing when the tool is missing or fails."""
    if shutil.which(argv[0]) is None:
        return ""
    return subprocess.run(argv, capture_output=True, text=True, check=False).stdout  # noqa: S603 - fixed tools


def open_firewall(port: int) -> str:
    """Allow inbound TCP on the port through the firewall that is active; say what was done."""
    if sys.platform == "win32":
        # A rule name without spaces avoids quoting problems on the command line.
        rule = f"TiQR-{port}"
        # The rule may not exist yet, so a failure here is expected and ignored.
        delete = ["netsh", "advfirewall", "firewall", "delete", "rule", f"name={rule}"]
        subprocess.run(delete, capture_output=True, check=False)  # noqa: S603 - fixed tool
        _run(
            [
                "netsh",
                "advfirewall",
                "firewall",
                "add",
                "rule",
                f"name={rule}",
                "dir=in",
                "action=allow",
                "protocol=TCP",
                f"localport={port}",
            ]
        )
        return f"Windows Firewall allows TCP {port}"
    if "Status: active" in _output(["ufw", "status"]):
        _run(["ufw", "allow", f"{port}/tcp"])
        return f"ufw allows TCP {port}"
    if _output(["firewall-cmd", "--state"]).strip() == "running":
        _run(["firewall-cmd", "--permanent", f"--add-port={port}/tcp"])
        _run(["firewall-cmd", "--reload"])
        return f"firewalld allows TCP {port}"
    return "No active firewall found; nothing to open"


def winsw_config(executable: Path, home: Path) -> str:
    return f"""<service>
  <id>{SERVICE_NAME}</id>
  <name>{SERVICE_NAME}</name>
  <description>TiQR ticket server</description>
  <executable>{escape(str(executable))}</executable>
  <arguments>serve</arguments>
  <env name="TIQR_HOME" value="{escape(str(home))}"/>
  <startmode>Automatic</startmode>
  <onfailure action="restart" delay="5 sec"/>
  <onfailure action="restart" delay="30 sec"/>
  <onfailure action="restart" delay="1 min"/>
  <resetfailure>1 hour</resetfailure>
  <logpath>{escape(str(home / "logs"))}</logpath>
  <log mode="roll"/>
  <serviceaccount>
    <username>NT SERVICE\\{SERVICE_NAME}</username>
    <allowservicelogon>true</allowservicelogon>
  </serviceaccount>
</service>
"""


def systemd_unit(executable: Path, home: Path) -> str:
    return f"""[Unit]
Description=TiQR ticket server
After=network-online.target
Wants=network-online.target
StartLimitIntervalSec=0

[Service]
Type=simple
User={SERVICE_USER}
Group={SERVICE_USER}
Environment="TIQR_HOME={home}"
ExecStart="{executable}" serve
Restart=on-failure
RestartSec=5s
NoNewPrivileges=yes
ProtectSystem=strict
ReadWritePaths={home}
ProtectHome=yes
PrivateTmp=yes

[Install]
WantedBy=multi-user.target
"""


def _install_windows_service(executable: Path, home: Path, wrapper: Path) -> None:
    target = home / WINSW_NAME
    if target.exists():
        # Stop and remove the old service first, so its wrapper is not in use when replaced.
        subprocess.run([str(target), "stop"], capture_output=True, check=False)  # noqa: S603 - our wrapper
        subprocess.run([str(target), "uninstall"], capture_output=True, check=False)  # noqa: S603 - our wrapper
    shutil.copyfile(wrapper, target)
    (home / WINSW_CONFIG).write_text(winsw_config(executable, home), encoding="utf-8")
    _run([str(target), "install"])
    # The virtual service account exists only once the service is installed.
    _run(["icacls", str(home), "/grant", f"NT SERVICE\\{SERVICE_NAME}:(OI)(CI)M"])
    _run([str(target), "start"])


def _install_linux_service(executable: Path, home: Path) -> None:
    if not _succeeds(["id", "-u", SERVICE_USER]):
        _run(
            [
                "useradd",
                "--system",
                "--home-dir",
                str(home),
                "--shell",
                "/usr/sbin/nologin",
                SERVICE_USER,
            ]
        )
    # The service writes its database, key and PDFs here. The program itself stays root-owned.
    owner = f"{SERVICE_USER}:{SERVICE_USER}"
    _run(["chown", owner, str(home)])
    for entry in home.iterdir():
        if entry.name not in (executable.name, BRANDING_FILE):
            _run(["chown", "-R", owner, str(entry)])
    UNIT_PATH.write_text(systemd_unit(executable, home), encoding="utf-8")
    _run(["systemctl", "daemon-reload"])
    _run(["systemctl", "enable", "tiqr.service"])
    # Restart rather than start, so a reinstall picks up the new unit and executable.
    _run(["systemctl", "restart", "tiqr.service"])


def register_service(executable: Path, home: Path, source: Path) -> str:
    """Install and start TiQR as a boot-time service running `executable` in place."""
    if sys.platform == "win32":
        wrapper = source / WINSW_NAME
        if not wrapper.exists():
            raise RuntimeError(f"{WINSW_NAME} (WinSW) is not in {source}; the service needs it")
        _install_windows_service(executable, home, wrapper)
        return f'Windows service "{SERVICE_NAME}" is running'
    _install_linux_service(executable, home)
    return "systemd unit tiqr.service is running"


def wait_until_healthy(host: str, port: int, timeout: float = 30.0) -> None:
    """Poll the server's health endpoint until it reports ok, or fail after the timeout."""
    # An unspecified bind address is not reachable as a destination; probe the loopback instead.
    probe = "127.0.0.1" if host in ("", "0.0.0.0", "::") else host  # noqa: S104 - a comparison
    if ":" in probe:
        probe = f"[{probe}]"
    url = f"http://{probe}:{port}/api/health"
    deadline = time.monotonic() + timeout
    while True:
        try:
            with urllib.request.urlopen(url, timeout=3) as response:
                if json.loads(response.read()).get("status") == "ok":
                    return
        except OSError, ValueError:
            pass
        if time.monotonic() >= deadline:
            raise RuntimeError(f"{url} did not report healthy within {timeout:.0f} seconds")
        time.sleep(1)
