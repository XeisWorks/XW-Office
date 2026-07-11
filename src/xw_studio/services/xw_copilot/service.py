"""Persisted settings, templates and audit log for Outlook add-in integration."""
from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import re
from pathlib import Path

from xw_studio.repositories.settings_kv import SettingKvRepository

logger = logging.getLogger(__name__)

_CONFIG_KEY = "xw_copilot.config"
_TEMPLATES_KEY = "xw_copilot.templates"
_AUDIT_KEY = "xw_copilot.audit_log"
_MAX_AUDIT_ENTRIES = 100


@dataclass(frozen=True)
class AuditEntry:
    timestamp: str
    action: str
    correlation_id: str
    accepted: bool
    mode: str


@dataclass(frozen=True)
class XWCopilotConfig:
    enabled: bool = False
    mode: str = "dry_run"
    outlook_tenant_id: str = ""
    outlook_client_id: str = ""
    mailbox_address: str = ""
    webhook_url: str = ""
    default_project: str = ""
    allowed_ips: str = ""


class XWCopilotService:
    """Read/write XW-Copilot settings and prompt blocks via SettingKvRepository."""

    def __init__(self, settings_repo: SettingKvRepository | None = None) -> None:
        self._repo = settings_repo

    def has_storage(self) -> bool:
        return self._repo is not None

    def load_config(self) -> XWCopilotConfig:
        if self._repo is None:
            return XWCopilotConfig()
        raw = self._repo.get_value_json(_CONFIG_KEY)
        if not raw:
            return XWCopilotConfig()
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            logger.warning("Invalid JSON in %s", _CONFIG_KEY)
            return XWCopilotConfig()
        if not isinstance(data, dict):
            return XWCopilotConfig()
        return XWCopilotConfig(
            enabled=bool(data.get("enabled", False)),
            mode=str(data.get("mode") or "dry_run"),
            outlook_tenant_id=str(data.get("outlook_tenant_id") or ""),
            outlook_client_id=str(data.get("outlook_client_id") or ""),
            mailbox_address=str(data.get("mailbox_address") or ""),
            webhook_url=str(data.get("webhook_url") or ""),
            default_project=str(data.get("default_project") or ""),
                allowed_ips=str(data.get("allowed_ips") or ""),
        )

    def save_config(self, config: XWCopilotConfig) -> None:
        if self._repo is None:
            return
        payload = {
            "enabled": config.enabled,
            "mode": config.mode,
            "outlook_tenant_id": config.outlook_tenant_id,
            "outlook_client_id": config.outlook_client_id,
            "mailbox_address": config.mailbox_address,
            "webhook_url": config.webhook_url,
            "default_project": config.default_project,
                "allowed_ips": config.allowed_ips,
        }
        self._repo.set_value_json(_CONFIG_KEY, json.dumps(payload, ensure_ascii=False, indent=2))

    def load_templates(self) -> list[dict[str, str]]:
        if self._repo is None:
            return []
        raw = self._repo.get_value_json(_TEMPLATES_KEY)
        if not raw:
            return []
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            logger.warning("Invalid JSON in %s", _TEMPLATES_KEY)
            return []
        if not isinstance(data, list):
            return []
        rows: list[dict[str, str]] = []
        for item in data:
            if not isinstance(item, dict):
                continue
            rows.append(
                {
                    "name": str(item.get("name") or ""),
                    "kind": str(item.get("kind") or "snippet"),
                    "content": str(item.get("content") or ""),
                }
            )
        return rows

    def save_templates(self, templates: list[dict[str, str]]) -> None:
        if self._repo is None:
            return
        clean: list[dict[str, str]] = []
        for item in templates:
            if not isinstance(item, dict):
                continue
            clean.append(
                {
                    "name": str(item.get("name") or ""),
                    "kind": str(item.get("kind") or "snippet"),
                    "content": str(item.get("content") or ""),
                }
            )
        self._repo.set_value_json(_TEMPLATES_KEY, json.dumps(clean, ensure_ascii=False, indent=2))

    # ------------------------------------------------------------------
    # Audit log
    # ------------------------------------------------------------------

    def append_audit_entry(self, entry: AuditEntry) -> None:
        """Append one audit entry and keep at most _MAX_AUDIT_ENTRIES entries."""
        if self._repo is None:
            return
        entries = self._load_raw_audit()
        entries.append(asdict(entry))
        if len(entries) > _MAX_AUDIT_ENTRIES:
            entries = entries[-_MAX_AUDIT_ENTRIES:]
        self._repo.set_value_json(_AUDIT_KEY, json.dumps(entries, ensure_ascii=False))

    def load_audit_entries(self) -> list[AuditEntry]:
        """Return stored audit entries, newest first."""
        raw = self._load_raw_audit()
        result: list[AuditEntry] = []
        for item in reversed(raw):
            if not isinstance(item, dict):
                continue
            result.append(
                AuditEntry(
                    timestamp=str(item.get("timestamp") or ""),
                    action=str(item.get("action") or ""),
                    correlation_id=str(item.get("correlation_id") or ""),
                    accepted=bool(item.get("accepted", False)),
                    mode=str(item.get("mode") or "dry_run"),
                )
            )
        return result

    def clear_audit_log(self) -> None:
        if self._repo is None:
            return
        self._repo.set_value_json(_AUDIT_KEY, "[]")

    def _load_raw_audit(self) -> list[dict[str, object]]:
        if self._repo is None:
            return []
        raw = self._repo.get_value_json(_AUDIT_KEY)
        if not raw:
            return []
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            logger.warning("Invalid JSON in %s", _AUDIT_KEY)
            return []
        if not isinstance(data, list):
            return []
        return [item for item in data if isinstance(item, dict)]

    @staticmethod
    def utc_now() -> str:
        return datetime.now(tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")

    # ------------------------------------------------------------------
    # Template rendering
    # ------------------------------------------------------------------

    @staticmethod
    def render_template(content: str, variables: dict[str, str]) -> str:
        """Substitute ``{{key}}`` placeholders in *content* with *variables* values.

        Unknown keys are left unchanged so partial renders are safe.
        """
        def _replacer(match: re.Match[str]) -> str:
            key = match.group(1).strip()
            return variables.get(key, match.group(0))

        return re.sub(r"\{\{([^}]+)\}\}", _replacer, content)

    # ------------------------------------------------------------------
    # JSON Schema export
    # ------------------------------------------------------------------

    @staticmethod
    def export_request_schema(path: Path) -> None:
        """Write XWCopilotRequest JSON Schema to *path* (created/overwritten)."""
        from xw_studio.services.xw_copilot.contracts import XWCopilotRequest

        schema = XWCopilotRequest.model_json_schema()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(schema, indent=2, ensure_ascii=False), encoding="utf-8")
        logger.info("XWCopilotRequest schema exported to %s", path)
