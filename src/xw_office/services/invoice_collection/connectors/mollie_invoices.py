"""Read-only Mollie invoices route with injected HTTP client or API double."""
from __future__ import annotations

from datetime import date, datetime
from pathlib import Path
import time
from typing import Any, Iterable, Protocol
from urllib.parse import urlparse

import httpx

from xw_office.services.invoice_collection.domain import (
    DocumentCandidate,
    DocumentType,
    DownloadedArtifact,
    ProviderConnection,
)
from xw_office.services.invoice_collection.errors import (
    InvoiceCollectionError,
    InvoiceErrorCode,
)
from xw_office.services.invoice_collection.naming import workspace_download_path
from xw_office.services.invoice_collection.ports import CancelToken


class MollieInvoiceApi(Protocol):
    def list_invoices(self) -> Iterable[dict[str, Any]]: ...

    def download_invoice_pdf(self, invoice: dict[str, Any], destination: Path) -> None: ...


class MollieInvoicesConnector:
    """Map only Mollie-owned fee invoices into the common document contract."""

    route_key = "invoices_api"

    def __init__(
        self,
        *,
        connection: ProviderConnection,
        api: MollieInvoiceApi,
        start: date | None = None,
        end: date | None = None,
    ) -> None:
        self.connection = connection
        self.api = api
        self.start = start
        self.end = end
        self._invoices: dict[str, dict[str, Any]] = {}

    def discover(self) -> list[DocumentCandidate]:
        candidates: list[DocumentCandidate] = []
        for invoice in self.api.list_invoices():
            invoice_id = str(invoice.get("id") or "").strip()
            if not invoice_id:
                continue
            invoice_date = _parse_date(invoice.get("date") or invoice.get("issuedAt"))
            if invoice_date is not None and self.start and invoice_date < self.start:
                continue
            if invoice_date is not None and self.end and invoice_date > self.end:
                continue
            self._invoices[invoice_id] = invoice
            candidates.append(
                DocumentCandidate(
                    connection=self.connection,
                    route_key=self.route_key,
                    source_id=invoice_id,
                    external_id=invoice_id,
                    document_type=DocumentType.FEE_INVOICE,
                    original_filename=f"{invoice_id}.pdf",
                    document_date=invoice_date,
                    currency=str(invoice.get("currency") or "EUR") or None,
                    metadata={"invoice_id": invoice_id},
                )
            )
        return candidates

    def download(
        self,
        candidate: DocumentCandidate,
        workspace: Path,
        cancel: CancelToken | None = None,
    ) -> DownloadedArtifact:
        if cancel is not None and cancel.cancelled:
            raise RuntimeError("Mollie-Abruf abgebrochen")
        invoice_id = str(candidate.external_id or candidate.source_id)
        invoice = self._invoices.get(invoice_id)
        if invoice is None:
            raise ValueError("Mollie-Rechnung wurde nicht durch discover() vorbereitet")
        workspace.mkdir(parents=True, exist_ok=True)
        destination = workspace_download_path(workspace, candidate.original_filename)
        self.api.download_invoice_pdf(invoice, destination)
        return DownloadedArtifact(candidate=candidate, path=destination)

    def close(self) -> None:
        close = getattr(self.api, "close", None)
        if callable(close):
            close()


class MollieInvoicesHttpClient:
    """Small, read-only HTTP client; token is held only in memory by the caller."""

    _PDF_CHUNK_BYTES = 64 * 1024
    _DEFAULT_MAX_PDF_BYTES = 25 * 1024 * 1024
    _MAX_INVOICE_PAGES = 1000

    def __init__(
        self,
        access_token: str,
        *,
        client: httpx.Client | None = None,
        base_url: str = "https://api.mollie.com",
        max_retries: int = 2,
        max_pdf_bytes: int = _DEFAULT_MAX_PDF_BYTES,
        sleeper: Any = time.sleep,
    ) -> None:
        if not access_token.strip():
            raise InvoiceCollectionError(InvoiceErrorCode.AUTH_REQUIRED, "Mollie-Token fehlt")
        self._token = access_token
        self._client = client or httpx.Client(timeout=httpx.Timeout(30.0))
        self._base_url = base_url.rstrip("/")
        self._max_retries = max(0, int(max_retries))
        self._max_pdf_bytes = int(max_pdf_bytes)
        if self._max_pdf_bytes <= 0:
            raise ValueError("max_pdf_bytes must be positive")
        self._sleeper = sleeper

    def list_invoices(self) -> list[dict[str, Any]]:
        invoices: list[dict[str, Any]] = []
        url: str | None = f"{self._base_url}/v2/invoices"
        first_page = True
        seen_urls: set[str] = set()
        while url:
            if url in seen_urls or len(seen_urls) >= self._MAX_INVOICE_PAGES:
                raise InvoiceCollectionError(
                    InvoiceErrorCode.PROVIDER_CHANGED,
                    "Mollie-Invoices API lieferte eine wiederholte oder zu lange Pagination",
                )
            seen_urls.add(url)
            response = self._request("GET", url, params={"limit": 100} if first_page else None)
            first_page = False
            payload = response.json()
            embedded = payload.get("_embedded") if isinstance(payload, dict) else {}
            page = embedded.get("invoices") if isinstance(embedded, dict) else []
            if isinstance(page, list):
                invoices.extend(item for item in page if isinstance(item, dict))
            links = payload.get("_links") if isinstance(payload, dict) else None
            next_link = links.get("next") if isinstance(links, dict) else None
            next_url = next_link.get("href") if isinstance(next_link, dict) else None
            url = str(next_url) if next_url else None
        return invoices

    def close(self) -> None:
        self._client.close()

    def download_invoice_pdf(self, invoice: dict[str, Any], destination: Path) -> None:
        pdf_url = _pdf_url(invoice)
        if not pdf_url:
            raise InvoiceCollectionError(InvoiceErrorCode.INVALID_DOCUMENT, "Mollie-PDF-Link fehlt")
        parsed = urlparse(pdf_url)
        if parsed.scheme != "https" or parsed.netloc.casefold() not in {
            "api.mollie.com",
            urlparse(self._base_url).netloc.casefold(),
        }:
            raise InvoiceCollectionError(
                InvoiceErrorCode.POLICY_BLOCKED, "Mollie-PDF-Link ist nicht erlaubt"
            )
        payload = self._download_pdf_bytes(pdf_url)
        destination.write_bytes(payload)

    def _download_pdf_bytes(self, url: str) -> bytes:
        for attempt in range(self._max_retries + 1):
            try:
                with self._client.stream(
                    "GET",
                    url,
                    headers={
                        "Authorization": f"Bearer {self._token}",
                        "Accept": "application/json",
                    },
                ) as response:
                    if response.status_code in {401, 403}:
                        raise InvoiceCollectionError(
                            InvoiceErrorCode.AUTH_REQUIRED,
                            "Mollie-Zugang wurde abgelehnt",
                        )
                    if response.status_code in {429, 500, 502, 503, 504}:
                        if attempt < self._max_retries:
                            self._sleeper(_retry_delay(response, attempt))
                            continue
                        code = (
                            InvoiceErrorCode.RATE_LIMITED
                            if response.status_code == 429
                            else InvoiceErrorCode.TRANSIENT_NETWORK
                        )
                        raise InvoiceCollectionError(
                            code, "Mollie-PDF-Abruf konnte nicht abgeschlossen werden"
                        )
                    response.raise_for_status()
                    _reject_oversized_content_length(
                        response, self._max_pdf_bytes
                    )
                    return _read_limited_pdf(response, self._max_pdf_bytes)
            except httpx.TimeoutException as exc:
                if attempt < self._max_retries:
                    self._sleeper(min(2**attempt, 8))
                    continue
                raise InvoiceCollectionError(
                    InvoiceErrorCode.TRANSIENT_NETWORK,
                    "Mollie-Zeitüberschreitung beim PDF-Abruf",
                ) from exc
        raise InvoiceCollectionError(
            InvoiceErrorCode.INTERNAL_ERROR, "Mollie-PDF-Retry wurde unerwartet beendet"
        )

    def _request(self, method: str, url: str, **kwargs: Any) -> httpx.Response:
        parsed = urlparse(url)
        base_host = urlparse(self._base_url).netloc.casefold()
        if parsed.scheme != "https" or parsed.netloc.casefold() not in {
            "api.mollie.com",
            base_host,
        }:
            raise InvoiceCollectionError(
                InvoiceErrorCode.POLICY_BLOCKED, "Mollie-URL ist nicht erlaubt"
            )
        for attempt in range(self._max_retries + 1):
            try:
                response = self._client.request(
                    method,
                    url,
                    headers={
                        "Authorization": f"Bearer {self._token}",
                        "Accept": "application/json",
                    },
                    **kwargs,
                )
            except httpx.TimeoutException as exc:
                if attempt < self._max_retries:
                    self._sleeper(min(2**attempt, 8))
                    continue
                raise InvoiceCollectionError(
                    InvoiceErrorCode.TRANSIENT_NETWORK, "Mollie-Zeitüberschreitung"
                ) from exc
            if response.status_code in {401, 403}:
                raise InvoiceCollectionError(
                    InvoiceErrorCode.AUTH_REQUIRED, "Mollie-Zugang wurde abgelehnt"
                )
            if response.status_code in {429, 500, 502, 503, 504}:
                if attempt < self._max_retries:
                    self._sleeper(_retry_delay(response, attempt))
                    continue
                code = (
                    InvoiceErrorCode.RATE_LIMITED
                    if response.status_code == 429
                    else InvoiceErrorCode.TRANSIENT_NETWORK
                )
                raise InvoiceCollectionError(code, "Mollie-Abruf konnte nicht abgeschlossen werden")
            response.raise_for_status()
            return response
        raise InvoiceCollectionError(
            InvoiceErrorCode.INTERNAL_ERROR, "Mollie-Retry wurde unerwartet beendet"
        )


def _pdf_url(invoice: dict[str, Any]) -> str:
    links = invoice.get("_links") or {}
    pdf = links.get("pdf") if isinstance(links, dict) else None
    if isinstance(pdf, dict) and pdf.get("href"):
        return str(pdf["href"])
    return str(invoice.get("pdfUrl") or "").strip()


def _retry_delay(response: httpx.Response, attempt: int) -> float:
    retry_after = response.headers.get("Retry-After", "")
    try:
        delay = float(str(retry_after))
        if delay < 0.0:
            return 0.0
        if delay > 30.0:
            return 30.0
        return delay
    except ValueError:
        fallback_delay = 2**attempt
        return float(fallback_delay if fallback_delay < 8 else 8)


def _reject_oversized_content_length(response: httpx.Response, limit: int) -> None:
    try:
        declared_length = int(response.headers.get("content-length", ""))
    except ValueError:
        return
    if declared_length > limit:
        raise InvoiceCollectionError(
            InvoiceErrorCode.INVALID_DOCUMENT, "Mollie-PDF ueberschreitet das Groessenlimit"
        )


def _read_limited_pdf(response: httpx.Response, limit: int) -> bytes:
    chunks: list[bytes] = []
    total = 0
    for chunk in response.iter_bytes(chunk_size=MollieInvoicesHttpClient._PDF_CHUNK_BYTES):
        total += len(chunk)
        if total > limit:
            raise InvoiceCollectionError(
                InvoiceErrorCode.INVALID_DOCUMENT,
                "Mollie-PDF ueberschreitet das Groessenlimit",
            )
        chunks.append(chunk)
    return b"".join(chunks)


def _parse_date(value: Any) -> date | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00")).date()
    except ValueError:
        try:
            return date.fromisoformat(text[:10])
        except ValueError:
            return None
