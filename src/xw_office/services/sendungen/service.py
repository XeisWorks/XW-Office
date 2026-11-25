"""Offene Sendungen: Graph-backed queue, AI extraction, labels and delivery notes."""

from __future__ import annotations

import json
import logging
import re
import time
import unicodedata
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from threading import RLock
from typing import Any, cast

import httpx

from xw_office.core.config import PrintingSection
from xw_office.repositories.settings_kv import SettingKvRepository
from xw_office.services.mailing.graph_client import GraphMailClient, html_to_text
from xw_office.services.printing.invoice_printer import InvoicePrinter
from xw_office.services.printing.print_queue import PrintQueueService
from xw_office.services.secrets.service import SecretService
from xw_office.services.sendungen.xw_flow_client import (
    FlowAftercareCase,
    FlowShippingEmailCase,
    XwFlowShipmentClient,
)
from xw_office.services.sevdesk.invoice_client import InvoiceClient, InvoiceSummary
from xw_office.services.shipping.countries import country_label_for_address
from xw_office.services.wix.client import WixOrdersClient

logger = logging.getLogger(__name__)

_OPEN_CASES_KEY = "daily_business.offene_sendungen.cases"
_DONE_CASES_KEY = "daily_business.offene_sendungen.done"
_EXTRACTIONS_KEY = "daily_business.offene_sendungen.extractions"
_MANUAL_KEY = "daily_business.offene_sendungen.manual"
_SOURCE_MAILBOX_KEY = "daily_business.offene_sendungen.source_mailbox"
_DEFAULT_MODEL = "gpt-4.1-mini"
_EXTRACTION_SCHEMA_VERSION = 5
_MEMORY_CACHE_SECONDS = 120.0
_DEFAULT_SHIPPING_MAILBOX = "shipping@xeisworks.at"
#: Sentinel ``SendungCase.sender`` for cases injected via create_manual_case
#: (e.g. from a Lieferkorrektur) — preserved across refresh_from_graph
#: instead of being overwritten by the next Graph fetch.
_MANUAL_CASE_SENDER = "lieferkorrektur"
_SOURCE_GRAPH = "graph_mail"
_SOURCE_MANUAL = "manual"
_SOURCE_FLOW = "xw_flow_share"
_FOOTER_LINES = [
    "XeisWorks",
    "Musikverlag Mag. Bernhard Holl",
    "8912 Admont | Johnsbach 92",
    "Steiermark | Austria",
    "www.xeisworks.at",
    "office@xeisworks.at",
]


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
    invoice_number: str = ""
    thread_text: str = ""
    sender_name: str = ""
    source_type: str = _SOURCE_GRAPH
    source_id: str = ""


@dataclass(frozen=True)
class SendungProductLine:
    quantity: str = "1"
    name: str = ""
    sku: str = ""
    note: str = ""
    free_delivery: bool = True
    delivery_price: str = "5,90"
    no_return_required: bool = True


@dataclass(frozen=True)
class SendungExtraction:
    summary: str
    address_lines: list[str]
    products: list[SendungProductLine]
    short_note: str = ""
    order_number: str = ""
    invoice_number: str = ""
    customer_name: str = ""
    case_type: str = "other"
    confidence_notes: list[str] | None = None
    source: str = "fallback"
    updated_at: str = ""
    thread_text: str = ""


@dataclass(frozen=True)
class _SendungBusinessContext:
    """Authoritative customer/order data resolved before the AI analysis."""

    invoice_number: str = ""
    order_number: str = ""
    customer_name: str = ""
    address_lines: tuple[str, ...] = ()
    products: tuple[SendungProductLine, ...] = ()
    source: str = ""
    confidence_notes: tuple[str, ...] = ()


class OffeneSendungenService:
    """Manage open shipping requests with persistence and optional AI support."""

    def __init__(
        self,
        settings_repo: SettingKvRepository | None,
        secrets: SecretService,
        wix_orders: WixOrdersClient | None = None,
        flow_shipments: XwFlowShipmentClient | None = None,
        invoice_client: InvoiceClient | None = None,
        aftercare_repo: object | None = None,
    ) -> None:
        self._repo = settings_repo
        self._secrets = secrets
        self._wix_orders = wix_orders
        self._flow_shipments = flow_shipments
        self._invoice_client = invoice_client
        self._aftercare_repo = aftercare_repo
        self._cache_lock = RLock()
        self._open_cases_cache: list[SendungCase] | None = None
        self._open_cases_cache_at = 0.0
        self._recipient_names_cache: dict[str, str] | None = None
        self._extraction_locks: dict[str, RLock] = {}

    def open_count(self) -> int:
        cases = self.load_open_cases()
        self.load_cached_recipient_names(cases)
        return len(cases)

    def load_open_cases(self) -> list[SendungCase]:
        with self._cache_lock:
            if (
                self._open_cases_cache is not None
                and time.monotonic() - self._open_cases_cache_at < _MEMORY_CACHE_SECONDS
            ):
                return list(self._open_cases_cache)
        all_cases = self._load_cached_cases()
        if not self._has_current_mailbox_cache():
            # The queue used to read shop@.  Never surface its cached mails
            # after switching to the dedicated shipping@ mailbox.  Manually
            # created Lieferkorrektur cases are independent of the mailbox and
            # remain available until the next Graph refresh.
            all_cases = [case for case in all_cases if case.source_type != _SOURCE_GRAPH]
        done = self._load_done_ids()
        open_cases = [case for case in all_cases if case.id not in done]
        with self._cache_lock:
            self._open_cases_cache = list(open_cases)
            self._open_cases_cache_at = time.monotonic()
        return open_cases

    def load_cached_recipient_names(
        self,
        cases: list[SendungCase] | None = None,
    ) -> dict[str, str]:
        """Return list labels without network calls or per-case database roundtrips."""
        with self._cache_lock:
            if self._recipient_names_cache is not None:
                return dict(self._recipient_names_cache)
        extractions = self._load_json_map(_EXTRACTIONS_KEY)
        manual = self._load_json_map(_MANUAL_KEY)
        names: dict[str, str] = {}
        for case in cases if cases is not None else self.load_open_cases():
            extraction = extractions.get(case.id)
            expected_name = self._confirmed_customer_name(case, extraction)
            address_lines: object = None
            manual_case = manual.get(case.id)
            if isinstance(manual_case, dict):
                address_lines = manual_case.get("address_lines")
            if self._address_conflicts_with_customer(address_lines, expected_name):
                address_lines = None
            if not isinstance(address_lines, list) or not address_lines:
                if isinstance(extraction, dict):
                    address_lines = extraction.get("address_lines")
            if self._address_conflicts_with_customer(address_lines, expected_name):
                address_lines = None
            if isinstance(address_lines, list) and address_lines:
                name = str(address_lines[0] or "").strip()
                if name:
                    names[case.id] = name
                    continue
            if expected_name:
                names[case.id] = expected_name
                continue
            if case.sender_name:
                names[case.id] = case.sender_name
        with self._cache_lock:
            self._recipient_names_cache = dict(names)
        return names

    def _invalidate_memory_cache(self, *, names: bool = True) -> None:
        with self._cache_lock:
            self._open_cases_cache = None
            self._open_cases_cache_at = 0.0
            if names:
                self._recipient_names_cache = None

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
        candidates = [msg for msg in messages if self._is_sendung_candidate(msg)]
        existing = self._load_cached_cases()
        non_graph_cases = [case for case in existing if case.source_type != _SOURCE_GRAPH]
        flow_cases = self._refresh_flow_cases(existing)
        self._save_cases(
            [case for case in non_graph_cases if case.source_type != _SOURCE_FLOW]
            + flow_cases
            + [self._to_case(msg) for msg in candidates],
            source_mailbox=self._shipping_mailbox(),
        )
        open_cases = self.load_open_cases()
        self._sync_shipping_email_snapshot(open_cases)
        self.sync_aftercare_cases()
        return open_cases

    def _sync_shipping_email_snapshot(self, cases: list[SendungCase]) -> None:
        if self._flow_shipments is not None and self._flow_shipments.is_configured():
            try:
                self._flow_shipments.sync_shipping_email_cases(
                    [
                        FlowShippingEmailCase(
                            external_id=case.source_id or case.id,
                            title=case.subject,
                            received_at=case.received_at,
                            details=self._flow_shipping_details(case),
                        )
                        for case in cases
                        if case.source_type in {_SOURCE_GRAPH, _SOURCE_MANUAL}
                        and not case.id.startswith("nachlieferung-")
                    ]
                )
            except Exception as exc:  # noqa: BLE001 - dashboard mirror must not block Office
                logger.warning("XW-Flow shipping-mail snapshot failed: %s", exc)

    def sync_aftercare_cases(self) -> None:
        """Mirror reviewable Nachlieferungen into XW-Flow's separate tab."""
        if (
            self._flow_shipments is None
            or not self._flow_shipments.is_configured()
            or self._aftercare_repo is None
        ):
            return
        list_cases = getattr(self._aftercare_repo, "list_by_statuses", None)
        item_loader = getattr(self._aftercare_repo, "get_items", None)
        if not callable(list_cases) or not callable(item_loader):
            return
        try:
            cases = list_cases(("PENDING_REVIEW", "WAITING", "TRIGGERED", "SNOOZED"))
            snapshots: list[FlowAftercareCase] = []
            for case in cases:
                items = item_loader(case.id)
                positions = [
                    {
                        "name": item.name,
                        "sku": item.sku,
                        "quantity": item.quantity,
                        "role": item.role,
                        "parent_sku": item.parent_sku,
                        "component_id": item.component_id,
                        "note": item.note,
                    }
                    for item in items
                    if item.role != "WRONG_DELIVERED"
                ]
                products = [
                    {
                        "quantity": str(max(1, int(item["quantity"] or 1))),
                        "name": str(item["name"] or item["sku"] or "Position"),
                        "sku": str(item["sku"] or ""),
                        "note": str(item["note"] or "Nachlieferung – nicht verrechnen"),
                        "free_delivery": True,
                        "delivery_price": "0",
                        "no_return_required": True,
                    }
                    for item in positions
                ]
                try:
                    address = json.loads(case.address_lines_json or "[]")
                except (TypeError, ValueError):
                    address = []
                address_lines = (
                    [str(line).strip() for line in address if str(line).strip()]
                    if isinstance(address, list)
                    else []
                )
                snapshots.append(
                    FlowAftercareCase(
                        external_id=f"aftercare:{case.id}",
                        title=(
                            f"Nachlieferung prüfen – {case.source_invoice_number}"
                            if case.source_invoice_number
                            else "Nachlieferung prüfen"
                        ),
                        received_at=case.created_at.isoformat() if case.created_at else "",
                        details={
                            "summary": case.note or "Nachlieferung aus Mail prüfen",
                            "customer_name": case.customer_name,
                            "invoice_number": case.source_invoice_number,
                            "order_number": case.source_wix_order_number,
                            "case_type": case.case_type or "aftercare",
                            "address_lines": address_lines,
                            "products": products,
                            "positions": positions,
                            "redelivery": True,
                            "aftercare_case_id": str(case.id),
                            "aftercare_status": case.status,
                            "source_invoice_date": case.source_invoice_date,
                            "source_subject": case.source_subject,
                            "source_mail_sender": case.source_mail_sender,
                            "created_at": case.created_at.isoformat() if case.created_at else "",
                            "due_at": case.due_at.isoformat() if case.due_at else "",
                            "snooze_mode": case.snooze_mode,
                            "snoozed_until": (
                                case.snoozed_until.isoformat() if case.snoozed_until else ""
                            ),
                            "snooze_reason": case.snooze_reason,
                            "position_editing": "xw_office",
                            "source": "nachlieferung@",
                            "confidence_notes": [],
                            "updated_at": case.updated_at.isoformat() if case.updated_at else "",
                        },
                    )
                )
            sync = getattr(self._flow_shipments, "sync_aftercare_cases", None)
            if callable(sync):
                sync(snapshots)
        except Exception as exc:  # noqa: BLE001 - Flow mirroring stays optional
            logger.warning("XW-Flow Nachlieferungssnapshot fehlgeschlagen: %s", exc)

    def _flow_shipping_details(self, case: SendungCase) -> dict[str, object] | None:
        """Return editable, derived shipping facts without sending mail content to Flow."""
        extraction = self._load_saved_extraction(case.id)
        manual = self.load_manual_fields(case.id)
        if extraction is None and not manual:
            return None

        address_lines = list(extraction.address_lines) if extraction is not None else []
        products = list(extraction.products) if extraction is not None else []
        summary = extraction.summary if extraction is not None else ""
        if manual:
            manual_address = manual.get("address_lines")
            if isinstance(manual_address, list):
                address_lines = [str(line).strip() for line in manual_address if str(line).strip()]
            manual_products = manual.get("products")
            if isinstance(manual_products, list):
                products = self._normalize_products(manual_products)
            manual_text = str(manual.get("manual_text") or "").strip()
            if manual_text:
                summary = manual_text

        details: dict[str, object] = {
            "summary": summary,
            "customer_name": extraction.customer_name if extraction is not None else case.sender_name,
            "invoice_number": extraction.invoice_number if extraction is not None else case.invoice_number,
            "order_number": extraction.order_number if extraction is not None else case.order_number,
            "case_type": extraction.case_type if extraction is not None else "other",
            "address_lines": address_lines,
            "products": [self._product_to_dict(product) for product in products],
            "redelivery": case.id.startswith("nachlieferung-"),
            "confidence_notes": extraction.confidence_notes if extraction is not None else [],
            "source": extraction.source if extraction is not None else "manual",
            "updated_at": extraction.updated_at if extraction is not None else str(manual.get("updated_at") or ""),
        }
        if case.id.startswith("nachlieferung-") and self._aftercare_repo is not None:
            try:
                loader = getattr(self._aftercare_repo, "get_case_by_dispatch_id", None)
                item_loader = getattr(self._aftercare_repo, "get_items", None)
                aftercare = loader(case.id) if callable(loader) else None
                if aftercare is not None:
                    items = item_loader(aftercare.id) if callable(item_loader) else []
                    details.update({
                        "aftercare_case_id": str(aftercare.id),
                        "aftercare_status": aftercare.status,
                        "source_invoice_date": aftercare.source_invoice_date,
                        "created_at": aftercare.created_at.isoformat() if aftercare.created_at else "",
                        "due_at": aftercare.due_at.isoformat() if aftercare.due_at else "",
                        "snooze_mode": aftercare.snooze_mode,
                        "snoozed_until": (
                            aftercare.snoozed_until.isoformat() if aftercare.snoozed_until else ""
                        ),
                        "snooze_reason": aftercare.snooze_reason,
                        "source_subject": aftercare.source_subject,
                        "positions": [
                            {
                                "name": item.name,
                                "sku": item.sku,
                                "quantity": item.quantity,
                                "parent_sku": item.parent_sku,
                                "component_id": item.component_id,
                            }
                            for item in items
                            if item.role in {"MISSING_TO_SEND", "CORRECTED_ORDER_ITEM"}
                        ],
                        "position_editing": "xw_office",
                    })
            except Exception as exc:  # noqa: BLE001 - Flow mirroring stays optional
                logger.warning("Nachlieferungsdetails fuer XW-Flow nicht lesbar: %s", exc)
        return details

    def _refresh_flow_cases(self, existing: list[SendungCase]) -> list[SendungCase]:
        """Fetch a full successful Flow snapshot, preserving its cache on error."""
        previous = [case for case in existing if case.source_type == _SOURCE_FLOW]
        if self._flow_shipments is None or not self._flow_shipments.is_configured():
            return previous
        try:
            remote_cases = self._flow_shipments.fetch_open_cases()
        except Exception as exc:  # noqa: BLE001 - stale cache is intentional for queue safety
            logger.warning("XW-Flow shipment refresh failed: %s", exc)
            return previous
        return [
            SendungCase(
                id=f"flow:{remote.id}",
                received_at=remote.created_at,
                sender="XW-Flow Share",
                subject=remote.title or "Neue Lieferung",
                snippet=remote.body_text[:700],
                body=remote.body_text,
                thread_id="",
                order_number=self._extract_order_number(f"{remote.title}\n{remote.body_text}"),
                invoice_number=self._extract_invoice_number(f"{remote.title}\n{remote.body_text}"),
                thread_text=remote.body_text,
                sender_name="XW-Flow",
                source_type=_SOURCE_FLOW,
                source_id=remote.id,
            )
            for remote in remote_cases
        ]

    def create_manual_case(
        self,
        *,
        case_id: str,
        subject: str,
        note: str,
        address_lines: list[str] | None = None,
        products: list[SendungProductLine] | None = None,
    ) -> SendungCase:
        """Inject a manually-created case (e.g. from a Lieferkorrektur) into Offene Sendungen.

        Reuses the existing cached-case/manual-fields/label/PDF pipeline as-is
        — additive only, never touches Graph-sourced case handling. Idempotent:
        calling again with the same *case_id* returns the existing case
        unchanged rather than duplicating it. Survives refresh_from_graph
        (see the manual-case preservation there).
        """
        cid = str(case_id or "").strip()
        if not cid:
            raise ValueError("case_id fehlt")
        existing = self._find_case(cid)
        if existing is not None:
            return existing

        reference_text = f"{subject}\n{note}"
        case = SendungCase(
            id=cid,
            received_at=self._utc_now_iso(),
            sender=_MANUAL_CASE_SENDER,
            subject=str(subject or "").strip(),
            snippet=str(note or "").strip(),
            body=str(note or "").strip(),
            thread_id="",
            order_number=self._extract_order_number(reference_text),
            invoice_number=self._extract_invoice_number(reference_text),
            source_type=_SOURCE_MANUAL,
            source_id=cid,
        )
        cases = self._load_cached_cases()
        cases.append(case)
        self._save_cases(cases)
        if address_lines or products:
            self.save_manual_fields(
                cid,
                address_lines=list(address_lines or []),
                products=list(products or []),
                manual_text=str(note or "").strip(),
            )
        self._sync_shipping_email_snapshot(self.load_open_cases())
        return case

    def refresh_count_from_graph_silent(
        self, *, lookback_days: int = 20, max_items: int = 120
    ) -> int:
        """Refresh mail and XW-Flow cases without starting interactive MS auth."""
        return len(
            self.refresh_from_graph(
                lookback_days=lookback_days,
                max_items=max_items,
                allow_interactive_auth=False,
            )
        )

    def mark_done(self, case_id: str, *, done: bool, resolve_aftercare: bool = True) -> None:
        cid = str(case_id or "").strip()
        if not cid:
            return
        case = self._find_case(cid)
        source_type = case.source_type if case is not None else _SOURCE_GRAPH
        if source_type == _SOURCE_FLOW:
            if case is None:
                raise RuntimeError("XW-Flow Sendungsfall nicht gefunden")
            if self._flow_shipments is None:
                raise RuntimeError("XW-Flow Versand-Bridge ist nicht konfiguriert")
            self._flow_shipments.set_status(
                case.source_id or cid.removeprefix("flow:"), completed=done
            )
        elif source_type == _SOURCE_GRAPH and done:
            client = self._graph_client(write=True)
            if client is None:
                raise RuntimeError("MS Graph ist nicht konfiguriert")
            client.mark_message_followup_complete(cid)
        ids = self._load_done_ids()
        if done:
            ids.add(cid)
        else:
            ids.discard(cid)
        self._save_done_ids(ids)
        if resolve_aftercare and cid.startswith("nachlieferung-") and self._aftercare_repo is not None:
            try:
                if done and hasattr(self._aftercare_repo, "mark_dispatch_completed"):
                    self._aftercare_repo.mark_dispatch_completed(cid)
            except (TypeError, ValueError, AttributeError):
                logger.warning("Nachlieferungsstatus konnte nicht synchronisiert werden: %s", cid)
        if source_type in {_SOURCE_GRAPH, _SOURCE_MANUAL}:
            self._sync_shipping_email_snapshot(self.load_open_cases())

    def load_manual_fields(self, case_id: str) -> dict[str, Any]:
        cid = str(case_id or "").strip()
        data = self._load_json_map(_MANUAL_KEY)
        value = data.get(cid)
        if not isinstance(value, dict):
            return {}
        case = self._find_case(cid)
        extraction = self._load_json_map(_EXTRACTIONS_KEY).get(cid)
        expected_name = self._confirmed_customer_name(case, extraction) if case else ""
        if self._address_conflicts_with_customer(value.get("address_lines"), expected_name):
            logger.warning("Mismatched saved shipping fields ignored for case %s", cid)
            return {}
        if (
            case is not None
            and case.source_type == _SOURCE_GRAPH
            and not value.get("edits_only")
            and isinstance(extraction, dict)
            and self._legacy_products_belong_to_another_case(cid, value, extraction, data)
        ):
            logger.warning("Copied legacy products and delivery note ignored for case %s", cid)
            return {key: item for key, item in value.items() if key not in {"products", "manual_text"}}
        return value

    def _legacy_products_belong_to_another_case(
        self,
        case_id: str,
        saved: dict[str, Any],
        extraction: dict[str, Any],
        saved_cases: dict[str, Any],
    ) -> bool:
        """Recognize legacy snapshots containing another case's products and note."""
        def identities(products: list[SendungProductLine]) -> set[tuple[str, str]]:
            return {
                (field, value.casefold())
                for product in products
                for field, value in (("name", product.name), ("sku", product.sku))
                if value
            }

        saved_products = saved.get("products")
        saved_ids = identities(self._normalize_products(saved_products))
        extracted_ids = identities(self._normalize_products(extraction.get("products")))
        if not saved_ids or not extracted_ids or saved_ids & extracted_ids:
            return False
        return any(
            other_id != case_id
            and isinstance(other, dict)
            and other.get("products") == saved_products
            and other.get("manual_text") == saved.get("manual_text")
            for other_id, other in saved_cases.items()
        )

    @classmethod
    def _confirmed_customer_name(cls, case: SendungCase, extraction: object) -> str:
        if not isinstance(extraction, dict):
            return ""
        name = str(extraction.get("customer_name") or "").strip()
        thread_text = str(extraction.get("thread_text") or case.thread_text or case.body or "")
        return name if name and cls._name_matches_case(name, case, thread_text) else ""

    @classmethod
    def _address_conflicts_with_customer(cls, address: object, customer_name: str) -> bool:
        if not customer_name or not isinstance(address, list) or not address:
            return False
        recipient = str(address[0] or "").strip()
        return bool(recipient and not cls._names_match(recipient, customer_name))

    def save_manual_fields(
        self,
        case_id: str,
        *,
        address_lines: list[str],
        products: list[SendungProductLine],
        manual_text: str = "",
        baseline: SendungExtraction | None = None,
    ) -> None:
        cid = str(case_id or "").strip()
        if not cid:
            return
        fields: dict[str, Any] = {
            "address_lines": [str(line).strip() for line in address_lines if str(line).strip()],
            "products": [self._product_to_dict(product) for product in products],
            "manual_text": str(manual_text or "").strip(),
        }
        if baseline is not None:
            defaults = {
                "address_lines": baseline.address_lines,
                "products": [self._product_to_dict(product) for product in baseline.products],
                "manual_text": baseline.short_note.strip(),
            }
            fields = {key: value for key, value in fields.items() if value != defaults[key]}

        if self._repo is not None:
            with self._cache_lock:
                self._repo.mutate_value_json(
                    _MANUAL_KEY,
                    lambda raw: self._replace_manual_fields(raw, cid, fields),
                )
                self._recipient_names_cache = None
        case = self._find_case(cid)
        if case is not None and case.source_type == _SOURCE_GRAPH:
            self._sync_shipping_email_snapshot(self.load_open_cases())

    def _replace_manual_fields(self, raw: str | None, cid: str, fields: dict[str, Any]) -> str:
        data = self._parse_json_map(raw)
        if fields:
            data[cid] = {**fields, "edits_only": True, "updated_at": self._utc_now_iso()}
        else:
            data.pop(cid, None)
        return json.dumps(data, ensure_ascii=False)

    def extract_case_details(
        self,
        case_id: str,
        *,
        force: bool = False,
        on_thread_loaded: Callable[[str], None] | None = None,
    ) -> SendungExtraction:
        cid = str(case_id or "").strip()
        with self._cache_lock:
            case_lock = self._extraction_locks.setdefault(cid, RLock())
        with case_lock:
            return self._extract_case_details_locked(
                cid, force=force, on_thread_loaded=on_thread_loaded
            )

    def _extract_case_details_locked(
        self,
        cid: str,
        *,
        force: bool,
        on_thread_loaded: Callable[[str], None] | None,
    ) -> SendungExtraction:
        case = self._find_case(cid)
        if case is None:
            raise RuntimeError("Sendungsfall nicht gefunden")
        if not force:
            cached = self._load_saved_extraction(cid)
            if cached is not None:
                return cached

        thread_text = self._full_case_text(case, on_text_loaded=on_thread_loaded)
        context = self._resolve_business_context(case, thread_text)

        api_key = self._secrets.get_secret("OPENAI_API_KEY")
        if api_key:
            try:
                extraction = self._openai_extract(
                    case,
                    api_key,
                    thread_text=thread_text,
                    context=context,
                )
                extraction = self._apply_business_context(case, extraction, context)
                self._save_extraction(cid, extraction)
                self._sync_shipping_email_snapshot(self.load_open_cases())
                return extraction
            except Exception as exc:  # noqa: BLE001
                logger.warning("OpenAI sendung extraction failed for %s: %s", cid, exc)

        extraction = self._fallback_extract(case, thread_text=thread_text)
        extraction = self._apply_business_context(case, extraction, context)
        self._save_extraction(cid, extraction)
        self._sync_shipping_email_snapshot(self.load_open_cases())
        return extraction

    def summarize_case(self, case: SendungCase) -> str:
        body = (case.thread_text or case.body).strip() or case.snippet.strip()
        if not body:
            return "Keine Mailinhalte verfuegbar."

        api_key = self._secrets.get_secret("OPENAI_API_KEY")
        if not api_key:
            return self._fallback_summary(case)

        try:
            return self._openai_summary(case, api_key)
        except Exception as exc:  # noqa: BLE001
            logger.warning("OpenAI summary failed for sendung %s: %s", case.id, exc)
            return self._fallback_summary(case)

    def create_label_lines(self, case: SendungCase) -> list[str]:
        manual = self.load_manual_fields(case.id)
        manual_lines = manual.get("address_lines") if isinstance(manual, dict) else None
        if isinstance(manual_lines, list) and manual_lines:
            return [str(line).strip() for line in manual_lines if str(line).strip()]

        cached = self._load_saved_extraction(case.id)
        if cached is not None and cached.address_lines:
            return cached.address_lines

        text = f"{case.subject}\n{case.thread_text or case.body}".strip()
        lines = [line.strip() for line in text.splitlines() if line.strip()]
        if not lines:
            return []

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
        return result or lines[:4]

    def generate_delivery_note_pdf(
        self,
        case_id: str,
        *,
        address_lines: list[str],
        products: list[SendungProductLine],
        manual_text: str = "",
        summary: str = "",  # Kept for callers; internal AI summary is never printed.
        short_note: str = "",
        baseline: SendungExtraction | None = None,
    ) -> Path:
        case = self._find_case(case_id)
        if case is None:
            raise RuntimeError("Sendungsfall nicht gefunden")
        address = [str(line).strip() for line in address_lines if str(line).strip()]
        if not address:
            raise ValueError("Lieferanschrift fehlt")
        shipping_products = [product for product in products if str(product.name or "").strip()]
        if not shipping_products:
            raise ValueError("Mindestens ein Produkt fehlt")
        note = str(short_note or manual_text or "").strip()
        if note and note == str(summary or "").strip():
            note = ""
        self.save_manual_fields(
            case.id,
            address_lines=address,
            products=shipping_products,
            manual_text=note,
            baseline=baseline,
        )
        return self._render_delivery_note_pdf(
            case,
            address_lines=address,
            products=shipping_products,
            short_note=note,
        )

    def print_delivery_note(
        self,
        pdf_path: str | Path,
        *,
        printing: PrintingSection,
        print_queue: PrintQueueService | None = None,
        wait: bool = False,
    ) -> None:
        path = Path(pdf_path)
        if not path.exists():
            raise RuntimeError("Lieferschein-PDF nicht gefunden")
        InvoicePrinter(printing, print_queue=print_queue).print_pdf_bytes(
            path.read_bytes(), wait=wait
        )

    def _fallback_summary(self, case: SendungCase) -> str:
        text = (case.thread_text or case.body or case.snippet or "").strip()
        short = text[:700]
        order_number = self._extract_order_number(f"{case.subject}\n{text}")
        return (
            f"Betreff: {case.subject}\n"
            f"Absender: {case.sender}\n"
            f"Wix-Order-Nr: {order_number or 'nicht erkannt'}\n\n"
            f"Inhalt (Kurzfassung):\n{short}"
        )

    def _openai_summary(self, case: SendungCase, api_key: str) -> str:
        prompt = (
            "Fasse diese Versand-Mail knapp zusammen und extrahiere: "
            "1) Auftrag/Bestellkontext, 2) Lieferadresse, 3) noetige Versandaktion. "
            "Antworte auf Deutsch in 5-8 Stichpunkten.\n\n"
            f"Betreff: {case.subject}\n"
            f"Absender: {case.sender}\n"
            f"Mail:\n{case.thread_text or case.body or case.snippet}"
        )
        headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
        body = {"model": _DEFAULT_MODEL, "input": prompt, "max_output_tokens": 350}
        with httpx.Client(timeout=30.0) as client:
            resp = client.post("https://api.openai.com/v1/responses", headers=headers, json=body)
            resp.raise_for_status()
            payload = resp.json()
        text = self._response_text(payload)
        return text or self._fallback_summary(case)

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
            # The queue needs metadata only.  Fetching the full body for up
            # to 150 messages made each background refresh unnecessarily
            # large; the selected message is loaded on demand below.
            values = client.list_inbox_messages(
                days=max(1, lookback_days),
                top=max(1, min(max_items, 200)),
                include_body=False,
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("MS Graph fetch failed for offene Sendungen: %s", exc)
            return self._load_cached_raw_messages()
        normalized = [self._normalize_graph_message(item) for item in values]
        filtered = [item for item in normalized if self._is_sendung_candidate(item)]
        self._save_raw_messages(filtered)
        return filtered

    def _shipping_mailbox(self) -> str:
        """Return the dedicated mailbox used exclusively for shipping jobs."""
        return (
            self._secrets.get_secret("MS_GRAPH_SHIPPING_MAILBOX").strip()
            or _DEFAULT_SHIPPING_MAILBOX
        )

    def _graph_client(self, *, write: bool = False) -> GraphMailClient | None:
        tenant_id = self._secrets.get_secret("MS_GRAPH_TENANT_ID")
        client_id = self._secrets.get_secret("MS_GRAPH_CLIENT_ID")
        if not tenant_id or not client_id:
            return None
        scopes = ["Mail.Read", "Mail.Read.Shared", "Mail.Send", "Mail.Send.Shared"]
        if write:
            scopes.extend(["Mail.ReadWrite", "Mail.ReadWrite.Shared"])
        return GraphMailClient(
            tenant_id=tenant_id,
            client_id=client_id,
            mailbox_user=self._shipping_mailbox(),
            scopes=scopes,
        )

    @staticmethod
    def _normalize_graph_message(msg: dict[str, Any]) -> dict[str, Any]:
        body_obj = (
            cast(dict[str, Any], msg.get("body")) if isinstance(msg.get("body"), dict) else {}
        )
        content = str(body_obj.get("content") or "").strip()
        content_type = str(body_obj.get("contentType") or "").strip()
        normalized = dict(msg)
        normalized["body"] = {
            "content": html_to_text(content)
            if content and content_type.lower() == "html"
            else content,
            "contentType": "text",
        }
        return normalized

    @staticmethod
    def _is_sendung_candidate(msg: dict[str, Any]) -> bool:
        """Accept every unresolved mail in the dedicated shipping mailbox."""
        if not str(msg.get("id") or "").strip():
            return False
        flag_obj = (
            cast(dict[str, Any], msg.get("flag")) if isinstance(msg.get("flag"), dict) else {}
        )
        flag_status = str(flag_obj.get("flagStatus") or "").strip().lower()
        return flag_status != "complete"

    def _to_case(self, msg: dict[str, Any]) -> SendungCase:
        from_obj = (
            cast(dict[str, Any], msg.get("from")) if isinstance(msg.get("from"), dict) else {}
        )
        email_obj = (
            cast(dict[str, Any], from_obj.get("emailAddress"))
            if isinstance(from_obj.get("emailAddress"), dict)
            else {}
        )
        sender = str(email_obj.get("address") or email_obj.get("name") or "").strip()
        sender_name = str(email_obj.get("name") or "").strip()

        body_obj = (
            cast(dict[str, Any], msg.get("body")) if isinstance(msg.get("body"), dict) else {}
        )
        body = str(body_obj.get("content") or "").strip()
        snippet = str(msg.get("bodyPreview") or "").strip()
        subject = str(msg.get("subject") or "").strip()
        reference_text = f"{subject}\n{snippet}\n{body}"
        order_number = self._extract_order_number(reference_text)
        invoice_number = self._extract_invoice_number(reference_text)

        return SendungCase(
            id=str(msg.get("id") or "").strip(),
            received_at=str(msg.get("receivedDateTime") or "").strip(),
            sender=sender,
            subject=subject,
            snippet=snippet,
            body=body,
            thread_id=str(msg.get("conversationId") or "").strip(),
            order_number=order_number,
            invoice_number=invoice_number,
            thread_text=str(msg.get("threadText") or "").strip(),
            sender_name=sender_name,
            source_type=_SOURCE_GRAPH,
            source_id=str(msg.get("id") or "").strip(),
        )

    def _find_case(self, case_id: str) -> SendungCase | None:
        cid = str(case_id or "").strip()
        for case in self._load_cached_cases():
            if case.id == cid:
                return case
        return None

    def _full_case_text(
        self,
        case: SendungCase,
        *,
        on_text_loaded: Callable[[str], None] | None = None,
    ) -> str:
        base = case.thread_text or case.body or case.snippet
        if case.source_type != _SOURCE_GRAPH:
            return str(base or "").strip()
        client = self._graph_client()
        if client is None:
            return str(base or "").strip()
        body = ""
        try:
            body = client.get_message_body(case.id).strip()
            if body and on_text_loaded is not None:
                on_text_loaded(body)
        except Exception as exc:  # noqa: BLE001
            logger.debug("Sendung body fetch failed for %s: %s", case.id, exc)
        if case.thread_id:
            try:
                thread = client.get_conversation_thread_text(case.thread_id, days=60, top=30)
                if thread.strip():
                    if on_text_loaded is not None and thread.strip() != body:
                        on_text_loaded(thread)
                    return thread
            except Exception as exc:  # noqa: BLE001
                logger.debug("Sendung conversation fetch failed for %s: %s", case.id, exc)
        if body:
            return body
        return str(base or "").strip()

    def _openai_extract(
        self,
        case: SendungCase,
        api_key: str,
        *,
        thread_text: str | None = None,
        context: _SendungBusinessContext | None = None,
    ) -> SendungExtraction:
        thread_text = str(thread_text if thread_text is not None else self._full_case_text(case))
        context = context or _SendungBusinessContext()
        prompt = (
            "Analysiere den vollstaendigen Mailverlauf fuer die Versandbearbeitung.\n"
            "Ermittle zuerst die aktuelle Absicht: shipment, complaint, address_change, "
            "information_request oder other. Eine Reklamation oder Erwaehnung einer frueheren "
            "Bestellung ist keine neue Bestellung.\n\n"
            "DATENPRIORITAETEN:\n"
            "1. Eine in der Mail ausdruecklich neu genannte oder korrigierte Lieferadresse hat Vorrang.\n"
            "2. Fehlt eine vollstaendige Mail-Lieferadresse, uebernimm die bereitgestellte "
            "System-Lieferadresse wortgetreu. Erfinde niemals eine Adresse.\n"
            "3. Bei eindeutig zugeordneten Rechnungspositionen verwende deren exakte Bezeichnung und "
            "SKU. Setze source_product_index auf die 1-basierte Nummer der passenden Position.\n"
            "4. Bei Reklamationen waehle nur konkret nachzusendende Positionen, niemals pauschal alle "
            "Positionen der urspruenglichen Rechnung. Versandkosten und digitale Downloads sind keine "
            "Versandprodukte.\n"
            "5. summary ist eine interne Handlungszusammenfassung nur fuer das Popup.\n"
            "6. short_note ist ein kurzer kundenfaehiger Text fuer den Lieferschein, maximal "
            "zwei Saetze. Nur konkrete Versandhinweise, keine interne Analyse oder Wiederholung "
            "von Adresse und Produktliste. Wenn kein Hinweis noetig ist, leer lassen.\n\n"
            f"AUTORITATIVE SYSTEMDATEN:\n{self._business_context_prompt(context)}\n\n"
            f"Betreff: {case.subject}\n"
            f"Absender: {case.sender}\n"
            f"Mailverlauf:\n{thread_text}"
        )
        headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
        body = {
            "model": _DEFAULT_MODEL,
            "input": [
                {
                    "role": "system",
                    "content": "Du extrahierst Versandfaelle faktengetreu und antwortest im vorgegebenen Schema.",
                },
                {"role": "user", "content": prompt},
            ],
            "text": {"format": self._openai_extraction_schema()},
            "max_output_tokens": 1200,
            "store": False,
        }
        with httpx.Client(timeout=45.0) as client:
            resp = client.post("https://api.openai.com/v1/responses", headers=headers, json=body)
            resp.raise_for_status()
            payload = resp.json()
        data = self._parse_json_object(self._response_text(payload))
        address_lines = self._restore_street_details(
            self._normalize_address_lines(data.get("address_lines")),
            thread_text,
        )
        extraction = SendungExtraction(
            summary=self._normalize_case_summary(
                str(data.get("summary") or "").strip() or self._fallback_summary(case),
                str(data.get("case_type") or ""),
                thread_text,
            ),
            short_note=str(data.get("short_note") or "").strip(),
            address_lines=address_lines,
            products=self._normalize_products(
                data.get("products"), authoritative_products=context.products
            ),
            order_number=str(
                context.order_number or data.get("order_number") or case.order_number or ""
            ).strip(),
            invoice_number=str(
                context.invoice_number or data.get("invoice_number") or case.invoice_number or ""
            ).strip(),
            customer_name=str(context.customer_name or data.get("customer_name") or "").strip(),
            case_type=str(data.get("case_type") or "other").strip(),
            confidence_notes=[
                str(item).strip()
                for item in data.get("confidence_notes") or []
                if str(item).strip()
            ]
            if isinstance(data.get("confidence_notes"), list)
            else [],
            source="openai",
            updated_at=self._utc_now_iso(),
            thread_text=thread_text,
        )
        if not extraction.products:
            fallback = self._fallback_extract(case, thread_text=thread_text)
            extraction = SendungExtraction(
                summary=extraction.summary,
                short_note=extraction.short_note,
                address_lines=extraction.address_lines or fallback.address_lines,
                products=fallback.products,
                order_number=extraction.order_number or fallback.order_number,
                invoice_number=extraction.invoice_number or fallback.invoice_number,
                customer_name=extraction.customer_name or fallback.customer_name,
                case_type=extraction.case_type or fallback.case_type,
                confidence_notes=extraction.confidence_notes or fallback.confidence_notes,
                source="openai+fallback",
                updated_at=extraction.updated_at,
                thread_text=thread_text,
            )
        return extraction

    @staticmethod
    def _openai_extraction_schema() -> dict[str, object]:
        product_schema = {
            "type": "object",
            "properties": {
                "quantity": {"type": "string"},
                "name": {"type": "string"},
                "sku": {"type": "string"},
                "note": {"type": "string"},
                "source_product_index": {"type": "integer"},
            },
            "required": ["quantity", "name", "sku", "note", "source_product_index"],
            "additionalProperties": False,
        }
        schema = {
            "type": "object",
            "properties": {
                "case_type": {
                    "type": "string",
                    "enum": [
                        "shipment",
                        "complaint",
                        "address_change",
                        "information_request",
                        "other",
                    ],
                },
                "summary": {"type": "string"},
                "short_note": {"type": "string"},
                "customer_name": {"type": "string"},
                "invoice_number": {"type": "string"},
                "order_number": {"type": "string"},
                "address_lines": {"type": "array", "items": {"type": "string"}},
                "products": {"type": "array", "items": product_schema},
                "confidence_notes": {"type": "array", "items": {"type": "string"}},
            },
            "required": [
                "case_type",
                "summary",
                "short_note",
                "customer_name",
                "invoice_number",
                "order_number",
                "address_lines",
                "products",
                "confidence_notes",
            ],
            "additionalProperties": False,
        }
        return {"type": "json_schema", "name": "shipping_case", "strict": True, "schema": schema}

    @staticmethod
    def _business_context_prompt(context: _SendungBusinessContext) -> str:
        products = [
            f"{index}. {item.quantity} x {item.name}"
            f"{f' | SKU {item.sku}' if item.sku else ''}"
            f"{f' | {item.note}' if item.note else ''}"
            for index, item in enumerate(context.products, start=1)
        ]
        return "\n".join(
            [
                f"Kunde: {context.customer_name or '-'}",
                f"sevDesk-Rechnung: {context.invoice_number or '-'}",
                f"Wix-Order: {context.order_number or '-'}",
                "System-Lieferadresse:",
                *(context.address_lines or ("-",)),
                "Rechnungs-/Bestellpositionen:",
                *(products or ["-"]),
            ]
        )

    @staticmethod
    def _normalize_case_summary(summary: str, case_type: str, thread_text: str) -> str:
        """Keep a complaint summary from being phrased as a new order.

        The model has the full conversation and therefore remains responsible
        for the details.  This small guard only fixes the misleading order
        verb when it has explicitly classified the thread as a complaint or
        the mail text clearly contains a complaint marker.
        """
        text = str(summary or "").strip()
        intent = str(case_type or "").strip().casefold()
        thread = str(thread_text or "").casefold()
        is_complaint = intent == "complaint" or any(
            marker in thread
            for marker in (
                "reklam",
                "fehlende",
                "fehlt",
                "nicht erhalten",
                "falsch geliefert",
                "beschädigt",
                "beschaedigt",
            )
        )
        if not text or not is_complaint:
            return text
        # Replace misleading purchase verbs only.  The noun "Bestellung" is a
        # valid historical reference ("bei der letzten Bestellung") and must
        # not turn into ungrammatical text such as "bei der letzten reklamiert".
        corrected = re.sub(r"\b(bestellt|kauft|gekauft)\b", "reklamiert", text, flags=re.IGNORECASE)
        if not corrected.casefold().startswith("reklamation"):
            corrected = f"Reklamation: {corrected}"
        return corrected

    def _fallback_extract(
        self,
        case: SendungCase,
        *,
        thread_text: str | None = None,
    ) -> SendungExtraction:
        text = str(thread_text if thread_text is not None else self._full_case_text(case))
        text = text or case.body or case.snippet
        address = self._extract_address_block(text)
        products = self._extract_product_lines(text)
        return SendungExtraction(
            summary=self._fallback_summary(case),
            address_lines=self._normalize_address_lines(address),
            products=products,
            order_number=self._extract_order_number(f"{case.subject}\n{text}") or case.order_number,
            invoice_number=self._extract_invoice_number(f"{case.subject}\n{text}")
            or case.invoice_number,
            case_type=self._infer_case_type(text),
            confidence_notes=["Fallback-Heuristik verwendet; bitte Adresse und Produkte pruefen."],
            source="fallback",
            updated_at=self._utc_now_iso(),
            thread_text=text,
        )

    def _resolve_business_context(
        self,
        case: SendungCase,
        thread_text: str,
    ) -> _SendungBusinessContext:
        """Resolve typed references against sevDesk first and Wix second."""
        reference_text = f"{case.subject}\n{case.snippet}\n{thread_text}"
        invoice_number = self._extract_invoice_number(reference_text) or case.invoice_number
        order_number = self._extract_order_number(reference_text)
        if not order_number and case.source_type != _SOURCE_GRAPH:
            order_number = case.order_number
        customer_name = ""
        address_lines: list[str] = []
        products: list[SendungProductLine] = []
        sources: list[str] = []
        notes: list[str] = []

        invoice_summary: InvoiceSummary | None = None
        invoice_customer_name = ""
        invoice_address: list[str] = []
        wix_address: list[str] = []
        wix_customer_name = ""
        if self._invoice_client is not None and (invoice_number or order_number):
            try:
                invoice_summary = self._find_invoice_summary(
                    invoice_number=invoice_number,
                    order_number=order_number,
                )
            except Exception as exc:  # noqa: BLE001 - enrichment remains best effort.
                logger.warning("sevDesk lookup failed for sendung %s: %s", case.id, exc)
                notes.append("sevDesk-Zuordnung konnte nicht geladen werden.")

        if invoice_summary is not None and self._invoice_client is not None:
            invoice_number = str(invoice_summary.invoice_number or invoice_number).strip()
            order_number = str(invoice_summary.order_reference or order_number).strip()
            invoice_customer_name = str(invoice_summary.contact_name or "").strip()
            try:
                invoice = self._invoice_client.fetch_invoice_by_id(invoice_summary.id)
                positions = self._invoice_client.fetch_invoice_positions(invoice_summary.id)
                invoice_address = self._invoice_address_lines(invoice, invoice_summary)
                if not self._is_usable_address(invoice_address):
                    invoice_address = []
                    notes.append("sevDesk-Lieferanschrift ist unvollständig.")
                products = self._invoice_product_lines(positions)
                sources.append("sevdesk-invoice")
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "sevDesk details failed for sendung %s invoice=%s: %s",
                    case.id,
                    invoice_number,
                    exc,
                )
                notes.append("sevDesk-Rechnungsdetails konnten nicht vollstaendig geladen werden.")

        customer_emails = {
            match.casefold()
            for match in re.findall(r"[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}", thread_text, re.I)
            if not match.casefold().endswith("@xeisworks.at")
        }
        if (
            case.sender
            and "@" in case.sender
            and not case.sender.casefold().endswith("@xeisworks.at")
        ):
            customer_emails.add(case.sender.casefold())
        customer_email = next(iter(customer_emails)) if len(customer_emails) == 1 else ""

        wix = self._wix_orders
        if wix is not None and (order_number or customer_email):
            try:
                resolver = getattr(wix, "resolve_latest_shipping_address", None)
                if callable(resolver):
                    result = (
                        resolver(reference=order_number, email=customer_email)
                        if customer_email
                        else resolver(reference=order_number)
                    )
                else:
                    result = {}
                wix_lines = (
                    self._normalize_address_lines(result.get("address_lines"))
                    if isinstance(result, dict)
                    else []
                )
                if wix_lines and self._is_usable_address(wix_lines):
                    resolved_order = str(result.get("order_number") or "").strip()
                    if resolved_order == order_number or (
                        not order_number and customer_email and resolved_order
                    ):
                        wix_address = wix_lines
                        order_number = resolved_order
                        sources.append(str(result.get("source") or "wix-order").strip())
                    else:
                        notes.append("Wix-Lieferadresse gehört zu einer anderen Bestellung.")
                elif wix_lines:
                    notes.append("Wix-Lieferanschrift ist unvollständig.")

                summary_resolver = getattr(wix, "resolve_order_summary", None)
                wix_summary = summary_resolver(order_number) if callable(summary_resolver) else {}
                if isinstance(wix_summary, dict):
                    wix_customer_name = str(wix_summary.get("wix_customer_name") or "").strip()

                if not products:
                    item_loader = getattr(wix, "fetch_order_line_items", None)
                    wix_items = item_loader(order_number) if callable(item_loader) else []
                    for item in wix_items or []:
                        if bool(getattr(item, "is_digital", False)):
                            continue
                        name = str(getattr(item, "name", "") or "").strip()
                        if not name or self._is_non_product_position(name):
                            continue
                        products.append(
                            SendungProductLine(
                                quantity=str(getattr(item, "qty", 1) or 1),
                                name=name,
                                sku=str(getattr(item, "sku", "") or "").strip(),
                                note=str(getattr(item, "note", "") or "").strip(),
                            )
                        )
                    if products:
                        sources.append("wix-products")
            except Exception as exc:  # noqa: BLE001
                logger.warning("Wix order lookup failed for sendung %s: %s", case.id, exc)
                notes.append("Wix-Bestelldaten konnten nicht vollstaendig geladen werden.")

        invoice_names = [line for line in invoice_address[:2] if not re.search(r"\d", line)]
        wix_names = [line for line in wix_address[:2] if not re.search(r"\d", line)]
        invoice_matches = bool(invoice_address) and (
            any(self._name_matches_case(name, case, thread_text) for name in invoice_names)
            or any(
                self._names_match(invoice_name, wix_name)
                for invoice_name in invoice_names
                for wix_name in wix_names
            )
        )
        wix_matches = bool(wix_address) and (
            any(self._name_matches_case(name, case, thread_text) for name in wix_names)
            or any(
                self._names_match(wix_name, invoice_name)
                for wix_name in wix_names
                for invoice_name in invoice_names
            )
        )
        if wix_matches:
            address_lines = wix_address
            customer_name = wix_customer_name or wix_names[0]
        elif invoice_matches:
            address_lines = invoice_address
            customer_name = invoice_customer_name or invoice_names[0]
        elif wix_address or invoice_address:
            notes.append("Bestell-/Rechnungsadresse nicht übernommen: Name nicht bestätigt.")

        if address_lines and self._outgoing_salutation_conflicts(case, thread_text, address_lines[0]):
            address_lines = []
            customer_name = ""
            notes.append("Lieferanschrift widerspricht der Anrede in der aktuellen Mail.")

        return _SendungBusinessContext(
            invoice_number=invoice_number,
            order_number=order_number,
            customer_name=customer_name,
            address_lines=tuple(address_lines),
            products=tuple(products),
            source="+".join(dict.fromkeys(source for source in sources if source)),
            confidence_notes=tuple(notes),
        )

    @staticmethod
    def _name_parts(value: str) -> list[tuple[str, ...]]:
        variants: list[tuple[str, ...]] = []
        for part in str(value or "").split("/"):
            plain = unicodedata.normalize("NFKD", part.casefold().replace("ß", "ss"))
            plain = "".join(char for char in plain if not unicodedata.combining(char))
            # Wix may spell an umlaut as ae/oe/ue while the mail uses ä/ö/ü.
            plain = plain.replace("ae", "a").replace("oe", "o").replace("ue", "u")
            tokens = tuple(
                token
                for token in re.findall(r"[a-z0-9]+", plain)
                if token not in {"herr", "herrn", "frau", "firma", "mag", "dr", "gmbh"}
            )
            if tokens:
                variants.append(tokens)
        return variants

    @classmethod
    def _outgoing_salutation_conflicts(
        cls, case: SendungCase, thread_text: str, recipient_name: str
    ) -> bool:
        if not case.sender.casefold().endswith("@xeisworks.at"):
            return False
        current_message = str(thread_text or "").split("\n\n---\n\n", 1)[0]
        match = re.search(
            r"(?im)^\s*(?:hallo|liebe[rn]?|sehr geehrte[rn]?)\s+"
            r"(?:herrn?|frau)\s+([A-Za-zÀ-ÿ-]+)\b",
            current_message,
        )
        if not match:
            return False
        addressee = cls._name_parts(match.group(1))
        recipients = cls._name_parts(recipient_name)
        return bool(
            addressee
            and recipients
            and addressee[0][-1] not in {token for variant in recipients for token in variant}
        )

    @classmethod
    def _names_match(cls, left: str, right: str) -> bool:
        for first in cls._name_parts(left):
            for second in cls._name_parts(right):
                if len(first) == len(second) == 1:
                    if first == second and len(first[0]) >= 5:
                        return True
                elif len(first) >= 2 and len(second) >= 2:
                    if set(first).issubset(second) or set(second).issubset(first):
                        return True
        return False

    @classmethod
    def _name_matches_case(cls, name: str, case: SendungCase, thread_text: str) -> bool:
        if cls._names_match(name, case.sender_name):
            return True
        plain = unicodedata.normalize(
            "NFKD", f"{case.subject}\n{case.snippet}\n{thread_text}".casefold().replace("ß", "ss")
        )
        plain = "".join(char for char in plain if not unicodedata.combining(char))
        plain = plain.replace("ae", "a").replace("oe", "o").replace("ue", "u")
        plain = " ".join(re.findall(r"[a-z0-9]+", plain))
        for tokens in cls._name_parts(name):
            if len(tokens) >= 2 and (
                " ".join(tokens) in plain or " ".join(reversed(tokens)) in plain
            ):
                return True
            if len(tokens) >= 2 and len(tokens[-1]) >= 5 and re.search(
                rf"\b(?:herr|herrn|frau)\s+{re.escape(tokens[-1])}\b", plain
            ):
                return True
            if len(tokens) == 1 and len(tokens[0]) >= 6 and re.search(
                rf"\b{re.escape(tokens[0])}\b", plain
            ):
                return True
        return False

    def _find_invoice_summary(
        self,
        *,
        invoice_number: str,
        order_number: str,
    ) -> InvoiceSummary | None:
        client = self._invoice_client
        if client is None:
            return None
        query = str(invoice_number or order_number or "").strip()
        if not query:
            return None
        matches, _searched_days = client.search_invoice_summaries(query)
        normalized_invoice = self._normalize_invoice_reference(invoice_number)
        normalized_order = str(order_number or "").strip()
        exact = [
            summary
            for summary in matches
            if (
                normalized_invoice
                and self._normalize_invoice_reference(summary.invoice_number) == normalized_invoice
            )
            or (normalized_order and str(summary.order_reference or "").strip() == normalized_order)
        ]
        return exact[0] if exact else None

    @classmethod
    def _invoice_address_lines(
        cls,
        invoice: dict[str, Any],
        summary: InvoiceSummary,
    ) -> list[str]:
        contact = (
            cast(dict[str, Any], invoice.get("contact"))
            if isinstance(invoice.get("contact"), dict)
            else {}
        )
        name = str(
            invoice.get("deliveryName")
            or invoice.get("shippingName")
            or invoice.get("name")
            or contact.get("name")
            or summary.contact_name
            or ""
        ).strip()
        street = str(
            invoice.get("deliveryStreet")
            or invoice.get("shippingStreet")
            or invoice.get("street")
            or ""
        ).strip()
        zip_code = str(
            invoice.get("deliveryZip") or invoice.get("shippingZip") or invoice.get("zip") or ""
        ).strip()
        city = str(
            invoice.get("deliveryCity") or invoice.get("shippingCity") or invoice.get("city") or ""
        ).strip()
        country = country_label_for_address(
            invoice.get("deliveryAddressCountry")
            or invoice.get("shippingCountry")
            or invoice.get("addressCountry")
            or summary.display_country
            or ""
        )
        structured = [
            part
            for part in (name, street, " ".join(p for p in (zip_code, city) if p), country)
            if part
        ]
        if cls._is_usable_address(structured):
            return structured

        for key in ("deliveryAddress", "shippingAddress", "address"):
            raw = invoice.get(key)
            if not isinstance(raw, str) or not raw.strip():
                continue
            text = re.sub(r"(?i)<br\s*/?>", "\n", raw)
            lines = [line.strip(" ,") for line in text.splitlines() if line.strip(" ,")]
            lines = [line for line in lines if line.casefold() not in {"herrn", "frau", "firma"}]
            if country and country.casefold() not in {line.casefold() for line in lines}:
                lines.append(country)
            if cls._is_usable_address(lines):
                return lines[:8]
        return structured[:8]

    @classmethod
    def _invoice_product_lines(cls, positions: list[dict[str, Any]]) -> list[SendungProductLine]:
        products: list[SendungProductLine] = []
        for position in positions:
            name = str(position.get("name") or position.get("text") or "").strip()
            if not name or cls._is_non_product_position(name):
                continue
            part = (
                cast(dict[str, Any], position.get("part"))
                if isinstance(position.get("part"), dict)
                else {}
            )
            note = str(position.get("text") or "").strip()
            if note.casefold() == name.casefold():
                note = ""
            products.append(
                SendungProductLine(
                    quantity=cls._format_quantity(position.get("quantity")),
                    name=name,
                    sku=str(part.get("partNumber") or position.get("partNumber") or "").strip(),
                    note=note,
                )
            )
        return products

    @staticmethod
    def _format_quantity(value: object) -> str:
        text = str(value if value not in (None, "") else "1").strip().replace(",", ".")
        try:
            number = float(text)
        except ValueError:
            return text or "1"
        return str(int(number)) if number.is_integer() else f"{number:g}"

    @staticmethod
    def _is_non_product_position(name: str) -> bool:
        normalized = re.sub(r"[^a-z0-9]+", " ", str(name or "").casefold())
        return any(
            marker in f" {normalized} "
            for marker in (
                " versand ",
                " versandkosten ",
                " express versand ",
                " porto ",
                " shipping ",
                " rabatt ",
                " gutschrift ",
            )
        )

    def _apply_business_context(
        self,
        case: SendungCase,
        extraction: SendungExtraction,
        context: _SendungBusinessContext,
    ) -> SendungExtraction:
        explicit_customer = (
            extraction.customer_name
            if extraction.customer_name
            and self._name_matches_case(extraction.customer_name, case, extraction.thread_text)
            else ""
        )
        context_customer = context.customer_name
        context_address = list(context.address_lines)
        conflicting_context = bool(
            explicit_customer
            and context_customer
            and not self._names_match(explicit_customer, context_customer)
        )
        if conflicting_context:
            context_customer = ""
            context_address = []
        address_lines = list(extraction.address_lines)
        address_from_system = False
        mail_address_is_supported = self._is_usable_address(
            address_lines
        ) and self._address_supported_by_text(address_lines, extraction.thread_text)
        confirmed_name = explicit_customer or context_customer
        if confirmed_name and self._name_matches_case(confirmed_name, case, extraction.thread_text):
            mail_address_is_supported = (
                mail_address_is_supported
                and not self._address_conflicts_with_customer(address_lines, confirmed_name)
            )
        if not mail_address_is_supported:
            address_lines = context_address
            address_from_system = bool(address_lines)

        products = list(extraction.products)
        if not products and extraction.case_type == "shipment" and context.products:
            products = list(context.products)

        invoice_number = (
            context.invoice_number
            or extraction.invoice_number
            or case.invoice_number
            or self._extract_invoice_number(extraction.thread_text)
        )
        order_number = (
            context.order_number
            or self._extract_order_number(extraction.thread_text)
            or (case.order_number if case.source_type != _SOURCE_GRAPH else "")
        )
        customer_name = (
            context_customer
            or extraction.customer_name
            or (address_lines[0] if address_lines else "")
            or case.sender_name
        )
        source_parts = [part for part in extraction.source.split("+") if part]
        source_parts.extend(part for part in context.source.split("+") if part)
        if address_from_system:
            source_parts.append("address-fallback")
        source = "+".join(dict.fromkeys(source_parts))
        confidence_notes = list(extraction.confidence_notes or [])
        confidence_notes.extend(context.confidence_notes)
        if conflicting_context:
            confidence_notes.append(
                "Systemadresse gehört zu einem anderen Kunden; bitte Lieferanschrift prüfen."
            )
        if context.invoice_number and not context.products:
            confidence_notes.append(
                "Rechnung zugeordnet, aber keine versandfaehige Position gefunden."
            )
        if not products:
            confidence_notes.append("Versandprodukt fehlt; bitte vor dem Lieferschein ergänzen.")

        return SendungExtraction(
            summary=self._clear_case_summary(
                extraction.summary,
                customer_name=customer_name,
                invoice_number=invoice_number,
                order_number=order_number,
                products=products,
                address_lines=address_lines,
            ),
            short_note=extraction.short_note,
            address_lines=address_lines,
            products=products,
            order_number=order_number,
            invoice_number=invoice_number,
            customer_name=customer_name,
            case_type=extraction.case_type,
            confidence_notes=list(dict.fromkeys(note for note in confidence_notes if note)),
            source=source or extraction.source,
            updated_at=extraction.updated_at or self._utc_now_iso(),
            thread_text=extraction.thread_text,
        )

    @staticmethod
    def _clear_case_summary(
        action_summary: str,
        *,
        customer_name: str,
        invoice_number: str,
        order_number: str,
        products: list[SendungProductLine],
        address_lines: list[str],
    ) -> str:
        references = " / ".join(
            part
            for part in (
                invoice_number,
                f"Wix {order_number}" if order_number else "",
            )
            if part
        )
        product_text = "; ".join(
            f"{product.quantity or '1'} x {product.name}" for product in products[:4]
        )
        if len(products) > 4:
            product_text += f"; +{len(products) - 4} weitere"
        address_text = ", ".join(address_lines[:4])
        lines = [
            " | ".join(
                part
                for part in (
                    f"Kunde: {customer_name}" if customer_name else "",
                    f"Bezug: {references}" if references else "",
                )
                if part
            ),
            str(action_summary or "").strip(),
            f"Produkte: {product_text}" if product_text else "Produkte: nicht eindeutig erkannt",
            f"Lieferanschrift: {address_text}"
            if address_text
            else "Lieferanschrift: nicht erkannt",
        ]
        return "\n".join(line for line in lines if line)

    @staticmethod
    def _is_usable_address(lines: list[str] | tuple[str, ...]) -> bool:
        normalized = [str(line or "").strip() for line in lines if str(line or "").strip()]
        if len(normalized) < 3:
            return False
        has_postal_city = any(
            re.search(r"\b\d{4,6}\b", line) and re.search(r"[A-Za-zÀ-ÖØ-öø-ÿ]", line)
            for line in normalized
        )
        has_street = any(
            re.search(r"\d", line) and not re.match(r"^\s*\d{4,6}\b", line) for line in normalized
        )
        return bool(has_postal_city and has_street)

    @staticmethod
    def _address_supported_by_text(
        lines: list[str] | tuple[str, ...],
        source_text: str,
    ) -> bool:
        """Require the extracted street and postal code to occur in the mail."""
        source = re.sub(r"[^a-z0-9]+", " ", str(source_text or "").casefold())
        source = " ".join(source.split())
        if not source:
            return False
        postal_codes = [
            match.group(0)
            for line in lines
            for match in re.finditer(r"\b\d{4,6}\b", str(line or ""))
        ]
        street_candidates = [
            re.sub(r"[^a-z0-9]+", " ", str(line or "").casefold()).strip()
            for line in lines
            if re.search(r"\d", str(line or "")) and not re.match(r"^\s*\d{4,6}\b", str(line or ""))
        ]
        has_postal = any(code in source for code in postal_codes)
        has_street = any(street and street in source for street in street_candidates)
        return bool(has_postal and has_street)

    @staticmethod
    def _infer_case_type(text: str) -> str:
        normalized = str(text or "").casefold()
        if any(
            marker in normalized
            for marker in (
                "reklam",
                "fehlte",
                "fehlten",
                "fehlt",
                "nicht erhalten",
                "falsch geliefert",
                "beschädigt",
                "beschaedigt",
            )
        ):
            return "complaint"
        if any(marker in normalized for marker in ("adressänder", "adressaender", "neue adresse")):
            return "address_change"
        if any(
            marker in normalized for marker in ("versenden", "verschicken", "sendung", "lieferung")
        ):
            return "shipment"
        return "other"

    @staticmethod
    def _response_text(payload: dict[str, Any]) -> str:
        text = str(payload.get("output_text") or "").strip()
        if text:
            return text
        output = payload.get("output")
        if isinstance(output, list):
            chunks: list[str] = []
            for item in output:
                if not isinstance(item, dict):
                    continue
                content = item.get("content")
                if not isinstance(content, list):
                    continue
                for block in content:
                    if isinstance(block, dict) and block.get("type") in {"output_text", "text"}:
                        value = str(block.get("text") or "").strip()
                        if value:
                            chunks.append(value)
            return "\n".join(chunks).strip()
        return ""

    @staticmethod
    def _parse_json_object(raw_text: str) -> dict[str, Any]:
        text = str(raw_text or "").strip()
        if not text:
            raise RuntimeError("OpenAI Antwort leer")
        if text.startswith("```"):
            text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.IGNORECASE)
            text = re.sub(r"\s*```$", "", text)
        start = text.find("{")
        end = text.rfind("}")
        if start >= 0 and end > start:
            text = text[start : end + 1]
        data = json.loads(text)
        if not isinstance(data, dict):
            raise RuntimeError("OpenAI Antwort ist kein JSON-Objekt")
        return data

    @staticmethod
    def _normalize_address_lines(value: object) -> list[str]:
        if not isinstance(value, list):
            return []
        return [str(line).strip() for line in value if str(line).strip()][:8]

    @staticmethod
    def _restore_street_details(address_lines: list[str], source_text: str) -> list[str]:
        """Restore house number/unit suffixes that an AI response shortened."""
        result = list(address_lines)
        source = re.sub(r"[\t\r\n]+", " ", str(source_text or ""))
        source = re.sub(r"\s+", " ", source).strip()
        if not source:
            return result
        postal_pattern = r"(?=\s+\d{4,5}\s+[A-Za-zÀ-ÖØ-öø-ÿ])"
        for index, line in enumerate(result):
            street = str(line or "").strip().rstrip(" ,.;")
            street_hint = re.search(
                r"(?:straße|strasse|str\.?|gasse|weg|platz|allee|road|street|lane|avenue|drive)\b",
                street,
                flags=re.IGNORECASE,
            )
            if not street or (not street_hint and not re.search(r"\d", street)):
                continue
            match = re.search(
                rf"\b{re.escape(street)}\b\s+(.+?){postal_pattern}",
                source,
                flags=re.IGNORECASE,
            )
            if not match:
                continue
            suffix = match.group(1).strip(" ,.;")
            if not re.search(r"\d", suffix) or len(suffix) > 60:
                continue
            result[index] = f"{street} {suffix}"
            break
        return result

    def _normalize_products(
        self,
        value: object,
        *,
        authoritative_products: tuple[SendungProductLine, ...] = (),
    ) -> list[SendungProductLine]:
        if not isinstance(value, list):
            return []
        products: list[SendungProductLine] = []
        for item in value:
            if isinstance(item, dict):
                authoritative: SendungProductLine | None = None
                try:
                    source_index = int(item.get("source_product_index") or 0)
                except (TypeError, ValueError):
                    source_index = 0
                if 1 <= source_index <= len(authoritative_products):
                    authoritative = authoritative_products[source_index - 1]
                product = SendungProductLine(
                    quantity=str(item.get("quantity") or "1").strip() or "1",
                    name=(
                        authoritative.name
                        if authoritative is not None
                        else str(item.get("name") or "").strip()
                    ),
                    sku=(
                        authoritative.sku
                        if authoritative is not None
                        else str(item.get("sku") or "").strip()
                    ),
                    note=str(
                        item.get("note")
                        or (authoritative.note if authoritative is not None else "")
                    ).strip(),
                    free_delivery=self._as_bool(item.get("free_delivery"), default=True),
                    delivery_price=str(item.get("delivery_price") or "5,90").strip() or "5,90",
                    no_return_required=self._as_bool(item.get("no_return_required"), default=True),
                )
            else:
                product = SendungProductLine(name=str(item or "").strip())
            if product.name:
                products.append(product)
        return products

    @staticmethod
    def _as_bool(value: object, *, default: bool) -> bool:
        if isinstance(value, bool):
            return value
        if value is None:
            return default
        return str(value).strip().casefold() not in {"", "0", "false", "no", "nein", "off"}

    @staticmethod
    def _extract_address_block(text: str) -> list[str]:
        lines = [line.strip(" \t|") for line in str(text or "").splitlines()]
        labels = (
            "versandadresse",
            "lieferadresse",
            "shipping address",
            "ship to",
            "empfaenger",
            "empfänger",
        )
        stops = (
            "rechnungsadresse",
            "billing",
            "bestell",
            "produkt",
            "artikel",
            "zahlung",
            "gesamt",
            "subtotal",
            "mit freundlichen",
            "www.",
        )
        for idx, line in enumerate(lines):
            low = line.lower().rstrip(":")
            if not any(label in low for label in labels):
                continue
            block: list[str] = []
            for candidate in lines[idx + 1 : idx + 10]:
                stripped = candidate.strip()
                if not stripped:
                    if block:
                        break
                    continue
                low_candidate = stripped.lower().rstrip(":")
                if any(stop in low_candidate for stop in stops):
                    break
                if len(stripped) > 120:
                    continue
                block.append(stripped)
            if len(block) >= 2:
                return block[:8]
        return []

    def _extract_product_lines(self, text: str) -> list[SendungProductLine]:
        products: list[SendungProductLine] = []
        seen: set[str] = set()
        stop_words = {"summe", "gesamt", "versand", "zahlung", "rabatt", "steuer", "mwst"}
        for raw in str(text or "").splitlines():
            line = re.sub(r"\s+", " ", raw.strip(" \t|-*")).strip()
            if len(line) < 4 or len(line) > 180:
                continue
            low = line.lower()
            if any(word in low for word in stop_words):
                continue
            qty = "1"
            name = ""
            sku = ""
            match = re.match(
                r"(?:(\d+)\s*(?:x|stk\.?|stueck|stück)\s+)(.+)", line, flags=re.IGNORECASE
            )
            if match:
                qty, name = match.group(1), match.group(2).strip()
            elif re.search(r"\b(sku|artikel|produkt|buch|noten|cd|pdf)\b", low):
                name = line
            if not name:
                continue
            sku_match = re.search(
                r"\b(?:sku|artikelnummer|art\.?-?nr\.?)[:\s]+([A-Z0-9._-]{2,})", name, re.IGNORECASE
            )
            if sku_match:
                sku = sku_match.group(1).strip()
            key = f"{qty}|{name}".casefold()
            if key in seen:
                continue
            seen.add(key)
            products.append(SendungProductLine(quantity=qty, name=name, sku=sku))
            if len(products) >= 20:
                break
        return products

    def _render_delivery_note_pdf(
        self,
        case: SendungCase,
        *,
        address_lines: list[str],
        products: list[SendungProductLine],
        short_note: str,
    ) -> Path:
        try:
            import fitz  # type: ignore[import-untyped]
        except Exception as exc:  # pragma: no cover
            raise RuntimeError("PyMuPDF fuer Lieferschein-PDF nicht verfuegbar") from exc

        out_dir = self._repo_root() / "state" / "generated" / "lieferscheine"
        out_dir.mkdir(parents=True, exist_ok=True)
        extraction = self._load_saved_extraction(case.id)
        order_number = (
            extraction.order_number if extraction is not None else ""
        ) or case.order_number
        invoice_number = (
            extraction.invoice_number if extraction is not None else ""
        ) or case.invoice_number
        stem = self._safe_filename_part(
            order_number or invoice_number or case.subject or case.id,
            fallback="sendung",
        )
        out_path = out_dir / f"lieferschein_{stem}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.pdf"

        doc = fitz.open()
        page = doc.new_page(width=595, height=842)
        margin = 50
        logo_path = self._repo_root() / "icons" / "logo NEU.png"
        if logo_path.exists():
            page.insert_image(
                fitz.Rect(margin, 24, margin + 190, 115),
                filename=str(logo_path),
                keep_proportion=True,
            )
        page.insert_text(
            (margin, 148), "LIEFERSCHEIN", fontsize=28, fontname="helv", color=(0.08, 0.08, 0.08)
        )
        page.draw_line((margin, 162), (545, 162), color=(0.84, 0.09, 0.09), width=2.2)
        meta = [
            f"Datum: {datetime.now().strftime('%d.%m.%Y')}",
        ]
        if order_number:
            meta.append(f"Wix-Bestellung: {order_number}")
        if invoice_number:
            meta.append(f"sevDesk-Rechnung: {invoice_number}")
        page.insert_textbox(
            fitz.Rect(330, 72, 545, 130),
            "\n".join(meta),
            fontsize=9.0,
            align=2,
            color=(0.25, 0.25, 0.25),
        )

        y = 190.0
        page.insert_text(
            (margin, y), "Lieferadresse", fontsize=13, fontname="helv", color=(0.84, 0.09, 0.09)
        )
        address_fit = page.insert_textbox(
            fitz.Rect(margin, y + 12, 280, y + 104),
            "\n".join(address_lines),
            fontsize=11,
            color=(0.05, 0.05, 0.05),
        )
        if address_fit < 0:
            raise ValueError("Lieferanschrift ist für den Lieferschein zu lang")
        if short_note:
            page.insert_text(
                (320, y), "Kurznotiz", fontsize=13, fontname="helv", color=(0.84, 0.09, 0.09)
            )
            note_fit = page.insert_textbox(
                fitz.Rect(320, y + 12, 545, y + 120),
                short_note,
                fontsize=9.5,
                color=(0.18, 0.18, 0.18),
            )
            if note_fit < 0:
                raise ValueError("Kurznotiz ist für den Lieferschein zu lang")

        def wrap_lines(value: str, width: float, size: float) -> list[str]:
            lines: list[str] = []
            for paragraph in str(value or "").splitlines() or [""]:
                words = paragraph.split()
                if not words:
                    lines.append("")
                    continue
                current = ""
                for word in words:
                    candidate = f"{current} {word}".strip()
                    if current and fitz.get_text_length(
                        candidate, fontname="helv", fontsize=size
                    ) > width:
                        lines.append(current)
                        current = word
                    else:
                        current = candidate
                lines.append(current)
            return lines

        def draw_footer(current_page: Any) -> None:
            current_page.draw_line(
                (margin, 745), (545, 745), color=(0.76, 0.76, 0.76), width=0.6
            )
            footer = (
                f"{_FOOTER_LINES[0]}  |  {_FOOTER_LINES[1]}\n"
                f"{_FOOTER_LINES[2]}  |  {_FOOTER_LINES[3]}\n"
                f"{_FOOTER_LINES[4]}  |  {_FOOTER_LINES[5]}"
            )
            current_page.insert_textbox(
                fitz.Rect(margin, 755, 545, 810),
                footer,
                fontsize=7.5,
                lineheight=1.15,
                align=1,
                color=(0.38, 0.38, 0.38),
            )

        def draw_table_header(current_page: Any, top: float) -> float:
            current_page.draw_rect(
                fitz.Rect(margin, top, 545, top + 36),
                color=(0.84, 0.09, 0.09),
                fill=(0.84, 0.09, 0.09),
            )
            current_page.insert_text((margin + 10, top + 22), "Menge", fontsize=10, color=(1, 1, 1))
            current_page.insert_text((margin + 72, top + 22), "Produkt", fontsize=10, color=(1, 1, 1))
            current_page.insert_text(
                (margin + 360, top + 22),
                "Versand / R\u00fccksendung",
                fontsize=9.5,
                color=(1, 1, 1),
            )
            return top + 36

        y = draw_table_header(page, 330)
        for index, product in enumerate(products):
            detail = " | ".join(part for part in (product.sku, product.note) if part)
            product_text = product.name + (f"\n{detail}" if detail else "")
            product_lines = wrap_lines(product_text, 270, 9.5)
            delivery_text = (
                "Kostenlose Lieferung"
                if product.free_delivery
                else f"Lieferkosten: {str(product.delivery_price or '5,90').strip()} EUR"
            )
            return_text = (
                "Keine R\u00fccksendung erforderlich"
                if product.no_return_required
                else "R\u00fccksendung erforderlich"
            )
            delivery_lines = wrap_lines(f"{delivery_text}\n{return_text}", 125, 8.4)
            row_height = max(48, 18 + max(len(product_lines) * 12, len(delivery_lines) * 11))
            if y + row_height > 730:
                page = doc.new_page(width=595, height=842)
                page.insert_text(
                    (margin, 61),
                    "LIEFERSCHEIN  |  FORTSETZUNG",
                    fontsize=16,
                    color=(0.08, 0.08, 0.08),
                )
                page.draw_line((margin, 75), (545, 75), color=(0.84, 0.09, 0.09), width=1.5)
                y = draw_table_header(page, 96)
            fill = (0.97, 0.97, 0.97) if index % 2 else (1, 1, 1)
            page.draw_rect(
                fitz.Rect(margin, y, 545, y + row_height),
                color=(0.88, 0.88, 0.88),
                fill=fill,
            )
            page.insert_textbox(
                fitz.Rect(margin + 10, y + 7, margin + 60, y + row_height - 3),
                str(product.quantity or "1"),
                fontsize=10,
            )
            product_fit = page.insert_textbox(
                fitz.Rect(margin + 72, y + 3, margin + 350, y + row_height - 2),
                "\n".join(product_lines),
                fontsize=9.5,
            )
            if product_fit < 0:
                raise ValueError(f"Produktzeile {index + 1} ist für den Lieferschein zu lang")
            delivery_fit = page.insert_textbox(
                fitz.Rect(margin + 360, y + 3, 539, y + row_height - 2),
                "\n".join(delivery_lines),
                fontsize=8.4,
            )
            if delivery_fit < 0:
                raise ValueError(f"Versandangabe in Produktzeile {index + 1} ist zu lang")
            y += row_height

        for current_page in doc:
            draw_footer(current_page)

        doc.save(str(out_path))
        doc.close()
        return out_path

    def _load_saved_extraction(self, case_id: str) -> SendungExtraction | None:
        value = self._load_json_map(_EXTRACTIONS_KEY).get(str(case_id or "").strip())
        if not isinstance(value, dict):
            return None
        try:
            schema_version = int(value.get("schema_version") or 0)
        except (TypeError, ValueError):
            schema_version = 0
        if schema_version < _EXTRACTION_SCHEMA_VERSION:
            return None
        return self._extraction_from_dict(value)

    def load_cached_summary(self, case_id: str) -> str:
        """Read an older summary before reanalysis to avoid reusing it as a delivery note."""
        value = self._load_json_map(_EXTRACTIONS_KEY).get(str(case_id or "").strip())
        return str(value.get("summary") or "").strip() if isinstance(value, dict) else ""

    def load_cached_summaries(self, cases: list[SendungCase]) -> dict[str, str]:
        """Fetch popup previews with a single settings read."""
        if not hasattr(self, "_repo"):
            return {}
        saved = self._load_json_map(_EXTRACTIONS_KEY)
        return {
            case.id: str(value.get("summary") or "").strip()
            for case in cases
            if isinstance((value := saved.get(case.id)), dict) and value.get("summary")
        }

    def prefetch_open_case_details(self, *, limit: int = 2) -> None:
        """Warm only the first open cases after invoice loading, without UI work."""
        if not self._secrets.get_secret("OPENAI_API_KEY"):
            return
        for case in self.load_open_cases()[: max(0, min(limit, 2))]:
            if self._load_saved_extraction(case.id) is None:
                try:
                    self.extract_case_details(case.id)
                except Exception as exc:  # noqa: BLE001 - optional warmup
                    logger.debug("Sendung prefetch failed for %s: %s", case.id, exc)

    def _save_extraction(self, case_id: str, extraction: SendungExtraction) -> None:
        with self._cache_lock:
            data = self._load_json_map(_EXTRACTIONS_KEY)
            data[str(case_id or "").strip()] = self._extraction_to_dict(extraction)
            self._save_json_map(_EXTRACTIONS_KEY, data)

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
                    invoice_number=str(item.get("invoice_number") or "").strip(),
                    thread_text=str(item.get("thread_text") or "").strip(),
                    sender_name=str(item.get("sender_name") or "").strip(),
                    source_type=str(
                        item.get("source_type")
                        or (
                            _SOURCE_MANUAL
                            if str(item.get("sender") or "").strip() == _MANUAL_CASE_SENDER
                            else _SOURCE_GRAPH
                        )
                    ).strip(),
                    source_id=str(item.get("source_id") or item.get("id") or "").strip(),
                )
            )
        return out

    def _save_cases(self, cases: list[SendungCase], *, source_mailbox: str | None = None) -> None:
        self._invalidate_memory_cache()
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
                "invoice_number": c.invoice_number,
                "thread_text": c.thread_text,
                "sender_name": c.sender_name,
                "source_type": c.source_type,
                "source_id": c.source_id,
            }
            for c in cases
        ]
        self._repo.set_value_json(_OPEN_CASES_KEY, json.dumps(payload, ensure_ascii=False))
        if source_mailbox is not None:
            self._repo.set_value_json(_SOURCE_MAILBOX_KEY, json.dumps(source_mailbox.lower()))

    def _has_current_mailbox_cache(self) -> bool:
        raw = self._repo.get_value_json(_SOURCE_MAILBOX_KEY) if self._repo is not None else None
        try:
            source_mailbox = str(json.loads(raw)) if raw else ""
        except json.JSONDecodeError:
            source_mailbox = ""
        return source_mailbox.strip().lower() == self._shipping_mailbox().lower()

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
        self._invalidate_memory_cache(names=False)
        if self._repo is not None:
            self._repo.set_value_json(_DONE_CASES_KEY, json.dumps(sorted(ids), ensure_ascii=False))

    def _load_cached_raw_messages(self) -> list[dict[str, Any]]:
        if not self._has_current_mailbox_cache():
            return []
        raw = (
            self._repo.get_value_json(f"{_OPEN_CASES_KEY}.raw_graph")
            if self._repo is not None
            else None
        )
        if not raw:
            return []
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            return []
        return [d for d in data if isinstance(d, dict)] if isinstance(data, list) else []

    def _save_raw_messages(self, messages: list[dict[str, Any]]) -> None:
        if self._repo is not None:
            self._repo.set_value_json(
                f"{_OPEN_CASES_KEY}.raw_graph", json.dumps(messages, ensure_ascii=False)
            )
            self._repo.set_value_json(
                _SOURCE_MAILBOX_KEY, json.dumps(self._shipping_mailbox().lower())
            )

    def _load_json_map(self, key: str) -> dict[str, Any]:
        raw = self._repo.get_value_json(key) if self._repo is not None else None
        return self._parse_json_map(raw)

    @staticmethod
    def _parse_json_map(raw: str | None) -> dict[str, Any]:
        if not raw:
            return {}
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            return {}
        return data if isinstance(data, dict) else {}

    def _save_json_map(self, key: str, value: dict[str, Any]) -> None:
        if key in {_EXTRACTIONS_KEY, _MANUAL_KEY}:
            with self._cache_lock:
                self._recipient_names_cache = None
        if self._repo is not None:
            self._repo.set_value_json(key, json.dumps(value, ensure_ascii=False))

    def _extraction_from_dict(self, data: dict[str, Any]) -> SendungExtraction:
        return SendungExtraction(
            summary=str(data.get("summary") or "").strip(),
            short_note=str(data.get("short_note") or "").strip(),
            address_lines=self._normalize_address_lines(data.get("address_lines")),
            products=self._normalize_products(data.get("products")),
            order_number=str(data.get("order_number") or "").strip(),
            invoice_number=str(data.get("invoice_number") or "").strip(),
            customer_name=str(data.get("customer_name") or "").strip(),
            case_type=str(data.get("case_type") or "other").strip(),
            confidence_notes=[
                str(item).strip()
                for item in data.get("confidence_notes") or []
                if str(item).strip()
            ]
            if isinstance(data.get("confidence_notes"), list)
            else [],
            source=str(data.get("source") or "cached").strip(),
            updated_at=str(data.get("updated_at") or "").strip(),
            thread_text=str(data.get("thread_text") or "").strip(),
        )

    def _extraction_to_dict(self, extraction: SendungExtraction) -> dict[str, Any]:
        return {
            "schema_version": _EXTRACTION_SCHEMA_VERSION,
            "summary": extraction.summary,
            "short_note": extraction.short_note,
            "address_lines": extraction.address_lines,
            "products": [self._product_to_dict(product) for product in extraction.products],
            "order_number": extraction.order_number,
            "invoice_number": extraction.invoice_number,
            "customer_name": extraction.customer_name,
            "case_type": extraction.case_type,
            "confidence_notes": extraction.confidence_notes or [],
            "source": extraction.source,
            "updated_at": extraction.updated_at or self._utc_now_iso(),
            "thread_text": extraction.thread_text,
        }

    @staticmethod
    def _product_to_dict(product: SendungProductLine) -> dict[str, object]:
        return {
            "quantity": str(product.quantity or "").strip(),
            "name": str(product.name or "").strip(),
            "sku": str(product.sku or "").strip(),
            "note": str(product.note or "").strip(),
            "free_delivery": bool(product.free_delivery),
            "delivery_price": str(product.delivery_price or "5,90").strip() or "5,90",
            "no_return_required": bool(product.no_return_required),
        }

    @staticmethod
    def _extract_order_number(text: str) -> str:
        value = str(text or "")
        contextual_patterns = (
            r"(?i)\b(?:wix\s*[- ]?\s*)?order(?:\s*[- ]?\s*(?:nummer|nr\.?|#))?"
            r"\s*[:#-]?\s*(\d{5})\b",
            r"(?i)\b(?:bestellung|bestellnummer|bestell[- ]?nr\.?|auftragsnummer|auftrag[- ]?nr\.?)"
            r"\s*[:#-]?\s*(\d{5})\b",
        )
        for pattern in contextual_patterns:
            match = re.search(pattern, value)
            if match:
                return match.group(1)
        return ""

    @staticmethod
    def _extract_invoice_number(text: str) -> str:
        match = re.search(r"(?i)(?<![A-Z0-9])RE\s*[-–—]?\s*(\d{6})(?!\d)", str(text or ""))
        return f"RE-{match.group(1)}" if match else ""

    @staticmethod
    def _normalize_invoice_reference(value: object) -> str:
        match = re.search(r"(?i)RE\s*[-–—]?\s*(\d{6})", str(value or ""))
        return f"RE-{match.group(1)}" if match else ""

    @staticmethod
    def _utc_now_iso() -> str:
        return datetime.now(timezone.utc).replace(microsecond=0).isoformat()

    @staticmethod
    def _repo_root() -> Path:
        return Path(__file__).resolve().parents[4]

    @staticmethod
    def _safe_filename_part(value: object, *, fallback: str) -> str:
        text = str(value or "").strip() or fallback
        text = re.sub(r"[^\w.-]+", "_", text, flags=re.UNICODE).strip("._")
        return (text or fallback)[:80]
