"""Keep `taxtrace ui` running: start it when you log in and restart it if it stops (a macOS launchd agent).

`taxtrace service install` writes ~/Library/LaunchAgents/<LABEL>.plist and loads it; `uninstall` stops it and
removes the file. The page is then always at http://taxtrace.localhost:<port>/ (what an installed app opens),
and its output goes to ~/Library/Logs/taxtrace-ui.log.

A launchd agent doesn't read your shell profile, so install records what the page needs from yours: the
workspace (TAXTRACE_HOME) and a PATH that finds agy and Homebrew's ocrmypdf. No key or password is written to
the plist: Claude's key is read from the Keychain item named by `--keychain` when a question is asked.
"""

from __future__ import annotations

import os
import plistlib
import re
import subprocess
import sys
import time
from pathlib import Path

from . import workspace
from .web import APP_HOST, PORT

LABEL = "io.github.taxtrace.ui"
GONE_WAIT = 15  # seconds to wait for a replaced job to stop before loading the new one
SYSTEM_PATH = "/usr/bin:/bin:/usr/sbin:/sbin"


class ServiceError(RuntimeError):
    pass


def plist_path() -> Path:
    return Path.home() / "Library" / "LaunchAgents" / f"{LABEL}.plist"


def log_path() -> Path:
    return Path.home() / "Library" / "Logs" / "taxtrace-ui.log"


def service_path(current: str | None = None) -> str:
    """The PATH for the agent: the tool folders first, then the one you installed from, then the system's."""
    dirs = [str(Path.home() / ".local" / "bin"), "/opt/homebrew/bin", "/usr/local/bin"]  # agy, ocrmypdf
    dirs += (current if current is not None else os.environ.get("PATH", "")).split(os.pathsep)
    dirs += SYSTEM_PATH.split(os.pathsep)
    return os.pathsep.join(dict.fromkeys(d for d in dirs if d))


def definition(home: Path, port: int, models: str, keychain: str) -> dict:
    """The launchd job: this Python and taxtrace, the workspace by absolute path, no browser tab."""
    return {
        "Label": LABEL,
        "ProgramArguments": [sys.executable, "-m", "taxtrace.cli", "ui", "--no-open", "--port", str(port),
                             "--models", models, "--keychain", keychain],
        "RunAtLoad": True,       # at login
        "KeepAlive": True,       # and again if it exits
        "ThrottleInterval": 30,  # not in a tight loop when it can't start (the port is taken)
        "StandardOutPath": str(log_path()),
        "StandardErrorPath": str(log_path()),
        "EnvironmentVariables": {"PYTHONUNBUFFERED": "1", "TAXTRACE_HOME": str(home), "PATH": service_path()},
    }


def _domain() -> str:
    return f"gui/{os.getuid()}"


def _launchctl(*args: str, check: bool = True) -> subprocess.CompletedProcess:
    r = subprocess.run(["launchctl", *args], capture_output=True, text=True)
    if check and r.returncode:
        raise ServiceError(f"launchctl {' '.join(args)}: {(r.stderr or r.stdout).strip() or r.returncode}")
    return r


def _mac():
    if sys.platform != "darwin":
        raise ServiceError("`taxtrace service` sets up a macOS login item; elsewhere, start `taxtrace ui "
                           "--no-open` from your system's service manager (e.g. a systemd user unit)")


def _wait_gone(seconds: float = GONE_WAIT):
    """Until launchd has let go of the old job: bootout returns while a running page is still stopping, and a
    bootstrap then fails with "Bootstrap failed: 5: Input/output error"."""
    deadline = time.monotonic() + seconds
    while _launchctl("print", f"{_domain()}/{LABEL}", check=False).returncode == 0 and time.monotonic() < deadline:
        time.sleep(0.2)


def install(port: int = PORT, models: str = "claude,agy,local", keychain: str = "anthropic") -> str:
    """Write and load the agent (replacing one installed before); returns the page's address."""
    _mac()
    home = workspace.outside_git(workspace.home())
    path = plist_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    log_path().parent.mkdir(parents=True, exist_ok=True)
    _launchctl("bootout", f"{_domain()}/{LABEL}", check=False)  # an older version, if any
    _wait_gone()
    with path.open("wb") as f:
        plistlib.dump(definition(home, port, models, keychain), f)
    _launchctl("bootstrap", _domain(), str(path))
    return f"http://{APP_HOST}:{port}/"


def uninstall() -> bool:
    """Stop the agent and remove it; False if it wasn't installed."""
    _mac()
    path = plist_path()
    _launchctl("bootout", f"{_domain()}/{LABEL}", check=False)
    if not path.exists():
        return False
    path.unlink()
    return True


def status() -> dict:
    _mac()
    path = plist_path()
    info = {"installed": path.exists(), "running": False, "pid": None, "log": str(log_path()), "url": None}
    if info["installed"]:
        args = plistlib.loads(path.read_bytes()).get("ProgramArguments", [])
        if "--port" in args:
            info["url"] = f"http://{APP_HOST}:{args[args.index('--port') + 1]}/"
    r = _launchctl("print", f"{_domain()}/{LABEL}", check=False)
    # The job's own lines come first; nested sections (sockets, endpoints) have "state = active" of their own.
    state = re.search(r"^\s*state = (\w+)", r.stdout, re.M)
    pid = re.search(r"^\s*pid = (\d+)", r.stdout, re.M)
    info["running"] = bool(state and state.group(1) == "running")
    info["pid"] = int(pid.group(1)) if pid else None
    return info
