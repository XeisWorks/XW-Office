"""CRM facade — live contact sync and deduplication."""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING

from xw_office.core.config import AppConfig
from xw_office.services.crm.matching import find_duplicate_candidates
from xw_office.services.crm.preflight import MergePreflightReport, build_preflight_report
from xw_office.services.crm.types import ContactRecord, DuplicateCandidate

if TYPE_CHECKING:
    from xw_office.services.sevdesk.contact_client import ContactClient
    from xw_office.services.sevdesk.invoice_client import InvoiceClient

logger = logging.getLogger(__name__)


class MergeBlockedError(RuntimeError):
    """Raised when a merge would silently lose or corrupt loser invoices.

    Carries the :class:`MergePreflightReport` so the caller (UI) can show
    the blocked invoices and let the user decide, instead of the merge
    failing with a raw sevDesk API error partway through. Pass
    ``force=True`` to :meth:`CrmService.merge_contacts` to proceed anyway.
    """

    def __init__(self, report: MergePreflightReport) -> None:
        super().__init__(
            f"CRM-Merge blockiert: {len(report.blocked_invoices)} Rechnung(en) von Kontakt "
            f"{report.duplicate_contact_id} koennen nicht automatisch verschoben werden."
        )
        self.report = report


@dataclass(frozen=True)
class MergeResult:
    """Result of a CRM duplicate merge decision."""

    master_id: str
    duplicate_id: str
    merged: ContactRecord
    loser_outcome: str = "not_written"  # "deleted" | "archived" | "ignored" | "not_written"


class CrmService:
    """Customer data operations backed by sevDesk ContactClient."""

    def __init__(
        self,
        config: AppConfig,
        contact_client: "ContactClient | None" = None,
        invoice_client: "InvoiceClient | None" = None,
    ) -> None:
        self._config = config
        self._contact_client = contact_client
        self._invoice_client = invoice_client

    def has_live_connection(self) -> bool:
        """True when a real ContactClient is wired (API token is set)."""
        return self._contact_client is not None

    def duplicate_threshold(self) -> int:
        return int(self._config.crm.fuzzy_match_threshold)

    def fetch_live_contacts(self) -> list[ContactRecord]:
        """Pull contacts from sevDesk.  Raises if no client is available."""
        if self._contact_client is None:
            raise RuntimeError("Kein sevDesk-Token konfiguriert.")
        return self._contact_client.list_contacts()

    def find_duplicates_in_memory(self, rows: list[ContactRecord]) -> list[DuplicateCandidate]:
        """Run duplicate scan for preloaded contacts (e.g. after sync)."""
        dups = find_duplicate_candidates(rows, threshold=self.duplicate_threshold())
        logger.info("CRM duplicate scan: %s candidates from %s contacts", len(dups), len(rows))
        return dups

    # ------------------------------------------------------------------ #
    # Merge preflight (dry-run) and live merge                            #
    # ------------------------------------------------------------------ #

    def preflight_merge(self, duplicate: ContactRecord) -> MergePreflightReport:
        """Read-only check: which of the duplicate's invoices are safe to lose?

        Does not write anything to sevDesk. Mirrors the dry-run step already
        established in ``xw_office.services.xw_copilot`` for any operation
        with write consequences.
        """
        if self._invoice_client is None:
            raise RuntimeError("Kein sevDesk-Token konfiguriert (InvoiceClient fehlt).")
        invoices = self._invoice_client.list_invoice_summaries_for_contact(duplicate.id)
        report = build_preflight_report(duplicate.id, invoices)
        logger.info(
            "CRM merge preflight for %s: %s Rechnung(en), %s blockiert",
            duplicate.id,
            report.invoice_count,
            len(report.blocked_invoices),
        )
        return report

    def merge_contacts(
        self,
        master: ContactRecord,
        duplicate: ContactRecord,
        *,
        force: bool = False,
    ) -> MergeResult:
        """Merge duplicate into master using deterministic field fallback rules.

        Writes back to sevDesk when a live ContactClient is available. Runs
        :meth:`preflight_merge` first when an InvoiceClient is wired and
        raises :class:`MergeBlockedError` if the duplicate has invoices that
        cannot be safely reassigned — unless ``force=True``, in which case
        the merge proceeds and the blocked invoices are left with the
        duplicate contact (which is then archived rather than deleted, see
        :meth:`_write_merge_to_sevdesk`).
        """
        merged = ContactRecord(
            id=master.id,
            name=(master.name or "").strip() or (duplicate.name or "").strip(),
            email=(master.email or "").strip() or (duplicate.email or "").strip() or None,
            phone=(master.phone or "").strip() or (duplicate.phone or "").strip() or None,
            city=(master.city or "").strip() or (duplicate.city or "").strip() or None,
        )

        report: MergePreflightReport | None = None
        if self._invoice_client is not None:
            report = self.preflight_merge(duplicate)
            if report.has_blocked_invoices and not force:
                raise MergeBlockedError(report)

        logger.info("CRM merge prepared: master=%s duplicate=%s", master.id, duplicate.id)
        loser_outcome = "not_written"
        if self._contact_client is not None:
            loser_has_blocked_invoices = bool(report and report.has_blocked_invoices)
            loser_outcome = self._write_merge_to_sevdesk(
                merged, duplicate, keep_loser=loser_has_blocked_invoices
            )
            logger.info(
                "CRM merge written to sevDesk: master=%s duplicate=%s outcome=%s",
                master.id,
                duplicate.id,
                loser_outcome,
            )
        return MergeResult(
            master_id=master.id,
            duplicate_id=duplicate.id,
            merged=merged,
            loser_outcome=loser_outcome,
        )

    def _write_merge_to_sevdesk(
        self,
        merged: ContactRecord,
        duplicate: ContactRecord,
        *,
        keep_loser: bool,
    ) -> str:
        """Apply the configured loser policy. Returns "deleted"/"archived"/"ignored"."""
        assert self._contact_client is not None
        self._contact_client.update_contact_fields(merged)

        policy = self._config.crm.merge_loser_policy
        if policy == "ignore":
            return "ignored"
        if keep_loser or policy == "archive_always":
            self._contact_client.archive_contact(duplicate.id, current_name=duplicate.name)
            return "archived"
        # default: delete_if_empty
        try:
            self._contact_client.delete_contact(duplicate.id)
            return "deleted"
        except Exception as exc:
            logger.info(
                "CRM merge: sevDesk refused to delete duplicate %s (%s); archiving instead",
                duplicate.id,
                exc,
            )
            self._contact_client.archive_contact(duplicate.id, current_name=duplicate.name)
            return "archived"
