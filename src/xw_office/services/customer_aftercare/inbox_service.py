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
import re
from typing import Any

from xw_office.repositories.customer_aftercare import (
    CustomerAftercareItemInput,
    CustomerAftercareRepository,
)
from xw_office.services.customer_aftercare.ai_classifier import classify_mail
from xw_office.services.mailing.graph_client import GraphMailClient, html_to_text
from xw_office.services.secrets.service import SecretService
from xw_office.services.sevdesk.invoice_client import InvoiceClient
from xw_office.services.wix.client import WixOrdersClient

logger = logging.getLogger(__name__)

_DEFAULT_AFTERCARE_MAILBOX = "nachlieferung@xeisworks.at"

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
        invoices: InvoiceClient | None = None,
        wix_orders: WixOrdersClient | None = None,
    ) -> None:
        self._repo = repo
        self._secrets = secrets
        self._invoices = invoices
        self._wix_orders = wix_orders

    def poll_inbox(
        self,
        *,
        lookback_days: int = 14,
        max_items: int = 60,
        allow_interactive_auth: bool = True,
    ) -> InboxPollResult:
        if self._repo is None:
            return InboxPollResult(scanned=0, new_cases=0)
        sources: list[tuple[GraphMailClient, bool]] = []
        client = self._graph_client()
        if client is not None:
            sources.append((client, False))
        primary_mailbox = str(self._secrets.get_secret("MS_GRAPH_MAILBOX") or "").strip()
        configured_aftercare = str(self._secrets.get_secret("MS_GRAPH_AFTERCARE_MAILBOX") or "").strip()
        dedicated_mailbox = configured_aftercare or (_DEFAULT_AFTERCARE_MAILBOX if primary_mailbox else "")
        if dedicated_mailbox and dedicated_mailbox.lower() != primary_mailbox.lower():
            dedicated = self._graph_client(mailbox=dedicated_mailbox)
            if dedicated is not None:
                sources.append((dedicated, True))
        if not sources:
            return InboxPollResult(scanned=0, new_cases=0)
        candidates: list[dict[str, Any]] = []
        seen_ids: set[str] = set()
        for source_client, dedicated in sources:
            if not allow_interactive_auth and not source_client.has_silent_token():
                continue
            try:
                messages = source_client.list_inbox_messages(
                    days=max(1, lookback_days), top=max(1, min(max_items, 200))
                )
            except Exception as exc:  # noqa: BLE001 - badge polling must remain non-blocking.
                logger.warning("Lieferkorrektur-Posteingang konnte nicht gelesen werden: %s", exc)
                continue
            for msg in messages:
                message_id = str(msg.get("id") or "").strip() if isinstance(msg, dict) else ""
                if message_id and message_id in seen_ids:
                    continue
                if message_id:
                    seen_ids.add(message_id)
                if dedicated or self._is_candidate(msg):
                    candidates.append(self._normalize_message(msg))
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
        context = self._resolve_business_context(subject, body_text)

        classification = classify_mail(
            subject=subject,
            sender=sender,
            body_text=body_text + context["prompt_suffix"],
            api_key=api_key,
        )

        reservation = self._repo.reserve_case_by_message_id(
            source_message_id=message_id,
            source_thread_id=thread_id,
            source_subject=subject,
            ai_suggested_type=classification.case_type,
            ai_confidence=classification.confidence,
            ai_payload_json=classification.to_payload_json(),
            customer_email=context["customer_email"] or classification.customer_email or sender,
            customer_name=context["customer_name"] or classification.customer_name,
            source_wix_order_id=context["wix_order_id"],
            source_wix_order_number=context["wix_order_number"] or classification.wix_order_number,
            source_invoice_id=context["invoice_id"],
            source_invoice_number=context["invoice_number"],
            sevdesk_contact_id=context["sevdesk_contact_id"],
            wix_contact_id=context["wix_contact_id"],
            address_lines=context["address_lines"],
            address_source=context["address_source"],
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

    def _resolve_business_context(self, subject: str, body_text: str) -> dict[str, Any]:
        """Resolve stable references before AI sees the message; AI never supplies authority."""
        haystack = f"{subject}\n{body_text}"
        invoice_match = re.search(r"\bRE[- ]?\d{4,}\b", haystack, re.IGNORECASE)
        order_match = re.search(r"(?<!\d)\d{5}(?!\d)", haystack)
        invoice_number = invoice_match.group(0) if invoice_match else ""
        order_number = order_match.group(0) if order_match else ""
        invoice_id = ""
        sevdesk_contact_id = ""
        customer_email = ""
        customer_name = ""
        address_lines: list[str] = []
        address_source = ""
        if invoice_number and self._invoices is not None:
            try:
                matches, _days = self._invoices.search_invoice_summaries(invoice_number)
                exact = next((row for row in matches if row.invoice_number.casefold() == invoice_number.casefold()), None)
                selected = exact or (matches[0] if matches else None)
                if selected is not None:
                    invoice_id = str(selected.id or "").strip()
                    invoice_number = str(selected.invoice_number or invoice_number).strip()
                    detail = self._invoices.fetch_invoice_by_id(invoice_id)
                    contact = detail.get("contact") if isinstance(detail.get("contact"), dict) else {}
                    sevdesk_contact_id = str(contact.get("id") or detail.get("contactId") or "").strip()
                    customer_email = str(detail.get("email") or contact.get("email") or "").strip()
                    customer_name = str(contact.get("name") or detail.get("customerName") or "").strip()
                    address_lines = self._invoice_address_lines(detail)
                    address_source = "sevdesk" if address_lines else ""
                    order_number = order_number or str(selected.order_reference or "").strip()
            except Exception as exc:  # noqa: BLE001 - mail remains reviewable without enrichment
                logger.info("sevDesk-Nachlieferungskontext nicht auflösbar: %s", exc)
        wix_contact_id = ""
        wix_order_id = ""
        if order_number and self._wix_orders is not None:
            try:
                order = self._wix_orders.resolve_order(order_number)
                if isinstance(order, dict):
                    wix_order_id = str(order.get("id") or "").strip()
                    buyer = order.get("buyerInfo") if isinstance(order.get("buyerInfo"), dict) else {}
                    wix_contact_id = str(buyer.get("contactId") or "").strip()
                    customer_email = customer_email or str(buyer.get("email") or "").strip()
                    customer_name = customer_name or str(buyer.get("firstName") or "").strip()
                    wix_address = self._wix_orders.best_address_lines_from_order(order)
                    if wix_address:
                        address_lines, address_source = wix_address, "wix"
            except Exception as exc:  # noqa: BLE001
                logger.info("Wix-Nachlieferungskontext nicht auflösbar: %s", exc)
        refs = (
            f"\nDeterministisch aufgelöster Kontext: Rechnung {invoice_number or 'unbekannt'}, "
            f"Wix-Bestellung {order_number or 'unbekannt'}, Kunde-ID {sevdesk_contact_id or wix_contact_id or 'unbekannt'}, "
            f"Adresse {' | '.join(address_lines) if address_lines else 'unbekannt'}."
        )
        return {
            "invoice_id": invoice_id,
            "invoice_number": invoice_number,
            "wix_order_id": wix_order_id,
            "wix_order_number": order_number,
            "sevdesk_contact_id": sevdesk_contact_id,
            "wix_contact_id": wix_contact_id,
            "customer_email": customer_email,
            "customer_name": customer_name,
            "address_lines": address_lines,
            "address_source": address_source,
            "prompt_suffix": refs,
        }

    @staticmethod
    def _invoice_address_lines(invoice: dict[str, Any]) -> list[str]:
        contact = invoice.get("contact") if isinstance(invoice.get("contact"), dict) else {}
        values = [
            invoice.get("deliveryName") or invoice.get("shippingName") or contact.get("name"),
            invoice.get("deliveryStreet") or invoice.get("shippingStreet") or invoice.get("addressStreet"),
            invoice.get("deliveryAddress") or invoice.get("shippingAddress"),
            " ".join(str(value).strip() for value in (
                invoice.get("deliveryZip") or invoice.get("shippingZip") or invoice.get("addressZip"),
                invoice.get("deliveryCity") or invoice.get("shippingCity") or invoice.get("addressCity"),
            ) if str(value or "").strip()),
            invoice.get("deliveryCountry") or invoice.get("shippingCountry") or invoice.get("addressCountry"),
        ]
        return [str(value).strip() for value in values if str(value or "").strip()]

    def _graph_client(
        self, *, write: bool = False, mailbox: str | None = None
    ) -> GraphMailClient | None:
        tenant_id = self._secrets.get_secret("MS_GRAPH_TENANT_ID")
        client_id = self._secrets.get_secret("MS_GRAPH_CLIENT_ID")
        mailbox = mailbox or self._secrets.get_secret("MS_GRAPH_MAILBOX")
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
