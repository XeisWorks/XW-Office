from __future__ import annotations

from pathlib import Path

import fitz
import httpx
import pytest

from xw_office.services.invoice_collection.connectors.browser import BrowserInvoiceConnector
from xw_office.services.invoice_collection.connectors.graph_mail import (
    GraphMailAttachmentConnector,
    MailMatchPolicy,
)
from xw_office.services.invoice_collection.connectors.graph_reader import GraphMailAttachmentReader
from xw_office.services.invoice_collection.connectors.mollie_invoices import MollieInvoicesHttpClient
from xw_office.services.invoice_collection.domain import (
    DocumentCandidate,
    DocumentType,
    ProviderConnection,
    TenantId,
)
from xw_office.services.invoice_collection.errors import InvoiceCollectionError, InvoiceErrorCode
from xw_office.services.invoice_collection.auth.graph import (
    CallbackGraphTokenProvider,
    MsalInteractiveGraphTokenProvider,
)
from xw_office.services.invoice_collection.playwright_session import PlaywrightPersistentSession


def _pdf(path: Path) -> None:
    with fitz.open() as document:
        document.new_page()
        document.save(path)


def _connection(provider: str = "fixture") -> ProviderConnection:
    return ProviderConnection.create(
        provider_id=provider,
        tenant_id=TenantId.XW,
        account_alias="account",
    )


class _MailReader:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.downloads: list[tuple[str, str]] = []

    def list_messages(self) -> list[dict[str, object]]:
        return [
            {
                "id": "message-1",
                "received_at": "2026-11-05T10:00:00Z",
                "sender_domain": "billing.example.test",
                "attachments": [
                    {"id": "pdf-1", "name": "invoice.pdf", "content_type": "application/pdf"},
                    {"id": "html-1", "name": "notice.html", "content_type": "text/html"},
                ],
            }
        ]

    def download_attachment(self, message_id: str, attachment_id: str, destination: Path) -> None:
        self.downloads.append((message_id, attachment_id))
        _pdf(destination)


def test_graph_mail_connector_requires_real_pdf_attachment_and_stable_ids(tmp_path: Path) -> None:
    reader = _MailReader(tmp_path)
    connector = GraphMailAttachmentConnector(
        connection=_connection(),
        reader=reader,
        policy=MailMatchPolicy(sender_domains=frozenset({"billing.example.test"})),
    )
    candidates = connector.discover()
    assert len(candidates) == 1
    assert candidates[0].source_id == "message-1:pdf-1"
    artifact = connector.download(candidates[0], tmp_path / "workspace")
    assert artifact.path.exists()
    assert reader.downloads == [("message-1", "pdf-1")]


def test_graph_reader_paginates_and_downloads_attachment_bytes(tmp_path: Path) -> None:
    pdf_bytes = b"%PDF-1.4 fake"

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/messages"):
            return httpx.Response(
                200,
                json={
                    "value": [
                        {
                            "id": "message-1",
                            "receivedDateTime": "2026-11-05T10:00:00Z",
                            "sender": {"emailAddress": {"address": "billing@example.test"}},
                            "attachments": [
                                {
                                    "id": "attachment-1",
                                    "name": "invoice.pdf",
                                    "contentType": "application/pdf",
                                    "size": len(pdf_bytes),
                                }
                            ],
                        }
                    ],
                    "@odata.nextLink": "https://graph.microsoft.com/v1.0/next",
                },
            )
        if request.url.path.endswith("/next"):
            return httpx.Response(200, json={"value": []})
        if request.url.path.endswith("/attachments/attachment-1"):
            return httpx.Response(200, content=pdf_bytes, headers={"content-type": "application/pdf"})
        return httpx.Response(404)

    reader = GraphMailAttachmentReader(
        mailbox="invoices@example.test",
        token_provider=CallbackGraphTokenProvider(lambda: "access-token"),
        client=httpx.Client(transport=httpx.MockTransport(handler)),
    )
    messages = reader.list_messages()
    assert messages[0]["sender_domain"] == "example.test"
    destination = tmp_path / "invoice.pdf"
    reader.download_attachment("message-1", "attachment-1", destination)
    assert destination.read_bytes() == pdf_bytes


def test_msal_provider_uses_silent_token_before_visible_interactive_login(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "local"))
    cache_path = tmp_path / "local" / "XeisWorks" / "XW-Office" / "invoice_collection" / "auth" / "graph.cache"
    calls: list[str] = []

    class FakeApp:
        def get_accounts(self):
            return [{"username": "user@example.test"}]

        def acquire_token_silent(self, scopes, account):
            calls.append("silent")
            return {"access_token": "silent-token"}

        def acquire_token_interactive(self, scopes):
            calls.append("interactive")
            return {"access_token": "interactive-token"}

    provider = MsalInteractiveGraphTokenProvider(
        client_id="client-id",
        authority="https://login.microsoftonline.com/common",
        scopes=("Mail.Read",),
        cache_path=cache_path,
        app_factory=lambda *args, **kwargs: FakeApp(),
        cache_factory=lambda path: object(),
    )
    assert provider.get_access_token() == "silent-token"
    assert calls == ["silent"]


def test_mollie_http_client_paginates_and_rejects_untrusted_pdf_host() -> None:
    requests: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(str(request.url))
        if request.url.path == "/v2/invoices":
            return httpx.Response(
                200,
                json={
                    "_embedded": {"invoices": [{"id": "inv-1"}]},
                    "_links": {"next": {"href": "https://api.mollie.com/page-2"}},
                },
            )
        if request.url.path == "/page-2":
            return httpx.Response(200, json={"_embedded": {"invoices": [{"id": "inv-2"}]}})
        return httpx.Response(404)

    client = MollieInvoicesHttpClient(
        "read-only-token",
        client=httpx.Client(transport=httpx.MockTransport(handler)),
    )
    invoices = client.list_invoices()
    assert [item["id"] for item in invoices] == ["inv-1", "inv-2"]
    assert requests == ["https://api.mollie.com/v2/invoices?limit=100", "https://api.mollie.com/page-2"]


def test_mollie_http_client_retries_rate_limit_with_bounded_backoff() -> None:
    attempts = 0
    delays: list[float] = []

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            return httpx.Response(429, headers={"Retry-After": "0"})
        return httpx.Response(200, json={"_embedded": {"invoices": []}})

    client = MollieInvoicesHttpClient(
        "read-only-token",
        client=httpx.Client(transport=httpx.MockTransport(handler)),
        sleeper=delays.append,
    )
    assert client.list_invoices() == []
    assert attempts == 2
    assert delays == [0.0]


class _BrowserSession:
    def __init__(self, candidate: DocumentCandidate, root: Path) -> None:
        self.candidate = candidate
        self.root = root
        self.login_opened = False

    def probe(self) -> bool:
        return False

    def open_login(self) -> None:
        self.login_opened = True

    def discover(self) -> list[DocumentCandidate]:
        return [self.candidate]

    def download(self, candidate: DocumentCandidate, destination: Path) -> None:
        _pdf(destination)


def test_browser_connector_keeps_login_and_download_injected(tmp_path: Path) -> None:
    candidate = DocumentCandidate(
        connection=_connection("fixture_browser"),
        route_key="billing_portal",
        source_id="portal-1",
        external_id="portal-1",
        document_type=DocumentType.EXPENSE_INVOICE,
        original_filename="invoice.pdf",
    )
    session = _BrowserSession(candidate, tmp_path)
    connector = BrowserInvoiceConnector(connection=candidate.connection, session=session)
    assert connector.probe() is False
    connector.open_login()
    assert session.login_opened is True
    assert connector.download(candidate, tmp_path / "workspace").path.exists()


def test_playwright_session_rejects_profile_outside_local_app_data(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "local"))
    session_path = tmp_path / "outside" / "profile"
    with pytest.raises(ValueError):
        PlaywrightPersistentSession(
            profile_dir=session_path,
            login_url="https://portal.example.test/login",
            probe_url="https://portal.example.test/invoices",
            allowed_hosts=frozenset({"portal.example.test"}),
            probe_callback=lambda page: True,
            discover_callback=lambda page: [],
            download_callback=lambda page, candidate, destination: None,
        )


def test_playwright_session_rejects_unallowlisted_login_host(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "local"))
    profile = tmp_path / "local" / "XeisWorks" / "XW-Office" / "invoice_collection" / "profiles" / "fixture"
    session = PlaywrightPersistentSession(
        profile_dir=profile,
        login_url="https://evil.example.test/login",
        probe_url="https://portal.example.test/invoices",
        allowed_hosts=frozenset({"portal.example.test"}),
        probe_callback=lambda page: True,
        discover_callback=lambda page: [],
        download_callback=lambda page, candidate, destination: None,
    )
    with pytest.raises(InvoiceCollectionError) as error:
        session.probe()
    assert error.value.code == InvoiceErrorCode.POLICY_BLOCKED
