"""Regression tests for the Windows desktop bootstrap."""

from __future__ import annotations

import importlib.util
from pathlib import Path
from types import SimpleNamespace


def _load_bootstrap_module():
    script = Path(__file__).parents[2] / "scripts" / "xw_office_gui.pyw"
    spec = importlib.util.spec_from_file_location("xw_office_gui_bootstrap", script)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_automatic_update_excludes_pythonw_redirector_and_interpreter(monkeypatch, tmp_path):
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

    assert bootstrap._run_update(tmp_path) is True
    command = captured["command"]
    assert command[command.index("-ExcludeProcessId") + 1] == "22076,22240"


def test_updater_parses_multiple_excluded_process_ids():
    script = (Path(__file__).parents[2] / "scripts" / "update_xw_office.ps1").read_text(
        encoding="utf-8"
    )

    assert "$ExcludeProcessId -split ','" in script
    assert "$_.ProcessId -notin $ExcludedProcessIds" in script
