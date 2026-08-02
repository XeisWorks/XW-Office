"""PdfBulkMapper — scan a PDF folder and fuzzy-match files to product SKUs/names.

Ported and simplified from the old sevDesk-project's ``pdf_bulk_mapping.py``.
No external fuzzy-matching library required; uses stdlib ``difflib``.

Typical flow
------------
1. Call ``PdfBulkMapper.scan(folder, catalog)`` to get a ``BulkScanResult``.
2. Show ``result.auto_matches`` to the user for confirmation.
3. Show ``result.review_candidates`` so the user can pick the right file.
4. Call ``PdfBulkMapper.apply(matches, catalog)`` to write ``print_file_path``
   on each Product in the catalog.
"""
from __future__ import annotations

import difflib
import logging
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path

if __name__ == "__main__":
    raise SystemExit("Not a script. Import from xw_office.services.products.pdf_bulk_mapper")

logger = logging.getLogger(__name__)

# Similarity score [0, 1] at or above which a match is accepted automatically.
AUTO_ACCEPT_THRESHOLD = 0.72
# Minimum score to include a file as a review candidate.
MIN_REVIEW_THRESHOLD = 0.40
# Maximum number of review candidates to propose per product.
MAX_REVIEW_CANDIDATES = 5


def _normalize_name(text: str) -> str:
    """Lower-case, strip accents, collapse whitespace, remove punctuation."""
    nfkd = unicodedata.normalize("NFKD", text)
    ascii_only = "".join(c for c in nfkd if not unicodedata.combining(c))
    lowered = ascii_only.lower()
    # Collapse non-alphanumeric runs to single space
    out: list[str] = []
    for ch in lowered:
        if ch.isalnum():
            out.append(ch)
        elif out and out[-1] != " ":
            out.append(" ")
    return "".join(out).strip()


def _similarity(a: str, b: str) -> float:
    """Return normalised similarity [0, 1] between two strings."""
    return difflib.SequenceMatcher(None, a, b, autojunk=False).ratio()


@dataclass
class PdfCandidate:
    """One PDF file that is a potential match for a product."""

    path: str
    filename_stem: str
    score: float  # 0-1, higher = better match


@dataclass
class ProductMatch:
    """Confirmed or auto-matched product ↔ PDF pair."""

    sku: str
    product_name: str
    pdf_path: str
    score: float
    is_auto: bool  # True = above threshold; False = user-confirmed review item


@dataclass
class ReviewItem:
    """Product that could not be auto-matched — user should pick from candidates."""

    sku: str
    product_name: str
    candidates: list[PdfCandidate]


@dataclass
class BulkScanResult:
    """Output of ``PdfBulkMapper.scan()``."""

    scanned_pdf_count: int = 0
    auto_matches: list[ProductMatch] = field(default_factory=list)
    review_items: list[ReviewItem] = field(default_factory=list)
    already_configured: list[str] = field(default_factory=list)  # SKUs with existing path
    skipped_products: list[str] = field(default_factory=list)    # digital / no name

    @property
    def summary_line(self) -> str:
        return (
            f"{self.scanned_pdf_count} PDFs gescannt · "
            f"{len(self.auto_matches)} auto-zugewiesen · "
            f"{len(self.review_items)} zur Überprüfung · "
            f"{len(self.already_configured)} bereits konfiguriert"
        )


class PdfBulkMapper:
    """Scan a PDF folder and match files to products in a ProductCatalogService."""

    # File name prefixes/suffixes that are strongly associated with specific queues
    # and should be preferred when scoring (A4-2x suffix = Noten in A4 landscape).
    _PREFERRED_SUFFIX_PATTERNS = ("_a4_2x", "-a4-2x", " a4 2x")

    @classmethod
    def scan(
        cls,
        folder: str | Path,
        catalog: object,  # ProductCatalogService — avoids circular import
        *,
        recursive: bool = True,
        overwrite_existing: bool = False,
    ) -> BulkScanResult:
        """Scan *folder* for PDFs and fuzzy-match against products in *catalog*.

        Args:
            folder: Root directory to scan for ``.pdf`` files.
            catalog: ``ProductCatalogService`` instance with products loaded.
            recursive: If True, scan all sub-directories.
            overwrite_existing: If True, also evaluate products that already have
                a ``print_file_path`` set (useful when re-mapping).
        """
        root = Path(folder)
        if not root.is_dir():
            logger.warning("PdfBulkMapper.scan: folder not found: %s", root)
            return BulkScanResult()

        pdf_files = cls._collect_pdf_files(root, recursive=recursive)
        result = BulkScanResult(scanned_pdf_count=len(pdf_files))
        if not pdf_files:
            logger.info("PdfBulkMapper: no PDF files found in %s", root)
            return result

        parsed = cls._parse_pdf_files(pdf_files)
        products = cls._get_matchable_products(catalog, result, overwrite_existing=overwrite_existing)

        for sku, name, is_digital in products:
            if is_digital:
                result.skipped_products.append(sku)
                continue
            norm_name = _normalize_name(name)
            norm_sku = _normalize_name(sku)

            candidates: list[PdfCandidate] = []
            for pdf_path, stem_norm in parsed:
                # Score against both product name and SKU; take the higher
                score_name = _similarity(norm_name, stem_norm)
                score_sku = _similarity(norm_sku, stem_norm)
                # Boost if the file has A4-2x suffix (preferred Noten format)
                boost = 0.04 if any(p in stem_norm for p in cls._PREFERRED_SUFFIX_PATTERNS) else 0.0
                best = max(score_name, score_sku) + boost
                if best >= MIN_REVIEW_THRESHOLD:
                    candidates.append(PdfCandidate(path=str(pdf_path), filename_stem=stem_norm, score=round(best, 3)))

            candidates.sort(key=lambda c: c.score, reverse=True)
            top = candidates[:MAX_REVIEW_CANDIDATES]

            if top and top[0].score >= AUTO_ACCEPT_THRESHOLD:
                result.auto_matches.append(
                    ProductMatch(
                        sku=sku,
                        product_name=name,
                        pdf_path=top[0].path,
                        score=top[0].score,
                        is_auto=True,
                    )
                )
                logger.debug(
                    "PdfBulkMapper: auto-match SKU=%r → %r (score=%.2f)",
                    sku, top[0].path, top[0].score,
                )
            elif top:
                result.review_items.append(
                    ReviewItem(sku=sku, product_name=name, candidates=top)
                )
                logger.debug(
                    "PdfBulkMapper: review SKU=%r → best candidate %r (score=%.2f)",
                    sku, top[0].filename_stem, top[0].score,
                )
            # else: no candidate at all → silently skip (digital or no PDF in folder)

        logger.info(
            "PdfBulkMapper scan done: %s",
            result.summary_line,
        )
        return result

    @classmethod
    def apply(
        cls,
        matches: list[ProductMatch],
        catalog: object,  # ProductCatalogService
    ) -> int:
        """Write confirmed matches back to the catalog.

        Returns the number of ``print_file_path`` values updated.
        """
        updated = 0
        for match in matches:
            product = cls._get_product(catalog, match.sku)
            if product is None:
                logger.warning("PdfBulkMapper.apply: SKU %r not in catalog — skip", match.sku)
                continue
            # ProductCatalogService exposes set_print_file_path()
            if hasattr(catalog, "set_print_file_path"):
                catalog.set_print_file_path(match.sku, match.pdf_path)
            else:
                object.__setattr__(product, "print_file_path", match.pdf_path)
            updated += 1
            logger.info(
                "PdfBulkMapper: applied SKU=%r → %r",
                match.sku, match.pdf_path,
            )
        return updated

    # ------------------------------------------------------------------ #
    # Internal helpers                                                     #
    # ------------------------------------------------------------------ #

    @staticmethod
    def _collect_pdf_files(root: Path, *, recursive: bool) -> list[Path]:
        pattern = "**/*.pdf" if recursive else "*.pdf"
        return [p for p in root.glob(pattern) if p.is_file()]

    @staticmethod
    def _parse_pdf_files(pdf_files: list[Path]) -> list[tuple[Path, str]]:
        """Return (path, normalized_stem) for each PDF."""
        result: list[tuple[Path, str]] = []
        for p in pdf_files:
            stem_norm = _normalize_name(p.stem)
            if stem_norm:
                result.append((p, stem_norm))
        return result

    @staticmethod
    def _get_matchable_products(
        catalog: object,
        result: BulkScanResult,
        *,
        overwrite_existing: bool,
    ) -> list[tuple[str, str, bool]]:
        """Yield (sku, name, is_digital) tuples from catalog."""
        out: list[tuple[str, str, bool]] = []
        # ProductCatalogService exposes _by_sku dict
        by_sku: dict = getattr(catalog, "_by_sku", {})
        for sku, product in by_sku.items():
            name = getattr(product, "name", "") or sku
            is_digital = bool(getattr(product, "is_digital", False))
            existing_path = str(getattr(product, "print_file_path", "") or "").strip()
            if existing_path and not overwrite_existing:
                result.already_configured.append(sku)
                continue
            out.append((sku, name, is_digital))
        return out

    @staticmethod
    def _get_product(catalog: object, sku: str) -> object | None:
        by_sku: dict = getattr(catalog, "_by_sku", {})
        return by_sku.get(sku)
