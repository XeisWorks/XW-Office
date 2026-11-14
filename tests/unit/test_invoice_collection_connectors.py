from __future__ import annotations

import base64
from datetime import date
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
from xw_office.services.invoice_collection.connectors.mollie_invoices import (
    MollieInvoicesConnector,
    MollieInvoicesHttpClient,
)
from xw_office.services.invoice_collection.domain import (
    DateRange,
    DocumentCandidate,
    DocumentType,
    ProviderConnection,
    RouteSettings,
    TenantId,
)
from xw_office.services.invoice_collection.errors import InvoiceCollectionError, InvoiceErrorCode
from xw_office.services.invoice_collection.auth.graph import (
    CallbackGraphTokenProvider,
    MsalInteractiveGraphTokenProvider,
)
from xw_office.services.invoice_collection.bootstrap import build_connector_factories
from xw_office.services.invoice_collection.playwright_session import PlaywrightPersistentSession
from xw_office.services.invoice_collection.pipeline import DocumentPipeline
from xw_office.services.invoice_collection.sinks.onedrive_local import OneDriveLocalSink


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
        start=date(2026, 10, 1),
        end=date(2026, 10, 31),
    )
    candidates = connector.discover()
    assert len(candidates) == 1
    assert candidates[0].source_id == "message-1:pdf-1"
    artifact = connector.download(candidates[0], tmp_path / "workspace")
    assert artifact.path.exists()
    assert reader.downloads == [("message-1", "pdf-1")]
    assert candidates[0].document_date is None
    assert candidates[0].metadata["received_at"] == "2026-11-05T10:00:00Z"
    assert candidates[0].metadata["selected_period_start"] == "2026-10-01"


def test_graph_mail_connector_fails_closed_without_verified_sender_domains(
    tmp_path: Path,
) -> None:
    connector = GraphMailAttachmentConnector(connection=_connection(), reader=_MailReader(tmp_path))
    assert connector.discover() == []


def test_graph_mail_factory_wires_local_connection_settings_and_selected_period(
    monkeypatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "local"))
    monkeypatch.setenv("MS_GRAPH_CLIENT_ID", "test-public-client-id")
    monkeypatch.setenv("MS_GRAPH_TENANT_ID", "test-tenant-id")

    class TokenProvider:
        def __init__(self, **kwargs: object) -> None:
            self.kwargs = kwargs

        def get_access_token(self) -> str:
            return "test-access-token"

    connection = ProviderConnection.create(
        provider_id="browserstack",
        tenant_id=TenantId.XW,
        account_alias="primary",
    )
    route = RouteSettings(
        route_key="mail_pdf",
        options={
            "mailbox": "invoices@example.test",
            "sender_domains": "billing.example.test",
            "document_type": DocumentType.EXPENSE_INVOICE.value,
        },
    )
    period = DateRange(date(2026, 11, 1), date(2026, 11, 30))
    connector = build_connector_factories(
        token_provider_factory=TokenProvider
    ).create("graph_mail_attachment", connection, route, period)
    assert isinstance(connector, GraphMailAttachmentConnector)
    assert connector.start == period.start
    assert connector.end == period.end
    assert connector.policy.sender_domains == frozenset({"billing.example.test"})
    assert connector.policy.document_type is DocumentType.EXPENSE_INVOICE
    connector.close()


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
            return httpx.Response(
                200, content=pdf_bytes, headers={"content-type": "application/pdf"}
            )
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


def test_graph_reader_stops_oversized_stream_and_closes_response(tmp_path: Path) -> None:
    class OversizedStream(httpx.SyncByteStream):
        def __init__(self) -> None:
            self.closed = False
            self.yielded = 0

        def __iter__(self):
            self.yielded += 1
            yield b"x" * (64 * 1024 + 1)
            self.yielded += 1
            yield b"unread"

        def close(self) -> None:
            self.closed = True

    body_stream = OversizedStream()

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            headers={"content-type": "application/pdf"},
            stream=body_stream,
        )

    reader = GraphMailAttachmentReader(
        mailbox="billing@example.test",
        token_provider=CallbackGraphTokenProvider(lambda: "test-token"),
        client=httpx.Client(transport=httpx.MockTransport(handler)),
        max_attachment_bytes=8,
    )
    destination = tmp_path / "nested" / "invoice.pdf"
    with pytest.raises(InvoiceCollectionError) as error:
        reader.download_attachment("message-1", "attachment-1", destination)

    assert error.value.code is InvoiceErrorCode.INVALID_DOCUMENT
    assert body_stream.closed
    assert body_stream.yielded == 1
    assert not destination.exists()
    assert not destination.parent.exists()


def test_graph_reader_rejects_json_base64_above_decoded_limit(tmp_path: Path) -> None:
    encoded = base64.b64encode(b"123456789").decode("ascii")

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={"contentBytes": encoded},
            headers={"content-type": "application/json"},
        )

    reader = GraphMailAttachmentReader(
        mailbox="billing@example.test",
        token_provider=CallbackGraphTokenProvider(lambda: "test-token"),
        client=httpx.Client(transport=httpx.MockTransport(handler)),
        max_attachment_bytes=8,
    )
    destination = tmp_path / "invoice.pdf"
    with pytest.raises(InvoiceCollectionError) as error:
        reader.download_attachment("message-1", "attachment-1", destination)

    assert error.value.code is InvoiceErrorCode.INVALID_DOCUMENT
    assert not destination.exists()


def test_graph_reader_mailbox_probe_reads_only_one_message_id() -> None:
    requests: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(str(request.url))
        return httpx.Response(200, json={"value": [{"id": "message-id"}]})

    reader = GraphMailAttachmentReader(
        mailbox="billing@example.test",
        token_provider=CallbackGraphTokenProvider(lambda: "test-token"),
        client=httpx.Client(transport=httpx.MockTransport(handler)),
    )
    reader.probe_mailbox()
    reader.close()
    assert len(requests) == 1
    assert "$select=id" in requests[0]
    assert "$top=1" in requests[0]
    assert "attachments" not in requests[0]


def test_msal_provider_uses_silent_token_before_visible_interactive_login(
    monkeypatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "local"))
    cache_path = (
        tmp_path
        / "local"
        / "XeisWorks"
        / "XW-Office"
        / "invoice_collection"
        / "auth"
        / "graph.cache"
    )
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
    assert requests == [
        "https://api.mollie.com/v2/invoices?limit=100",
        "https://api.mollie.com/page-2",
    ]


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


def test_mollie_connector_sends_fee_invoice_through_common_pipeline(tmp_path: Path) -> None:
    class FakeApi:
        closed = False

        def list_invoices(self):
            return [{"id": "inv-1", "date": "2026-11-05", "currency": "EUR"}]

        def download_invoice_pdf(self, invoice, destination: Path) -> None:
            _pdf(destination)

        def close(self) -> None:
            self.closed = True

    api = FakeApi()
    connector = MollieInvoicesConnector(connection=_connection("mollie_fees"), api=api)
    candidates = connector.discover()
    assert candidates[0].document_type is DocumentType.FEE_INVOICE
    artifact = connector.download(candidates[0], tmp_path / "workspace")
    destination = tmp_path / "onedrive"
    destination.mkdir()
    result = DocumentPipeline(sink=OneDriveLocalSink(destination)).process(artifact)
    assert result.receipt.outcome.value == "NEW"
    assert result.receipt.target_path.exists()
    connector.close()
    assert api.closed is True


class _BrowserSession:
    def __init__(self, candidate: DocumentCandidate, root: Path) -> None:
        self.candidate = candidate
        self.root = root
        self.login_opened = False
        self.closed = False

    def probe(self) -> bool:
        return False

    def open_login(self) -> None:
        self.login_opened = True

    def discover(self) -> list[DocumentCandidate]:
        return [self.candidate]

    def download(self, candidate: DocumentCandidate, destination: Path) -> None:
        _pdf(destination)

    def close(self) -> None:
        self.closed = True


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
    connector.close()
    assert session.closed is True


def test_browser_connector_resumes_only_after_route_probe_succeeds(tmp_path: Path) -> None:
    candidate = DocumentCandidate(
        connection=_connection("fixture_browser_resume"),
        route_key="billing_portal",
        source_id="portal-1",
        external_id="portal-1",
        document_type=DocumentType.EXPENSE_INVOICE,
        original_filename="invoice.pdf",
    )

    class Session:
        authenticated = False

        def probe(self) -> bool:
            return self.authenticated

        def open_login(self) -> None:
            self.authenticated = True

        def discover(self) -> list[DocumentCandidate]:
            return [candidate]

        def download(self, candidate, destination: Path) -> None:
            _pdf(destination)

    session = Session()
    connector = BrowserInvoiceConnector(connection=candidate.connection, session=session)
    with pytest.raises(InvoiceCollectionError) as error:
        connector.resume_after_login()
    assert error.value.code == InvoiceErrorCode.AUTH_REQUIRED
    connector.open_login()
    assert connector.resume_after_login() == [candidate]


def test_playwright_fake_portal_resumes_only_after_manual_login_and_downloads_pdf(
    monkeypatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "local"))
    profile = (
        tmp_path
        / "local"
        / "XeisWorks"
        / "XW-Office"
        / "invoice_collection"
        / "profiles"
        / "fixture-portal"
    )
    connection = _connection("fixture_portal")
    candidate = DocumentCandidate(
        connection=connection,
        route_key="billing_portal",
        source_id="fake-portal-invoice",
        external_id=None,
        document_type=DocumentType.EXPENSE_INVOICE,
        original_filename="invoice.pdf",
        document_date=date(2026, 11, 5),
    )

    class FakePage:
        authenticated = False

        def goto(self, url, **kwargs):
            self.current_url = url

        def confirm_manual_login_and_2fa(self):
            self.authenticated = True

    class FakeContext:
        def __init__(self):
            self.pages = [FakePage()]

        def close(self):
            return None

    class FakeChromium:
        def launch_persistent_context(self, **kwargs):
            return FakeContext()

    class FakeRuntime:
        chromium = FakeChromium()

        def start(self):
            return self

        def stop(self):
            return None

    session = PlaywrightPersistentSession(
        profile_dir=profile,
        login_url="https://portal.example.test/login",
        probe_url="https://portal.example.test/invoices",
        allowed_hosts=frozenset({"portal.example.test"}),
        probe_callback=lambda page: page.authenticated,
        discover_callback=lambda page: [candidate] if page.authenticated else [],
        download_callback=lambda page, _candidate, destination: _pdf(destination),
        playwright_factory=lambda: FakeRuntime(),
    )
    connector = BrowserInvoiceConnector(connection=connection, session=session)

    with pytest.raises(InvoiceCollectionError) as error:
        connector.resume_after_login()
    assert error.value.code is InvoiceErrorCode.AUTH_REQUIRED

    connector.open_login()
    page = session._context.pages[0]
    page.confirm_manual_login_and_2fa()
    assert connector.resume_after_login() == [candidate]
    artifact = connector.download(candidate, tmp_path / "workspace")
    assert artifact.path.is_file()
    assert artifact.path.read_bytes().startswith(b"%PDF-")

    connector.close()
    assert not profile.with_name("fixture-portal.lock").exists()


def test_playwright_system_chrome_start_failure_releases_profile_and_runtime(
    monkeypatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "local"))
    monkeypatch.setattr("xw_office.services.invoice_collection.playwright_session._find_system_chrome", lambda: None)
    profile = (
        tmp_path
        / "local"
        / "XeisWorks"
        / "XW-Office"
        / "invoice_collection"
        / "profiles"
        / "fixture-cdp"
    )
    runtime = type(
        "FakeRuntime",
        (),
        {"start": lambda self: self, "stop": lambda self: setattr(self, "stopped", True)},
    )()
    session = PlaywrightPersistentSession(
        profile_dir=profile,
        login_url="https://portal.example.test/login",
        probe_url="https://portal.example.test/invoices",
        allowed_hosts=frozenset({"portal.example.test"}),
        probe_callback=lambda _page: True,
        discover_callback=lambda _page: [],
        download_callback=lambda _page, _candidate, _destination: None,
        playwright_factory=lambda: runtime,
        browser_mode="system_chrome_cdp",
    )

    with pytest.raises(InvoiceCollectionError) as error:
        session.probe()

    assert error.value.code is InvoiceErrorCode.CONFIGURATION_ERROR
    assert getattr(runtime, "stopped", False) is True
    assert not profile.with_name("fixture-cdp.lock").exists()


@pytest.mark.parametrize(
    ("callback", "expected_code"),
    [
        (
            lambda _page: (_ for _ in ()).throw(TimeoutError("private timeout detail")),
            InvoiceErrorCode.TRANSIENT_NETWORK,
        ),
        (
            lambda _page: (_ for _ in ()).throw(RuntimeError("private page response")),
            InvoiceErrorCode.PROVIDER_CHANGED,
        ),
    ],
)
def test_playwright_page_callbacks_return_typed_redacted_errors(
    monkeypatch, tmp_path: Path, callback, expected_code: InvoiceErrorCode
) -> None:
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "local"))
    profile = (
        tmp_path
        / "local"
        / "XeisWorks"
        / "XW-Office"
        / "invoice_collection"
        / "profiles"
        / "fixture-error"
    )

    class FakePage:
        def goto(self, _url, **_kwargs):
            return None

    class FakeContext:
        pages = [FakePage()]

        def close(self):
            return None

    class FakeChromium:
        def launch_persistent_context(self, **_kwargs):
            return FakeContext()

    class FakeRuntime:
        chromium = FakeChromium()

        def start(self):
            return self

        def stop(self):
            return None

    session = PlaywrightPersistentSession(
        profile_dir=profile,
        login_url="https://portal.example.test/login",
        probe_url="https://portal.example.test/invoices",
        allowed_hosts=frozenset({"portal.example.test"}),
        probe_callback=callback,
        discover_callback=lambda _page: [],
        download_callback=lambda _page, _candidate, _destination: None,
        playwright_factory=lambda: FakeRuntime(),
    )

    with pytest.raises(InvoiceCollectionError) as error:
        session.probe()

    assert error.value.code is expected_code
    assert "private" not in str(error.value)
    session.close()


def test_browser_connector_filters_candidates_to_requested_period(tmp_path: Path) -> None:
    from datetime import date

    connection = _connection("fixture_browser_period")
    in_period = DocumentCandidate(
        connection=connection,
        route_key="billing_portal",
        source_id="in-period",
        external_id="in-period",
        document_type=DocumentType.EXPENSE_INVOICE,
        original_filename="november.pdf",
        document_date=date(2026, 11, 1),
    )
    before_period = DocumentCandidate(
        connection=connection,
        route_key="billing_portal",
        source_id="before-period",
        external_id="before-period",
        document_type=DocumentType.EXPENSE_INVOICE,
        original_filename="october.pdf",
        document_date=date(2026, 10, 31),
    )

    class Session:
        def probe(self) -> bool:
            return True

        def open_login(self) -> None:
            return None

        def discover(self) -> list[DocumentCandidate]:
            return [before_period, in_period]

        def download(self, candidate, destination: Path) -> None:
            _pdf(destination)

    connector = BrowserInvoiceConnector(
        connection=connection,
        session=Session(),
        start=date(2026, 11, 1),
    )
    assert [candidate.source_id for candidate in connector.discover()] == ["in-period"]


def test_playwright_session_rejects_profile_outside_local_app_data(
    monkeypatch, tmp_path: Path
) -> None:
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
    profile = (
        tmp_path
        / "local"
        / "XeisWorks"
        / "XW-Office"
        / "invoice_collection"
        / "profiles"
        / "fixture"
    )
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


def test_playwright_session_uses_visible_fake_runtime_and_releases_profile_lock(
    monkeypatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "local"))
    profile = (
        tmp_path
        / "local"
        / "XeisWorks"
        / "XW-Office"
        / "invoice_collection"
        / "profiles"
        / "fixture"
    )
    calls: list[dict[str, object]] = []

    class FakePage:
        def goto(self, url, **kwargs):
            calls.append({"url": url, **kwargs})

    class FakeContext:
        def __init__(self):
            self.pages = [FakePage()]

        def close(self):
            calls.append({"closed": True})

    class FakeChromium:
        def launch_persistent_context(self, **kwargs):
            calls.append(kwargs)
            return FakeContext()

    class FakeRuntime:
        chromium = FakeChromium()

        def start(self):
            return self

        def stop(self):
            calls.append({"stopped": True})

    session = PlaywrightPersistentSession(
        profile_dir=profile,
        login_url="https://portal.example.test/login",
        probe_url="https://portal.example.test/invoices",
        allowed_hosts=frozenset({"portal.example.test"}),
        probe_callback=lambda page: True,
        discover_callback=lambda page: [],
        download_callback=lambda page, candidate, destination: None,
        playwright_factory=lambda: FakeRuntime(),
    )
    assert session.probe() is True
    assert calls[0]["headless"] is False
    assert calls[0]["user_data_dir"] == str(profile)
    session.close()
    assert not profile.with_name("fixture.lock").exists()


def test_playwright_download_helper_uses_expect_download_and_save_as(tmp_path: Path) -> None:
    calls: list[str] = []

    class Download:
        def save_as(self, destination: str) -> None:
            calls.append(destination)

    class DownloadInfo:
        value = Download()

    class Page:
        def expect_download(self):
            class Context:
                def __enter__(self):
                    return DownloadInfo()

                def __exit__(self, exc_type, exc, traceback):
                    return False

            return Context()

    destination = tmp_path / "invoice.pdf"
    PlaywrightPersistentSession.save_download(Page(), lambda: calls.append("trigger"), destination)
    assert calls == ["trigger", str(destination)]
