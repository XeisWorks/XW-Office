"""UVA SOAP backend mocks (no network)."""
from __future__ import annotations

import pytest

from xw_studio.core.config import AppConfig, FinanzOnlineSection
from xw_studio.services.finanzonline.client import FinanzOnlineClient
from xw_studio.services.finanzonline.uva_models import UvaKennzahlen, UvaPayloadResult
from xw_studio.services.finanzonline.uva_service import UvaService
from xw_studio.services.finanzonline.uva_soap import (
    MockUvaSoapBackend,
    UvaSoapUnavailableError,
    UvaSubmitResult,
    ZeepUvaSoapBackend,
)


def test_unconfigured_client_raises() -> None:
    client = FinanzOnlineClient(AppConfig())
    with pytest.raises(UvaSoapUnavailableError):
        client.submit_uva({"jahr": 2026, "monat": 1})


def test_mock_backend_returns_result() -> None:
    mock = MockUvaSoapBackend()
    client = FinanzOnlineClient(AppConfig(), uva_backend=mock)
    out = client.submit_uva({"jahr": 2026, "monat": 3})
    assert out.ok is True
    assert out.reference_id == "MOCK-REF-001"
    assert len(mock.calls) == 1
    assert mock.calls[0]["jahr"] == 2026


def test_uva_service_uses_injected_client() -> None:
    mock = MockUvaSoapBackend(
        result=UvaSubmitResult(ok=True, reference_id="X-9", message="ok"),
    )
    client = FinanzOnlineClient(AppConfig(), uva_backend=mock)
    svc = UvaService(AppConfig(), client)
    got = svc.submit_uva({"a": 1})
    assert got.reference_id == "X-9"


def test_mock_can_raise() -> None:
    err = ValueError("SOAP fault (test)")
    mock = MockUvaSoapBackend(error=err)
    client = FinanzOnlineClient(AppConfig(), uva_backend=mock)
    with pytest.raises(ValueError, match="SOAP fault"):
        client.submit_uva({})


class _ZeepServiceStub:
    def submitUva(self, *, payload: dict[str, object], teilnehmer_id: str, benutzer_id: str, pin: str) -> dict[str, object]:
        _ = (teilnehmer_id, benutzer_id, pin)
        return {
            "ok": True,
            "reference_id": "LIVE-REF-1",
            "message": f"accepted {payload.get('monat')}",
        }


class _ZeepClientStub:
    def __init__(self, _wsdl: str) -> None:
        self.service = _ZeepServiceStub()


class _SecretsStub:
    def __init__(self, values: dict[str, str]) -> None:
        self._values = values

    def get_secret(self, key: str) -> str:
        return self._values.get(key, "")


class _PayloadServiceStub:
    def build_payload(self, year: int, month: int) -> UvaPayloadResult:
        assert (year, month) == (2026, 3)
        return UvaPayloadResult(
            year=year,
            month=month,
            kennzahlen=UvaKennzahlen(A000="123.45", A029="100.00", C060="10.00"),
            zahlbetrag="0.00",
            warnings=[],
        )

    def render_kennzahlen_text(self, payload: UvaPayloadResult) -> str:
        return f"KZ000={payload.kennzahlen.A000}"


def test_zeep_backend_calls_operation() -> None:
    backend = ZeepUvaSoapBackend(
        wsdl_url="https://fon.example/wsdl",
        operation_name="submitUva",
        static_kwargs={"teilnehmer_id": "T", "benutzer_id": "B", "pin": "P"},
        client_factory=lambda wsdl: _ZeepClientStub(wsdl),
    )

    out = backend.submit_uva({"jahr": 2026, "monat": 4})

    assert out.ok is True
    assert out.reference_id == "LIVE-REF-1"


def test_finanzonline_client_uses_live_backend_when_wsdl_set(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("FON_SOAP_WSDL", "https://fon.example/wsdl")
    monkeypatch.setenv("FON_SOAP_OPERATION", "submitUva")
    secrets = _SecretsStub(
        {
            "FON_TEILNEHMER_ID": "T",
            "FON_BENUTZER_ID": "B",
            "FON_PIN": "P",
        }
    )

    client = FinanzOnlineClient(AppConfig(), secret_service=secrets)  # type: ignore[arg-type]

    assert client.backend_mode().startswith("live")


def test_uva_service_builds_submission_payload_from_kennzahlen() -> None:
    mock = MockUvaSoapBackend()
    client = FinanzOnlineClient(AppConfig(), uva_backend=mock)
    service = UvaService(AppConfig(), client, payload_service=_PayloadServiceStub())  # type: ignore[arg-type]

    payload = service.build_submission_payload(2026, 3)

    assert payload["jahr"] == 2026
    assert payload["monat"] == 3
    assert payload["meldung"] == "U30"
    assert payload["kennzahlen"]["KZ000"] == "123.45"


def test_uva_service_describes_single_cash_basis_calculation() -> None:
    mock = MockUvaSoapBackend()
    client = FinanzOnlineClient(AppConfig(), uva_backend=mock)
    service = UvaService(AppConfig(), client, payload_service=_PayloadServiceStub())  # type: ignore[arg-type]

    text = service.describe_capabilities()

    assert "IST-Monatsberechnung" in text
    assert "Aggregator" in text
    assert "Phase-1/2" not in text


def test_uva_service_submit_month_uses_built_submission_payload() -> None:
    mock = MockUvaSoapBackend()
    client = FinanzOnlineClient(AppConfig(), uva_backend=mock)
    service = UvaService(AppConfig(), client, payload_service=_PayloadServiceStub())  # type: ignore[arg-type]

    result = service.submit_month(2026, 3)

    assert result.ok is True
    assert mock.calls[-1]["meldung"] == "U30"
    assert mock.calls[-1]["kennzahlen"]["KZ000"] == "123.45"


def test_finanzonline_client_uses_configured_wsdl_without_env() -> None:
    cfg = AppConfig(
        finanzonline=FinanzOnlineSection(
            wsdl_url="https://fon.example/config.wsdl",
            operation_name="submitUva",
            test_mode=True,
        )
    )
    secrets = _SecretsStub(
        {
            "FON_TEILNEHMER_ID": "T",
            "FON_BENUTZER_ID": "B",
            "FON_PIN": "P",
        }
    )

    client = FinanzOnlineClient(cfg, secret_service=secrets)  # type: ignore[arg-type]

    assert client.backend_mode().startswith("live")
    assert client.participant_id() == "T"


def test_zeep_backend_wraps_runtime_faults() -> None:
    class _FaultyService:
        def submitUva(self, **_: object) -> object:
            raise RuntimeError("SOAP endpoint unavailable")

    class _FaultyClient:
        def __init__(self, _wsdl: str) -> None:
            self.service = _FaultyService()

    backend = ZeepUvaSoapBackend(
        wsdl_url="https://fon.example/wsdl",
        operation_name="submitUva",
        static_kwargs={"teilnehmer_id": "T", "benutzer_id": "B", "pin": "P"},
        client_factory=lambda wsdl: _FaultyClient(wsdl),
    )

    out = backend.submit_uva({"jahr": 2026, "monat": 4})

    assert out.ok is False
    assert "SOAP endpoint unavailable" in out.message
