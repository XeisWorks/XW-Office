"""Regression tests for the Windows desktop bootstrap."""

from __future__ import annotations

import importlib.util
from importlib.machinery import SourceFileLoader
from pathlib import Path
from types import SimpleNamespace

import pytest


def _load_bootstrap_module():
    script = Path(__file__).parents[2] / "scripts" / "xw_office_gui.pyw"
    loader = SourceFileLoader("xw_office_gui_bootstrap", str(script))
    spec = importlib.util.spec_from_file_location(loader.name, script, loader=loader)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize("check_running_only", [False, True])
def test_automatic_update_excludes_pythonw_redirector_and_interpreter(
    monkeypatch, tmp_path, check_running_only
):
    bootstrap = _load_bootstrap_module()
    update_script = tmp_path / "scripts" / "update_xw_office.ps1"
    update_script.parent.mkdir()
    update_script.touch()
    captured: dict[str, object] = {}

    def fake_run(command, **kwargs):
        captured["command"] = command
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(bootstrap.os, "getpid", lambda: 22076)
    monkeypatch.setattr(bootstrap.os, "getppid", lambda: 22240)
    monkeypatch.setattr(bootstrap.subprocess, "run", fake_run)

    assert bootstrap._run_updater(tmp_path, check_running_only=check_running_only) == 0
    command = captured["command"]
    assert command[command.index("-ExcludeProcessId") + 1] == "22076,22240"
    assert ("-CheckRunningOnly" in command) == check_running_only


def test_updater_parses_multiple_excluded_process_ids():
    script = (Path(__file__).parents[2] / "scripts" / "update_xw_office.ps1").read_text(
        encoding="utf-8"
    )

    assert "$ExcludeProcessId -split ','" in script
    assert "$_.ProcessId -notin $ExcludedProcessIds" in script


@pytest.mark.parametrize("result", [1, 2, None])
def test_update_offer_is_skipped_when_running_check_is_not_clear(monkeypatch, tmp_path, result):
    bootstrap = _load_bootstrap_module()
    monkeypatch.delenv("XW_OFFICE_SKIP_UPDATE_CHECK", raising=False)
    monkeypatch.setattr(bootstrap, "_update_available", lambda _repo: True)
    calls = []

    def run_updater(_repo, *, check_running_only=False):
        calls.append(check_running_only)
        return result

    monkeypatch.setattr(bootstrap, "_run_updater", run_updater)
    monkeypatch.setattr(bootstrap, "_ask_update_now", lambda: calls.append("prompt"))

    bootstrap._maybe_offer_update(tmp_path)

    assert calls == [True]


@pytest.mark.parametrize("result", [0, 1, 2])
def test_confirmed_update_distinguishes_deferral_from_failure(monkeypatch, tmp_path, result):
    bootstrap = _load_bootstrap_module()
    monkeypatch.delenv("XW_OFFICE_SKIP_UPDATE_CHECK", raising=False)
    monkeypatch.setattr(bootstrap, "_update_available", lambda _repo: True)
    monkeypatch.setattr(bootstrap, "_ask_update_now", lambda: True)
    monkeypatch.setattr(
        bootstrap, "_run_updater", lambda _repo, check_running_only=False: 0 if check_running_only else result
    )
    message_icons = []
    monkeypatch.setattr(bootstrap, "_show_message", lambda _title, _message, icon: message_icons.append(icon))

    bootstrap._maybe_offer_update(tmp_path)

    assert message_icons == {
        0: [],
        1: [bootstrap.MB_ICONERROR],
        2: [bootstrap.MB_ICONINFORMATION],
    }[result]
