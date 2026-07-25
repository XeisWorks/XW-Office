"""Expense audit / Ausgaben-Check.

Reconciles bank transactions against booked sevDesk documents per month
and mandant. Ignore rules and period shifts are real, multi-PC-synced
tables (see :mod:`xw_studio.models.expense_check`) instead of the legacy
flat JSON files, and are matched with the shared fuzzy-text utilities so a
recurring payment whose reference changes each month is still recognized.
"""
from __future__ import annotations

import csv
import io
import json
import logging
import re
import uuid
from dataclasses import dataclass
from enum import Enum
from typing import TYPE_CHECKING

from xw_studio.core.fuzzy_match import fuzzy_ratio
from xw_studio.core.text_normalize import clean_bank_purpose, normalize_german_text
from xw_studio.repositories.settings_kv import SettingKvRepository

if TYPE_CHECKING:
    from xw_studio.models.expense_check import ExpenseIgnoreRule, ExpenseShiftEntry
    from xw_studio.repositories.expense_check import ExpenseCheckRepository

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
    ) -> None:
        self._repo = settings_repo
        self._expense_repo = expense_check_repo

    def describe(self) -> str:
        return (
            "Ausgaben-Check: Belege pruefen und fuer UVA/FIBU vorbereiten "
            "(DB-Liste + Filter + CSV-Export, mit Ignore-Regeln und Perioden-Verschiebung)."
        )

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
