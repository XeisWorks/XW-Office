"""Offene Sendungen: Graph-backed queue, AI extraction, labels and delivery notes."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import json
import logging
from pathlib import Path
import re
from typing import Any

import httpx

from xw_office.core.config import PrintingSection
from xw_office.repositories.settings_kv import SettingKvRepository
from xw_office.services.mailing.graph_client import GraphMailClient, html_to_text
from xw_office.services.printing.invoice_printer import InvoicePrinter
from xw_office.services.printing.print_queue import PrintQueueService
from xw_office.services.secrets.service import SecretService
from xw_office.services.wix.client import WixOrdersClient

logger = logging.getLogger(__name__)

_OPEN_CASES_KEY = "daily_business.offene_sendungen.cases"
_DONE_CASES_KEY = "daily_business.offene_sendungen.done"
_EXTRACTIONS_KEY = "daily_business.offene_sendungen.extractions"
_MANUAL_KEY = "daily_business.offene_sendungen.manual"
_WIX_ADDRESS_KEY = "daily_business.offene_sendungen.wix_addresses"
_DEFAULT_MODEL = "gpt-4.1-mini"
_EXCLUDED_WIX_SENDER = "no-reply@mystore.wix.com"
_EXCLUDED_ORDER_SENDER = "office@xeisworks.at"
_EXCLUDED_ORDER_SUBJECT_PREFIX = "neue bestellung"
#: Sentinel ``SendungCase.sender`` for cases injected via create_manual_case
#: (e.g. from a Lieferkorrektur) — preserved across refresh_from_graph
#: instead of being overwritten by the next Graph fetch.
_MANUAL_CASE_SENDER = "lieferkorrektur"
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
    thread_text: str = ""


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
    order_number: str = ""
    confidence_notes: list[str] | None = None
    source: str = "fallback"
    updated_at: str = ""
    thread_text: str = ""


class OffeneSendungenService:
    """Manage open shipping requests with persistence and optional AI support."""

    def __init__(
        self,
        settings_repo: SettingKvRepository | None,
        secrets: SecretService,
        wix_orders: WixOrdersClient | None = None,
    ) -> None:
        self._repo = settings_repo
        self._secrets = secrets
        self._wix_orders = wix_orders

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
        candidates = [msg for msg in messages if self._is_sendung_candidate(msg)]
        manual_cases = [case for case in self._load_cached_cases() if case.sender == _MANUAL_CASE_SENDER]
        self._save_cases(manual_cases + [self._to_case(msg) for msg in candidates])
        return self.load_open_cases()

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

        case = SendungCase(
            id=cid,
            received_at=self._utc_now_iso(),
            sender=_MANUAL_CASE_SENDER,
            subject=str(subject or "").strip(),
            snippet=str(note or "").strip(),
            body=str(note or "").strip(),
            thread_id="",
            order_number="",
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
        return case

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
        if done:
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

    def load_manual_fields(self, case_id: str) -> dict[str, Any]:
        data = self._load_json_map(_MANUAL_KEY)
        value = data.get(str(case_id or "").strip())
        return value if isinstance(value, dict) else {}

    def save_manual_fields(
        self,
        case_id: str,
        *,
        address_lines: list[str],
        products: list[SendungProductLine],
        manual_text: str = "",
    ) -> None:
        cid = str(case_id or "").strip()
        if not cid:
            return
        data = self._load_json_map(_MANUAL_KEY)
        data[cid] = {
            "address_lines": [str(line).strip() for line in address_lines if str(line).strip()],
            "products": [self._product_to_dict(product) for product in products],
            "manual_text": str(manual_text or "").strip(),
            "updated_at": self._utc_now_iso(),
        }
        self._save_json_map(_MANUAL_KEY, data)

    def extract_case_details(self, case_id: str, *, force: bool = False) -> SendungExtraction:
        cid = str(case_id or "").strip()
        case = self._find_case(cid)
        if case is None:
            raise RuntimeError("Sendungsfall nicht gefunden")
        if not force:
            cached = self._load_saved_extraction(cid)
            if cached is not None:
                return self._with_wix_shipping_address(case, cached)

        api_key = self._secrets.get_secret("OPENAI_API_KEY")
        if api_key:
            try:
                extraction = self._openai_extract(case, api_key)
                extraction = self._with_wix_shipping_address(case, extraction, refresh=force)
                self._save_extraction(cid, extraction)
                return extraction
            except Exception as exc:  # noqa: BLE001
                logger.warning("OpenAI sendung extraction failed for %s: %s", cid, exc)

        extraction = self._fallback_extract(case)
        extraction = self._with_wix_shipping_address(case, extraction, refresh=force)
        self._save_extraction(cid, extraction)
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
        summary: str = "",
    ) -> Path:
        case = self._find_case(case_id)
        if case is None:
            raise RuntimeError("Sendungsfall nicht gefunden")
        self.save_manual_fields(
            case.id,
            address_lines=address_lines,
            products=products,
            manual_text=manual_text,
        )
        return self._render_delivery_note_pdf(
            case,
            address_lines=[line for line in address_lines if str(line).strip()],
            products=products,
            manual_text=manual_text,
            summary=summary,
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
        InvoicePrinter(printing, print_queue=print_queue).print_pdf_bytes(path.read_bytes(), wait=wait)

    def _fallback_summary(self, case: SendungCase) -> str:
        text = (case.thread_text or case.body or case.snippet or "").strip()
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
            values = client.list_inbox_messages(days=max(1, lookback_days), top=max(1, min(max_items, 200)))
        except Exception as exc:  # noqa: BLE001
            logger.warning("MS Graph fetch failed for offene Sendungen: %s", exc)
            return self._load_cached_raw_messages()
        normalized = [self._normalize_graph_message(item) for item in values]
        filtered = [item for item in normalized if self._is_sendung_candidate(item)]
        self._save_raw_messages(filtered)
        return filtered

    def _graph_client(self, *, write: bool = False) -> GraphMailClient | None:
        tenant_id = self._secrets.get_secret("MS_GRAPH_TENANT_ID")
        client_id = self._secrets.get_secret("MS_GRAPH_CLIENT_ID")
        mailbox = self._secrets.get_secret("MS_GRAPH_MAILBOX")
        if not tenant_id or not client_id:
            return None
        scopes = ["Mail.Read", "Mail.Read.Shared", "Mail.Send", "Mail.Send.Shared"]
        if write:
            scopes.extend(["Mail.ReadWrite", "Mail.ReadWrite.Shared"])
        return GraphMailClient(
            tenant_id=tenant_id,
            client_id=client_id,
            mailbox_user=mailbox or None,
            scopes=scopes,
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
        """Apply the legacy Offene-Sendungen inbox exclusions.

        The legacy Daily Business panel treated every non-system inbox mail as
        actionable. Requiring shipping keywords here hid legitimate replies
        whose subject and preview only contained an order or invoice reference.
        """
        if not str(msg.get("id") or "").strip():
            return False
        flag_obj = msg.get("flag") if isinstance(msg.get("flag"), dict) else {}
        flag_status = str(flag_obj.get("flagStatus") or "").strip().lower()
        if flag_status == "complete":
            return False
        from_obj = msg.get("from") if isinstance(msg.get("from"), dict) else {}
        email_obj = from_obj.get("emailAddress") if isinstance(from_obj.get("emailAddress"), dict) else {}
        sender = str(email_obj.get("address") or "").strip().lower()
        subject = str(msg.get("subject") or "").strip().lower()
        if sender == _EXCLUDED_WIX_SENDER:
            return False
        if sender == _EXCLUDED_ORDER_SENDER and subject.startswith(_EXCLUDED_ORDER_SUBJECT_PREFIX):
            return False
        return True

    def _to_case(self, msg: dict[str, Any]) -> SendungCase:
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
            thread_text=str(msg.get("threadText") or "").strip(),
        )

    def _find_case(self, case_id: str) -> SendungCase | None:
        cid = str(case_id or "").strip()
        for case in self._load_cached_cases():
            if case.id == cid:
                return case
        return None

    def _full_case_text(self, case: SendungCase) -> str:
        base = case.thread_text or case.body or case.snippet
        client = self._graph_client()
        if client is not None and case.thread_id:
            try:
                thread = client.get_conversation_thread_text(case.thread_id, days=60, top=30)
                if thread.strip():
                    return thread
            except Exception as exc:  # noqa: BLE001
                logger.debug("Sendung conversation fetch failed for %s: %s", case.id, exc)
        return str(base or "").strip()

    def _openai_extract(self, case: SendungCase, api_key: str) -> SendungExtraction:
        thread_text = self._full_case_text(case)
        prompt = (
            "Du analysierst den vollstaendigen Mailverlauf einer Shop-Sendung. "
            "Extrahiere die aktuell gueltige Lieferadresse und alle physischen Produkte, "
            "die tatsaechlich verschickt werden muessen. Ignoriere digitale Downloads, "
            "Signaturen, alte ueberholte Adressen und reine Rueckfragen. "
            "Wenn im Verlauf eine Adresse korrigiert wurde, verwende die zuletzt gueltige. "
            "Antworte ausschliesslich als JSON.\n\n"
            "JSON-Schema:\n"
            "{\n"
            '  "summary": "kurze deutsche Zusammenfassung",\n'
            '  "order_number": "Bestellnummer oder leer",\n'
            '  "address_lines": ["Name", "Strasse", "PLZ Ort", "Land"],\n'
            '  "products": [{"quantity": "1", "name": "Produktname", "sku": "optional", "note": "optional"}],\n'
            '  "confidence_notes": ["kurze Hinweise bei Unsicherheit"]\n'
            "}\n\n"
            f"Betreff: {case.subject}\n"
            f"Absender: {case.sender}\n"
            f"Mailverlauf:\n{thread_text}"
        )
        headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
        body = {"model": _DEFAULT_MODEL, "input": prompt, "max_output_tokens": 900}
        with httpx.Client(timeout=45.0) as client:
            resp = client.post("https://api.openai.com/v1/responses", headers=headers, json=body)
            resp.raise_for_status()
            payload = resp.json()
        data = self._parse_json_object(self._response_text(payload))
        extraction = SendungExtraction(
            summary=str(data.get("summary") or "").strip() or self._fallback_summary(case),
            address_lines=self._normalize_address_lines(data.get("address_lines")),
            products=self._normalize_products(data.get("products")),
            order_number=str(data.get("order_number") or case.order_number or "").strip(),
            confidence_notes=[str(item).strip() for item in data.get("confidence_notes") or [] if str(item).strip()]
            if isinstance(data.get("confidence_notes"), list)
            else [],
            source="openai",
            updated_at=self._utc_now_iso(),
            thread_text=thread_text,
        )
        if not extraction.products:
            fallback = self._fallback_extract(case)
            extraction = SendungExtraction(
                summary=extraction.summary,
                address_lines=extraction.address_lines or fallback.address_lines,
                products=fallback.products,
                order_number=extraction.order_number or fallback.order_number,
                confidence_notes=extraction.confidence_notes or fallback.confidence_notes,
                source="openai+fallback",
                updated_at=extraction.updated_at,
                thread_text=thread_text,
            )
        return extraction

    def _fallback_extract(self, case: SendungCase) -> SendungExtraction:
        text = self._full_case_text(case) or case.body or case.snippet
        address = self._extract_address_block(text) or self.create_label_lines(case)
        products = self._extract_product_lines(text)
        return SendungExtraction(
            summary=self._fallback_summary(case),
            address_lines=self._normalize_address_lines(address),
            products=products,
            order_number=case.order_number,
            confidence_notes=["Fallback-Heuristik verwendet; bitte Adresse und Produkte pruefen."],
            source="fallback",
            updated_at=self._utc_now_iso(),
            thread_text=text,
        )

    def _with_wix_shipping_address(
        self,
        case: SendungCase,
        extraction: SendungExtraction,
        *,
        refresh: bool = False,
    ) -> SendungExtraction:
        """Prefer the newest strict Wix shipping address and cache it per case.

        A direct order-number lookup wins.  If no order number is available,
        Wix is searched by the sender email and then by the extracted recipient
        name.  Billing addresses are deliberately never used here.
        """
        wix = self._wix_orders
        if wix is None:
            return extraction
        cache = self._load_json_map(_WIX_ADDRESS_KEY)
        cached = cache.get(case.id)
        if not refresh and isinstance(cached, dict):
            lines = self._normalize_address_lines(cached.get("address_lines"))
            if lines:
                address_source = str(cached.get("source") or "wix-cache").strip()
                combined_source = extraction.source
                if address_source not in combined_source.split("+"):
                    combined_source = f"{combined_source}+{address_source}"
                return SendungExtraction(
                    summary=extraction.summary,
                    address_lines=lines,
                    products=extraction.products,
                    order_number=str(cached.get("order_number") or extraction.order_number).strip(),
                    confidence_notes=extraction.confidence_notes,
                    source=combined_source,
                    updated_at=extraction.updated_at,
                    thread_text=extraction.thread_text,
                )
            if cached.get("not_found") is True:
                return extraction

        recipient_name = extraction.address_lines[0] if extraction.address_lines else ""
        sender_email = (
            case.sender
            if "@" in case.sender and not case.sender.casefold().endswith("@xeisworks.at")
            else ""
        )
        try:
            result = wix.resolve_latest_shipping_address(
                reference=extraction.order_number or case.order_number,
                customer_name=recipient_name,
                email=sender_email,
            )
        except Exception as exc:  # noqa: BLE001 - address enrichment must not block the workflow.
            logger.warning("Wix shipping-address lookup failed for sendung %s: %s", case.id, exc)
            return extraction
        lines = self._normalize_address_lines(result.get("address_lines")) if isinstance(result, dict) else []
        if not lines:
            cache[case.id] = {"not_found": True, "updated_at": self._utc_now_iso()}
            self._save_json_map(_WIX_ADDRESS_KEY, cache)
            return extraction
        order_number = str(result.get("order_number") or extraction.order_number or case.order_number).strip()
        source = str(result.get("source") or "wix").strip()
        cache[case.id] = {
            "address_lines": lines,
            "order_number": order_number,
            "source": source,
            "updated_at": self._utc_now_iso(),
        }
        self._save_json_map(_WIX_ADDRESS_KEY, cache)
        combined_source = extraction.source
        if source not in combined_source.split("+"):
            combined_source = f"{combined_source}+{source}"
        return SendungExtraction(
            summary=extraction.summary,
            address_lines=lines,
            products=extraction.products,
            order_number=order_number,
            confidence_notes=extraction.confidence_notes,
            source=combined_source,
            updated_at=extraction.updated_at,
            thread_text=extraction.thread_text,
        )

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

    def _normalize_products(self, value: object) -> list[SendungProductLine]:
        if not isinstance(value, list):
            return []
        products: list[SendungProductLine] = []
        for item in value:
            if isinstance(item, dict):
                product = SendungProductLine(
                    quantity=str(item.get("quantity") or "1").strip() or "1",
                    name=str(item.get("name") or "").strip(),
                    sku=str(item.get("sku") or "").strip(),
                    note=str(item.get("note") or "").strip(),
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
        labels = ("versandadresse", "lieferadresse", "shipping address", "ship to", "empfaenger", "empfänger")
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
            match = re.match(r"(?:(\d+)\s*(?:x|stk\.?|stueck|stück)\s+)(.+)", line, flags=re.IGNORECASE)
            if match:
                qty, name = match.group(1), match.group(2).strip()
            elif re.search(r"\b(sku|artikel|produkt|buch|noten|cd|pdf)\b", low):
                name = line
            if not name:
                continue
            sku_match = re.search(r"\b(?:sku|artikelnummer|art\.?-?nr\.?)[:\s]+([A-Z0-9._-]{2,})", name, re.IGNORECASE)
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
        manual_text: str,
        summary: str,
    ) -> Path:
        try:
            import fitz
        except Exception as exc:  # pragma: no cover
            raise RuntimeError("PyMuPDF fuer Lieferschein-PDF nicht verfuegbar") from exc

        out_dir = self._repo_root() / "state" / "generated" / "lieferscheine"
        out_dir.mkdir(parents=True, exist_ok=True)
        stem = self._safe_filename_part(case.order_number or case.subject or case.id, fallback="sendung")
        out_path = out_dir / f"lieferschein_{stem}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.pdf"

        doc = fitz.open()
        page = doc.new_page(width=595, height=842)
        margin = 50
        logo_path = self._repo_root() / "icons" / "logo NEU.png"
        if logo_path.exists():
            page.insert_image(fitz.Rect(margin, 46, margin + 150, 104), filename=str(logo_path), keep_proportion=True)
        page.insert_text((margin, 132), "LIEFERSCHEIN", fontsize=28, fontname="helv", color=(0.08, 0.08, 0.08))
        page.draw_line((margin, 146), (545, 146), color=(0.84, 0.09, 0.09), width=2.2)
        meta = [
            f"Datum: {datetime.now().strftime('%d.%m.%Y')}",
            f"Bestellung: {case.order_number or '-'}",
            f"Betreff: {case.subject or '-'}",
        ]
        page.insert_textbox(fitz.Rect(350, 86, 545, 140), "\n".join(meta), fontsize=9.5, align=2, color=(0.25, 0.25, 0.25))

        y = 176
        page.insert_text((margin, y), "Lieferadresse", fontsize=13, fontname="helv", color=(0.84, 0.09, 0.09))
        page.insert_textbox(
            fitz.Rect(margin, y + 12, 280, y + 104),
            "\n".join(address_lines) or "Adresse bitte ergaenzen",
            fontsize=11,
            color=(0.05, 0.05, 0.05),
        )
        if summary:
            page.insert_text((320, y), "Kurznotiz", fontsize=13, fontname="helv", color=(0.84, 0.09, 0.09))
            page.insert_textbox(fitz.Rect(320, y + 12, 545, y + 104), summary[:420], fontsize=9.5, color=(0.18, 0.18, 0.18))

        y = 318
        table_x = margin
        table_w = 495
        row_h = 36
        page.draw_rect(fitz.Rect(table_x, y, table_x + table_w, y + row_h), color=(0.84, 0.09, 0.09), fill=(0.84, 0.09, 0.09))
        page.insert_text((table_x + 10, y + 18), "Menge", fontsize=10, color=(1, 1, 1))
        page.insert_text((table_x + 72, y + 18), "Produkt", fontsize=10, color=(1, 1, 1))
        page.insert_text((table_x + 360, y + 18), "Versand / Rücksendung", fontsize=9.5, color=(1, 1, 1))
        y += row_h
        rows = products or [SendungProductLine(quantity="", name="Produkte bitte ergaenzen")]
        for idx, product in enumerate(rows[:8]):
            fill = (0.97, 0.97, 0.97) if idx % 2 else (1, 1, 1)
            page.draw_rect(fitz.Rect(table_x, y, table_x + table_w, y + row_h), color=(0.88, 0.88, 0.88), fill=fill)
            page.insert_textbox(fitz.Rect(table_x + 10, y + 7, table_x + 60, y + row_h), product.quantity, fontsize=10)
            product_text = product.name
            sku_note = " | ".join(part for part in (product.sku, product.note) if part)
            if sku_note:
                product_text = f"{product_text}\n{sku_note}"
            page.insert_textbox(fitz.Rect(table_x + 72, y + 6, table_x + 350, y + row_h), product_text, fontsize=9.5)
            delivery_text = (
                "Kostenlose Lieferung"
                if product.free_delivery
                else f"Lieferkosten: € {str(product.delivery_price or '5,90').strip()}"
            )
            return_text = (
                "Keine Rücksendung erforderlich"
                if product.no_return_required
                else "Rücksendung eingetroffen"
            )
            page.insert_textbox(
                fitz.Rect(table_x + 360, y + 5, table_x + table_w - 6, y + row_h),
                f"{delivery_text}\n{return_text}",
                fontsize=8.4,
            )
            y += row_h

        if manual_text.strip():
            y += 24
            page.insert_text((margin, y), "Hinweis", fontsize=13, fontname="helv", color=(0.84, 0.09, 0.09))
            page.insert_textbox(fitz.Rect(margin, y + 14, 545, min(y + 110, 720)), manual_text.strip(), fontsize=10.5)

        footer_y = 742
        page.draw_line((margin, footer_y - 16), (545, footer_y - 16), color=(0.72, 0.72, 0.72), width=0.8)
        page.insert_textbox(fitz.Rect(margin, footer_y, 545, 820), "\n".join(_FOOTER_LINES), fontsize=9, align=1, color=(0.22, 0.22, 0.22))
        doc.save(str(out_path))
        doc.close()
        return out_path

    def _load_saved_extraction(self, case_id: str) -> SendungExtraction | None:
        value = self._load_json_map(_EXTRACTIONS_KEY).get(str(case_id or "").strip())
        return self._extraction_from_dict(value) if isinstance(value, dict) else None

    def _save_extraction(self, case_id: str, extraction: SendungExtraction) -> None:
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
                    thread_text=str(item.get("thread_text") or "").strip(),
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
                "thread_text": c.thread_text,
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
        if self._repo is not None:
            self._repo.set_value_json(_DONE_CASES_KEY, json.dumps(sorted(ids), ensure_ascii=False))

    def _load_cached_raw_messages(self) -> list[dict[str, Any]]:
        raw = self._repo.get_value_json(f"{_OPEN_CASES_KEY}.raw_graph") if self._repo is not None else None
        if not raw:
            return []
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            return []
        return [d for d in data if isinstance(d, dict)] if isinstance(data, list) else []

    def _save_raw_messages(self, messages: list[dict[str, Any]]) -> None:
        if self._repo is not None:
            self._repo.set_value_json(f"{_OPEN_CASES_KEY}.raw_graph", json.dumps(messages, ensure_ascii=False))

    def _load_json_map(self, key: str) -> dict[str, Any]:
        raw = self._repo.get_value_json(key) if self._repo is not None else None
        if not raw:
            return {}
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            return {}
        return data if isinstance(data, dict) else {}

    def _save_json_map(self, key: str, value: dict[str, Any]) -> None:
        if self._repo is not None:
            self._repo.set_value_json(key, json.dumps(value, ensure_ascii=False))

    def _extraction_from_dict(self, data: dict[str, Any]) -> SendungExtraction:
        return SendungExtraction(
            summary=str(data.get("summary") or "").strip(),
            address_lines=self._normalize_address_lines(data.get("address_lines")),
            products=self._normalize_products(data.get("products")),
            order_number=str(data.get("order_number") or "").strip(),
            confidence_notes=[str(item).strip() for item in data.get("confidence_notes") or [] if str(item).strip()]
            if isinstance(data.get("confidence_notes"), list)
            else [],
            source=str(data.get("source") or "cached").strip(),
            updated_at=str(data.get("updated_at") or "").strip(),
            thread_text=str(data.get("thread_text") or "").strip(),
        )

    def _extraction_to_dict(self, extraction: SendungExtraction) -> dict[str, Any]:
        return {
            "summary": extraction.summary,
            "address_lines": extraction.address_lines,
            "products": [self._product_to_dict(product) for product in extraction.products],
            "order_number": extraction.order_number,
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
        match = re.search(r"\b\d{4,12}\b", text)
        return match.group(0) if match else ""

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
