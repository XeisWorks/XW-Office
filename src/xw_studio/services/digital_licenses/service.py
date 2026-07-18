"""Services for paid digital sheet-music license fulfillment."""
from __future__ import annotations

import json
import logging
import os
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from xw_studio.services.layout.service import LayoutToolsService
from xw_studio.services.sevdesk.invoice_client import InvoiceSummary

if TYPE_CHECKING:
    from xw_studio.repositories.settings_kv import SettingKvRepository
    from xw_studio.services.inventory.service import InventoryService
    from xw_studio.services.invoice_processing.service import InvoiceProcessingService
    from xw_studio.services.products.catalog import ProductCatalogService
    from xw_studio.services.secrets.service import SecretService
    from xw_studio.services.wix.client import WixOrdersClient

logger = logging.getLogger(__name__)

_COMPLETED_KEY = "digital_licenses.completed"
_DEFAULT_OUTPUT_DIR = r"C:\Users\bernh\OneDrive - XeisWorks\02 XeisWorks\24 Digitale Lizensierung"
_HANDLING_TOKENS = ("digital delivery handling",)
_INVOICE_STATUSES = (100, 1000)


@dataclass(slots=True)
class DigitalLicenseLine:
    sku: str
    name: str
    quantity: int
    print_file_path: str = ""
    missing_print_file: bool = False


@dataclass(slots=True)
class DigitalLicenseCase:
    invoice_id: str
    invoice_number: str
    order_reference: str
    customer_name: str
    customer_email: str
    lines: list[DigitalLicenseLine]


class DigitalLicenseService:
    """Find paid digital orders and prepare licensed PDF mail drafts."""

    def __init__(
        self,
        *,
        invoices: "InvoiceProcessingService",
        wix_orders: "WixOrdersClient",
        catalog: "ProductCatalogService",
        layout: LayoutToolsService,
        secret_service: "SecretService",
        settings_repo: "SettingKvRepository | None" = None,
        inventory: "InventoryService | None" = None,
        output_dir: str = _DEFAULT_OUTPUT_DIR,
    ) -> None:
        self._invoices = invoices
        self._wix_orders = wix_orders
        self._catalog = catalog
        self._layout = layout
        self._secrets = secret_service
        self._settings_repo = settings_repo
        self._inventory = inventory
        self._output_dir = output_dir

    def open_count(self) -> int:
        return len(self.list_open_cases())

    def list_open_cases(self, *, limit: int = 100) -> list[DigitalLicenseCase]:
        completed = self._load_completed()
        summaries: list[InvoiceSummary] = []
        seen_invoice_ids: set[str] = set()
        for status in _INVOICE_STATUSES:
            for summary in self._invoices.load_invoice_summaries(status=status, limit=limit, offset=0):
                invoice_id = str(summary.id or "").strip()
                if invoice_id and invoice_id in seen_invoice_ids:
                    continue
                if invoice_id:
                    seen_invoice_ids.add(invoice_id)
                summaries.append(summary)
        cases: list[DigitalLicenseCase] = []
        for summary in summaries:
            invoice_id = str(summary.id or "").strip()
            if not invoice_id or invoice_id in completed:
                continue
            ref = str(summary.order_reference or "").strip()
            if not ref:
                continue
            try:
                if not self._wix_orders.is_reference_digital_only(ref, use_cache=False):
                    continue
                case = self._build_case(summary)
            except Exception as exc:  # noqa: BLE001
                logger.warning("Digital license case skipped invoice=%s ref=%s: %s", invoice_id, ref, exc)
                continue
            if case.lines:
                cases.append(case)
        return cases

    def apply_print_path(self, sku: str, path: str) -> None:
        clean_sku = str(sku or "").strip().upper()
        clean_path = str(path or "").strip()
        if not clean_sku or not clean_path:
            return
        self._catalog.set_print_file_path(clean_sku, clean_path)
        if self._inventory is None:
            return
        try:
            rows = self._inventory.list_products()
            updated = []
            found = False
            for row in rows:
                if row.sku.strip().upper() == clean_sku:
                    row.print_file_path = clean_path
                    found = True
                updated.append(row)
            if found:
                self._inventory.save_products(updated)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Persisting print path failed for %s: %s", clean_sku, exc)

    def prepare_license_mail(self, case: DigitalLicenseCase) -> list[Path]:
        name = self._license_name(case.customer_name)
        if not name:
            raise RuntimeError("Kundenname fehlt")
        output_files: list[Path] = []
        for line in case.lines:
            source = str(line.print_file_path or "").strip()
            if not source:
                raise RuntimeError(f"Druckpfad fehlt fuer {line.sku or line.name}")
            output_files.append(
                self._layout.watermark_side_a4_pdf(
                    source,
                    output_dir=self._output_dir,
                    user_name=name,
                )
            )
        self._open_outlook_draft(case, output_files)
        return output_files

    def mark_done(self, case: DigitalLicenseCase) -> None:
        ref = str(case.order_reference or "").strip()
        if ref:
            items = self._wix_orders.get_fulfillable_items(ref)
            normalized = self._normalize_fulfillment_items(items)
            if normalized:
                created = self._wix_orders.create_fulfillment(ref, normalized, notify_customer=False)
                if not created:
                    raise RuntimeError(f"Wix-Fulfillment konnte nicht bestaetigt werden fuer {ref}")
        completed = self._load_completed()
        completed[str(case.invoice_id)] = {
            "invoice_number": case.invoice_number,
            "order_reference": case.order_reference,
            "customer_name": case.customer_name,
        }
        self._save_completed(completed)

    def _build_case(self, summary: InvoiceSummary) -> DigitalLicenseCase:
        ref = str(summary.order_reference or "").strip()
        meta = self._wix_orders.resolve_order_summary(ref) if ref else {}
        customer_name = (
            str(meta.get("wix_customer_name") or "").strip()
            or str(summary.contact_name or "").strip()
        )
        customer_email = str(meta.get("wix_customer_email") or "").strip()
        lines: list[DigitalLicenseLine] = []
        for item in self._wix_orders.fetch_order_line_items(ref):
            name = str(item.name or "").strip()
            sku = str(item.sku or "").strip().upper()
            if self._is_handling_line(sku, name):
                continue
            product = self._catalog.resolve_sku(sku) if sku else None
            print_file_path = str(getattr(product, "print_file_path", "") or "").strip()
            lines.append(
                DigitalLicenseLine(
                    sku=sku,
                    name=name or sku,
                    quantity=max(1, int(item.qty or 1)),
                    print_file_path=print_file_path,
                    missing_print_file=not bool(print_file_path and Path(print_file_path).is_file()),
                )
            )
        return DigitalLicenseCase(
            invoice_id=str(summary.id or "").strip(),
            invoice_number=str(summary.invoice_number or "").strip(),
            order_reference=ref,
            customer_name=customer_name,
            customer_email=customer_email,
            lines=lines,
        )

    @staticmethod
    def _is_handling_line(sku: str, name: str) -> bool:
        haystack = f"{sku} {name}".casefold()
        return any(token in haystack for token in _HANDLING_TOKENS)

    @staticmethod
    def _license_name(value: str) -> str:
        parts = [part for part in str(value or "").replace("\n", " ").split() if part]
        return " ".join(parts[:2]) if len(parts) >= 2 else " ".join(parts)

    @staticmethod
    def _normalize_fulfillment_items(raw_items: list[dict[str, object]]) -> list[dict[str, object]]:
        normalized: list[dict[str, object]] = []
        for raw in raw_items:
            item_id = str(raw.get("id") or raw.get("lineItemId") or "").strip()
            if not item_id:
                line_item = raw.get("lineItem") if isinstance(raw.get("lineItem"), dict) else {}
                item_id = str(line_item.get("id") or line_item.get("lineItemId") or "").strip()
            if not item_id:
                continue
            quantity_raw = raw.get("quantity") or raw.get("fulfillableQuantity") or 1
            try:
                quantity = max(1, int(float(str(quantity_raw))))
            except (TypeError, ValueError):
                quantity = 1
            normalized.append({"id": item_id, "quantity": quantity})
        return normalized

    def _open_outlook_draft(self, case: DigitalLicenseCase, attachments: list[Path]) -> None:
        sender = str(self._secrets.get_secret("OUTLOOK_SENDER_EMAIL") or "").strip()
        if not sender:
            raise RuntimeError("OUTLOOK_SENDER_EMAIL fehlt")
        if not case.customer_email:
            raise RuntimeError("Kunden-E-Mail fehlt")
        payload = json.dumps(
            {
                "to": case.customer_email,
                "subject": self._mail_subject(case),
                "sender": sender,
                "body": self._mail_body(case),
                "attachments": [str(path) for path in attachments],
            },
            ensure_ascii=False,
        )
        env = dict(os.environ)
        src_path = str(Path(__file__).resolve().parents[3])
        existing_pythonpath = env.get("PYTHONPATH", "")
        env["PYTHONPATH"] = f"{src_path}{os.pathsep}{existing_pythonpath}" if existing_pythonpath else src_path
        completed = subprocess.run(
            [sys.executable, "-m", "xw_studio.services.mailing.outlook_compose"],
            input=payload,
            text=True,
            capture_output=True,
            timeout=25,
            env=env,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            check=False,
        )
        if completed.returncode != 0:
            raise RuntimeError((completed.stderr or completed.stdout or "Outlook draft failed").strip())

    @staticmethod
    def _mail_subject(case: DigitalLicenseCase) -> str:
        ref = str(case.order_reference or "").strip()
        return f"Your licensed sheet music PDFs for order {ref}" if ref else "Your licensed sheet music PDFs"

    @staticmethod
    def _mail_body(case: DigitalLicenseCase) -> str:
        first_name = str(case.customer_name or "").strip().split(" ")[0] or "there"
        product_lines = "\n".join(f"- {line.name}" for line in case.lines)
        return (
            f"Dear {first_name},\n\n"
            "Thank you for your order. Please find your personally licensed sheet music PDF file(s) attached.\n\n"
            "This license is issued for your personal use only. Please do not share, resell, upload, or redistribute "
            "the attached file(s).\n\n"
            f"Included:\n{product_lines}\n\n"
            "Best regards,\n"
            "XeisWorks"
        )

    def _load_completed(self) -> dict[str, dict[str, object]]:
        if self._settings_repo is None:
            return {}
        raw = self._settings_repo.get_value_json(_COMPLETED_KEY)
        if not raw:
            return {}
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            return {}
        return data if isinstance(data, dict) else {}

    def _save_completed(self, data: dict[str, dict[str, object]]) -> None:
        if self._settings_repo is None:
            return
        self._settings_repo.set_value_json(_COMPLETED_KEY, json.dumps(data, ensure_ascii=False, sort_keys=True))
