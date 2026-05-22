"""Orchestrates invoice-related operations (no UI)."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
import html
import json
import logging
import re
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Callable

from xw_studio.repositories.settings_kv import SettingKvRepository
from xw_studio.core.config import AppConfig
from xw_studio.services.draft_invoice.service import DraftInvoiceService
from xw_studio.services.mailing.service import MailAttachment, MailDeliveryService
from xw_studio.services.printing.invoice_printer import InvoicePrinter
from xw_studio.services.printing.label_printer import LabelPrinter
from xw_studio.services.sevdesk.invoice_client import InvoiceClient, InvoiceSummary
from xw_studio.services.sevdesk.invoice_client import DEFAULT_SENSITIVE_COUNTRY_CODES
from xw_studio.services.wix.client import WixOrdersClient

logger = logging.getLogger(__name__)

_SENSITIVE_COUNTRIES_KEY = "rechnungen.sensitive_country_codes"
_ALLOWED_COUNTRIES_KEY = "rechnungen.allowed_country_codes"
_SKU_FLAGS_KEY = "rechnungen.sku_flags"
_FULFILLMENT_STATUS_KEY = "rechnungen.fulfillment_status"
_FULFILLMENT_MAIL_TEMPLATE_KEY = "rechnungen.fulfillment_mail_template_html"
_FULFILLMENT_MAIL_SUBJECT_KEY = "rechnungen.fulfillment_mail_subject"

_DEFAULT_SKU_FLAGS = {
    "exact": ["XW-010", "XW-011", "XW-600.0"],
    "prefixes": ["XW-4", "XW-6", "XW-7", "XW-12"],
}
_DEFAULT_ALLOWED_COUNTRIES = [
    "Austria",
    "Germany",
    "Belgium",
    "Estonia",
    "Finland",
    "Denmark",
    "Slovenia",
    "Czech Republic",
    "Netherlands",
    "Sweden",
    "Lithuania",
    "Luxembourg",
    "France",
    "Italy",
    "Switzerland",
    "Norway",
    "Oesterreich",
    "Deutschland",
    "Schweiz",
    "Norwegen",
    "AT",
    "BE",
    "EE",
    "FI",
    "DK",
    "SI",
    "CZ",
    "NL",
    "SE",
    "LT",
    "LU",
    "FR",
    "DE",
    "IT",
    "CH",
    "NO",
]
_SKU_TOKEN_RE = re.compile(r"\bXW-[A-Z0-9][A-Z0-9.-]*\b", re.IGNORECASE)
_LEGACY_MAIL_SUBJECT = "Ihre Rechnung {invoice_number}"
_LEGACY_MAIL_BODY = (
    "Guten Tag,\n\n"
    "wir freuen uns, Ihnen mitteilen zu können, dass Ihre Bestellung soeben versendet wurde.\n\n"
    "Die bestellten Produkte befinden sich nun auf dem Weg zu Ihnen. Je nach Versandart und Zielort kann die Zustellung einige Werktage in Anspruch nehmen.\n\n"
    "Die zugehörige Rechnung finden Sie im Anhang dieser E-Mail.\n\n"
    "Sollten Sie in der Zwischenzeit Fragen zu Ihrer Bestellung oder zum Lieferstatus haben, stehen wir Ihnen selbstverständlich gerne zur Verfügung.\n\n"
    "Vielen Dank für Ihr Vertrauen und Ihre Bestellung.\n\n"
    "Mit freundlichen Grüßen\n"
    "XeisWorks\n"
    "Mag. Bernhard Holl\n"
    "Johnsbach 92\n"
    "8912 Admont\n"
    "office@xeisworks.at\n"
    "www.xeisworks.at\n"
)


@dataclass(frozen=True)
class FulfillmentFlags:
    """Persisted fulfillment state shown in the invoice table chips."""

    label_printed: bool = False
    invoice_printed: bool = False
    product_ready: bool = False
    mail_sent: bool = False
    wix_fulfilled: bool = False
    payment_applicable: bool = False
    payment_booked: bool = False
    last_run_iso: str = ""
    last_error: str = ""
    last_warning: str = ""

    def as_row_payload(self) -> dict[str, object]:
        return {
            "label_printed": self.label_printed,
            "invoice_printed": self.invoice_printed,
            "product_ready": self.product_ready,
            "mail_sent": self.mail_sent,
            "wix_fulfilled": self.wix_fulfilled,
            "payment_applicable": self.payment_applicable,
            "payment_booked": self.payment_booked,
            "last_run_iso": self.last_run_iso,
            "last_error": self.last_error,
            "last_warning": self.last_warning,
        }

    @classmethod
    def from_payload(cls, payload: object) -> "FulfillmentFlags":
        if not isinstance(payload, dict):
            return cls()
        return cls(
            label_printed=bool(payload.get("label_printed")),
            invoice_printed=bool(payload.get("invoice_printed")),
            product_ready=bool(payload.get("product_ready")),
            mail_sent=bool(payload.get("mail_sent")),
            wix_fulfilled=bool(payload.get("wix_fulfilled")),
            payment_applicable=bool(payload.get("payment_applicable")),
            payment_booked=bool(payload.get("payment_booked")),
            last_run_iso=str(payload.get("last_run_iso") or ""),
            last_error=str(payload.get("last_error") or ""),
            last_warning=str(payload.get("last_warning") or ""),
        )


@dataclass(frozen=True)
class InvoiceListHintFlags:
    """Legacy-style hint flags for the invoice list."""

    buyer_note: str = ""
    address_mismatch: bool = False
    unreleased_sku: bool = False
    country_invalid: bool = False
    country_label: str = ""
    billing_lines: tuple[str, ...] = ()
    shipping_lines: tuple[str, ...] = ()

    def icon_keys(self) -> list[str]:
        keys: list[str] = []
        if self.unreleased_sku:
            keys.append("print")
        if self.buyer_note.strip():
            keys.append("note")
        if self.address_mismatch:
            keys.append("alternateshippingaddress")
        if self.country_invalid:
            keys.append("country")
        return keys

    def tooltip(self) -> str:
        lines: list[str] = []
        if self.unreleased_sku:
            lines.append("Druck-/SKU-Alarm aktiv (RECHNUNGEN_SKU-FLAGS)")
        if self.buyer_note.strip():
            lines.append("Käufernotiz vorhanden:")
            lines.append(self.buyer_note.strip())
        if self.address_mismatch:
            lines.append("Abweichende Lieferanschrift:")
            lines.append(f"Rechnung: {' | '.join(self.billing_lines) or '-'}")
            lines.append(f"Lieferung: {' | '.join(self.shipping_lines) or '-'}")
        if self.country_invalid:
            lines.append(f"Lieferland außerhalb Freigabe: {self.country_label or '-'}")
        return "\n".join(line for line in lines if str(line).strip())

    def as_row_patch(self) -> dict[str, object]:
        tooltip = self.tooltip()
        return {
            "Hinweise": "",
            "__icons__Hinweise": self.icon_keys(),
            "__tooltip__Hinweise": tooltip,
            "__fg__Hinweise": "#ef4444" if tooltip else "",
        }


class InvoiceProcessingService:
    """Facade over sevDesk invoice clients for the Rechnungen module."""

    def __init__(
        self,
        config: AppConfig,
        invoice_client: InvoiceClient,
        settings_repo: SettingKvRepository | None = None,
        wix_orders: WixOrdersClient | None = None,
        mail_service: MailDeliveryService | None = None,
        draft_invoice_service: DraftInvoiceService | None = None,
    ) -> None:
        self._invoices = invoice_client
        self._settings_repo = settings_repo
        self._wix_orders = wix_orders
        self._invoice_printer = InvoicePrinter(config.printing)
        self._label_printer = LabelPrinter(config.printing)
        self._invoice_pdf_cache: dict[str, bytes] = {}
        self._invoice_detail_cache: dict[str, dict[str, Any]] = {}
        self._wix_address_cache: dict[str, list[str]] = {}
        self._wix_digital_cache: dict[str, bool] = {}
        self._wix_order_summary_cache: dict[str, dict[str, str]] = {}
        self._wix_hint_cache: dict[str, InvoiceListHintFlags] = {}
        self._mail_service = mail_service
        self._drafts = draft_invoice_service

    def load_invoice_table_rows(
        self,
        *,
        status: int | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[dict[str, str]]:
        """Load invoices and return rows for :class:`DataTable` (German keys)."""
        summaries = self._invoices.list_invoice_summaries(
            limit=limit,
            offset=offset,
            status=status,
        )
        self._apply_sensitive_country_flags(summaries)
        self._apply_unreleased_sku_flags(summaries)
        logger.info(
            "Loaded %s invoices from sevDesk (status=%s offset=%s limit=%s)",
            len(summaries),
            status,
            offset,
            limit,
        )
        return self._rows_with_fulfillment(summaries)

    def load_invoice_summaries(
        self,
        *,
        status: int | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[InvoiceSummary]:
        """Return typed summaries (e.g. for detail panel / export)."""
        summaries = self._invoices.list_invoice_summaries(
            limit=limit,
            offset=offset,
            status=status,
        )
        self._apply_sensitive_country_flags(summaries)
        self._apply_unreleased_sku_flags(summaries)
        return summaries

    def load_invoice_batch(
        self,
        *,
        status: int | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[list[dict[str, str]], list[InvoiceSummary]]:
        """Return table rows and parallel summaries for detail view."""
        summaries = self._invoices.list_invoice_summaries(
            limit=limit,
            offset=offset,
            status=status,
        )
        self._apply_sensitive_country_flags(summaries)
        self._apply_unreleased_sku_flags(summaries)
        rows = [s.as_table_row() for s in summaries]
        return self._rows_with_fulfillment(summaries, rows), summaries

    def search_invoice_batch(
        self,
        query: str,
        *,
        initial_window_days: int = 100,
        window_step_days: int = 100,
    ) -> tuple[list[dict[str, str]], list[InvoiceSummary], int]:
        """Search invoices via sevDesk with widening date windows."""
        summaries, searched_days = self._invoices.search_invoice_summaries(
            query,
            initial_window_days=initial_window_days,
            window_step_days=window_step_days,
        )
        self._apply_sensitive_country_flags(summaries)
        self._apply_unreleased_sku_flags(summaries)
        rows = [summary.as_table_row() for summary in summaries]
        return self._rows_with_fulfillment(summaries, rows), summaries, searched_days

    def read_fulfillment_flags(self, invoice_id: str) -> FulfillmentFlags:
        all_flags = self._load_fulfillment_flags_map()
        return all_flags.get(str(invoice_id), FulfillmentFlags())

    def write_fulfillment_flags(self, invoice_id: str, flags: FulfillmentFlags) -> None:
        if self._settings_repo is None:
            return
        all_flags = self._load_fulfillment_flags_map()
        all_flags[str(invoice_id)] = flags
        payload = {
            key: value.as_row_payload()
            for key, value in all_flags.items()
        }
        self._settings_repo.set_value_json(
            _FULFILLMENT_STATUS_KEY,
            json.dumps(payload, ensure_ascii=False),
        )

    def write_fulfillment_flags_batch(self, updates: dict[str, FulfillmentFlags]) -> None:
        if self._settings_repo is None or not updates:
            return
        all_flags = self._load_fulfillment_flags_map()
        for invoice_id, flags in updates.items():
            all_flags[str(invoice_id)] = flags
        payload = {
            key: value.as_row_payload()
            for key, value in all_flags.items()
        }
        self._settings_repo.set_value_json(
            _FULFILLMENT_STATUS_KEY,
            json.dumps(payload, ensure_ascii=False),
        )

    def run_start_fullflow(
        self,
        *,
        full_mode: bool,
        should_abort: Callable[[], bool] | None = None,
        mail_recipient_override: str | None = None,
        invoice_ids: list[str] | None = None,
    ) -> dict[str, object]:
        """Execute invoice processing flow for all open drafts (status=100)."""
        started = time.perf_counter()
        summaries = self._load_all_open_drafts(limit_per_page=100, max_pages=20)
        if invoice_ids:
            wanted = {str(invoice_id).strip() for invoice_id in invoice_ids if str(invoice_id).strip()}
            summaries = [summary for summary in summaries if str(summary.id).strip() in wanted]
        if full_mode:
            self._prefetch_wix_order_context(summaries)
        updates: dict[str, FulfillmentFlags] = {}
        processed = 0
        failures = 0
        successful = 0
        aborted = False
        for summary in summaries:
            if should_abort is not None and should_abort():
                aborted = True
                logger.info("START aborted before invoice %s", summary.id)
                break
            processed += 1
            flags = self.read_fulfillment_flags(summary.id)
            try:
                self._repair_draft_products(summary)
                digital_only = self._is_digital_only(summary) if summary.order_reference.strip() else False
                flags = self._run_finalize_step(
                    summary,
                    flags,
                    digital_only=digital_only,
                    printed_copy=(full_mode and not digital_only),
                )
                if full_mode:
                    if not digital_only:
                        flags = self._run_invoice_print_step(summary, flags)
                        flags = self._run_label_print_step(summary, flags)
                    flags = self._run_product_step(summary, flags)
                flags = self._run_mail_step(summary, flags, recipient_override=mail_recipient_override)
                successful += 1
            except Exception as exc:
                failures += 1
                flags = self._with_error(flags, exc)
            updates[summary.id] = flags
        self.write_fulfillment_flags_batch(updates)
        elapsed_ms = int((time.perf_counter() - started) * 1000)
        logger.info(
            "START metric total_ms=%s processed=%s failures=%s full_mode=%s",
            elapsed_ms,
            processed,
            failures,
            full_mode,
        )
        return {
            "processed": processed,
            "failures": failures,
            "successful": successful,
            "full_mode": full_mode,
            "aborted": aborted,
        }

    def _prefetch_wix_order_context(self, summaries: list[InvoiceSummary]) -> None:
        if self._wix_orders is None or not self._wix_orders.has_credentials():
            return
        refs = sorted({s.order_reference.strip() for s in summaries if s.order_reference.strip()})
        if not refs:
            return

        missing = [
            ref
            for ref in refs
            if ref not in self._wix_address_cache or ref not in self._wix_digital_cache
        ]
        if not missing:
            return

        started = time.perf_counter()
        workers = max(2, min(8, len(missing)))

        def load_ref(ref: str) -> tuple[str, list[str], bool]:
            lines = self._wix_orders.resolve_order_address_lines(ref)
            digital_only = self._wix_orders.is_reference_digital_only(ref)
            return ref, lines, bool(digital_only)

        with ThreadPoolExecutor(max_workers=workers) as pool:
            futures = [pool.submit(load_ref, ref) for ref in missing]
            for fut in as_completed(futures):
                try:
                    ref, lines, digital_only = fut.result()
                    self._wix_address_cache[ref] = list(lines)
                    self._wix_digital_cache[ref] = digital_only
                except Exception as exc:
                    logger.warning("Wix prefetch failed: %s", exc)

        elapsed_ms = int((time.perf_counter() - started) * 1000)
        logger.info(
            "START metric wix_prefetch_ms=%s refs=%s workers=%s",
            elapsed_ms,
            len(missing),
            workers,
        )

    def _get_wix_address_lines_cached(self, reference: str) -> list[str]:
        ref = str(reference or "").strip()
        if not ref or self._wix_orders is None or not self._wix_orders.has_credentials():
            return []
        cached = self._wix_address_cache.get(ref)
        if cached is not None:
            return list(cached)
        lines = self._wix_orders.resolve_order_address_lines(ref)
        self._wix_address_cache[ref] = list(lines)
        return list(lines)

    def _get_wix_order_summary_cached(self, reference: str) -> dict[str, str]:
        ref = str(reference or "").strip()
        if not ref or self._wix_orders is None or not self._wix_orders.has_credentials():
            return {}
        cached = self._wix_order_summary_cache.get(ref)
        if cached is not None:
            return dict(cached)
        summary = self._wix_orders.resolve_order_summary(ref)
        normalized = summary if isinstance(summary, dict) else {}
        self._wix_order_summary_cache[ref] = dict(normalized)
        return dict(normalized)

    def _is_digital_only(self, summary: InvoiceSummary) -> bool:
        ref = str(summary.order_reference or "").strip()
        if not ref or self._wix_orders is None or not self._wix_orders.has_credentials():
            return False
        cached = self._wix_digital_cache.get(ref)
        if cached is not None:
            return bool(cached)
        try:
            resolved = bool(self._wix_orders.is_reference_digital_only(ref))
        except Exception as exc:
            logger.warning("Wix digital-only resolve failed ref=%s: %s", ref, exc)
            resolved = False
        self._wix_digital_cache[ref] = resolved
        return resolved

    def retry_fulfillment_step(
        self,
        invoice_id: str,
        step: str,
        *,
        mail_recipient_override: str | None = None,
    ) -> FulfillmentFlags:
        """Retry one fulfillment step for a single invoice and persist state."""
        summary = self._load_summary_by_id(invoice_id)
        flags = self.read_fulfillment_flags(summary.id)
        if step == "label_printed":
            next_flags = self._run_label_print_step(summary, flags)
        elif step == "invoice_printed":
            next_flags = self._run_invoice_print_step(summary, flags)
        elif step == "product_ready":
            next_flags = self._run_product_step(summary, flags)
        elif step == "mail_sent":
            next_flags = self._run_mail_step(summary, flags, recipient_override=mail_recipient_override)
        elif step == "wix_fulfilled":
            next_flags = self._run_product_step(summary, flags)
        else:
            raise ValueError(f"Unbekannter Schritt: {step}")
        self.write_fulfillment_flags(summary.id, next_flags)
        return next_flags

    def print_label_for_invoice(
        self,
        invoice_id: str,
        *,
        override_lines: list[str] | None = None,
    ) -> FulfillmentFlags:
        """Print one shipping label for *invoice_id* and persist ``label_printed``.

        ``override_lines`` allows UI-edited address lines to be used instead of the
        address resolved from Wix/sevDesk.
        """
        summary = self._load_summary_by_id(invoice_id)
        flags = self.read_fulfillment_flags(summary.id)
        lines = [
            str(line or "").strip()
            for line in (override_lines or [])
            if str(line or "").strip()
        ]
        if not lines:
            full = self._invoices.fetch_invoice_by_id(summary.id)
            lines = self._shipping_lines_from_invoice(full, summary)
        if not lines:
            raise RuntimeError("Keine Lieferadresse für Labeldruck")
        self._label_printer.print_address(lines)
        next_flags = self._next_flags(flags, label_printed=True)
        self.write_fulfillment_flags(summary.id, next_flags)
        return next_flags

    def send_invoice_mail_for_invoice(
        self,
        summary: InvoiceSummary,
        *,
        recipient_override: str | None = None,
    ) -> tuple[FulfillmentFlags, str, str]:
        """Send one invoice manually using the same sevDesk-first path as START."""

        flags = self.read_fulfillment_flags(summary.id)
        invoice = self._fetch_invoice_detail(summary.id)
        to_email = str(recipient_override or "").strip() or self._resolve_customer_email(summary, invoice)
        if not to_email:
            raise RuntimeError("Keine E-Mail-Adresse fuer Rechnungsversand")
        subject, text_body = self._build_mail_content(summary, invoice)
        html_body = self._build_mail_html(text_body)
        sevdesk_error: Exception | None = None
        sender = getattr(self._invoices, "send_invoice_via_email", None)
        if callable(sender):
            try:
                sender(
                    summary.id,
                    to_email=to_email,
                    subject=subject,
                    text=text_body,
                    copy=True,
                )
            except TypeError:
                try:
                    sender(
                        summary.id,
                        to=to_email,
                        subject=subject,
                        text=text_body,
                        copy=True,
                    )
                except Exception as exc:  # noqa: BLE001 - Graph fallback below.
                    sevdesk_error = exc
                    logger.warning("sevDesk invoice mail failed for %s: %s", summary.id, exc)
                else:
                    next_flags = self._next_flags(flags, mail_sent=True)
                    self.write_fulfillment_flags(summary.id, next_flags)
                    return next_flags, to_email, subject
            except Exception as exc:  # noqa: BLE001 - Graph fallback below.
                sevdesk_error = exc
                logger.warning("sevDesk invoice mail failed for %s: %s", summary.id, exc)
            else:
                next_flags = self._next_flags(flags, mail_sent=True)
                self.write_fulfillment_flags(summary.id, next_flags)
                return next_flags, to_email, subject
        else:
            sevdesk_error = RuntimeError("sevDesk sendViaEmail ist nicht verfuegbar")

        if self._mail_service is not None and self._mail_service.is_configured():
            try:
                attachment = self._build_invoice_attachment(summary, invoice)
                self._mail_service.send_mail(
                    to_email=to_email,
                    subject=subject,
                    text_body=text_body,
                    html_body=html_body,
                    attachments=[attachment],
                )
            except Exception as exc:  # noqa: BLE001
                raise RuntimeError(
                    f"sevDesk-Mail fehlgeschlagen ({sevdesk_error}); Graph-Mail fehlgeschlagen ({exc})"
                ) from exc
            next_flags = self._next_flags(flags, mail_sent=True)
            self.write_fulfillment_flags(summary.id, next_flags)
            return next_flags, to_email, subject

        raise RuntimeError(f"sevDesk-Mail fehlgeschlagen ({sevdesk_error}); Graph-Mail nicht konfiguriert")

    def get_invoice_detail_context(self, summary: InvoiceSummary) -> dict[str, object]:
        """Return sevDesk-backed customer/shipping fallback data for the detail panel."""

        invoice = self._fetch_invoice_detail(summary.id)
        return {
            "customer_name": self._resolve_customer_name(summary, invoice),
            "customer_email": self._contact_email_from_invoice(invoice),
            "shipping_lines": self._shipping_lines_from_invoice_data(invoice, summary),
        }

    def _load_all_open_drafts(self, *, limit_per_page: int, max_pages: int) -> list[InvoiceSummary]:
        all_rows: list[InvoiceSummary] = []
        offset = 0
        for _ in range(max_pages):
            batch = self.load_invoice_summaries(status=100, limit=limit_per_page, offset=offset)
            if not batch:
                break
            all_rows.extend(batch)
            if len(batch) < limit_per_page:
                break
            offset += limit_per_page
        return all_rows

    def _load_summary_by_id(self, invoice_id: str) -> InvoiceSummary:
        raw = self._invoices.fetch_invoice_by_id(invoice_id)
        if not raw:
            raise ValueError(f"Rechnung {invoice_id} nicht gefunden")
        summary = InvoiceSummary.from_api_object(raw)
        self._apply_sensitive_country_flags([summary])
        self._apply_unreleased_sku_flags([summary])
        return summary

    def _stamp(self, flags: FulfillmentFlags) -> FulfillmentFlags:
        return FulfillmentFlags(
            label_printed=flags.label_printed,
            invoice_printed=flags.invoice_printed,
            product_ready=flags.product_ready,
            mail_sent=flags.mail_sent,
            wix_fulfilled=flags.wix_fulfilled,
            payment_applicable=flags.payment_applicable,
            payment_booked=flags.payment_booked,
            last_run_iso=datetime.now(timezone.utc).isoformat(timespec="seconds"),
            last_error=flags.last_error,
            last_warning=flags.last_warning,
        )

    def _next_flags(self, flags: FulfillmentFlags, **overrides: object) -> FulfillmentFlags:
        stamped = self._stamp(flags)
        data: dict[str, object] = {
            "label_printed": stamped.label_printed,
            "invoice_printed": stamped.invoice_printed,
            "product_ready": stamped.product_ready,
            "mail_sent": stamped.mail_sent,
            "wix_fulfilled": stamped.wix_fulfilled,
            "payment_applicable": stamped.payment_applicable,
            "payment_booked": stamped.payment_booked,
            "last_run_iso": stamped.last_run_iso,
            "last_error": "",
            "last_warning": "",
        }
        data.update(overrides)
        return FulfillmentFlags(**data)

    def _with_error(self, flags: FulfillmentFlags, exc: Exception) -> FulfillmentFlags:
        stamped = self._stamp(flags)
        return FulfillmentFlags(
            label_printed=stamped.label_printed,
            invoice_printed=stamped.invoice_printed,
            product_ready=stamped.product_ready,
            mail_sent=stamped.mail_sent,
            wix_fulfilled=stamped.wix_fulfilled,
            payment_applicable=stamped.payment_applicable,
            payment_booked=stamped.payment_booked,
            last_run_iso=stamped.last_run_iso,
            last_error=str(exc),
            last_warning=stamped.last_warning,
        )

    def _with_warning(self, flags: FulfillmentFlags, message: str) -> FulfillmentFlags:
        stamped = self._stamp(flags)
        return FulfillmentFlags(
            label_printed=stamped.label_printed,
            invoice_printed=stamped.invoice_printed,
            product_ready=stamped.product_ready,
            mail_sent=stamped.mail_sent,
            wix_fulfilled=stamped.wix_fulfilled,
            payment_applicable=stamped.payment_applicable,
            payment_booked=stamped.payment_booked,
            last_run_iso=stamped.last_run_iso,
            last_error="",
            last_warning=str(message or "").strip(),
        )

    def _run_finalize_step(
        self,
        summary: InvoiceSummary,
        flags: FulfillmentFlags,
        *,
        digital_only: bool = False,
        printed_copy: bool = False,
    ) -> FulfillmentFlags:
        if printed_copy:
            self._invoices.send_invoice_document(summary.id, send_type="VPR", send_draft=False)
        elif digital_only:
            logger.info("Invoice %s: digital-only finalization delegated to sendViaEmail", summary.id)
        else:
            logger.info("Invoice %s: mail-only finalization delegated to sendViaEmail", summary.id)
        return self._next_flags(
            flags,
            payment_applicable=(self._stamp(flags).payment_applicable or bool(summary.order_reference.strip())),
            mail_sent=self._stamp(flags).mail_sent,
        )

    def _run_invoice_print_step(self, summary: InvoiceSummary, flags: FulfillmentFlags) -> FulfillmentFlags:
        pdf_bytes = self._get_invoice_pdf_bytes(summary.id)
        if not pdf_bytes:
            raise RuntimeError("PDF nicht verfügbar")
        self._invoice_printer.print_pdf_bytes(pdf_bytes)
        logger.info("Invoice %s printed", summary.invoice_number or summary.id)
        return self._next_flags(flags, invoice_printed=True)

    def _run_label_print_step(self, summary: InvoiceSummary, flags: FulfillmentFlags) -> FulfillmentFlags:
        if not flags.invoice_printed:
            raise RuntimeError("Labeldruck erst nach Rechnungsdruck möglich")
        full = self._invoices.fetch_invoice_by_id(summary.id)
        lines = self._shipping_lines_from_invoice(full, summary)
        if not lines:
            raise RuntimeError("Keine Lieferadresse für Labeldruck")
        self._label_printer.print_address(lines)
        logger.info("Invoice %s label printed", summary.invoice_number or summary.id)
        return self._next_flags(flags, label_printed=True)

    def _run_product_step(self, summary: InvoiceSummary, flags: FulfillmentFlags) -> FulfillmentFlags:
        if not summary.order_reference.strip() or self._wix_orders is None:
            return self._next_flags(flags, product_ready=False, wix_fulfilled=False)

        reference = summary.order_reference.strip()
        digital_only = self._is_digital_only(summary)
        fulfillment_status = ""
        if hasattr(self._wix_orders, "fulfillment_status"):
            try:
                fulfillment_status = str(self._wix_orders.fulfillment_status(reference) or "").strip().upper()
            except Exception as exc:
                logger.warning("Wix fulfillment-status resolve failed ref=%s: %s", reference, exc)

        items = self._wix_orders.get_fulfillable_items(reference)
        if not items:
            existing_fulfillments = self._wix_orders.list_fulfillments(reference)
            if existing_fulfillments or fulfillment_status == "FULFILLED":
                return self._next_flags(flags, product_ready=True, wix_fulfilled=True)
            message = (
                f"Wix-Fulfillment nicht bestaetigt: keine fulfillable items fuer {reference}"
                if not digital_only
                else f"Wix-Digital-Fulfillment nicht bestaetigt fuer {reference}"
            )
            return self._next_flags(flags, product_ready=True, wix_fulfilled=False, last_warning=message)

        created = self._wix_orders.create_fulfillment(reference, items)
        if not created:
            return self._next_flags(
                flags,
                product_ready=True,
                wix_fulfilled=False,
                last_warning=f"Wix-Fulfillment konnte nicht erstellt werden fuer {reference}",
            )
        return self._next_flags(flags, product_ready=True, wix_fulfilled=True)

    def _run_mail_step(
        self,
        summary: InvoiceSummary,
        flags: FulfillmentFlags,
        *,
        recipient_override: str | None = None,
    ) -> FulfillmentFlags:
        if flags.mail_sent:
            return self._stamp(flags)
        next_flags, _to_email, _subject = self.send_invoice_mail_for_invoice(
            summary,
            recipient_override=recipient_override,
        )
        return next_flags

    def _shipping_lines_from_invoice(self, invoice: dict[str, Any], summary: InvoiceSummary) -> list[str]:
        if summary.order_reference.strip():
            wix_lines = self._get_wix_address_lines_cached(summary.order_reference)
            if wix_lines:
                return wix_lines

        return self._shipping_lines_from_invoice_data(invoice, summary)

    def _shipping_lines_from_invoice_data(self, invoice: dict[str, Any], summary: InvoiceSummary) -> list[str]:
        """Build shipping lines from sevDesk invoice/contact data only."""

        contact = invoice.get("contact") if isinstance(invoice.get("contact"), dict) else {}
        delivery_name = str(invoice.get("deliveryName") or "").strip()
        name = delivery_name or str(invoice.get("name") or contact.get("name") or summary.contact_name or "").strip()

        street = str(
            invoice.get("deliveryStreet")
            or invoice.get("shippingStreet")
            or invoice.get("street")
            or ""
        ).strip()
        zip_code = str(
            invoice.get("deliveryZip")
            or invoice.get("shippingZip")
            or invoice.get("zip")
            or ""
        ).strip()
        city = str(
            invoice.get("deliveryCity")
            or invoice.get("shippingCity")
            or invoice.get("city")
            or ""
        ).strip()
        country = str(
            invoice.get("deliveryAddressCountry")
            or invoice.get("shippingCountry")
            or invoice.get("addressCountryCode")
            or summary.display_country
            or ""
        ).strip()

        city_line = " ".join(part for part in (zip_code, city) if part)
        lines = [line for line in (name, street, city_line, country) if str(line).strip()]
        return lines

    @staticmethod
    def _invoice_number(summary: InvoiceSummary, invoice: dict[str, Any]) -> str:
        for value in (
            summary.invoice_number,
            invoice.get("invoiceNumber"),
            invoice.get("number"),
            invoice.get("header"),
            summary.id,
        ):
            text = str(value or "").strip()
            if text:
                return text
        return str(summary.id or "").strip()

    @staticmethod
    def _contact_email_from_invoice(invoice: dict[str, Any]) -> str:
        candidates: list[str] = []
        for key in ("email", "toEmail", "contactEmail"):
            value = str(invoice.get(key) or "").strip()
            if value:
                candidates.append(value)
        contact = invoice.get("contact") if isinstance(invoice.get("contact"), dict) else {}
        for key in ("email", "emailAddress"):
            value = str(contact.get(key) or "").strip()
            if value:
                candidates.append(value)
        emails = contact.get("emails")
        if isinstance(emails, list):
            for item in emails:
                if not isinstance(item, dict):
                    continue
                value = str(item.get("value") or item.get("email") or "").strip()
                if value:
                    candidates.append(value)
        for candidate in candidates:
            if candidate:
                return candidate
        return ""

    def _resolve_customer_email(self, summary: InvoiceSummary, invoice: dict[str, Any]) -> str:
        if summary.order_reference.strip():
            wix_summary = self._get_wix_order_summary_cached(summary.order_reference)
            wix_email = str(wix_summary.get("wix_customer_email") or "").strip()
            if wix_email:
                return wix_email
        return self._contact_email_from_invoice(invoice)

    def _repair_draft_products(self, summary: InvoiceSummary) -> None:
        if self._drafts is None:
            return
        reference = str(summary.order_reference or "").strip()
        if not reference:
            return
        try:
            self._drafts.repair_draft_product_mapping(summary.id, reference, create_missing_products=False)
        except Exception as exc:
            logger.warning("Produktabgleich fuer Entwurf %s fehlgeschlagen: %s", summary.id, exc)

    def _resolve_customer_name(self, summary: InvoiceSummary, invoice: dict[str, Any]) -> str:
        if summary.order_reference.strip():
            wix_summary = self._get_wix_order_summary_cached(summary.order_reference)
            wix_name = str(wix_summary.get("wix_customer_name") or "").strip()
            if wix_name:
                return wix_name
        for value in (
            invoice.get("name"),
            (invoice.get("contact") or {}).get("name") if isinstance(invoice.get("contact"), dict) else "",
            summary.contact_name,
        ):
            text = str(value or "").strip()
            if text:
                return text
        return "Kunde"

    @staticmethod
    def _looks_like_html(value: str) -> bool:
        return bool(re.search(r"<[a-zA-Z][^>]*>", str(value or "")))

    @staticmethod
    def _invoice_items_html(invoice: dict[str, Any]) -> str:
        lines: list[str] = []
        raw_positions = invoice.get("positions") or invoice.get("invoicePosSave") or invoice.get("invoicePos")
        if isinstance(raw_positions, list):
            for item in raw_positions:
                if not isinstance(item, dict):
                    continue
                name = str(item.get("name") or item.get("text") or item.get("partName") or "").strip()
                quantity = str(item.get("quantity") or item.get("qty") or item.get("count") or "").strip()
                if name and quantity:
                    lines.append(f"{html.escape(quantity)}x {html.escape(name)}")
                elif name:
                    lines.append(html.escape(name))
        return "<br>".join(lines)

    def _mail_template_values(self, summary: InvoiceSummary, invoice: dict[str, Any]) -> dict[str, str]:
        invoice_number = self._invoice_number(summary, invoice)
        return {
            "{{customer_name}}": self._resolve_customer_name(summary, invoice),
            "{{invoice_number}}": invoice_number,
            "{{download_link}}": "",
            "{{items_html}}": self._invoice_items_html(invoice),
        }

    def _load_mail_templates(self) -> tuple[str, str]:
        if self._settings_repo is None:
            return "", ""
        subject = self._settings_repo.get_value_json(_FULFILLMENT_MAIL_SUBJECT_KEY)
        body = self._settings_repo.get_value_json(_FULFILLMENT_MAIL_TEMPLATE_KEY)
        return str(subject or "").strip(), str(body or "").strip()

    def _build_mail_content(self, summary: InvoiceSummary, invoice: dict[str, Any]) -> tuple[str, str]:
        invoice_number = self._invoice_number(summary, invoice)
        subject_template, body_template = self._load_mail_templates()
        subject = subject_template or _LEGACY_MAIL_SUBJECT
        body = body_template or _LEGACY_MAIL_BODY
        for token, value in self._mail_template_values(summary, invoice).items():
            subject = subject.replace(token, value).replace(token.replace("{{", "{").replace("}}", "}"), value)
            body = body.replace(token, value).replace(token.replace("{{", "{").replace("}}", "}"), value)
        subject = subject.replace("{invoice_number}", invoice_number)
        body = body.replace("{invoice_number}", invoice_number)
        body = body.strip() or _LEGACY_MAIL_BODY.format(invoice_number=invoice_number).strip()
        return subject.strip() or _LEGACY_MAIL_SUBJECT.format(invoice_number=invoice_number), body

    def _build_mail_html(self, body: str) -> str:
        content = str(body or "").strip()
        if self._looks_like_html(content):
            inner = content
        elif self._mail_service is not None:
            inner = self._mail_service.plain_text_to_html(content)
        else:
            normalized = content.replace("\r\n", "\n").replace("\r", "\n").strip()
            paragraphs = [chunk.strip() for chunk in re.split(r"\n\s*\n", normalized) if chunk.strip()]
            inner = "\n".join(f"<p>{html.escape(paragraph).replace('\n', '<br>')}</p>" for paragraph in paragraphs)
        return (
            "<html><body style=\"font-family:Segoe UI,Arial,sans-serif;color:#0f172a;line-height:1.5;\">"
            f"{inner}"
            "</body></html>"
        )

    def _build_invoice_attachment(self, summary: InvoiceSummary, invoice: dict[str, Any]) -> MailAttachment:
        pdf_bytes = self._get_invoice_pdf_bytes(summary.id)
        invoice_number = self._invoice_number(summary, invoice)
        return MailAttachment(filename=f"{invoice_number}.pdf", content=pdf_bytes, mime_type="application/pdf")

    def _fetch_invoice_detail(self, invoice_id: str) -> dict[str, Any]:
        cached = self._invoice_detail_cache.get(str(invoice_id))
        if cached is not None:
            return cached
        invoice = self._invoices.fetch_invoice_by_id(invoice_id)
        normalized = invoice if isinstance(invoice, dict) else {}
        self._invoice_detail_cache[str(invoice_id)] = normalized
        return normalized

    def _get_invoice_pdf_bytes(self, invoice_id: str) -> bytes:
        cached = self._invoice_pdf_cache.get(str(invoice_id))
        if cached:
            return cached
        extractor = getattr(self._invoices, "extract_pdf_from_payload", None)
        last_exc: Exception | None = None
        for attempt, delay in enumerate((0.0, 0.5, 1.0, 2.0, 4.0), start=1):
            if delay:
                time.sleep(delay)
            try:
                render_payload = self._invoices.render_invoice_pdf(invoice_id)
                if callable(extractor):
                    rendered_pdf = extractor(render_payload)
                    if rendered_pdf:
                        self._invoice_pdf_cache[str(invoice_id)] = rendered_pdf
                        return rendered_pdf
                pdf_bytes = self._invoices.get_invoice_pdf(invoice_id)
                if pdf_bytes:
                    self._invoice_pdf_cache[str(invoice_id)] = pdf_bytes
                    return pdf_bytes
            except Exception as exc:  # noqa: BLE001 - retry transient sevDesk render/getPdf states.
                last_exc = exc
                logger.info("Invoice %s PDF attempt %s failed: %s", invoice_id, attempt, exc)
        raise RuntimeError("PDF nicht verfügbar") from last_exc

    def _load_fulfillment_flags_map(self) -> dict[str, FulfillmentFlags]:
        if self._settings_repo is None:
            return {}
        raw = self._settings_repo.get_value_json(_FULFILLMENT_STATUS_KEY)
        if not raw:
            return {}
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            return {}
        if not isinstance(data, dict):
            return {}
        out: dict[str, FulfillmentFlags] = {}
        for key, payload in data.items():
            if not isinstance(key, str) or not key.strip():
                continue
            out[key] = FulfillmentFlags.from_payload(payload)
        return out

    def _rows_with_fulfillment(
        self,
        summaries: list[InvoiceSummary],
        rows: list[dict[str, Any]] | None = None,
    ) -> list[dict[str, Any]]:
        row_list = rows if rows is not None else [s.as_table_row() for s in summaries]
        states = self._load_fulfillment_flags_map()
        for summary, row in zip(summaries, row_list):
            flags = states.get(summary.id)
            if flags is None:
                flags = FulfillmentFlags(
                    product_ready=bool(summary.order_reference.strip()),
                    payment_applicable=bool(summary.order_reference.strip()),
                )
            row["FULFILLMENT"] = ""
            row["__fulfillment__"] = flags.as_row_payload()
            row["__tooltip__FULFILLMENT"] = "Label | Rechnung | Produkt | Mail | Wix | Zahlung"
            row["__align__FULFILLMENT"] = "center"
        return row_list

    def get_cached_invoice_list_hints(self, reference: str) -> InvoiceListHintFlags | None:
        ref = str(reference or "").strip()
        if not ref:
            return None
        return self._wix_hint_cache.get(ref)

    def resolve_invoice_list_hints(self, reference: str) -> InvoiceListHintFlags:
        ref = str(reference or "").strip()
        if not ref:
            return InvoiceListHintFlags()
        cached = self._wix_hint_cache.get(ref)
        if cached is not None:
            return cached
        empty = InvoiceListHintFlags()
        if self._wix_orders is None or not self._wix_orders.has_credentials():
            self._wix_hint_cache[ref] = empty
            return empty
        try:
            order = self._wix_orders.resolve_order(ref)
        except Exception as exc:
            logger.warning("Invoice hints: Wix resolve failed ref=%s: %s", ref, exc)
            self._wix_hint_cache[ref] = empty
            return empty
        if not order:
            logger.info("Invoice hints: no Wix order found for ref=%s", ref)
            self._wix_hint_cache[ref] = empty
            return empty
        flags = self._build_invoice_list_hints_from_order(order)
        self._wix_hint_cache[ref] = flags
        return flags

    def count_invoices(self, *, status: int | None = None, batch_size: int = 200) -> int:
        """Count invoices by paging through API results to avoid hard caps in UI badges."""
        safe_batch = max(10, int(batch_size))
        offset = 0
        total = 0
        while True:
            rows = self._invoices.list_invoice_summaries(
                limit=safe_batch,
                offset=offset,
                status=status,
            )
            count = len(rows)
            total += count
            if count < safe_batch:
                break
            offset += safe_batch
        return total

    @staticmethod
    def _normalize_country_key(value: object) -> str:
        text = str(value or "").strip().lower()
        replacements = {
            "ä": "ae",
            "ö": "oe",
            "ü": "ue",
            "ß": "ss",
        }
        for src, dest in replacements.items():
            text = text.replace(src, dest)
        return " ".join(text.split())

    @classmethod
    def _normalize_address_line(cls, value: object) -> str:
        text = cls._normalize_country_key(value)
        text = re.sub(r"[|,;]", " ", text)
        return " ".join(text.split())

    def _load_allowed_country_keys(self) -> set[str]:
        defaults = {
            self._normalize_country_key(item)
            for item in _DEFAULT_ALLOWED_COUNTRIES
            if str(item).strip()
        }
        if self._settings_repo is None:
            return defaults
        raw = self._settings_repo.get_value_json(_ALLOWED_COUNTRIES_KEY)
        if not raw:
            return defaults
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            return defaults
        if not isinstance(data, list):
            return defaults
        parsed = {
            self._normalize_country_key(item)
            for item in data
            if str(item).strip()
        }
        return parsed or defaults

    def _build_invoice_list_hints_from_order(self, order: dict[str, Any]) -> InvoiceListHintFlags:
        note = str(order.get("buyerNote") or order.get("buyerNotes") or "").strip()
        billing_lines = tuple(self._wix_orders.billing_address_lines_from_order(order)) if self._wix_orders else ()
        shipping_lines = tuple(self._wix_orders.shipping_address_lines_from_order(order)) if self._wix_orders else ()
        address_mismatch = bool(billing_lines and shipping_lines and self._addresses_differ(billing_lines, shipping_lines))
        shipping_country = shipping_lines[-1] if shipping_lines else ""
        country_invalid = bool(shipping_country) and not self._country_allowed(shipping_country)
        unreleased_sku = self._order_has_flagged_sku(order)
        return InvoiceListHintFlags(
            buyer_note=note,
            address_mismatch=address_mismatch,
            unreleased_sku=unreleased_sku,
            country_invalid=country_invalid,
            country_label=shipping_country,
            billing_lines=billing_lines,
            shipping_lines=shipping_lines,
        )

    def _country_allowed(self, country_label: str) -> bool:
        normalized = self._normalize_country_key(country_label)
        if not normalized:
            return True
        return normalized in self._load_allowed_country_keys()

    def _addresses_differ(self, left: tuple[str, ...] | list[str], right: tuple[str, ...] | list[str]) -> bool:
        def normalize(lines: tuple[str, ...] | list[str]) -> list[str]:
            normalized: list[str] = []
            for line in lines:
                text = self._normalize_address_line(line)
                if text:
                    normalized.append(text)
            return normalized

        left_norm = normalize(left)
        right_norm = normalize(right)
        if not left_norm and not right_norm:
            return False
        if left_norm == right_norm:
            return False
        return " ".join(left_norm) != " ".join(right_norm)

    def _order_has_flagged_sku(self, order: dict[str, Any]) -> bool:
        exact, prefixes = self._load_sku_flags()
        raw_items = order.get("lineItems") if isinstance(order.get("lineItems"), list) else []
        for raw_item in raw_items:
            if not isinstance(raw_item, dict):
                continue
            sku = self._line_item_sku(raw_item)
            if sku in exact or any(sku.startswith(prefix) for prefix in prefixes):
                return True
        return False

    def is_flagged_sku(self, sku: str) -> bool:
        normalized = str(sku or "").strip().upper()
        if not normalized:
            return False
        exact, prefixes = self._load_sku_flags()
        return normalized in exact or any(normalized.startswith(prefix) for prefix in prefixes)

    @staticmethod
    def _line_item_sku(raw_item: dict[str, Any]) -> str:
        physical = raw_item.get("physicalProperties") if isinstance(raw_item.get("physicalProperties"), dict) else {}
        sku = str(physical.get("sku") or "").strip().upper()
        if sku:
            return sku
        catalog = raw_item.get("catalogReference") if isinstance(raw_item.get("catalogReference"), dict) else {}
        options = catalog.get("catalogItemOptions") if isinstance(catalog.get("catalogItemOptions"), dict) else {}
        return str(options.get("sku") or "").strip().upper()

    def _load_sensitive_country_codes(self) -> set[str]:
        if self._settings_repo is None:
            return set(DEFAULT_SENSITIVE_COUNTRY_CODES)
        raw = self._settings_repo.get_value_json(_SENSITIVE_COUNTRIES_KEY)
        if not raw:
            return set(DEFAULT_SENSITIVE_COUNTRY_CODES)
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            return set(DEFAULT_SENSITIVE_COUNTRY_CODES)
        if not isinstance(data, list):
            return set(DEFAULT_SENSITIVE_COUNTRY_CODES)
        parsed = {
            str(item).strip().upper()
            for item in data
            if str(item).strip()
        }
        return parsed or set(DEFAULT_SENSITIVE_COUNTRY_CODES)

    def _apply_sensitive_country_flags(self, summaries: list[InvoiceSummary]) -> None:
        sensitive_codes = self._load_sensitive_country_codes()
        for summary in summaries:
            code = summary.address_country_code.strip().upper()
            delivery_code = summary.delivery_country_code.strip().upper()
            summary.is_sensitive_country = code in sensitive_codes or delivery_code in sensitive_codes

    def _load_sku_flags(self) -> tuple[set[str], tuple[str, ...]]:
        if self._settings_repo is None:
            return self._default_sku_flags()
        raw = self._settings_repo.get_value_json(_SKU_FLAGS_KEY)
        if not raw:
            return self._default_sku_flags()
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            return self._default_sku_flags()
        if not isinstance(data, dict):
            return self._default_sku_flags()

        exact_raw = data.get("exact")
        prefixes_raw = data.get("prefixes")
        if not isinstance(exact_raw, list) or not isinstance(prefixes_raw, list):
            return self._default_sku_flags()

        exact = {str(item).strip().upper() for item in exact_raw if str(item).strip()}
        prefixes = tuple(str(item).strip().upper() for item in prefixes_raw if str(item).strip())
        if not exact and not prefixes:
            return self._default_sku_flags()
        return exact, prefixes

    def _default_sku_flags(self) -> tuple[set[str], tuple[str, ...]]:
        exact = {str(item).strip().upper() for item in _DEFAULT_SKU_FLAGS["exact"]}
        prefixes = tuple(str(item).strip().upper() for item in _DEFAULT_SKU_FLAGS["prefixes"])
        return exact, prefixes

    def _apply_unreleased_sku_flags(self, summaries: list[InvoiceSummary]) -> None:
        exact, prefixes = self._load_sku_flags()
        for summary in summaries:
            hay = " ".join(
                [
                    summary.order_reference,
                    summary.buyer_note,
                    summary.invoice_number,
                ]
            )
            tokens = {match.group(0).upper() for match in _SKU_TOKEN_RE.finditer(hay)}
            summary.has_unreleased_sku = any(
                token in exact or any(token.startswith(prefix) for prefix in prefixes)
                for token in tokens
            )
