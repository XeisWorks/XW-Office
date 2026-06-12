"""Resolve shared OneDrive paths across Windows user profiles."""
from __future__ import annotations

import os
from pathlib import Path, PureWindowsPath


def resolve_shared_path(value: str) -> str:
    """Return an existing local equivalent for a shared OneDrive path."""
    raw = str(value or "").strip()
    if not raw:
        return ""
    expanded = os.path.expandvars(os.path.expanduser(raw))
    original = Path(expanded)
    if original.exists():
        return expanded

    windows_path = PureWindowsPath(expanded)
    parts = windows_path.parts
    anchor_index = next(
        (index for index, part in enumerate(parts) if part.casefold().startswith("onedrive")),
        None,
    )
    if anchor_index is None:
        return expanded

    relative_parts = parts[anchor_index + 1 :]
    roots: list[Path] = []
    for variable in ("OneDriveCommercial", "OneDriveConsumer", "OneDrive"):
        configured = str(os.getenv(variable) or "").strip()
        if configured:
            roots.append(Path(os.path.expandvars(os.path.expanduser(configured))))

    user_profile = str(os.getenv("USERPROFILE") or "").strip()
    if user_profile:
        roots.append(Path(user_profile) / parts[anchor_index])

    seen: set[str] = set()
    for root in roots:
        marker = str(root).casefold()
        if marker in seen:
            continue
        seen.add(marker)
        candidate = root.joinpath(*relative_parts)
        if candidate.exists():
            return str(candidate)
    return expanded
