"""Auto-update mechanism: git pull + pip install at app start."""
from __future__ import annotations

import logging
import subprocess
import sys
from dataclasses import dataclass

from xw_office.core.app_paths import find_repo_root

logger = logging.getLogger(__name__)


@dataclass
class UpdateResult:
    updated: bool = False
    needs_restart: bool = False
    error: str | None = None


def check_and_update(*, enabled: bool = True) -> UpdateResult:
    """Check for updates from origin/main and apply if available."""
    if not enabled:
        return UpdateResult()

    repo = find_repo_root()
    try:
        branch = subprocess.run(
            ["git", "branch", "--show-current"],
            cwd=str(repo), capture_output=True, text=True, timeout=10,
        )
        current_branch = branch.stdout.strip()
        if branch.returncode != 0:
            return UpdateResult(error="Aktueller Git-Branch konnte nicht ermittelt werden.")
        if current_branch != "main":
            return UpdateResult(
                error=(
                    f"Auto-Update abgebrochen: Aktueller Branch ist '{current_branch or 'DETACHED'}'. "
                    "Bitte lokale Aenderungen sichern, dann 'git switch main' und "
                    "'git pull --ff-only origin main' ausfuehren."
                )
            )

        subprocess.run(
            ["git", "fetch", "origin", "main"],
            cwd=str(repo), capture_output=True, timeout=15,
        )
        diff = subprocess.run(
            ["git", "diff", "HEAD", "origin/main", "--quiet"],
            cwd=str(repo), capture_output=True, timeout=10,
        )
        if diff.returncode == 0:
            logger.info("No updates available.")
            return UpdateResult()

        logger.info("Updates found, pulling...")
        pull = subprocess.run(
            ["git", "pull", "--ff-only", "origin", "main"],
            cwd=str(repo), capture_output=True, timeout=30,
        )
        if pull.returncode != 0:
            return UpdateResult(
                error="Update nicht als Fast-Forward moeglich. Bitte Git-Stand manuell pruefen."
            )

        req_diff = subprocess.run(
            ["git", "diff", "HEAD~1", "HEAD", "--", "requirements.txt", "pyproject.toml"],
            cwd=str(repo), capture_output=True, timeout=10,
        )
        if req_diff.stdout:
            logger.info("Dependencies changed, running pip install...")
            subprocess.run(
                [sys.executable, "-m", "pip", "install", "-e", ".[dev]", "--quiet"],
                cwd=str(repo), capture_output=True, timeout=120,
            )

        return UpdateResult(updated=True, needs_restart=True)

    except Exception as exc:
        logger.warning("Auto-update failed: %s", exc)
        return UpdateResult(error=str(exc))
