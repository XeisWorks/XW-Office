from __future__ import annotations

from pathlib import Path
from subprocess import CompletedProcess

from xw_studio.core import updater


def test_update_refuses_non_main_branch(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(updater, "find_repo_root", lambda: tmp_path)
    calls: list[list[str]] = []

    def fake_run(command: list[str], **kwargs: object) -> CompletedProcess[str]:
        calls.append(command)
        return CompletedProcess(command, 0, stdout="agent/performance\n", stderr="")

    monkeypatch.setattr(updater.subprocess, "run", fake_run)

    result = updater.check_and_update()

    assert result.updated is False
    assert result.error is not None
    assert "git switch main" in result.error
    assert calls == [["git", "branch", "--show-current"]]


def test_update_uses_fast_forward_pull(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(updater, "find_repo_root", lambda: tmp_path)
    calls: list[list[str]] = []

    def fake_run(command: list[str], **kwargs: object) -> CompletedProcess[bytes] | CompletedProcess[str]:
        calls.append(command)
        if command == ["git", "branch", "--show-current"]:
            return CompletedProcess(command, 0, stdout="main\n", stderr="")
        if command[:2] == ["git", "diff"] and "--quiet" in command:
            return CompletedProcess(command, 1, stdout=b"", stderr=b"")
        return CompletedProcess(command, 0, stdout=b"", stderr=b"")

    monkeypatch.setattr(updater.subprocess, "run", fake_run)

    result = updater.check_and_update()

    assert result.updated is True
    assert ["git", "pull", "--ff-only", "origin", "main"] in calls
