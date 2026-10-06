"""Order-independent printing with immutable official catalogue data."""
from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import fitz  # type: ignore[import-untyped]

from xw_office.core.config import PrintingSection
from xw_office.core.shared_paths import resolve_shared_path
from xw_office.print_center.models import ArticleInput, PrintArticle, PrintReceipt
from xw_office.print_center.official import OfficialCatalogue
from xw_office.print_center.repository import OwnArticleRepository
from xw_office.services.printing.planned_pdf_printer import (
    PlanTarget,
    page_indices_from_range_text,
    print_pdf_by_plan,
    resolve_plan_targets,
)
from xw_office.services.printing.print_queue import PrintQueueService


class PrintCenterService:
    def __init__(
        self, official: OfficialCatalogue, own: OwnArticleRepository,
        printing: Callable[[], PrintingSection], queue: PrintQueueService,
    ) -> None:
        self._official = official
        self._own = own
        self._printing = printing
        self._queue = queue

    def list_articles(self) -> list[PrintArticle]:
        return self._official.list_articles() + self._own.list_articles()

    def printing_settings(self) -> PrintingSection:
        return self._printing()

    def shutdown(self) -> bool:
        return self._queue.shutdown(wait_ms=100)

    def save_own(
        self, data: ArticleInput, *, article_id: str | None = None, version: int = 1
    ) -> PrintArticle:
        # Validate profiles/ranges before storing, but allow temporarily unavailable
        # shared PDFs so an article can be maintained from a non-print workstation.
        targets = resolve_plan_targets(
            self._printing(), print_plan=[step.model_dump() for step in data.print_plan]
        )
        self._require_native(targets)
        path = resolve_shared_path(data.pdf_path)
        if Path(path).is_file():
            with fitz.open(path) as document:
                for target in targets:
                    page_indices_from_range_text(target.range_text, page_count=len(document))
        return self._own.save(data, article_id=article_id, version=version)

    def delete_own(self, article_id: str, *, version: int) -> None:
        self._own.delete(article_id, version=version)

    @staticmethod
    def _require_native(
        targets: list[PlanTarget],
    ) -> None:
        if not targets:
            raise ValueError("Bitte mindestens ein Druckprofil zuordnen.")
        if any(target.backend != "pdf_xchange" for target in targets):
            raise ValueError(
                "Produktdruck benoetigt ein natives PDF-XChange-Profil. "
                "Druckprofile werden ausschliesslich in XW-Office gepflegt."
            )

    def print_article(self, selection: PrintArticle, copies: int) -> PrintReceipt:
        if not 1 <= copies <= 999:
            raise ValueError("Die Druckmenge muss zwischen 1 und 999 liegen.")
        if selection.source == "official":
            article = next(
                (item for item in self._official.list_articles() if item.id == selection.id), None
            )
            if article is None:
                raise ValueError("Das offizielle Produkt ist nicht mehr im Katalog. Bitte neu laden.")
        else:
            article = self._own.get(selection.id)
        path = resolve_shared_path(article.pdf_path)
        if not path or not Path(path).is_file():
            raise ValueError("Die zugeordnete PDF ist auf diesem PC nicht erreichbar.")
        printing = self._printing()
        plan = [step.model_dump() for step in article.print_plan]
        targets = resolve_plan_targets(printing, print_plan=plan, profile_id=article.profile_id)
        self._require_native(targets)
        # Preflight every row before dispatching the first page.
        with fitz.open(path) as document:
            if document.needs_pass or len(document) == 0:
                raise ValueError("Die PDF ist leer oder passwortgeschuetzt.")
            page_count = len(document)
            for target in targets:
                page_indices_from_range_text(target.range_text, page_count=page_count)
        job_ids = print_pdf_by_plan(
            path, printing, print_plan=plan, profile_id=article.profile_id,
            copies=copies, page_count=page_count, print_queue=self._queue,
            job_kind="product", wait=True,
        )
        return PrintReceipt(name=article.name, copies=copies, job_ids=tuple(job_ids))
