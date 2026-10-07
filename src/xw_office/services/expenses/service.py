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
import uuid
from dataclasses import dataclass
from decimal import Decimal
from enum import Enum
from typing import TYPE_CHECKING

from xw_office.core.fuzzy_match import fuzzy_ratio
from xw_office.core.text_normalize import clean_bank_purpose, normalize_german_text
from xw_office.repositories.settings_kv import SettingKvRepository
from xw_office.services.expenses.bank_provider import (
    BankDocumentLink,
    BankExpense,
    SevdeskExpenseProvider,
)
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
    ) -> None:
        self._repo = settings_repo
        self._expense_repo = expense_check_repo
        self._bank_provider = bank_provider
        self._pipeline_repo = pipeline_repo
        self._memory_profile_flags: dict[tuple[str, str], str] = {}

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
    ) -> list[BankExpenseRow]:
        """Load outgoing sevDesk transactions and persist normalized snapshots."""
        if self._bank_provider is None:
            return []
        if refresh:
            _account, rows = self._bank_provider.fetch(start, end, outgoing_only=True)
        elif self._pipeline_repo is not None:
            rows = []
            for snapshot in self._pipeline_repo.list_snapshots(
                start=start, end=end, direction="outgoing"
            ):
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
        link_scan_complete = True
        if refresh:
            try:
                account = self._bank_provider.find_account()
                for link in self._bank_provider.resolve_document_links(
                    start, end, account_id=account.id
                ):
                    links_by_transaction.setdefault(link.transaction_external_id, []).append(link)
            except Exception as exc:  # noqa: BLE001
                logger.warning("sevDesk-Belegscan unvollständig: %s", exc)
                link_scan_complete = False

        result: list[BankExpenseRow] = []
        rules = self._pipeline_repo.list_rules(profile_key) if self._pipeline_repo and profile_key else []
        for row in rows:
            snapshot_id = ""
            if self._pipeline_repo is not None:
                snapshot = self._pipeline_repo.upsert_snapshot(
                    {
                        "account_id": row.account_id,
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
                snapshot_id = str(snapshot.id)
                for link in links_by_transaction.get(row.external_id, []):
                    self._pipeline_repo.add_document_link(
                        transaction_id=snapshot.id,
                        resource_type=link.resource_type,
                        external_id=link.external_id,
                        document_number=link.document_number,
                    )
            status = ""
            source = ""
            if profile_key:
                status, source = self._match_profile_rule(row, profile_key, rules)
                if self._pipeline_repo is not None and snapshot_id:
                    assignment = self._pipeline_repo.get_assignment(
                        transaction_id=uuid.UUID(snapshot_id), profile_key=profile_key
                    )
                    if assignment is not None:
                        status = assignment.status
                        source = assignment.source
                status = status or self._memory_profile_flags.get((profile_key, row.external_id), "")
            document_links = links_by_transaction.get(row.external_id, [])
            sevdesk_link = ""
            if document_links:
                first_link = document_links[0]
                sevdesk_link = sevdesk_document_url(
                    self._bank_provider.base_url,
                    first_link.resource_type,
                    first_link.external_id,
                )
            supplier_url = ""
            if self._pipeline_repo is not None:
                supplier_links = self._pipeline_repo.list_supplier_links(
                    profile_key=profile_key,
                    payee_normalized=row.payee_normalized,
                    iban=row.counterparty_iban,
                )
                if not supplier_links:
                    supplier_links = self._pipeline_repo.list_supplier_links(
                        profile_key=profile_key,
                        payee_normalized=normalize_german_text(row.display_reference),
                        iban=row.counterparty_iban,
                    )
                if supplier_links:
                    supplier_url = supplier_links[0].url
            result.append(
                BankExpenseRow(
                    transaction_id=snapshot_id or row.external_id,
                    value_date=row.value_date,
                    payee=row.payee_name,
                    iban=row.counterparty_iban,
                    purpose=row.display_reference,
                    amount=row.amount,
                    currency=row.currency,
                    sevdesk_url=sevdesk_link,
                    supplier_url=supplier_url,
                    profile_status=status,
                    rule_source=source,
                    document_link_scan_complete=link_scan_complete,
                )
            )
        return result

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
        rules: list[object],
    ) -> tuple[str, str]:
        for rule in rules:
            match_field = str(getattr(rule, "match_field", ""))
            expected = str(getattr(rule, "value_normalized", ""))
            actual = row.counterparty_iban if match_field == "iban" else row.payee_normalized
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
