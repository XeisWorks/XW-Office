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
        destination = workspace / candidate.original_filename
        self.api.download_invoice_pdf(invoice, destination)
        return DownloadedArtifact(candidate=candidate, path=destination)


class MollieInvoicesHttpClient:
    """Small, read-only HTTP client; token is held only in memory by the caller."""

    def __init__(
        self,
        access_token: str,
        *,
        client: httpx.Client | None = None,
        base_url: str = "https://api.mollie.com",
        max_retries: int = 2,
        sleeper: Any = time.sleep,
    ) -> None:
        if not access_token.strip():
            raise InvoiceCollectionError(InvoiceErrorCode.AUTH_REQUIRED, "Mollie-Token fehlt")
        self._token = access_token
        self._client = client or httpx.Client(timeout=httpx.Timeout(30.0))
        self._base_url = base_url.rstrip("/")
        self._max_retries = max(0, int(max_retries))
        self._sleeper = sleeper

    def list_invoices(self) -> list[dict[str, Any]]:
        invoices: list[dict[str, Any]] = []
        url: str | None = f"{self._base_url}/v2/invoices"
        first_page = True
        while url:
            response = self._request("GET", url, params={"limit": 100} if first_page else None)
            first_page = False
            payload = response.json()
            embedded = payload.get("_embedded") if isinstance(payload, dict) else {}
            page = embedded.get("invoices") if isinstance(embedded, dict) else []
            if isinstance(page, list):
                invoices.extend(item for item in page if isinstance(item, dict))
            next_link = (
                ((payload.get("_links") or {}).get("next") or {})
                if isinstance(payload, dict)
                else {}
            )
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
        response = self._request("GET", pdf_url)
        destination.write_bytes(response.content)

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
                    retry_after = response.headers.get("Retry-After", "")
                    try:
                        delay = min(max(float(retry_after), 0.0), 30.0)
                    except ValueError:
                        delay = min(2**attempt, 8)
                    self._sleeper(delay)
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
