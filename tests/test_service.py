"""The login item for `taxtrace ui`, with launchctl and the home folder faked. Every value here is made up."""

from __future__ import annotations

import plistlib
import subprocess
import sys

import pytest

from taxtrace import cli, service

SECRET = "sk-ant-made-up-key-0000"


@pytest.fixture
def launchd(tmp_path, monkeypatch):
    """A fake home, workspace and launchctl: records the calls, reports the job as running once bootstrapped."""
    monkeypatch.setattr(service.Path, "home", lambda: tmp_path)
    monkeypatch.setattr(service.sys, "platform", "darwin")
    monkeypatch.setenv("TAXTRACE_HOME", str(tmp_path / "Returns"))
    monkeypatch.setenv("PATH", "/made/up/bin:/usr/bin")
    monkeypatch.setenv("ANTHROPIC_API_KEY", SECRET)
    calls, loaded = [], []

    def run(cmd, **kwargs):
        calls.append(cmd[1:])
        if cmd[1] == "bootstrap":
            loaded.append(True)
        # Shaped like launchctl print: nested sections have states of their own after the job's.
        out = ("\tstate = running\n\tpid = 4242\n\tendpoints = {\n\t\tstate = active\n\t}\n"
               if cmd[1] == "print" and loaded else "")
        return subprocess.CompletedProcess(cmd, 0 if out or cmd[1] != "print" else 113, out, "")
    monkeypatch.setattr(service.subprocess, "run", run)
    return calls


def test_install_writes_a_login_item_for_this_workspace(launchd, tmp_path, capsys):
    assert cli.main(["service", "install", "--port", "8800", "--models", "claude,local"]) == 0
    assert "http://taxtrace.localhost:8800/" in capsys.readouterr().out
    raw = service.plist_path().read_bytes()
    job = plistlib.loads(raw)
    assert job["Label"] == service.LABEL and job["RunAtLoad"] and job["KeepAlive"]
    assert job["ProgramArguments"] == [sys.executable, "-m", "taxtrace.cli", "ui", "--no-open", "--port", "8800",
                                       "--models", "claude,local", "--keychain", "anthropic"]
    env = job["EnvironmentVariables"]
    assert env["TAXTRACE_HOME"] == str((tmp_path / "Returns").resolve())
    assert set(env) == {"PYTHONUNBUFFERED", "TAXTRACE_HOME", "PATH"}
    assert SECRET.encode() not in raw and b"ANTHROPIC_API_KEY" not in raw
    assert [c[0] for c in launchd] == ["bootout", "print", "bootstrap"]
    assert service.status() == {"installed": True, "running": True, "pid": 4242, "log": str(service.log_path()),
                                "url": "http://taxtrace.localhost:8800/"}
    cli.main(["service", "status"])
    assert "running (pid 4242)" in capsys.readouterr().out
    assert cli.main(["service", "uninstall"]) == 0
    assert not service.plist_path().exists() and "Removed" in capsys.readouterr().out
    cli.main(["service", "status"])
    assert "Not installed" in capsys.readouterr().out


def test_the_path_finds_agy_homebrew_and_the_install_shells_tools(launchd, tmp_path):
    service.install()
    dirs = plistlib.loads(service.plist_path().read_bytes())["EnvironmentVariables"]["PATH"].split(":")
    assert dirs[:3] == [str(tmp_path / ".local" / "bin"), "/opt/homebrew/bin", "/usr/local/bin"]
    assert "/made/up/bin" in dirs and "/bin" in dirs
    assert len(dirs) == len(set(dirs))


def test_uninstall_when_not_installed(launchd, capsys):
    assert cli.main(["service", "uninstall"]) == 0
    assert "Not installed" in capsys.readouterr().out


def test_a_reinstall_waits_for_the_old_page_to_stop(tmp_path, monkeypatch):
    monkeypatch.setattr(service.Path, "home", lambda: tmp_path)
    monkeypatch.setattr(service.sys, "platform", "darwin")
    monkeypatch.setattr(service.time, "sleep", lambda s: None)
    monkeypatch.setenv("TAXTRACE_HOME", str(tmp_path / "Returns"))
    calls, stopping = [], [2]  # launchd still lists the old job twice after bootout

    def run(cmd, **kwargs):
        calls.append(cmd[1])
        if cmd[1] == "print":
            stopping[0] -= 1
            return subprocess.CompletedProcess(cmd, 0 if stopping[0] >= 0 else 113, "", "")
        if cmd[1] == "bootstrap" and stopping[0] >= 0:
            return subprocess.CompletedProcess(cmd, 5, "", "Bootstrap failed: 5: Input/output error")
        return subprocess.CompletedProcess(cmd, 0, "", "")
    monkeypatch.setattr(service.subprocess, "run", run)
    service.install()
    assert calls == ["bootout", "print", "print", "print", "bootstrap"]


def test_install_needs_a_mac_and_a_workspace_outside_git(launchd, tmp_path, monkeypatch, capsys):
    (tmp_path / "Repo" / ".git").mkdir(parents=True)
    monkeypatch.setenv("TAXTRACE_HOME", str(tmp_path / "Repo" / "data"))
    assert cli.main(["service", "install"]) == 1
    assert "git" in capsys.readouterr().err and not service.plist_path().exists()
    monkeypatch.setattr(service.sys, "platform", "linux")
    assert cli.main(["service", "status"]) == 1
    assert "macOS" in capsys.readouterr().err
