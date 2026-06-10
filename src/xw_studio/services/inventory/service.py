"""Inventory and print-plan coordination for START preflight."""
from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path

from xw_studio.core.config import AppConfig
from xw_studio.repositories.settings_kv import SettingKvRepository
from xw_studio.services.printing.planned_pdf_printer import print_pdf_by_plan
from xw_studio.services.printing.print_queue import PrintQueueService

try:
    import fitz
except Exception:  # pragma: no cover - optional at import time
    fitz = None

logger = logging.getLogger(__name__)

_STOCK_KEY = "inventory.stock_levels"
_REQUIREMENTS_KEY = "daily_business.pending_requirements"
_PRODUCTS_KEY = "inventory.products"
_PRINT_PLANS_KEY = "inventory.print_plans"


@dataclass(frozen=True)
class StartDecision:
    """Single SKU decision for START preflight."""

    sku: str
    required_qty: int
    on_hand_qty: int
    missing_qty: int
    final_print_qty: int
    will_print: bool


@dataclass(frozen=True)
class StartPreflight:
    """Preflight result for START dialog and orchestration."""

    open_invoice_count: int
    decisions: list[StartDecision]
    missing_position_data: bool


class StartMode(str, Enum):
    """Execution mode selected in START dialog."""

    INVOICES_ONLY = "invoices"
    INVOICES_AND_PRINT = "full"


@dataclass(frozen=True)
class StartExecutionReport:
    """Result payload for START execution after dialog confirmation."""

    mode: StartMode
    open_invoice_count: int
    decisions_count: int
    printed_skus: list[str]
    consumed_skus: list[str]
    stock_updated: bool
    warnings: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class ReprintDecision:
    """Single SKU decision for REPRINTS (print-only, no consumption)."""

    sku: str
    on_hand_qty: int
    min_stock_target: int
    reprint_batch_qty: int
    will_print: bool
    final_print_qty: int


@dataclass(frozen=True)
class ReprintPreflight:
    """Preflight result for REPRINTS dialog (restock decision)."""

    decisions: list[ReprintDecision]
    missing_position_data: bool


@dataclass(frozen=True)
class ReprintExecutionReport:
    """Result payload for REPRINTS execution (stock auffülling only)."""

    decisions_count: int
    printed_skus: list[str]
    stock_updated: bool
    warnings: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class ProductRow:
    """Single product row for UI tables."""

    sku: str
    name: str
    category: str
    on_hand: int
    price_eur: str
    wix_id: str
    sevdesk_id: str
    brand_name: str = ""
    brand_id: str = ""
    print_file_path: str = ""
    print_profile_id: str = ""
    print_plan: list[dict[str, str]] | None = None
    title_print_configs: dict[str, dict[str, object]] | None = None


@dataclass(frozen=True)
class LegacyPrintImportReport:
    source_path: str
    records_seen: int
    products_updated: int
    title_configs_imported: int
    missing_files: list[str]
    unknown_profiles: list[str]


class InventoryService:
    """Stock levels and print buffer rules for daily START workflow."""

    def __init__(
        self,
        config: AppConfig,
        settings_repo: SettingKvRepository | None = None,
        print_queue: PrintQueueService | None = None,
    ) -> None:
        self._config = config
        self._settings_repo = settings_repo
        self._print_queue = print_queue

    def load_stock_levels(self) -> dict[str, int]:
        """Return stock levels by SKU (from DB setting if available)."""
        if self._settings_repo is None:
            return {}
        raw = self._settings_repo.get_value_json(_STOCK_KEY)
        if not raw:
            return {}
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            logger.warning("Invalid JSON in %s", _STOCK_KEY)
            return {}
        if not isinstance(data, dict):
            return {}
        result: dict[str, int] = {}
        for key, value in data.items():
            if not isinstance(key, str):
                continue
            try:
                result[key] = max(0, int(value))
            except (TypeError, ValueError):
                continue
        return result

    def load_pending_requirements(self) -> dict[str, int]:
        """Return required print quantities by SKU for current queue."""
        if self._settings_repo is None:
            return {}
        raw = self._settings_repo.get_value_json(_REQUIREMENTS_KEY)
        if not raw:
            return {}
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            logger.warning("Invalid JSON in %s", _REQUIREMENTS_KEY)
            return {}
        if not isinstance(data, dict):
            return {}
        result: dict[str, int] = {}
        for key, value in data.items():
            if not isinstance(key, str):
                continue
            try:
                qty = int(value)
            except (TypeError, ValueError):
                continue
            if qty > 0:
                result[key] = qty
        return result

    def build_start_preflight(self, open_invoice_count: int) -> StartPreflight:
        """Create decision list: print only when stock is below required quantity."""
        requirements = self.load_pending_requirements()
        if not requirements:
            return StartPreflight(
                open_invoice_count=max(0, int(open_invoice_count)),
                decisions=[],
                missing_position_data=True,
            )

        stock_levels = self.load_stock_levels()
        buffer_qty = max(0, int(self._config.printing.buffer_quantity))
        decisions: list[StartDecision] = []

        for sku in sorted(requirements):
            required = max(0, int(requirements.get(sku, 0)))
            on_hand = max(0, int(stock_levels.get(sku, 0)))
            missing = max(0, required - on_hand)
            will_print = missing > 0
            final_print_qty = missing + buffer_qty if will_print else 0
            decisions.append(
                StartDecision(
                    sku=sku,
                    required_qty=required,
                    on_hand_qty=on_hand,
                    missing_qty=missing,
                    final_print_qty=final_print_qty,
                    will_print=will_print,
                )
            )

        return StartPreflight(
            open_invoice_count=max(0, int(open_invoice_count)),
            decisions=decisions,
            missing_position_data=False,
        )

    def build_reprint_preflight(
        self,
        requirements: dict[str, int] | None = None,
    ) -> ReprintPreflight:
        """Build preflight for REPRINTS (restock without invoice consumption).

        If *requirements* is None, uses load_pending_requirements().
        Returns decisions for products that need restocking (on_hand <= min_stock_target).
        """
        if requirements is None:
            requirements = self.load_pending_requirements()
        if not requirements:
            return ReprintPreflight(decisions=[], missing_position_data=True)

        stock_levels = self.load_stock_levels()
        buffer_qty = max(0, int(self._config.printing.buffer_quantity))
        decisions: list[ReprintDecision] = []

        for sku in sorted(requirements):
            on_hand = max(0, int(stock_levels.get(sku, 0)))
            # For reprints, use simple heuristic: restock if on_hand is low
            min_target = 5  # Default minimum stock target
            reprint_batch = buffer_qty
            will_print = on_hand <= min_target
            final_print_qty = reprint_batch if will_print else 0
            decisions.append(
                ReprintDecision(
                    sku=sku,
                    on_hand_qty=on_hand,
                    min_stock_target=min_target,
                    reprint_batch_qty=reprint_batch,
                    will_print=will_print,
                    final_print_qty=final_print_qty,
                )
            )

        return ReprintPreflight(
            decisions=decisions,
            missing_position_data=False,
        )

    def execute_reprint_workflow(
        self,
        preflight: ReprintPreflight,
    ) -> ReprintExecutionReport:
        """Execute REPRINTS: only print, only auffüllen (no invoice consumption).

        Returns a report with printed SKUs and updated stock levels.
        """
        if preflight.missing_position_data or not preflight.decisions:
            return ReprintExecutionReport(
                decisions_count=len(preflight.decisions),
                printed_skus=[],
                stock_updated=False,
            )

        stock_levels = self.load_stock_levels()
        printed_skus: list[str] = []
        warnings: list[str] = []

        for decision in preflight.decisions:
            if not decision.will_print:
                continue
            printed = self._print_decision_product(decision.sku, decision.final_print_qty, warnings)
            if not printed:
                continue
            current = max(0, int(stock_levels.get(decision.sku, decision.on_hand_qty)))
            produced = max(0, int(decision.final_print_qty))
            final_stock = current + produced
            stock_levels[decision.sku] = final_stock
            printed_skus.append(decision.sku)

        self._save_stock_levels(stock_levels)
        return ReprintExecutionReport(
            decisions_count=len(preflight.decisions),
            printed_skus=printed_skus,
            stock_updated=True,
            warnings=warnings,
        )

    def execute_start_workflow(
        self,
        preflight: StartPreflight,
        mode: StartMode,
    ) -> StartExecutionReport:
        """Execute START side effects for the selected *mode*.

        In ``INVOICES_AND_PRINT`` mode this updates inventory.stock_levels with
        post-run amounts (required quantities consumed, shortage printed with
        configured buffer). In ``PRINT_ONLY`` mode it only applies print production
        to stock levels (no invoice consumption).
        """
        if mode == StartMode.INVOICES_ONLY:
            return StartExecutionReport(
                mode=mode,
                open_invoice_count=preflight.open_invoice_count,
                decisions_count=len(preflight.decisions),
                printed_skus=[],
                consumed_skus=[],
                stock_updated=False,
            )

        if preflight.missing_position_data or not preflight.decisions:
            return StartExecutionReport(
                mode=mode,
                open_invoice_count=preflight.open_invoice_count,
                decisions_count=len(preflight.decisions),
                printed_skus=[],
                consumed_skus=[],
                stock_updated=False,
            )

        stock_levels = self.load_stock_levels()
        printed_skus: list[str] = []
        consumed_skus: list[str] = []
        warnings: list[str] = []

        for decision in preflight.decisions:
            current = max(0, int(stock_levels.get(decision.sku, decision.on_hand_qty)))
            produced = 0
            if decision.will_print:
                requested_production = max(0, int(decision.final_print_qty))
                if self._print_decision_product(decision.sku, requested_production, warnings):
                    produced = requested_production
            consumed = 0
            if mode == StartMode.INVOICES_AND_PRINT:
                consumed = max(0, int(decision.required_qty))
            final_stock = max(0, current + produced - consumed)
            stock_levels[decision.sku] = final_stock

            if produced > 0:
                printed_skus.append(decision.sku)
            if consumed > 0:
                consumed_skus.append(decision.sku)

        self._save_stock_levels(stock_levels)
        return StartExecutionReport(
            mode=mode,
            open_invoice_count=preflight.open_invoice_count,
            decisions_count=len(preflight.decisions),
            printed_skus=printed_skus,
            consumed_skus=consumed_skus,
            stock_updated=True,
            warnings=warnings,
        )

    def _print_decision_product(self, sku: str, qty: int, warnings: list[str]) -> bool:
        """Print one SKU through the new PyMuPDF/QPrinter print-plan path."""
        qty = max(0, int(qty or 0))
        if qty <= 0:
            return False
        product = self._product_row_by_sku(sku)
        if product is None:
            warnings.append(f"{sku}: kein Produktdatensatz fuer Notendruck gefunden")
            return False
        pdf_path = str(product.print_file_path or "").strip()
        if not pdf_path:
            warnings.append(f"{sku}: kein PDF-Pfad fuer Notendruck hinterlegt")
            return False
        if not Path(pdf_path).is_file():
            warnings.append(f"{sku}: PDF-Datei nicht gefunden: {pdf_path}")
            return False
        if not str(product.print_profile_id or "").strip() and not product.print_plan:
            warnings.append(f"{sku}: kein Druckprofil/Druckplan im neuen Modul hinterlegt")
            return False
        page_count = self._pdf_page_count(pdf_path)
        try:
            print_pdf_by_plan(
                pdf_path,
                self._config.printing,
                print_plan=list(product.print_plan or []),
                profile_id=str(product.print_profile_id or "").strip(),
                copies=qty,
                page_count=page_count,
                print_queue=self._print_queue,
                job_kind="product",
            )
        except Exception as exc:  # noqa: BLE001
            warnings.append(f"{sku}: Notendruck fehlgeschlagen: {exc}")
            logger.warning("START product print failed for %s: %s", sku, exc)
            return False
        return True

    def _product_row_by_sku(self, sku: str) -> ProductRow | None:
        wanted = str(sku or "").strip().upper()
        if not wanted:
            return None
        for product in self.list_products():
            if str(product.sku or "").strip().upper() == wanted:
                return product
        return None

    @staticmethod
    def _pdf_page_count(pdf_path: str) -> int | None:
        if fitz is None:
            return None
        doc = None
        try:
            doc = fitz.open(pdf_path)
            return len(doc)
        except Exception:
            return None
        finally:
            try:
                if doc is not None:
                    doc.close()
            except Exception:
                pass

    def _save_stock_levels(self, stock_levels: dict[str, int]) -> None:
        if self._settings_repo is None:
            return
        clean: dict[str, int] = {}
        for sku, qty in stock_levels.items():
            if not isinstance(sku, str) or not sku:
                continue
            clean[sku] = max(0, int(qty))
        self._settings_repo.set_value_json(_STOCK_KEY, json.dumps(clean, ensure_ascii=False))

    def describe(self) -> str:
        return (
            "Produkte / Inventar: Bestand, Druckplaene, Wix/sevDesk-Abgleich — "
            "persistiert spaeter in PostgreSQL."
        )

    def list_products(self) -> list[ProductRow]:
        """Return product catalogue rows from DB (``inventory.products`` JSON array).

        Each entry must be a JSON object with optional keys:
        ``sku``, ``name``, ``category``, ``on_hand``, ``price_eur``, ``wix_id``, ``sevdesk_id``.
        Returns an empty list when no DB connection or data is available.
        """
        if self._settings_repo is None:
            return []
        raw = self._settings_repo.get_value_json(_PRODUCTS_KEY)
        if not raw:
            return []
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            logger.warning("Invalid JSON in %s", _PRODUCTS_KEY)
            return []
        if not isinstance(data, list):
            return []
        rows: list[ProductRow] = []
        for item in data:
            if not isinstance(item, dict):
                continue
            try:
                on_hand = int(item.get("on_hand") or 0)
            except (TypeError, ValueError):
                on_hand = 0
            rows.append(
                ProductRow(
                    sku=str(item.get("sku") or ""),
                    name=str(item.get("name") or ""),
                    category=str(item.get("category") or ""),
                    on_hand=on_hand,
                    price_eur=str(item.get("price_eur") or ""),
                    brand_name=str(item.get("brand_name") or item.get("brand") or ""),
                    brand_id=str(item.get("brand_id") or ""),
                    wix_id=str(item.get("wix_id") or ""),
                    sevdesk_id=str(item.get("sevdesk_id") or ""),
                    print_file_path=str(item.get("print_file_path") or ""),
                    print_profile_id=str(item.get("print_profile_id") or ""),
                    print_plan=[
                        entry for entry in (item.get("print_plan") or [])
                        if isinstance(entry, dict)
                    ],
                    title_print_configs=(
                        dict(item.get("title_print_configs"))
                        if isinstance(item.get("title_print_configs"), dict)
                        else {}
                    ),
                )
            )
        return rows

    def save_products(self, rows: list[ProductRow]) -> None:
        """Persist ``inventory.products`` rows to settings repository."""
        if self._settings_repo is None:
            return
        payload = [
            {
                "sku": row.sku,
                "name": row.name,
                "category": row.category,
                "on_hand": max(0, int(row.on_hand)),
                "price_eur": row.price_eur,
                "brand_name": str(row.brand_name or "").strip(),
                "brand_id": str(row.brand_id or "").strip(),
                "wix_id": row.wix_id,
                "sevdesk_id": row.sevdesk_id,
                "print_file_path": str(row.print_file_path or "").strip(),
                "print_profile_id": str(row.print_profile_id or "").strip(),
                "print_plan": list(row.print_plan or []),
                "title_print_configs": dict(row.title_print_configs or {}),
            }
            for row in rows
            if row.sku
        ]
        self._settings_repo.set_value_json(_PRODUCTS_KEY, json.dumps(payload, ensure_ascii=False))

    def save_product_print_config(
        self,
        *,
        sku: str,
        name: str = "",
        print_file_path: str,
        print_profile_id: str,
        print_plan: list[dict[str, str]] | None = None,
    ) -> ProductRow:
        """Persist a default and title-specific print config for one SKU."""
        clean_sku = str(sku or "").strip().upper()
        if not clean_sku:
            raise RuntimeError("SKU fehlt")
        clean_path = str(print_file_path or "").strip()
        clean_profile = str(print_profile_id or "").strip()
        clean_plan = [entry for entry in (print_plan or []) if isinstance(entry, dict)]
        if not clean_path:
            raise RuntimeError("Druckpfad fehlt")
        if not clean_profile and not clean_plan:
            raise RuntimeError("Druckplan oder Profil fehlt")

        rows = self.list_products()
        by_sku = {row.sku.strip().upper(): row for row in rows if row.sku.strip()}
        current = by_sku.get(clean_sku)
        if current is None:
            current = ProductRow(
                sku=clean_sku,
                name=str(name or clean_sku).strip(),
                category="",
                on_hand=0,
                price_eur="",
                wix_id="",
                sevdesk_id="",
            )

        title_configs = dict(current.title_print_configs or {})
        title = str(name or current.name or "").strip()
        title_config = {
            "path": clean_path,
            "profile_id": clean_profile,
            "print_plan": clean_plan,
        }
        if title:
            title_configs[title] = title_config

        updated = ProductRow(
            sku=current.sku or clean_sku,
            name=current.name or title or clean_sku,
            category=current.category,
            on_hand=current.on_hand,
            price_eur=current.price_eur,
            wix_id=current.wix_id,
            sevdesk_id=current.sevdesk_id,
            print_file_path=current.print_file_path or clean_path,
            print_profile_id=current.print_profile_id or clean_profile,
            print_plan=list(current.print_plan or clean_plan),
            title_print_configs=title_configs,
        )
        by_sku[clean_sku] = updated
        self.save_products(sorted(by_sku.values(), key=lambda row: row.sku))
        return updated

    def load_print_plans(self) -> list[dict[str, object]]:
        """Load print plan list (free-form JSON objects) from settings."""
        if self._settings_repo is None:
            return []
        raw = self._settings_repo.get_value_json(_PRINT_PLANS_KEY)
        if not raw:
            return []
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            logger.warning("Invalid JSON in %s", _PRINT_PLANS_KEY)
            return []
        if not isinstance(data, list):
            return []
        return [item for item in data if isinstance(item, dict)]

    def save_print_plans(self, plans: list[dict[str, object]]) -> None:
        """Persist print plan list to settings."""
        if self._settings_repo is None:
            return
        clean = [item for item in plans if isinstance(item, dict)]
        self._settings_repo.set_value_json(_PRINT_PLANS_KEY, json.dumps(clean, ensure_ascii=False, indent=2))

    def import_legacy_print_data(self) -> LegacyPrintImportReport:
        """Import legacy PDF paths and print plans into ``inventory.products``."""
        source = self._detect_legacy_inventory_store_path()
        if source is None:
            raise RuntimeError("Legacy inventory_store.json nicht gefunden")

        try:
            payload = json.loads(source.read_text(encoding="utf-8"))
        except Exception as exc:
            raise RuntimeError(f"Legacy inventory_store.json unlesbar: {exc}") from exc

        records = payload.get("records") if isinstance(payload, dict) else None
        if not isinstance(records, dict):
            raise RuntimeError("Legacy inventory_store.json hat kein gueltiges 'records'-Objekt")

        existing = {row.sku.strip().upper(): row for row in self.list_products() if row.sku.strip()}
        unknown_profiles: set[str] = set()
        missing_files: list[str] = []
        products_updated = 0
        title_configs_imported = 0

        valid_profile_ids = {profile.id for profile in self._config.printing.all_profiles()}
        valid_profile_ids.update(
            {"noten_a4_simplex", "noten_a4_duplex", "canon_brochure_mono", "canon_brochure_duo"}
        )

        for raw_sku, raw_record in records.items():
            if not isinstance(raw_record, dict):
                continue
            sku = str(raw_sku or "").strip().upper()
            if not sku:
                continue
            current = existing.get(sku) or ProductRow(
                sku=sku,
                name=str(raw_record.get("name") or "").strip(),
                category=str(raw_record.get("category") or "").strip(),
                on_hand=0,
                price_eur="",
                brand_name="",
                brand_id="",
                wix_id="",
                sevdesk_id=str(raw_record.get("sevdesk_part_id") or "").strip(),
            )

            default_entry = self._normalize_legacy_pdf_entry(source, self._pick_default_pdf_entry(raw_record.get("pdfs")))
            title_entries, title_count = self._normalize_legacy_title_configs(source, raw_record.get("title_print_configs"))
            title_configs_imported += title_count

            for candidate in [default_entry, *title_entries.values()]:
                profile_id = str(candidate.get("profile_id") or "").strip()
                if profile_id and profile_id not in valid_profile_ids:
                    unknown_profiles.add(profile_id)
                path = str(candidate.get("path") or "").strip()
                if not path:
                    raw_path = str(candidate.get("_raw_path") or "").strip()
                    if raw_path:
                        missing_files.append(f"{sku}: {raw_path}")

            updated = ProductRow(
                sku=current.sku,
                name=current.name or str(raw_record.get("name") or "").strip(),
                category=current.category or str(raw_record.get("category") or "").strip(),
                on_hand=current.on_hand,
                price_eur=current.price_eur,
                brand_name=current.brand_name,
                brand_id=current.brand_id,
                wix_id=current.wix_id,
                sevdesk_id=current.sevdesk_id or str(raw_record.get("sevdesk_part_id") or "").strip(),
                print_file_path=str(default_entry.get("path") or current.print_file_path or "").strip(),
                print_profile_id=str(default_entry.get("profile_id") or current.print_profile_id or "").strip(),
                print_plan=list(default_entry.get("print_plan") or current.print_plan or []),
                title_print_configs=title_entries or dict(current.title_print_configs or {}),
            )
            if updated != current:
                products_updated += 1
            existing[sku] = updated

        self.save_products(sorted(existing.values(), key=lambda row: row.sku))

        return LegacyPrintImportReport(
            source_path=str(source),
            records_seen=len(records),
            products_updated=products_updated,
            title_configs_imported=title_configs_imported,
            missing_files=missing_files,
            unknown_profiles=sorted(unknown_profiles),
        )

    @staticmethod
    def _pick_default_pdf_entry(raw_entries: object) -> dict[str, object]:
        if not isinstance(raw_entries, list):
            return {}
        first_entry: dict[str, object] = {}
        for raw in raw_entries:
            if not isinstance(raw, dict):
                continue
            if not first_entry:
                first_entry = raw
            if bool(raw.get("is_default")):
                return raw
        return first_entry

    @staticmethod
    def _normalize_legacy_pdf_entry(base_path: Path, raw: dict[str, object]) -> dict[str, object]:
        if not isinstance(raw, dict):
            return {}
        raw_path = str(raw.get("path") or "").strip()
        resolved_path = ""
        if raw_path:
            path = Path(raw_path)
            if not path.is_absolute():
                path = (base_path.parent / path).resolve()
            if path.exists():
                resolved_path = str(path)
        return {
            "path": resolved_path,
            "_raw_path": raw_path,
            "profile_id": str(raw.get("profile_id") or "").strip(),
            "print_plan": InventoryService._normalize_print_plan(raw.get("print_plan")),
        }

    @staticmethod
    def _normalize_legacy_title_configs(base_path: Path, raw_configs: object) -> tuple[dict[str, dict[str, object]], int]:
        if not isinstance(raw_configs, dict):
            return {}, 0
        out: dict[str, dict[str, object]] = {}
        imported = 0
        for state in raw_configs.values():
            if not isinstance(state, dict):
                continue
            title = str(state.get("title") or "").strip()
            if not title:
                continue
            entry = InventoryService._normalize_legacy_pdf_entry(
                base_path,
                InventoryService._pick_default_pdf_entry(state.get("pdfs")),
            )
            if not entry:
                continue
            out[title] = entry
            imported += 1
        return out, imported

    @staticmethod
    def _normalize_print_plan(raw_plan: object) -> list[dict[str, str]]:
        if not isinstance(raw_plan, list):
            return []
        plan: list[dict[str, str]] = []
        for raw in raw_plan:
            if not isinstance(raw, dict):
                continue
            range_text = str(raw.get("range") or "").strip() or "Alle Seiten"
            profile_id = str(raw.get("profile_id") or "").strip()
            if not profile_id:
                continue
            plan.append({"range": range_text, "profile_id": profile_id})
        return plan

    @staticmethod
    def _detect_legacy_inventory_store_path() -> Path | None:
        env_path = str(os.environ.get("XW_LEGACY_INVENTORY_STORE_PATH") or "").strip()
        candidates: list[Path] = []
        if env_path:
            candidates.append(Path(env_path).expanduser())
        repo_root = Path(__file__).resolve().parents[4]
        candidates.extend(
            [
                repo_root / "data" / "inventory_store.json",
                repo_root.parent / "sevDesk" / "data" / "inventory_store.json",
                repo_root.parent / "sevDesk" / "sevdesk_wix_fulfillment" / "data" / "inventory_store.json",
            ]
        )
        for candidate in candidates:
            try:
                resolved = candidate.resolve()
            except OSError:
                continue
            if resolved.exists() and resolved.is_file():
                return resolved
        return None
