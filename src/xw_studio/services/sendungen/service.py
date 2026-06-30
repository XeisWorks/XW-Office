"""Offene Sendungen: Graph-backed queue with optional OpenAI summary."""
from __future__ import annotations

from dataclasses import dataclass
import json
import logging
import re
from typing import Any

import httpx

from xw_studio.repositories.settings_kv import SettingKvRepository
from xw_studio.services.mailing.graph_client import GraphMailClient, html_to_text
from xw_studio.services.secrets.service import SecretService

logger = logging.getLogger(__name__)

_OPEN_CASES_KEY = "daily_business.offene_sendungen.cases"
_DONE_CASES_KEY = "daily_business.offene_sendungen.done"


@dataclass(frozen=True)
class SendungCase:
    id: str
    received_at: str
    sender: str
    subject: str
    snippet: str
    body: str
    thread_id: str
    order_number: str


class OffeneSendungenService:
    """Manage open shipping requests with persistence and optional AI support."""

    def __init__(self, settings_repo: SettingKvRepository | None, secrets: SecretService) -> None:
        self._repo = settings_repo
        self._secrets = secrets

    def open_count(self) -> int:
        return len(self.load_open_cases())

    def load_open_cases(self) -> list[SendungCase]:
        all_cases = self._load_cached_cases()
        done = self._load_done_ids()
        return [case for case in all_cases if case.id not in done]

    def refresh_from_graph(
        self,
        *,
        lookback_days: int = 20,
        max_items: int = 120,
        allow_interactive_auth: bool = True,
    ) -> list[SendungCase]:
        messages = self._fetch_graph_messages(
            lookback_days=lookback_days,
            max_items=max_items,
            allow_interactive_auth=allow_interactive_auth,
        )
        cases = [self._to_case(msg) for msg in messages]
        self._save_cases(cases)
        return self.load_open_cases()

    def refresh_count_from_graph_silent(self, *, lookback_days: int = 20, max_items: int = 120) -> int:
        """Refresh Graph-backed cases only when cached MS auth is already available."""
        return len(
            self.refresh_from_graph(
                lookback_days=lookback_days,
                max_items=max_items,
                allow_interactive_auth=False,
            )
        )

    def mark_done(self, case_id: str, *, done: bool) -> None:
        cid = str(case_id or "").strip()
        if not cid:
            return
        ids = self._load_done_ids()
        if done:
            ids.add(cid)
        else:
            ids.discard(cid)
        self._save_done_ids(ids)

    def summarize_case(self, case: SendungCase) -> str:
        body = case.body.strip() or case.snippet.strip()
        if not body:
            return "Keine Mailinhalte verfügbar."

        api_key = self._secrets.get_secret("OPENAI_API_KEY")
        if not api_key:
            return self._fallback_summary(case)

        try:
            return self._openai_summary(case, api_key)
        except Exception as exc:  # noqa: BLE001
            logger.warning("OpenAI summary failed for sendung %s: %s", case.id, exc)
            return self._fallback_summary(case)

    def create_label_lines(self, case: SendungCase) -> list[str]:
        text = f"{case.subject}\n{case.body}".strip()
        lines = [line.strip() for line in text.splitlines() if line.strip()]
        if not lines:
            return []

        # Heuristic extraction for postal blocks.
        name = ""
        street = ""
        city_line = ""
        country = ""
        for line in lines:
            if not name and len(line) >= 3 and not any(ch.isdigit() for ch in line):
                name = line
                continue
            if not street and re.search(r"\d", line):
                street = line
                continue
            if not city_line and re.search(r"\b\d{4,5}\b", line):
                city_line = line
                continue
            if not country and line.upper() in {"DE", "AT", "CH", "NL", "BE", "FR", "IT", "ES"}:
                country = line.upper()

        result = [part for part in (name, street, city_line, country) if part]
        if not result:
            # Last-resort: first lines as manual starting point.
            return lines[:4]
        return result

    def _fallback_summary(self, case: SendungCase) -> str:
        text = (case.body or case.snippet or "").strip()
        short = text[:700]
        return (
            f"Betreff: {case.subject}\n"
            f"Absender: {case.sender}\n"
            f"Wix-Order-Nr: {case.order_number or 'nicht erkannt'}\n\n"
            f"Inhalt (Kurzfassung):\n{short}"
        )

    def _openai_summary(self, case: SendungCase, api_key: str) -> str:
        prompt = (
            "Fasse diese Versand-Mail knapp zusammen und extrahiere: "
            "1) Auftrag/Bestellkontext, 2) Lieferadresse, 3) nötige Versandaktion. "
            "Antworte auf Deutsch in 5-8 Stichpunkten.\n\n"
            f"Betreff: {case.subject}\n"
            f"Absender: {case.sender}\n"
            f"Mail:\n{case.body or case.snippet}"
        )
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }
        body = {
            "model": "gpt-4.1-mini",
            "input": prompt,
            "max_output_tokens": 350,
        }
        with httpx.Client(timeout=30.0) as client:
            resp = client.post("https://api.openai.com/v1/responses", headers=headers, json=body)
            resp.raise_for_status()
            payload = resp.json()

        output = payload.get("output")
        if isinstance(output, list):
            for item in output:
                if not isinstance(item, dict):
                    continue
                content = item.get("content")
                if not isinstance(content, list):
                    continue
                for block in content:
                    if isinstance(block, dict) and block.get("type") in {"output_text", "text"}:
                        text = str(block.get("text") or "").strip()
                        if text:
                            return text

        text = str(payload.get("output_text") or "").strip()
        if text:
            return text
        return self._fallback_summary(case)

    def _fetch_graph_messages(
        self,
        *,
        lookback_days: int,
        max_items: int,
        allow_interactive_auth: bool = True,
    ) -> list[dict[str, Any]]:
        client = self._graph_client()
        if client is None:
            return self._load_cached_raw_messages()
        if not allow_interactive_auth and not client.has_silent_token():
            logger.info("MS Graph silent token missing; using cached offene Sendungen")
            return self._load_cached_raw_messages()
        try:
            values = client.list_inbox_messages(days=max(1, lookback_days), top=max(1, min(max_items, 200)))
        except Exception as exc:  # noqa: BLE001
            logger.warning("MS Graph fetch failed for offene Sendungen: %s", exc)
            return self._load_cached_raw_messages()
        normalized = [self._normalize_graph_message(item) for item in values]
        filtered = [item for item in normalized if self._is_sendung_candidate(item)]
        self._save_raw_messages(filtered)
        return filtered

    def _graph_client(self) -> GraphMailClient | None:
        tenant_id = self._secrets.get_secret("MS_GRAPH_TENANT_ID")
        client_id = self._secrets.get_secret("MS_GRAPH_CLIENT_ID")
        mailbox = self._secrets.get_secret("MS_GRAPH_MAILBOX")
        if not tenant_id or not client_id:
            return None
        return GraphMailClient(
            tenant_id=tenant_id,
            client_id=client_id,
            mailbox_user=mailbox or None,
        )

    @staticmethod
    def _normalize_graph_message(msg: dict[str, Any]) -> dict[str, Any]:
        body_obj = msg.get("body") if isinstance(msg.get("body"), dict) else {}
        content = str(body_obj.get("content") or "").strip()
        content_type = str(body_obj.get("contentType") or "").strip()
        normalized = dict(msg)
        normalized["body"] = {
            "content": html_to_text(content) if content and content_type.lower() == "html" else content,
            "contentType": "text",
        }
        return normalized

    @staticmethod
    def _is_sendung_candidate(msg: dict[str, Any]) -> bool:
        subject = str(msg.get("subject") or "").lower()
        snippet = str(msg.get("bodyPreview") or "").lower()
        hay = f"{subject} {snippet}"
        return any(token in hay for token in ("sendung", "versand", "etikett", "label", "shipment"))

    def _to_case(self, msg: dict[str, Any]) -> SendungCase:
        sender = ""
        from_obj = msg.get("from") if isinstance(msg.get("from"), dict) else {}
        email_obj = from_obj.get("emailAddress") if isinstance(from_obj.get("emailAddress"), dict) else {}
        sender = str(email_obj.get("address") or email_obj.get("name") or "").strip()

        body_obj = msg.get("body") if isinstance(msg.get("body"), dict) else {}
        body = str(body_obj.get("content") or "").strip()
        snippet = str(msg.get("bodyPreview") or "").strip()
        subject = str(msg.get("subject") or "").strip()

        order_number = self._extract_order_number(f"{subject}\n{snippet}\n{body}")

        return SendungCase(
            id=str(msg.get("id") or "").strip(),
            received_at=str(msg.get("receivedDateTime") or "").strip(),
            sender=sender,
            subject=subject,
            snippet=snippet,
            body=body,
            thread_id=str(msg.get("conversationId") or "").strip(),
            order_number=order_number,
        )

    @staticmethod
    def _extract_order_number(text: str) -> str:
        m = re.search(r"\b\d{4,12}\b", text)
        return m.group(0) if m else ""

    def _load_cached_cases(self) -> list[SendungCase]:
        raw = self._repo.get_value_json(_OPEN_CASES_KEY) if self._repo is not None else None
        if not raw:
            return []
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            return []
        if not isinstance(data, list):
            return []
        out: list[SendungCase] = []
        for item in data:
            if not isinstance(item, dict):
                continue
            out.append(
                SendungCase(
                    id=str(item.get("id") or "").strip(),
                    received_at=str(item.get("received_at") or "").strip(),
                    sender=str(item.get("sender") or "").strip(),
                    subject=str(item.get("subject") or "").strip(),
                    snippet=str(item.get("snippet") or "").strip(),
                    body=str(item.get("body") or "").strip(),
                    thread_id=str(item.get("thread_id") or "").strip(),
                    order_number=str(item.get("order_number") or "").strip(),
                )
            )
        return out

    def _save_cases(self, cases: list[SendungCase]) -> None:
        if self._repo is None:
            return
        payload = [
            {
                "id": c.id,
                "received_at": c.received_at,
                "sender": c.sender,
                "subject": c.subject,
                "snippet": c.snippet,
                "body": c.body,
                "thread_id": c.thread_id,
                "order_number": c.order_number,
            }
            for c in cases
        ]
        self._repo.set_value_json(_OPEN_CASES_KEY, json.dumps(payload, ensure_ascii=False))

    def _load_done_ids(self) -> set[str]:
        raw = self._repo.get_value_json(_DONE_CASES_KEY) if self._repo is not None else None
        if not raw:
            return set()
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            return set()
        if not isinstance(data, list):
            return set()
        return {str(item).strip() for item in data if str(item).strip()}

    def _save_done_ids(self, ids: set[str]) -> None:
        if self._repo is None:
            return
        self._repo.set_value_json(_DONE_CASES_KEY, json.dumps(sorted(ids), ensure_ascii=False))

    def _load_cached_raw_messages(self) -> list[dict[str, Any]]:
        raw = self._repo.get_value_json(f"{_OPEN_CASES_KEY}.raw_graph") if self._repo is not None else None
        if not raw:
            return []
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            return []
        if not isinstance(data, list):
            return []
        return [d for d in data if isinstance(d, dict)]

    def _save_raw_messages(self, messages: list[dict[str, Any]]) -> None:
        if self._repo is None:
            return
        self._repo.set_value_json(f"{_OPEN_CASES_KEY}.raw_graph", json.dumps(messages, ensure_ascii=False))
