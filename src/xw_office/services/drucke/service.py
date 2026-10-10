"""Dedicated print@ mailbox queue with XW-Flow synchronization."""
from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import json
import logging
import uuid
from typing import Any

from xw_office.repositories.settings_kv import SettingKvRepository
from xw_office.services.drucke.xw_flow_client import FlowPrintEmailCase, XwFlowPrintClient
from xw_office.services.mailing.graph_client import GraphMailClient
from xw_office.services.secrets.service import SecretService

logger = logging.getLogger(__name__)
_CASES_KEY = "daily_business.offene_drucke.cases"
_DONE_KEY = "daily_business.offene_drucke.done"
_SOURCE_GRAPH = "graph_mail"
_SOURCE_FLOW = "xw_flow_share"
_MAILBOX = "print@xeisworks.at"


@dataclass(frozen=True)
class PrintCase:
    id: str
    title: str
    detail: str
    received_at: str
    source_type: str
    source_id: str


class OffeneDruckeService:
    def __init__(self, settings_repo: SettingKvRepository | None, secrets: SecretService, flow_prints: XwFlowPrintClient | None = None) -> None:
        self._repo = settings_repo
        self._secrets = secrets
        self._flow_prints = flow_prints

    def open_count(self) -> int:
        return len(self.load_open_cases())

    def load_open_cases(self) -> list[PrintCase]:
        done = self._load_done()
        return [case for case in self._load_cases() if case.id not in done]

    def refresh_count_from_graph_silent(self, *, lookback_days: int = 30, max_items: int = 150) -> int:
        try:
            return len(self.refresh_from_graph(lookback_days=lookback_days, max_items=max_items, allow_interactive_auth=False))
        except Exception as exc:  # noqa: BLE001
            logger.warning("Open-print refresh failed: %s", exc)
            return self.open_count()

    def refresh_from_graph(self, *, lookback_days: int = 30, max_items: int = 150, allow_interactive_auth: bool = True) -> list[PrintCase]:
        existing = self._load_cases()
        graph_cases = self._fetch_graph_cases(lookback_days, max_items, allow_interactive_auth)
        self._complete_flow_completed_emails(graph_cases, allow_interactive_auth)
        flow_cases = self._refresh_flow_cases(existing)
        self._save_cases(flow_cases + graph_cases)
        open_cases = self.load_open_cases()
        self._sync_email_snapshot(open_cases)
        return open_cases

    def mark_done(self, case_id: str, *, done: bool) -> None:
        case = next((item for item in self._load_cases() if item.id == case_id), None)
        if case is None:
            raise ValueError("Druckauftrag nicht gefunden")
        if case.source_type == _SOURCE_FLOW and self._flow_prints is not None:
            self._flow_prints.set_status(case.source_id, completed=done)
        elif case.source_type == _SOURCE_GRAPH and done:
            client = self._graph_client(write=True)
            if client is None:
                raise RuntimeError("MS Graph ist nicht konfiguriert")
            client.mark_message_followup_complete(case.source_id)
        done_ids = self._load_done()
        if done: done_ids.add(case.id)
        else: done_ids.discard(case.id)
        self._save_done(done_ids)
        self._sync_email_snapshot(self.load_open_cases())

    def _fetch_graph_cases(self, days: int, top: int, allow_interactive_auth: bool) -> list[PrintCase]:
        client = self._graph_client()
        if client is None or (not allow_interactive_auth and not client.has_silent_token()):
            return [case for case in self._load_cases() if case.source_type == _SOURCE_GRAPH]
        try:
            messages = client.list_inbox_messages(days=max(1, days), top=max(1, min(top, 200)), include_body=False)
        except Exception as exc:  # noqa: BLE001
            logger.warning("MS Graph fetch failed for open prints: %s", exc)
            return [case for case in self._load_cases() if case.source_type == _SOURCE_GRAPH]
        cases: list[PrintCase] = []
        for item in messages:
            message_id = str(item.get("id") or "").strip()
            if not message_id:
                continue
            sender_obj = item.get("from") if isinstance(item.get("from"), dict) else {}
            address = sender_obj.get("emailAddress") if isinstance(sender_obj.get("emailAddress"), dict) else {}
            sender = str(address.get("address") or address.get("name") or "").strip()
            cases.append(PrintCase(id=f"mail:{message_id}", title=str(item.get("subject") or "E-Mail ohne Betreff").strip(), detail=str(item.get("bodyPreview") or sender).strip(), received_at=str(item.get("receivedDateTime") or "").strip(), source_type=_SOURCE_GRAPH, source_id=message_id))
        return cases

    def _complete_flow_completed_emails(self, cases: list[PrintCase], allow_interactive_auth: bool) -> None:
        if self._flow_prints is None or not self._flow_prints.is_configured() or not allow_interactive_auth:
            return
        try: completed = self._flow_prints.fetch_completed_email_request_ids()
        except Exception as exc:  # noqa: BLE001
            logger.warning("XW-Flow print completion refresh failed: %s", exc); return
        if not completed: return
        client = self._graph_client(write=True)
        if client is None: return
        done = self._load_done()
        for case in cases:
            if str(self._email_request_id(case.source_id)) not in completed: continue
            try:
                client.mark_message_followup_complete(case.source_id)
                done.add(case.id)
            except Exception as exc:  # noqa: BLE001
                logger.warning("Could not complete print mail in Graph: %s", exc)
        self._save_done(done)

    def _refresh_flow_cases(self, existing: list[PrintCase]) -> list[PrintCase]:
        previous = [case for case in existing if case.source_type == _SOURCE_FLOW]
        if self._flow_prints is None or not self._flow_prints.is_configured(): return previous
        try: remote = self._flow_prints.fetch_open_cases()
        except Exception as exc:  # noqa: BLE001
            logger.warning("XW-Flow print refresh failed: %s", exc); return previous
        return [PrintCase(id=f"flow:{item.id}", title=item.title, detail=item.body_text or item.source_url, received_at=item.created_at, source_type=_SOURCE_FLOW, source_id=item.id) for item in remote]

    def _sync_email_snapshot(self, cases: list[PrintCase]) -> None:
        if self._flow_prints is None or not self._flow_prints.is_configured(): return
        try: self._flow_prints.sync_print_email_cases([FlowPrintEmailCase(external_id=case.source_id, title=case.title, received_at=case.received_at) for case in cases if case.source_type == _SOURCE_GRAPH])
        except Exception as exc: logger.warning("XW-Flow print-mail snapshot failed: %s", exc)

    @staticmethod
    def _email_request_id(external_id: str) -> uuid.UUID:
        return uuid.uuid5(uuid.NAMESPACE_URL, f"xw-flow:print-email:{external_id}")

    def _graph_client(self, *, write: bool = False) -> GraphMailClient | None:
        tenant_id = self._secrets.get_secret("MS_GRAPH_TENANT_ID")
        client_id = self._secrets.get_secret("MS_GRAPH_CLIENT_ID")
        if not tenant_id or not client_id: return None
        scopes = ["Mail.Read", "Mail.Read.Shared"]
        if write: scopes.extend(["Mail.ReadWrite", "Mail.ReadWrite.Shared"])
        return GraphMailClient(tenant_id=tenant_id, client_id=client_id, mailbox_user=_MAILBOX, scopes=scopes)

    def _load_cases(self) -> list[PrintCase]:
        raw = self._repo.get_value_json(_CASES_KEY) if self._repo else None
        try: values = json.loads(raw) if raw else []
        except json.JSONDecodeError: values = []
        return [PrintCase(**value) for value in values if isinstance(value, dict) and all(key in value for key in ("id", "title", "detail", "received_at", "source_type", "source_id"))]

    def _save_cases(self, cases: list[PrintCase]) -> None:
        if self._repo: self._repo.set_value_json(_CASES_KEY, json.dumps([asdict(case) for case in cases], ensure_ascii=False))

    def _load_done(self) -> set[str]:
        raw = self._repo.get_value_json(_DONE_KEY) if self._repo else None
        try: return {str(item) for item in (json.loads(raw) if raw else [])}
        except json.JSONDecodeError: return set()

    def _save_done(self, ids: set[str]) -> None:
        if self._repo: self._repo.set_value_json(_DONE_KEY, json.dumps(sorted(ids)))
