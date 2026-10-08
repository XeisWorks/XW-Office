"""Expense audit / Ausgaben-Check.

Reconciles bank transactions against booked sevDesk documents per month
and mandant. Ignore rules and period shifts are real, multi-PC-synced
tables (see :mod:`xw_office.models.expense_check`) instead of the legacy
flat JSON files, and are matched with the shared fuzzy-text utilities so a
recurring payment whose reference changes each month is still recognized.
"""
from __future__ import annotations

import csv
import datetime
import io
import json
import logging
import re
import threading
import uuid
from collections.abc import Sequence
from dataclasses import dataclass, replace
from decimal import Decimal
from enum import Enum
from types import SimpleNamespace
from typing import TYPE_CHECKING

from xw_office.core.fuzzy_match import fuzzy_ratio
from xw_office.core.text_normalize import clean_bank_purpose, normalize_german_text
from xw_office.models.expense_pipeline import (
    ExpensePositionRule,
    ExpensePurposeRule,
    ExpenseSupplierLink,
)
from xw_office.repositories.settings_kv import SettingKvRepository
from xw_office.services.expenses.bank_provider import (
    BankDocumentLink,
    BankExpense,
    SevdeskBankAccount,
    SevdeskExpenseProvider,
)
from xw_office.services.expenses.reference_parser import project_expense_text
from xw_office.services.sevdesk.urls import sevdesk_document_url

if TYPE_CHECKING:
    from xw_office.models.expense_check import ExpenseIgnoreRule, ExpenseShiftEntry
    from xw_office.repositories.expense_check import ExpenseCheckRepository
    from xw_office.repositories.expense_pipeline import ExpensePipelineRepository

logger = logging.getLogger(__name__)

_EXPENSES_KEY = "expenses.open_items"
_PERIOD_RE = re.compile(r"^\d{4}-(0[1-9]|1[0-2])$")

# Legacy Ausgaben-Check default: SequenceMatcher ratio >= 0.68 recognizes a
# recurring transaction whose purpose text varies slightly month to month.
DEFAULT_IGNORE_THRESHOLD = 0.68


@dataclass(frozen=True)
class ExpenseRow:
    """One expense row for review/export."""

    ref: str
    supplier: str
    gross_amount: str
    category: str
    status: str
    note: str


@dataclass(frozen=True)
class BankExpenseRow:
    """Normalized bank row shared by the central and profile-filtered views."""

    transaction_id: str
    value_date: datetime.date
    payee: str
    purpose: str
    amount: Decimal
    currency: str
    iban: str = ""
    profile_status: str = ""
    review_status: str = "open"
    sevdesk_url: str = ""
    supplier_url: str = ""
    rule_source: str = ""
    document_link_scan_complete: bool = True
    raw_payee: str = ""
    raw_payment_reference: str = ""
    raw_purpose: str = ""
    display_source: str = ""
    display_confidence: float = 0.0
    position_key: str = ""
    position_source: str = ""
    position_rule_label: str = ""
    documents: tuple["ExpenseDocumentView", ...] = ()


@dataclass(frozen=True)
class ExpenseDocumentView:
    resource_type: str
    external_id: str
    document_number: str
    url: str


@dataclass(frozen=True)
class ExpensePositionView:
    key: str
    label: str
    initials: str
    color: str
    sort_order: int
    enabled: bool = True


DEFAULT_EXPENSE_POSITIONS: tuple[ExpensePositionView, ...] = (
    ExpensePositionView("xw", "XeisWorks", "XW", "#c6922d", 10),
    ExpensePositionView("mh", "MusikHeroes", "MH", "#c0392b", 20),
    ExpensePositionView("wm", "WüdaraMusi", "WM", "#2e8b57", 30),
    ExpensePositionView("bh", "Blechhaufn", "BH", "#2878b5", 40),
    ExpensePositionView("priv", "Privat", "PRIV", "#777777", 50),
)


class ExpenseAction(str, Enum):
    """Actions a user can take on one open Ausgaben-Check row."""

    IGNORE_ONCE = "ignore_once"
    IGNORE_FOREVER = "ignore_forever"
    SHIFT = "shift"
    FLAG = "flag"


@dataclass(frozen=True)
class IgnoreRuleView:
    """UI-facing view of a persisted :class:`ExpenseIgnoreRule`."""

    id: str
    mandant: str
    pattern_original: str
    pattern_normalized: str
    scope: str


@dataclass(frozen=True)
class ShiftEntryView:
    """UI-facing view of a persisted :class:`ExpenseShiftEntry`."""

    id: str
    mandant: str
    transaction_ref: str
    source_period: str
    target_period: str
    note: str


@dataclass(frozen=True)
class ExpenseRowClassification:
    """One row plus the ignore/shift decision applied to it."""

    row: ExpenseRow
    effective_status: str  # "open" | "ignored" | "shifted"
    matched_ignore_rule: IgnoreRuleView | None = None
    shift_entry: ShiftEntryView | None = None


def _to_ignore_rule_view(row: "ExpenseIgnoreRule") -> IgnoreRuleView:
    return IgnoreRuleView(
        id=str(row.id),
        mandant=row.mandant,
        pattern_original=row.pattern_original,
        pattern_normalized=row.pattern_normalized,
        scope=row.scope,
    )


def _to_shift_entry_view(row: "ExpenseShiftEntry") -> ShiftEntryView:
    return ShiftEntryView(
        id=str(row.id),
        mandant=row.mandant,
        transaction_ref=row.transaction_ref,
        source_period=row.source_period,
        target_period=row.target_period,
        note=row.note,
    )


class ExpenseAuditService:
    """Review, classify, and export expenses for tax reporting."""

    def __init__(
        self,
        settings_repo: SettingKvRepository | None = None,
        *,
        expense_check_repo: "ExpenseCheckRepository | None" = None,
        bank_provider: SevdeskExpenseProvider | None = None,
        pipeline_repo: "ExpensePipelineRepository | None" = None,
        tenant_key: str = "xw",
        tenant_providers: dict[str, SevdeskExpenseProvider] | None = None,
    ) -> None:
        self._repo = settings_repo
        self._expense_repo = expense_check_repo
        self._tenant_key = tenant_key.strip().lower() or "xw"
        self._tenant_providers = dict(tenant_providers or {})
        self._bank_provider = self._tenant_providers.get(self._tenant_key, bank_provider)
        self._pipeline_repo = pipeline_repo
        self._memory_profile_flags: dict[tuple[str, str], str] = {}
        self._document_scan_lock = threading.Lock()

    def for_tenant(self, tenant_key: str) -> "ExpenseAuditService":
        """Return an independent, account-bound view of this shared service."""
        key = tenant_key.strip().lower() or "xw"
        return ExpenseAuditService(
            self._repo,
            expense_check_repo=self._expense_repo,
            bank_provider=self._tenant_providers.get(key),
            pipeline_repo=self._pipeline_repo,
            tenant_key=key,
            tenant_providers=self._tenant_providers,
        )

    def _stored_position_key(self, key: str) -> str:
        normalized = key.strip().lower()
        return normalized if self._tenant_key == "xw" else f"{self._tenant_key}:{normalized}"

    def _public_position_key(self, key: str) -> str:
        prefix = f"{self._tenant_key}:"
        return key[len(prefix) :] if key.startswith(prefix) else key

    def _owns_position_key(self, key: str) -> bool:
        return ":" not in key if self._tenant_key == "xw" else key.startswith(f"{self._tenant_key}:")

    def _cache_account_id(self, account_id: str) -> str:
        return account_id if self._tenant_key == "xw" else f"{self._tenant_key}:{account_id}"

    def _cache_document_type(self, resource_type: str) -> str:
        return resource_type if self._tenant_key == "xw" else f"{self._tenant_key}:{resource_type}"

    def list_positions(self, *, enabled_only: bool = True) -> list[ExpensePositionView]:
        if self._pipeline_repo is None:
            return [item for item in DEFAULT_EXPENSE_POSITIONS if item.enabled or not enabled_only]
        self._pipeline_repo.ensure_positions(
            [
                {
                    "key": self._stored_position_key(item.key),
                    "label": item.label,
                    "initials": item.initials,
                    "color": item.color,
                    "sort_order": item.sort_order,
                    "enabled": item.enabled,
                }
                for item in DEFAULT_EXPENSE_POSITIONS
            ]
        )
        return [
            ExpensePositionView(
                self._public_position_key(row.key),
                row.label,
                row.initials,
                row.color,
                row.sort_order,
                row.enabled,
            )
            for row in self._pipeline_repo.list_positions(enabled_only=enabled_only)
            if self._owns_position_key(row.key)
        ]

    def describe(self) -> str:
        return (
            "Ausgaben-Check: Belege pruefen und fuer UVA/FIBU vorbereiten "
            "(DB-Liste + Filter + CSV-Export, mit Ignore-Regeln und Perioden-Verschiebung)."
        )

    def list_bank_expenses(
        self,
        *,
        start: datetime.date,
        end: datetime.date,
        profile_key: str = "",
        refresh: bool = True,
        refresh_document_links: bool = False,
        force_document_refresh: bool = False,
        outgoing_only: bool = True,
        retry_unlinked_documents: bool = False,
    ) -> list[BankExpenseRow]:
        """Load cached or current bank transactions and resolve linked documents.

        ``refresh_document_links`` intentionally avoids a new bank import. It
        compares sevDesk document headers with the local scan cache and only
        resolves newly added or changed documents.
        """
        if self._bank_provider is None:
            return []
        account: SevdeskBankAccount | None = None
        if refresh:
            account, rows = self._bank_provider.fetch(start, end, outgoing_only=outgoing_only)
        elif self._pipeline_repo is not None:
            rows = []
            cached_snapshots = [
                snapshot
                for snapshot in self._pipeline_repo.list_snapshots(
                    start=start, end=end, direction="outgoing" if outgoing_only else ""
                )
                if (
                    ":" not in snapshot.account_id
                    if self._tenant_key == "xw"
                    else snapshot.account_id.startswith(f"{self._tenant_key}:")
                )
            ]
            for snapshot in cached_snapshots:
                rows.append(
                    BankExpense(
                        external_id=snapshot.external_id,
                        account_id=snapshot.account_id,
                        value_date=snapshot.value_date,
                        entry_date=snapshot.entry_date,
                        amount=Decimal(str(snapshot.amount)),
                        currency=snapshot.currency,
                        direction=snapshot.direction,
                        payee_name=snapshot.payee_name,
                        payee_normalized=snapshot.payee_normalized,
                        counterparty_iban=snapshot.counterparty_iban,
                        payment_reference=snapshot.payment_reference,
                        purpose=snapshot.purpose,
                        sevdesk_status=snapshot.sevdesk_status,
                    )
                )
        else:
            rows = []

        links_by_transaction: dict[str, list[BankDocumentLink]] = {}
        snapshot_ids: dict[str, uuid.UUID] = {}
        existing_external_ids: set[str] = set()
        if self._pipeline_repo is not None and refresh:
            cached_account_id = self._cache_account_id(str(getattr(account, "id", "")))
            existing_external_ids = {
                snapshot.external_id
                for snapshot in self._pipeline_repo.list_snapshots(
                    start=start,
                    end=end,
                    direction="outgoing" if outgoing_only else "",
                    account_id=cached_account_id,
                )
            }
            for row in rows:
                snapshot = self._pipeline_repo.upsert_snapshot(
                    {
                        "account_id": cached_account_id,
                        "external_id": row.external_id,
                        "value_date": row.value_date,
                        "entry_date": row.entry_date,
                        "amount": row.amount,
                        "currency": row.currency,
                        "direction": row.direction,
                        "payee_name": row.payee_name,
                        "payee_normalized": row.payee_normalized,
                        "counterparty_iban": row.counterparty_iban,
                        "payment_reference": row.payment_reference,
                        "purpose": row.purpose,
                        "sevdesk_status": row.sevdesk_status,
                    }
                )
                snapshot_ids[row.external_id] = snapshot.id
        elif self._pipeline_repo is not None:
            snapshot_ids = {snapshot.external_id: snapshot.id for snapshot in cached_snapshots}

        link_scan_complete = False
        has_new_transactions = any(row.external_id not in existing_external_ids for row in rows)
        completed_scan_exists = (
            self._pipeline_repo is not None
            and account is not None
            and all(row.external_id in existing_external_ids for row in rows)
            and self._pipeline_repo.has_complete_import_run(
                account_id=self._cache_account_id(account.id),
                period_start=start,
                period_end=end,
            )
        )
        if refresh and completed_scan_exists and not force_document_refresh and not retry_unlinked_documents:
            # A refresh still obtains current bank movements, but avoids paging
            # every historical sevDesk document for a range already checked.
            # The UI exposes an explicit force action for a manual re-check.
            link_scan_complete = True
        elif refresh or refresh_document_links:
            try:
                account = account or self._bank_provider.find_account()
                with self._document_scan_lock:
                    cached_document_fingerprints = (
                        self._pipeline_repo.list_document_scan_fingerprints()
                        if self._pipeline_repo is not None
                        else {}
                    )
                    cache_type_prefix = f"{self._tenant_key}:"
                    cached_fingerprints = {
                        (
                            resource_type[len(cache_type_prefix) :]
                            if self._tenant_key != "xw"
                            else resource_type,
                            external_id,
                        ): fingerprint
                        for (resource_type, external_id), fingerprint in cached_document_fingerprints.items()
                        if (
                            ":" not in resource_type
                            if self._tenant_key == "xw"
                            else resource_type.startswith(cache_type_prefix)
                        )
                    }
                    retry_cached_documents = set()
                    if not refresh_document_links:
                        retry_cached_documents = (
                            set(cached_fingerprints)
                            if has_new_transactions
                            else (
                                {
                                    (
                                        resource_type[len(cache_type_prefix) :]
                                        if self._tenant_key != "xw"
                                        else resource_type,
                                        external_id,
                                    )
                                    for resource_type, external_id in self._pipeline_repo.list_unlinked_document_scan_keys()
                                    if (
                                        ":" not in resource_type
                                        if self._tenant_key == "xw"
                                        else resource_type.startswith(cache_type_prefix)
                                    )
                                }
                                if self._pipeline_repo is not None and retry_unlinked_documents
                                else set()
                            )
                        )
                    # A focused Beleg-Refresh must not re-query every already
                    # unlinked document. A new assignment changes its header
                    # fingerprint and is therefore picked up by the scan.
                    scan = self._bank_provider.resolve_document_links(
                        start,
                        end,
                        account_id=account.id,
                        cached_fingerprints=cached_fingerprints,
                        retry_cached_documents=retry_cached_documents,
                        force=force_document_refresh,
                    )
                    link_scan_complete = scan.complete
                    for link in scan.links:
                        links_by_transaction.setdefault(link.transaction_external_id, []).append(link)
                    if self._pipeline_repo is not None:
                        for document in scan.scanned_documents:
                            self._pipeline_repo.delete_document_links_for_document(
                                resource_type=document.resource_type,
                                external_id=document.external_id,
                                transaction_ids=list(snapshot_ids.values()),
                            )
                            self._pipeline_repo.upsert_document_scan(
                                resource_type=self._cache_document_type(document.resource_type),
                                external_id=document.external_id,
                                fingerprint=document.fingerprint,
                            )
                        for link in scan.links:
                            transaction_id = snapshot_ids.get(link.transaction_external_id)
                            if transaction_id is not None:
                                self._pipeline_repo.add_document_link(
                                    transaction_id=transaction_id,
                                    resource_type=link.resource_type,
                                    external_id=link.external_id,
                                    document_number=link.document_number,
                                )
                        self._pipeline_repo.record_import_run(
                            account_id=self._cache_account_id(account.id),
                            account_name=str(getattr(account, "name", "")),
                            period_start=start,
                            period_end=end,
                            status="complete" if scan.complete else "partial",
                            sevdesk_last_sync_at=getattr(account, "last_sync_at", None),
                            transaction_count=len(rows),
                            linked_count=len(scan.links),
                            error_count=scan.error_count,
                        )
            except Exception as exc:  # noqa: BLE001
                logger.warning("sevDesk-Belegscan unvollständig: %s", exc)
                link_scan_complete = False
                if self._pipeline_repo is not None and account is not None:
                    self._pipeline_repo.record_import_run(
                        account_id=self._cache_account_id(account.id),
                        account_name=str(getattr(account, "name", "")),
                        period_start=start,
                        period_end=end,
                        status="partial",
                        sevdesk_last_sync_at=getattr(account, "last_sync_at", None),
                        transaction_count=len(rows),
                        linked_count=0,
                        error_count=1,
                        error_text=str(exc)[:2000],
                    )
        elif self._pipeline_repo is not None and rows:
            link_scan_complete = self._pipeline_repo.has_complete_import_run(
                account_id=rows[0].account_id,
                period_start=start,
                period_end=end,
            )

        persisted_links_by_transaction = (
            self._pipeline_repo.list_document_links_for_transactions(list(snapshot_ids.values()))
            if self._pipeline_repo is not None
            else {}
        )
        transaction_ids = list(snapshot_ids.values())
        profile_assignments = (
            self._pipeline_repo.list_assignments_for_transactions(
                transaction_ids=transaction_ids, profile_key=profile_key
            )
            if self._pipeline_repo is not None and profile_key
            else {}
        )
        position_assignments = (
            self._pipeline_repo.list_position_assignments_for_transactions(transaction_ids)
            if self._pipeline_repo is not None
            else {}
        )
        supplier_links = (
            [
                link
                for link in self._pipeline_repo.list_all_supplier_links()
                if link.profile_key == self._tenant_key
                or (self._tenant_key == "xw" and link.profile_key == "")
            ]
            if self._pipeline_repo is not None
            else []
        )
        purpose_rules = (
            self._pipeline_repo.list_purpose_rules(
                enabled_only=True, tenant_key=self._tenant_key
            )
            if self._pipeline_repo is not None
            else []
        )

        result: list[BankExpenseRow] = []
        rules = self._pipeline_repo.list_rules(profile_key) if self._pipeline_repo and profile_key else []
        position_rules = (
            [
                rule
                for rule in self._pipeline_repo.list_position_rules()
                if self._owns_position_key(rule.position_key)
            ]
            if self._pipeline_repo
            else []
        )
        for row in rows:
            projection = project_expense_text(
                payee_name=row.payee_name,
                payment_reference=row.payment_reference,
                purpose=row.purpose,
            )
            projection = replace(
                projection,
                purpose=self._apply_purpose_rules(
                    projection.purpose,
                    row.payee_normalized or projection.merchant_key,
                    purpose_rules,
                ),
            )
            snapshot_id = str(snapshot_ids.get(row.external_id) or "")
            status = ""
            source = ""
            if profile_key:
                status, source = self._match_profile_rule(row, profile_key, rules)
                if self._pipeline_repo is not None and snapshot_id:
                    profile_assignment = profile_assignments.get(uuid.UUID(snapshot_id))
                    if profile_assignment is not None:
                        status = profile_assignment.status
                        source = profile_assignment.source
                status = status or self._memory_profile_flags.get((profile_key, row.external_id), "")
            document_links = links_by_transaction.get(row.external_id, [])
            position_key = ""
            position_source = ""
            position_rule_label = ""
            if self._pipeline_repo is not None and snapshot_id:
                tx_uuid = uuid.UUID(snapshot_id)
                persisted_links = persisted_links_by_transaction.get(tx_uuid, [])
                document_links = [
                    BankDocumentLink(
                        transaction_external_id=row.external_id,
                        resource_type=link.resource_type,
                        external_id=link.external_id,
                        document_number=link.document_number,
                    )
                    for link in persisted_links
                ]
                position_assignment = position_assignments.get(tx_uuid)
                matched_position_rule = self._match_position_rule(row, position_rules)
                if position_assignment is None and matched_position_rule is not None:
                    position_assignment = self._pipeline_repo.assign_position(
                        transaction_id=tx_uuid,
                        position_key=matched_position_rule.position_key,
                        source="automatic",
                        matched_rule_id=matched_position_rule.id,
                    )
                    position_assignments[tx_uuid] = position_assignment
                if position_assignment is not None:
                    position_key = self._public_position_key(position_assignment.position_key)
                    position_source = position_assignment.source
                    if position_assignment.matched_rule_id:
                        matching = next(
                            (
                                item
                                for item in position_rules
                                if item.id == position_assignment.matched_rule_id
                            ),
                            None,
                        )
                        position_rule_label = str(getattr(matching, "label", "") or "")
            if profile_key == "musikheroes" and position_key == "mh":
                status = "included"
                source = position_source or "position"
            sevdesk_link = ""
            document_views = tuple(
                ExpenseDocumentView(
                    resource_type=link.resource_type,
                    external_id=link.external_id,
                    document_number=link.document_number or link.external_id,
                    url=sevdesk_document_url(
                        self._bank_provider.base_url, link.resource_type, link.external_id
                    ),
                )
                for link in document_links
            )
            if document_views:
                sevdesk_link = document_views[0].url
            supplier_url = ""
            if self._pipeline_repo is not None:
                match = self._matching_supplier_link(
                    supplier_links, row.payee_normalized, row.counterparty_iban
                ) or self._matching_supplier_link(
                    supplier_links, projection.merchant_key, row.counterparty_iban
                )
                if match is not None:
                    supplier_url = match.url
            result.append(
                BankExpenseRow(
                    transaction_id=snapshot_id or row.external_id,
                    value_date=row.value_date,
                    payee=projection.payee,
                    iban=row.counterparty_iban,
                    purpose=projection.purpose,
                    amount=row.amount,
                    currency=row.currency,
                    sevdesk_url=sevdesk_link,
                    supplier_url=supplier_url,
                    profile_status=status,
                    rule_source=source,
                    document_link_scan_complete=link_scan_complete,
                    raw_payee=row.payee_name,
                    raw_payment_reference=row.payment_reference,
                    raw_purpose=row.purpose,
                    display_source=projection.source,
                    display_confidence=projection.confidence,
                    position_key=position_key,
                    position_source=position_source,
                    position_rule_label=position_rule_label,
                    documents=document_views,
                )
            )
        return result

    @staticmethod
    def _matching_supplier_link(
        links: Sequence[ExpenseSupplierLink], payee_normalized: str, iban: str
    ) -> ExpenseSupplierLink | None:
        """Mirror repository supplier matching without opening a session per row."""
        for link in links:
            if link.payee_normalized != payee_normalized:
                continue
            if iban and link.counterparty_iban not in ("", iban):
                continue
            return link
        return None

    @staticmethod
    def _apply_purpose_rules(
        purpose: str, payee_normalized: str, rules: Sequence[ExpensePurposeRule]
    ) -> str:
        """Apply recipient-scoped display cleanup without altering source data."""
        result = purpose
        normalized_payee = normalize_german_text(payee_normalized)
        for rule in rules:
            if rule.payee_normalized != normalized_payee or not rule.remove_text.strip():
                continue
            result = re.sub(re.escape(rule.remove_text.strip()), "", result, flags=re.IGNORECASE)
        result = re.sub(r"\s{2,}", " ", result)
        result = re.sub(r"\s+([,.;:])", r"\1", result).strip(" \t-–—,;")
        return result or purpose

    @staticmethod
    def _match_position_rule(
        row: BankExpense, rules: Sequence[ExpensePositionRule]
    ) -> ExpensePositionRule | None:
        projection = project_expense_text(
            payee_name=row.payee_name,
            payment_reference=row.payment_reference,
            purpose=row.purpose,
        )
        payee = row.payee_normalized or projection.merchant_key
        iban = row.counterparty_iban.replace(" ", "").upper()
        purpose = normalize_german_text(
            " ".join(
                (
                    row.payee_name,
                    row.payment_reference,
                    row.purpose,
                    projection.purpose,
                )
            )
        )
        matches: list[ExpensePositionRule] = []
        for rule in rules:
            expected_payee = str(getattr(rule, "payee_normalized", "") or "")
            expected_iban = str(getattr(rule, "counterparty_iban", "") or "").replace(" ", "").upper()
            expected_purpose = normalize_german_text(
                str(getattr(rule, "purpose_contains", "") or "")
            )
            if expected_payee and expected_payee != payee:
                continue
            if expected_iban and expected_iban != iban:
                continue
            if expected_purpose and expected_purpose not in purpose:
                continue
            if any((expected_payee, expected_iban, expected_purpose)):
                matches.append(rule)
        positions = {str(getattr(rule, "position_key", "")) for rule in matches}
        if len(positions) != 1:
            return None
        return matches[0]

    def assign_transaction_position(self, *, transaction_id: str, position_key: str) -> None:
        if self._pipeline_repo is None:
            raise RuntimeError("Datenbank für Kategoriezuordnung nicht verfügbar")
        valid = {position.key for position in self.list_positions()}
        if position_key not in valid:
            raise ValueError(f"Unbekannte Kategorie: {position_key}")
        self._pipeline_repo.assign_position(
            transaction_id=uuid.UUID(transaction_id),
            position_key=self._stored_position_key(position_key),
            source="manual",
        )

    def remember_position_rule(
        self,
        *,
        transaction_id: str,
        position_key: str,
        payee: str = "",
        iban: str = "",
        purpose_contains: str = "",
        label: str = "",
    ) -> None:
        if self._pipeline_repo is None:
            raise RuntimeError("Datenbank für Kategorienregeln nicht verfügbar")
        normalized_payee = normalize_german_text(payee)
        normalized_iban = iban.replace(" ", "").upper().strip()
        rule = self._pipeline_repo.add_position_rule(
            position_key=self._stored_position_key(position_key),
            label=label or f"{position_key.upper()} · {payee or purpose_contains}",
            payee_normalized=normalized_payee,
            counterparty_iban=normalized_iban,
            purpose_contains=normalize_german_text(purpose_contains),
        )
        self._pipeline_repo.assign_position(
            transaction_id=uuid.UUID(transaction_id),
            position_key=self._stored_position_key(position_key),
            source="manual",
            matched_rule_id=rule.id,
        )

    def add_position_rule(
        self,
        *,
        position_key: str,
        label: str = "",
        payee: str = "",
        iban: str = "",
        purpose_contains: str = "",
    ) -> None:
        if self._pipeline_repo is None:
            raise RuntimeError("Datenbank für Kategorienregeln nicht verfügbar")
        self._pipeline_repo.add_position_rule(
            position_key=self._stored_position_key(position_key),
            label=label.strip(),
            payee_normalized=normalize_german_text(payee),
            counterparty_iban=iban.replace(" ", "").upper().strip(),
            purpose_contains=normalize_german_text(purpose_contains),
        )

    def save_position(
        self, *, key: str, label: str, initials: str, color: str, enabled: bool = True
    ) -> None:
        if self._pipeline_repo is None:
            raise RuntimeError("Datenbank für Kategorien nicht verfügbar")
        current = self.list_positions(enabled_only=False)
        existing = next((item for item in current if item.key == key), None)
        sort_order = existing.sort_order if existing else (max((item.sort_order for item in current), default=0) + 10)
        self._pipeline_repo.upsert_position(
            key=self._stored_position_key(key),
            label=label,
            initials=initials,
            color=color,
            sort_order=sort_order,
            enabled=enabled,
        )

    def list_position_rules(self) -> list[ExpensePositionRule]:
        if self._pipeline_repo is None:
            return []
        return [
            SimpleNamespace(
                id=item.id,
                position_key=self._public_position_key(item.position_key),
                label=item.label,
                payee_normalized=item.payee_normalized,
                counterparty_iban=item.counterparty_iban,
                purpose_contains=item.purpose_contains,
                enabled=item.enabled,
            )
            for item in self._pipeline_repo.list_position_rules(enabled_only=False)
            if self._owns_position_key(item.position_key)
        ]  # type: ignore[return-value]

    def set_position_rule_enabled(self, rule_id: str, enabled: bool) -> bool:
        if self._pipeline_repo is None:
            return False
        return self._pipeline_repo.set_position_rule_enabled(uuid.UUID(rule_id), enabled)

    def list_supplier_links(self) -> list[ExpenseSupplierLink]:
        if self._pipeline_repo is None:
            return []
        return [
            item
            for item in self._pipeline_repo.list_all_supplier_links()
            if item.profile_key == self._tenant_key
            or (self._tenant_key == "xw" and item.profile_key == "")
        ]

    def set_supplier_link_enabled(self, link_id: str, enabled: bool) -> bool:
        if self._pipeline_repo is None:
            return False
        return self._pipeline_repo.set_supplier_link_enabled(uuid.UUID(link_id), enabled)

    def update_supplier_link(
        self, *, link_id: str, payee: str, iban: str, label: str, url: str
    ) -> None:
        if self._pipeline_repo is None:
            raise RuntimeError("Datenbank für Lieferantenlinks nicht verfügbar")
        normalized_url = url.strip()
        if not normalized_url.startswith("https://"):
            raise ValueError("Lieferantenlinks müssen mit https:// beginnen")
        updated = self._pipeline_repo.update_supplier_link(
            link_id=uuid.UUID(link_id),
            payee_normalized=normalize_german_text(payee),
            counterparty_iban=iban.replace(" ", "").upper().strip(),
            label=label.strip() or payee.strip(),
            url=normalized_url,
        )
        if updated is None:
            raise ValueError("Lieferantenlink wurde nicht gefunden")

    def add_supplier_link(
        self, *, payee: str, iban: str, label: str, url: str
    ) -> None:
        if self._pipeline_repo is None:
            raise RuntimeError("Datenbank für Lieferantenlinks nicht verfügbar")
        normalized_url = url.strip()
        if not normalized_url.startswith("https://"):
            raise ValueError("Lieferantenlinks müssen mit https:// beginnen")
        self._pipeline_repo.add_supplier_link(
            profile_key=self._tenant_key,
            payee_normalized=normalize_german_text(payee),
            counterparty_iban=iban.replace(" ", "").upper().strip(),
            label=label.strip() or payee.strip(),
            url=normalized_url,
        )

    def list_purpose_rules(self) -> list[ExpensePurposeRule]:
        if self._pipeline_repo is None:
            return []
        return self._pipeline_repo.list_purpose_rules(tenant_key=self._tenant_key)

    def add_purpose_rule(self, *, payee: str, remove_text: str, label: str = "") -> None:
        if self._pipeline_repo is None:
            raise RuntimeError("Datenbank für Zweckregeln nicht verfügbar")
        if not payee.strip() or not remove_text.strip():
            raise ValueError("Empfänger und zu entfernender Text sind erforderlich")
        self._pipeline_repo.add_purpose_rule(
            tenant_key=self._tenant_key,
            payee_normalized=normalize_german_text(payee),
            remove_text=remove_text.strip(),
            label=label.strip() or payee.strip(),
        )

    def update_purpose_rule(
        self, *, rule_id: str, payee: str, remove_text: str, label: str
    ) -> None:
        if self._pipeline_repo is None:
            raise RuntimeError("Datenbank für Zweckregeln nicht verfügbar")
        if not payee.strip() or not remove_text.strip():
            raise ValueError("Empfänger und zu entfernender Text sind erforderlich")
        updated = self._pipeline_repo.update_purpose_rule(
            rule_id=uuid.UUID(rule_id),
            payee_normalized=normalize_german_text(payee),
            remove_text=remove_text.strip(),
            label=label.strip() or payee.strip(),
        )
        if updated is None:
            raise ValueError("Zweckregel wurde nicht gefunden")

    def set_purpose_rule_enabled(self, rule_id: str, enabled: bool) -> bool:
        if self._pipeline_repo is None:
            return False
        return self._pipeline_repo.set_purpose_rule_enabled(uuid.UUID(rule_id), enabled)

    def flag_profile_transaction(
        self,
        *,
        transaction_id: str,
        profile_key: str,
        payee: str,
        iban: str = "",
        include: bool = True,
    ) -> None:
        """Flag one transaction and remember exact IBAN/payee candidates."""
        status = "included" if include else "excluded"
        self._memory_profile_flags[(profile_key, transaction_id)] = status
        if self._pipeline_repo is None:
            return
        try:
            tx_id = uuid.UUID(transaction_id)
        except ValueError:
            return
        self._pipeline_repo.add_assignment(
            transaction_id=tx_id,
            profile_key=profile_key,
            status=status,
            source="manual",
        )
        if include:
            normalized_iban = iban.replace(" ", "").upper().strip()
            if normalized_iban:
                self._pipeline_repo.add_rule(
                    profile_key=profile_key,
                    action="candidate",
                    match_field="iban",
                    value_normalized=normalized_iban,
                    value_original=iban,
                )
            normalized_payee = normalize_german_text(payee)
            if normalized_payee:
                self._pipeline_repo.add_rule(
                    profile_key=profile_key,
                    action="candidate",
                    match_field="payee",
                    value_normalized=normalized_payee,
                    value_original=payee,
                )

    @staticmethod
    def _match_profile_rule(
        row: BankExpense,
        profile_key: str,
        rules: Sequence[object],
    ) -> tuple[str, str]:
        for rule in rules:
            match_field = str(getattr(rule, "match_field", ""))
            expected = str(getattr(rule, "value_normalized", ""))
            if match_field == "iban":
                actual = row.counterparty_iban
            elif match_field == "payee":
                actual = row.payee_normalized or project_expense_text(
                    payee_name=row.payee_name,
                    payment_reference=row.payment_reference,
                    purpose=row.purpose,
                ).merchant_key
            elif match_field == "purpose":
                actual = normalize_german_text(
                    project_expense_text(
                        payee_name=row.payee_name,
                        payment_reference=row.payment_reference,
                        purpose=row.purpose,
                    ).purpose
                )
            else:
                actual = ""
            if expected and actual and expected == actual:
                return "candidate", f"{profile_key}:{match_field}"
        return "", ""

    # ------------------------------------------------------------------ #
    # Existing list/filter/export (unchanged behavior)                    #
    # ------------------------------------------------------------------ #

    def list_open(self) -> list[ExpenseRow]:
        if self._repo is None:
            return []
        raw = self._repo.get_value_json(_EXPENSES_KEY)
        if not raw:
            return []
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            logger.warning("Invalid expenses JSON in %s", _EXPENSES_KEY)
            return []
        if not isinstance(data, list):
            return []
        rows: list[ExpenseRow] = []
        for item in data:
            if not isinstance(item, dict):
                continue
            rows.append(
                ExpenseRow(
                    ref=str(item.get("ref") or ""),
                    supplier=str(item.get("supplier") or ""),
                    gross_amount=str(item.get("gross_amount") or ""),
                    category=str(item.get("category") or ""),
                    status=str(item.get("status") or ""),
                    note=str(item.get("note") or ""),
                )
            )
        return rows

    def filter_rows(self, rows: list[ExpenseRow], needle: str = "", status: str = "") -> list[ExpenseRow]:
        search = needle.lower().strip()
        want_status = status.lower().strip()
        out: list[ExpenseRow] = []
        for row in rows:
            if want_status and row.status.lower().strip() != want_status:
                continue
            hay = f"{row.ref} {row.supplier} {row.gross_amount} {row.category} {row.status} {row.note}".lower()
            if search and search not in hay:
                continue
            out.append(row)
        return out

    def export_csv(self, rows: list[ExpenseRow]) -> str:
        buf = io.StringIO()
        writer = csv.writer(buf, delimiter=";")
        writer.writerow(["Ref", "Lieferant", "Brutto", "Kategorie", "Status", "Hinweis"])
        for row in rows:
            writer.writerow([row.ref, row.supplier, row.gross_amount, row.category, row.status, row.note])
        return buf.getvalue()

    # ------------------------------------------------------------------ #
    # Ignore rules                                                         #
    # ------------------------------------------------------------------ #

    def list_ignore_rules(self, mandant: str = "") -> list[IgnoreRuleView]:
        if self._expense_repo is None:
            return []
        return [_to_ignore_rule_view(row) for row in self._expense_repo.list_ignore_rules(mandant)]

    def add_ignore_rule(self, *, mandant: str, purpose_text: str, scope: str) -> IgnoreRuleView:
        if self._expense_repo is None:
            raise RuntimeError("Ausgaben-Check-Datenbank ist nicht konfiguriert.")
        if scope not in {"once", "forever"}:
            raise ValueError(f"Unbekannter Ignore-Scope: {scope!r}")
        normalized = normalize_german_text(clean_bank_purpose(purpose_text))
        if not normalized:
            raise ValueError("Leerer Buchungstext kann nicht ignoriert werden.")
        rule = self._expense_repo.add_ignore_rule(
            mandant=mandant,
            pattern_original=purpose_text.strip(),
            pattern_normalized=normalized,
            scope=scope,
        )
        return _to_ignore_rule_view(rule)

    def remove_ignore_rule(self, rule_id: str) -> bool:
        if self._expense_repo is None:
            return False
        return self._expense_repo.remove_ignore_rule(uuid.UUID(rule_id))

    def is_ignored(
        self,
        purpose_text: str,
        *,
        mandant: str = "",
        threshold: float = DEFAULT_IGNORE_THRESHOLD,
    ) -> IgnoreRuleView | None:
        return self._match_ignore_rule(purpose_text, self.list_ignore_rules(mandant), threshold=threshold)

    @staticmethod
    def _match_ignore_rule(
        purpose_text: str,
        rules: list[IgnoreRuleView],
        *,
        threshold: float,
    ) -> IgnoreRuleView | None:
        if not rules:
            return None
        needle = normalize_german_text(clean_bank_purpose(purpose_text))
        if not needle:
            return None
        best_rule: IgnoreRuleView | None = None
        best_score = 0.0
        for rule in rules:
            score = fuzzy_ratio(needle, rule.pattern_normalized)
            if score >= threshold and score > best_score:
                best_rule, best_score = rule, score
        return best_rule

    # ------------------------------------------------------------------ #
    # Period shifts                                                        #
    # ------------------------------------------------------------------ #

    def list_shift_entries(self, mandant: str = "") -> list[ShiftEntryView]:
        if self._expense_repo is None:
            return []
        return [_to_shift_entry_view(row) for row in self._expense_repo.list_shift_entries(mandant)]

    def shift_period(
        self,
        *,
        mandant: str,
        transaction_ref: str,
        source_period: str,
        target_period: str,
        note: str = "",
    ) -> ShiftEntryView:
        if self._expense_repo is None:
            raise RuntimeError("Ausgaben-Check-Datenbank ist nicht konfiguriert.")
        if not transaction_ref.strip():
            raise ValueError("transaction_ref darf nicht leer sein.")
        if not _PERIOD_RE.match(source_period) or not _PERIOD_RE.match(target_period):
            raise ValueError("Perioden muessen im Format JJJJ-MM angegeben werden.")
        entry = self._expense_repo.add_shift_entry(
            mandant=mandant,
            transaction_ref=transaction_ref.strip(),
            source_period=source_period,
            target_period=target_period,
            note=note.strip(),
        )
        return _to_shift_entry_view(entry)

    # ------------------------------------------------------------------ #
    # Flagging (reuses the existing open-items JSON list, atomically)     #
    # ------------------------------------------------------------------ #

    def flag_row(self, ref: str, *, note: str = "") -> None:
        if self._repo is None:
            raise RuntimeError("Ausgaben-Check-Datenbank ist nicht konfiguriert.")

        def _mutate(raw: str | None) -> str:
            try:
                data = json.loads(raw) if raw else []
            except json.JSONDecodeError:
                data = []
            if not isinstance(data, list):
                data = []
            found = False
            for item in data:
                if isinstance(item, dict) and str(item.get("ref") or "") == ref:
                    item["status"] = "flagged"
                    if note:
                        item["note"] = note
                    found = True
            if not found:
                logger.warning("flag_row: Beleg %s nicht in %s gefunden", ref, _EXPENSES_KEY)
            return json.dumps(data, ensure_ascii=False)

        self._repo.mutate_value_json(_EXPENSES_KEY, _mutate)

    # ------------------------------------------------------------------ #
    # Classification and unified action entry point                       #
    # ------------------------------------------------------------------ #

    def classify_rows(
        self,
        rows: list[ExpenseRow],
        *,
        mandant: str = "",
        period: str = "",
        threshold: float = DEFAULT_IGNORE_THRESHOLD,
    ) -> list[ExpenseRowClassification]:
        """Annotate each row with its ignore/shift decision.

        A row already reassigned into a different period via
        :meth:`shift_period` is reported as ``"shifted"``. Otherwise, if its
        supplier/note text fuzzy-matches a persisted ignore rule, it is
        reported as ``"ignored"``. Everything else stays ``"open"``.
        """
        ignore_rules = self.list_ignore_rules(mandant)
        shift_entries = self.list_shift_entries(mandant)
        shift_by_ref = {entry.transaction_ref: entry for entry in shift_entries}

        out: list[ExpenseRowClassification] = []
        for row in rows:
            shift_entry = shift_by_ref.get(row.ref)
            if shift_entry is not None and (not period or shift_entry.source_period == period):
                out.append(ExpenseRowClassification(row, "shifted", shift_entry=shift_entry))
                continue
            purpose_text = f"{row.supplier} {row.note}".strip()
            matched = self._match_ignore_rule(purpose_text, ignore_rules, threshold=threshold)
            if matched is not None:
                out.append(ExpenseRowClassification(row, "ignored", matched_ignore_rule=matched))
                continue
            out.append(ExpenseRowClassification(row, "open"))
        return out

    def apply_action(
        self,
        action: ExpenseAction,
        row: ExpenseRow,
        *,
        mandant: str = "",
        source_period: str = "",
        target_period: str = "",
        note: str = "",
    ) -> IgnoreRuleView | ShiftEntryView | None:
        """Single dispatch entry point mirroring the legacy action set."""
        if action in (ExpenseAction.IGNORE_ONCE, ExpenseAction.IGNORE_FOREVER):
            scope = "once" if action is ExpenseAction.IGNORE_ONCE else "forever"
            purpose_text = f"{row.supplier} {row.note}".strip()
            return self.add_ignore_rule(mandant=mandant, purpose_text=purpose_text, scope=scope)
        if action is ExpenseAction.SHIFT:
            if not target_period:
                raise ValueError("target_period ist fuer 'shift' erforderlich.")
            return self.shift_period(
                mandant=mandant,
                transaction_ref=row.ref,
                source_period=source_period,
                target_period=target_period,
                note=note,
            )
        if action is ExpenseAction.FLAG:
            self.flag_row(row.ref, note=note)
            return None
        raise ValueError(f"Unbekannte Aktion: {action!r}")
