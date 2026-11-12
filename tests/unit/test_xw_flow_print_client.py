from __future__ import annotations

import httpx
import pytest

from xw_office.core.config import AppConfig, FlowShippingApiSection
from xw_office.services.drucke.xw_flow_client import XwFlowPrintClient


class _Secrets:
    def get_secret(self, _key: str) -> str:
        return "bridge-secret"


def _client(payload: object, monkeypatch: pytest.MonkeyPatch) -> XwFlowPrintClient:
    original_client = httpx.Client

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=payload)

    transport = httpx.MockTransport(handler)

    def make_client(*args: object, **kwargs: object) -> httpx.Client:
        return original_client(*args, **kwargs, transport=transport)

    monkeypatch.setattr(httpx, "Client", make_client)
    config = AppConfig(
        flow_shipping_api=FlowShippingApiSection(base_url="https://flow.example")
    )
    return XwFlowPrintClient(config, _Secrets())  # type: ignore[arg-type]


def test_fetch_open_cases_filters_invalid_rows_and_attachments(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = _client(
        {
            "cases": [
                {
                    "id": " print-1 ",
                    "attachments": [{"id": "file-1", "name": "score.pdf"}, "bad-row"],
                },
                {"id": " "},
                None,
            ]
        },
        monkeypatch,
    )

    cases = client.fetch_open_cases()

    assert len(cases) == 1
    assert cases[0].id == "print-1"
    assert cases[0].title == "Neuer Druckauftrag"
    assert cases[0].attachments == [{"id": "file-1", "name": "score.pdf"}]


def test_fetch_open_cases_rejects_missing_or_null_cases(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = _client({"cases": None}, monkeypatch)

    with pytest.raises(TypeError, match="Druckantwort"):
        client.fetch_open_cases()


def test_fetch_completed_email_ids_rejects_missing_or_null_list(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = _client({"client_request_ids": None}, monkeypatch)

    with pytest.raises(TypeError, match="Abschlussantwort"):
        client.fetch_completed_email_request_ids()


def test_fetch_completed_email_ids_normalizes_values(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = _client({"client_request_ids": [" req-1 ", "", 7]}, monkeypatch)

    assert client.fetch_completed_email_request_ids() == {"req-1", "7"}
