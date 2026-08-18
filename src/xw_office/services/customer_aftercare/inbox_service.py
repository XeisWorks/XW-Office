"""Poll shop@xeisworks.at for Lieferkorrektur mails and create PENDING_REVIEW cases (spec §3).

Mirrors the mailbox-secret resolution already used by
:class:`xw_office.services.sendungen.service.OffeneSendungenService` (same
``shop@xeisworks.at`` inbox, via ``MS_GRAPH_MAILBOX``/``MS_GRAPH_TENANT_ID``/
``MS_GRAPH_CLIENT_ID``) — no new secret is introduced. The AI classifier
(:mod:`ai_classifier`) never creates a Rechnung, Label or Versandauftrag by
itself; this service only ever produces ``PENDING_REVIEW`` cases for the
review popup to confirm.
"""
from __future__ import annotations

from dataclasses import dataclass
import logging
from typing import Any

from xw_office.repositories.customer_aftercare import (
    CustomerAftercareItemInput,
    CustomerAftercareRepository,
)
from xw_office.services.customer_aftercare.ai_classifier import classify_mail
from xw_office.services.mailing.graph_client import GraphMailClient, html_to_text
from xw_office.services.secrets.service import SecretService

logger = logging.getLogger(__name__)

_EXCLUDED_WIX_SENDER = "no-reply@mystore.wix.com"
_EXCLUDED_OWN_SENDERS = {"office@xeisworks.at", "shop@xeisworks.at"}

#: Cheap subject/body pre-filter so every shop@ mail doesn't turn into an AI
#: call + PENDING_REVIEW case — only candidates get classified (spec §3).
_CANDIDATE_KEYWORDS = (
    "falsch geliefert",
    "falsche lieferung",
    "falschlieferung",
    "lieferkorrektur",
    "fehlt noch",
    "fehlende artikel",
    "fehlender artikel",
    "falsch bestellt",
    "verklickt",
    "statt bestellt",
    "falsches produkt",
    "falscher artikel",
)


@dataclass(frozen=True)
class InboxPollResult:
    scanned: int
    new_cases: int


class CustomerAftercareInboxService:
    """Read the shop mailbox, pre-filter, classify, and persist PENDING_REVIEW cases."""

    def __init__(
        self,
        repo: CustomerAftercareRepository | None,
        secrets: SecretService,
    ) -> None:
        self._repo = repo
        self._secrets = secrets

    def poll_inbox(
        self,
        *,
        lookback_days: int = 14,
        max_items: int = 60,
        allow_interactive_auth: bool = True,
    ) -> InboxPollResult:
        if self._repo is None:
            return InboxPollResult(scanned=0, new_cases=0)
        client = self._graph_client()
        if client is None:
            return InboxPollResult(scanned=0, new_cases=0)
        if not allow_interactive_auth and not client.has_silent_token():
            logger.info("MS Graph silent token missing; skipping Lieferkorrektur poll")
            return InboxPollResult(scanned=0, new_cases=0)
        try:
            messages = client.list_inbox_messages(
                days=max(1, lookback_days), top=max(1, min(max_items, 200))
            )
        except Exception as exc:  # noqa: BLE001 - inbox polling must never crash the badge/background job.
            logger.warning("Lieferkorrektur-Posteingang konnte nicht gelesen werden: %s", exc)
            return InboxPollResult(scanned=0, new_cases=0)

        candidates = [self._normalize_message(msg) for msg in messages if self._is_candidate(msg)]
        api_key = self._secrets.get_secret("OPENAI_API_KEY") or None
        new_cases = sum(1 for msg in candidates if self._process_message(msg, api_key))
        return InboxPollResult(scanned=len(candidates), new_cases=new_cases)

    def _process_message(self, msg: dict[str, Any], api_key: str | None) -> bool:
        assert self._repo is not None  # guarded by poll_inbox
        message_id = str(msg.get("id") or "").strip()
        if not message_id:
            return False
        if self._repo.get_case_by_message_id(message_id) is not None:
            return False  # already processed — idempotent (spec IDEMP-01)

        subject = str(msg.get("subject") or "").strip()
        sender = self._sender_address(msg)
        body_text = self._body_text(msg)
        thread_id = str(msg.get("conversationId") or "").strip()

        classification = classify_mail(
            subject=subject, sender=sender, body_text=body_text, api_key=api_key
        )

        reservation = self._repo.reserve_case_by_message_id(
            source_message_id=message_id,
            source_thread_id=thread_id,
            source_subject=subject,
            ai_suggested_type=classification.case_type,
            ai_confidence=classification.confidence,
            ai_payload_json=classification.to_payload_json(),
            customer_email=classification.customer_email or sender,
            customer_name=classification.customer_name,
            source_wix_order_number=classification.wix_order_number,
        )
        if reservation.state != "created":
            return False

        items = [
            CustomerAftercareItemInput(
                role="WRONG_DELIVERED",
                name=item.name,
                sku=item.sku,
                quantity=_as_quantity(item.quantity),
            )
            for item in classification.wrong_items
        ] + [
            CustomerAftercareItemInput(
                role="MISSING_TO_SEND",
                name=item.name,
                sku=item.sku,
                quantity=_as_quantity(item.quantity),
            )
            for item in classification.missing_items
        ]
        if items:
            self._repo.add_items(reservation.case.id, items)
        return True

    def _graph_client(self, *, write: bool = False) -> GraphMailClient | None:
        tenant_id = self._secrets.get_secret("MS_GRAPH_TENANT_ID")
        client_id = self._secrets.get_secret("MS_GRAPH_CLIENT_ID")
        mailbox = self._secrets.get_secret("MS_GRAPH_MAILBOX")
        if not tenant_id or not client_id:
            return None
        scopes = ["Mail.Read", "Mail.Read.Shared"]
        if write:
            scopes.extend(["Mail.ReadWrite", "Mail.ReadWrite.Shared"])
        return GraphMailClient(
            tenant_id=tenant_id,
            client_id=client_id,
            mailbox_user=mailbox or None,
            scopes=scopes,
        )

    @staticmethod
    def _normalize_message(msg: dict[str, Any]) -> dict[str, Any]:
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
    def _sender_address(msg: dict[str, Any]) -> str:
        from_obj = msg.get("from") if isinstance(msg.get("from"), dict) else {}
        email_obj = from_obj.get("emailAddress") if isinstance(from_obj.get("emailAddress"), dict) else {}
        return str(email_obj.get("address") or email_obj.get("name") or "").strip()

    @staticmethod
    def _body_text(msg: dict[str, Any]) -> str:
        body_obj = msg.get("body") if isinstance(msg.get("body"), dict) else {}
        content = str(body_obj.get("content") or "").strip()
        return content or str(msg.get("bodyPreview") or "").strip()

    @classmethod
    def _is_candidate(cls, msg: dict[str, Any]) -> bool:
        sender = cls._sender_address(msg).lower()
        if sender == _EXCLUDED_WIX_SENDER:
            return False
        subject = str(msg.get("subject") or "").strip().lower()
        preview = str(msg.get("bodyPreview") or "").strip().lower()
        body_obj = msg.get("body") if isinstance(msg.get("body"), dict) else {}
        body = str(body_obj.get("content") or "").strip().lower()
        haystack = f"{subject}\n{preview}\n{body}"
        return any(keyword in haystack for keyword in _CANDIDATE_KEYWORDS)


def _as_quantity(raw: str) -> int:
    try:
        return max(1, int(str(raw).strip().split()[0]))
    except (ValueError, IndexError):
        return 1
