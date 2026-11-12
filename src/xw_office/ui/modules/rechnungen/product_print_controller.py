"""Business orchestration for a single invoice product print."""
from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass

from xw_office.services.inventory import InventoryService
from xw_office.services.products.print_decision import PieceBlock, PrintDecisionEngine
from xw_office.services.printing.planned_pdf_printer import PrintPlanPartialFailure

logger = logging.getLogger(__name__)


class ProductPdfPreparationError(RuntimeError):
    """A product PDF failed validation before a printer job was submitted."""


@dataclass(frozen=True)
class ProductPrintBatchResult:
    printed: tuple[str, ...]
    warnings: tuple[str, ...]
    claim_warnings: tuple[str, ...]


class InvoiceProductPrintController:
    """Coordinate the print claim, physical dispatch and confirmed stock write."""

    def __init__(self, engine: PrintDecisionEngine, inventory: InventoryService) -> None:
        self._engine = engine
        self._inventory = inventory

    def execute_many(
        self,
        jobs: list[tuple[PieceBlock, int, Callable[[], None]]],
        *,
        invoice_ref: str = "",
    ) -> ProductPrintBatchResult:
        """Run each independent print claim and retain confirmed partial sets."""
        printed: list[str] = []
        warnings: list[str] = []
        claim_warnings: list[str] = []
        for piece, requested_quantity, print_job in jobs:
            try:
                result = self.execute(
                    piece,
                    requested_quantity,
                    invoice_ref=invoice_ref,
                    print_job=print_job,
                )
            except Exception as exc:
                if isinstance(exc, ProductPdfPreparationError):
                    status = "PDF konnte vor dem Druck nicht vorbereitet werden"
                elif isinstance(exc, PrintPlanPartialFailure) and exc.completed_copies <= 0:
                    status = "Keine Kopie wurde gedruckt"
                else:
                    status = "Druckergebnis unklar"
                logger.warning("Batch product print failed for %s: %s", piece.sku, exc)
                warnings.append(f"{piece.sku}: {status}: {exc}")
                continue

            claim_warning = str(result.get("claim_warning") or "").strip()
            if claim_warning:
                claim_warnings.append(f"{piece.sku}: {claim_warning}")
                continue

            raw_quantity = result.get("quantity")
            completed = raw_quantity if isinstance(raw_quantity, int) else 0
            if completed > 0:
                printed.append(f"{piece.sku} ({completed}x)")
            for warning_key in ("stock_warning", "print_warning"):
                warning = str(result.get(warning_key) or "").strip()
                if warning:
                    warnings.append(f"{piece.sku}: {warning}")

        return ProductPrintBatchResult(
            printed=tuple(printed),
            warnings=tuple(warnings),
            claim_warnings=tuple(claim_warnings),
        )

    def execute(
        self,
        piece: PieceBlock,
        quantity: int,
        *,
        invoice_ref: str,
        print_job: Callable[[], None],
    ) -> dict[str, object]:
        claim = self._engine.acquire_product_print_claim(piece)
        if not claim.acquired:
            return {
                "sku": piece.sku,
                "quantity": 0,
                "claim_warning": (
                    f"Druck ist durch einen {claim.state}-Claim gesperrt. "
                    "Bei unklarem Druckergebnis erst den physischen Lauf abgleichen."
                ),
            }

        completed = quantity
        print_warning = ""
        try:
            print_job()
        except PrintPlanPartialFailure as exc:
            # Preserve confirmed full sets when a later plan target fails.
            completed = exc.completed_copies
            print_warning = str(exc)
            if completed <= 0:
                self._engine.finish_product_print_claim(
                    claim, "failed", error="Kein Exemplar wurde gedruckt"
                )
                raise
        except ProductPdfPreparationError as exc:
            self._engine.finish_product_print_claim(claim, "failed", error=str(exc))
            raise
        except Exception as exc:
            self._engine.finish_product_print_claim(claim, "unknown", error=str(exc))
            raise

        part_id = str(piece.product.sevdesk_part_id or "").strip() if piece.product else ""
        if not part_id:
            self._engine.finish_product_print_claim(
                claim, "unknown", error="Druck bestaetigt, aber kein sevDesk-Part zugeordnet"
            )
            return {
                "sku": piece.sku,
                "quantity": completed,
                "stock_warning": "kein sevDesk-Part fuer Bestandsbuchung hinterlegt",
                "print_warning": print_warning,
            }

        try:
            self._engine.record_confirmed_print(
                piece,
                completed,
                self._inventory,
                operation_id=claim.operation_id,
                invoice_ref=invoice_ref,
            )
        except Exception as exc:
            self._engine.finish_product_print_claim(claim, "unknown", error=str(exc))
            logger.warning("Stock update after product print failed: %s", exc)
            return {
                "sku": piece.sku,
                "quantity": completed,
                "stock_warning": str(exc),
                "print_warning": print_warning,
            }

        self._engine.finish_product_print_claim(claim, "succeeded")
        return {
            "sku": piece.sku,
            "quantity": completed,
            "stock_warning": "",
            "local_warning": "",
            "print_warning": print_warning,
        }
