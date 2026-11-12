"""Business orchestration for a single invoice product print."""
from __future__ import annotations

import logging
from collections.abc import Callable

from xw_office.services.inventory import InventoryService
from xw_office.services.products.print_decision import PieceBlock, PrintDecisionEngine
from xw_office.services.printing.planned_pdf_printer import PrintPlanPartialFailure

logger = logging.getLogger(__name__)


class ProductPdfPreparationError(RuntimeError):
    """A product PDF failed validation before a printer job was submitted."""


class InvoiceProductPrintController:
    """Coordinate the print claim, physical dispatch and confirmed stock write."""

    def __init__(self, engine: PrintDecisionEngine, inventory: InventoryService) -> None:
        self._engine = engine
        self._inventory = inventory

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
