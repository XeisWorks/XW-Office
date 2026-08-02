"""UVA SOAP backend mocks (no network)."""
from __future__ import annotations

import pytest

from xw_office.core.config import AppConfig, FinanzOnlineSection
from xw_office.services.finanzonline.client import FinanzOnlineClient
from xw_office.services.finanzonline.monthly_snapshot import TaxMonthlySnapshotStore
from xw_office.services.finanzonline.u13_xml import build_u13_xml, validate_u13_xml
from xw_office.services.finanzonline.u30_xml import build_u30_xml, validate_u30_xml
from xw_office.services.finanzonline.uva_models import UvaKennzahlen, UvaPayloadResult
from xw_office.services.finanzonline.uva_service import UvaService, build_uva_zm_reconciliation
from xw_office.services.finanzonline.uva_soap import (
    FinanzOnlineFileUploadBackend,
    MockUvaSoapBackend,
    UvaSoapUnavailableError,
    UvaSubmitResult,
    ZeepUvaSoapBackend,
)
from xw_office.services.finanzonline.zm_service import ZmCalculationResult, ZmRow


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


class _SessionServiceStub:
    def __init__(self, recorder: list[tuple[str, dict[str, object]]]) -> None:
        self._recorder = recorder

    def login(self, **kwargs: object) -> dict[str, object]:
        self._recorder.append(("login", dict(kwargs)))
        return {"id": "SESSION1234", "rc": 0, "msg": "login ok"}

    def logout(self, **kwargs: object) -> dict[str, object]:
        self._recorder.append(("logout", dict(kwargs)))
        return {"rc": 0, "msg": "logout ok"}


class _UploadServiceStub:
    def __init__(self, recorder: list[tuple[str, dict[str, object]]]) -> None:
        self._recorder = recorder

    def upload(self, **kwargs: object) -> dict[str, object]:
        self._recorder.append(("upload", dict(kwargs)))
        return {"rc": 0, "msg": "upload ok"}


class _FonClientStub:
    def __init__(self, service: object) -> None:
        self.service = service


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


class _ZmServiceStub:
    def calculate_month(self, year: int, month: int):
        assert (year, month) == (2026, 3)
        return type(
            "ZmCalc",
            (),
            {
                "rows": [ZmRow(uid="DE123456789", amount_eur_int=124, kind="service")],
                "invalid": [],
                "warnings": [],
            },
        )()

    def render_preview_text(self, _result: object) -> str:
        return "ZM preview"


class _ZmServiceWithCounter:
    def __init__(self) -> None:
        self.calls = 0

    def calculate_month(self, year: int, month: int) -> ZmCalculationResult:
        assert (year, month) == (2026, 3)
        self.calls += 1
        return ZmCalculationResult(
            year=year,
            month=month,
            rows=[ZmRow(uid="DE123456789", amount_eur_int=124, kind="service")],
        )

    def render_preview_text(self, _result: object) -> str:
        return "ZM preview"


class _BlockingZmService:
    def calculate_month(self, year: int, month: int) -> ZmCalculationResult:
        assert (year, month) == (2026, 3)
        return ZmCalculationResult(
            year=year,
            month=month,
            invalid=["ungueltige/fehlende UID: Test"],
        )

    def render_preview_text(self, _result: object) -> str:
        return "ZM blocked"


class _PreviewResultStub:
    year = 2026
    month = 3
    warnings: list[str] = []

    def model_dump(self) -> dict[str, object]:
        return {"year": self.year, "month": self.month}


class _PreviewServiceWithCounter:
    def __init__(self) -> None:
        self.calls = 0

    def build_preview(self, year: int, month: int) -> _PreviewResultStub:
        assert (year, month) == (2026, 3)
        self.calls += 1
        return _PreviewResultStub()

    def render_preview_text(self, _preview: _PreviewResultStub) -> str:
        return "preview"


class _PayloadServiceWithPreviewCounter:
    def __init__(self) -> None:
        self.from_preview_calls = 0
        self.direct_calls = 0

    def build_payload_from_preview(self, preview: _PreviewResultStub) -> UvaPayloadResult:
        self.from_preview_calls += 1
        return UvaPayloadResult(
            year=preview.year,
            month=preview.month,
            kennzahlen=UvaKennzahlen(A000="123.45", A029="100.00", C060="10.00"),
            zahlbetrag="90.00",
            warnings=["cached-warning"],
        )

    def build_payload(self, year: int, month: int) -> UvaPayloadResult:
        assert (year, month) == (2026, 3)
        self.direct_calls += 1
        return UvaPayloadResult(
            year=year,
            month=month,
            kennzahlen=UvaKennzahlen(A000="999.99"),
            zahlbetrag="999.99",
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


def test_u30_xml_validates_against_legacy_xsd() -> None:
    xml = build_u30_xml(
        {
            "jahr": 2026,
            "monat": 5,
            "kennzahlen": {
                "KZ000": "12750.60",
                "KZ022": "118.83",
                "KZ029": "3363.40",
                "KZ006": "6269.60",
                "KZ060": "209.22",
            },
        },
        fastnr="989999999",
    )

    validate_u30_xml(xml)

    assert "<ERKLAERUNG art=\"U30\">" in xml
    assert "<FASTNR>989999999</FASTNR>" in xml
    assert "<KZ000 type=\"kz\">12750.60</KZ000>" in xml


def test_u13_xml_validates_against_legacy_xsd() -> None:
    xml = build_u13_xml(
        year=2026,
        month=5,
        rows=[
            ZmRow(uid="DE123456789", amount_eur_int=124, kind="service"),
            ZmRow(uid="IT12345678901", amount_eur_int=200, kind="delivery"),
        ],
        fastnr="989999999",
        kundeninfo="XW-Office ZM 2026-05",
    )

    validate_u13_xml(xml)

    assert "<ERKLAERUNG art=\"U13\">" in xml
    assert "<ANBRINGEN>U13</ANBRINGEN>" in xml
    assert "<SOLEI>J</SOLEI>" in xml
    assert "<UID_MS>IT12345678901</UID_MS>" in xml


def test_fileupload_backend_logs_in_uploads_and_logs_out() -> None:
    calls: list[tuple[str, dict[str, object]]] = []

    def factory(wsdl: str) -> _FonClientStub:
        if "session" in wsdl:
            return _FonClientStub(_SessionServiceStub(calls))
        return _FonClientStub(_UploadServiceStub(calls))

    backend = FinanzOnlineFileUploadBackend(
        session_wsdl_url="session.wsdl",
        upload_wsdl_url="fileupload.wsdl",
        tid="123456789012",
        benid="BENID1",
        pin="secret1",
        hersteller_id="ATU12345678",
        fastnr="989999999",
        test_mode=True,
        client_factory=factory,
    )

    result = backend.submit_uva(
        {
            "meldung": "U30",
            "jahr": 2026,
            "monat": 5,
            "kennzahlen": {"KZ000": "100.00", "KZ022": "100.00", "KZ060": "5.00"},
        }
    )

    assert result.ok is True
    assert result.test_mode is True
    assert result.xml_validated is True
    assert [name for name, _ in calls] == ["login", "upload", "logout"]
    upload = calls[1][1]
    assert upload["art"] == "U30"
    assert upload["uebermittlung"] == "T"
    assert "<KZ022 type=\"kz\">100.00</KZ022>" in str(upload["data"])


def test_fileupload_backend_uploads_u13_zm() -> None:
    calls: list[tuple[str, dict[str, object]]] = []

    def factory(wsdl: str) -> _FonClientStub:
        if "session" in wsdl:
            return _FonClientStub(_SessionServiceStub(calls))
        return _FonClientStub(_UploadServiceStub(calls))

    backend = FinanzOnlineFileUploadBackend(
        session_wsdl_url="session.wsdl",
        upload_wsdl_url="fileupload.wsdl",
        tid="123456789012",
        benid="BENID1",
        pin="secret1",
        hersteller_id="ATU12345678",
        fastnr="989999999",
        test_mode=True,
        client_factory=factory,
    )

    result = backend.submit_zm(
        {
            "meldung": "U13",
            "jahr": 2026,
            "monat": 5,
            "rows": [ZmRow(uid="DE123456789", amount_eur_int=124, kind="service").model_dump()],
        }
    )

    assert result.ok is True
    assert [name for name, _ in calls] == ["login", "upload", "logout"]
    upload = calls[1][1]
    assert upload["art"] == "U13"
    assert "<SOLEI>J</SOLEI>" in str(upload["data"])


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


def test_finanzonline_client_uses_fileupload_backend_with_submission_credentials() -> None:
    secrets = _SecretsStub(
        {
            "FON_TEILNEHMER_ID": "123456789012",
            "FON_BENUTZER_ID": "BENID1",
            "FON_PIN": "secret1",
            "FINANZONLINE_UID": "ATU12345678",
            "FON_STEUERNUMMER": "989999999",
        }
    )

    client = FinanzOnlineClient(AppConfig(), secret_service=secrets)  # type: ignore[arg-type]

    assert client.backend_mode() == "fileupload/test"
    assert client.has_submission_credentials() is True
    assert client.fastnr() == "989999999"


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


def test_uva_service_submit_month_sends_zm_after_successful_u30() -> None:
    mock = MockUvaSoapBackend()
    client = FinanzOnlineClient(AppConfig(), uva_backend=mock)
    service = UvaService(
        AppConfig(),
        client,
        payload_service=_PayloadServiceStub(),  # type: ignore[arg-type]
        zm_service=_ZmServiceStub(),  # type: ignore[arg-type]
    )

    result = service.submit_month(2026, 3)

    assert result.ok is True
    assert result.zm_ok is True
    assert [call["meldung"] for call in mock.calls] == ["U30", "U13"]
    assert mock.calls[-1]["rows"][0]["kind"] == "service"


def test_uva_service_reuses_month_calculation_for_submission_payload() -> None:
    mock = MockUvaSoapBackend()
    client = FinanzOnlineClient(AppConfig(), uva_backend=mock)
    preview_service = _PreviewServiceWithCounter()
    payload_service = _PayloadServiceWithPreviewCounter()
    service = UvaService(
        AppConfig(),
        client,
        preview_service=preview_service,  # type: ignore[arg-type]
        payload_service=payload_service,  # type: ignore[arg-type]
    )

    preview_payload = service.calculate_month(2026, 3)
    submission_payload = service.build_submission_payload(2026, 3)
    cached_payload = service.calculate_month(2026, 3)

    assert preview_payload["zahlbetrag"] == "90.00"
    assert submission_payload["zahlbetrag"] == "90.00"
    assert submission_payload["kennzahlen"]["KZ000"] == "123.45"
    assert cached_payload["cache"]["hit"] is True
    assert preview_service.calls == 1
    assert payload_service.from_preview_calls == 1
    assert payload_service.direct_calls == 0


def test_uva_service_reuses_cached_zm_for_submit_after_preview() -> None:
    mock = MockUvaSoapBackend()
    client = FinanzOnlineClient(AppConfig(), uva_backend=mock)
    preview_service = _PreviewServiceWithCounter()
    payload_service = _PayloadServiceWithPreviewCounter()
    zm_service = _ZmServiceWithCounter()
    service = UvaService(
        AppConfig(),
        client,
        preview_service=preview_service,  # type: ignore[arg-type]
        payload_service=payload_service,  # type: ignore[arg-type]
        zm_service=zm_service,  # type: ignore[arg-type]
    )

    service.calculate_month(2026, 3)
    result = service.submit_month(2026, 3)

    assert result.ok is True
    assert [call["meldung"] for call in mock.calls] == ["U30", "U13"]
    assert zm_service.calls == 1


def test_uva_service_blocks_submission_when_data_quality_blocks() -> None:
    mock = MockUvaSoapBackend()
    client = FinanzOnlineClient(AppConfig(), uva_backend=mock)
    service = UvaService(
        AppConfig(),
        client,
        preview_service=_PreviewServiceWithCounter(),  # type: ignore[arg-type]
        payload_service=_PayloadServiceWithPreviewCounter(),  # type: ignore[arg-type]
        zm_service=_BlockingZmService(),  # type: ignore[arg-type]
    )

    result = service.submit_month(2026, 3)

    assert result.ok is False
    assert "Datenqualitaet blockiert" in result.message
    assert mock.calls == []


class _JunePreviewResultStub(_PreviewResultStub):
    year = 2026
    month = 6


class _JunePreviewServiceWithCounter(_PreviewServiceWithCounter):
    def build_preview(self, year: int, month: int) -> _JunePreviewResultStub:
        assert (year, month) == (2026, 6)
        self.calls += 1
        return _JunePreviewResultStub()


class _JuneOffReferencePayloadService(_PayloadServiceWithPreviewCounter):
    def build_payload_from_preview(self, preview: _PreviewResultStub) -> UvaPayloadResult:
        self.from_preview_calls += 1
        return UvaPayloadResult(
            year=preview.year,
            month=preview.month,
            kennzahlen=UvaKennzahlen(A000="1.00"),
            zahlbetrag="1.00",
            warnings=[],
        )


def test_uva_service_blocks_submission_when_golden_master_delta_is_too_large() -> None:
    mock = MockUvaSoapBackend()
    client = FinanzOnlineClient(AppConfig(), uva_backend=mock)
    service = UvaService(
        AppConfig(),
        client,
        preview_service=_JunePreviewServiceWithCounter(),  # type: ignore[arg-type]
        payload_service=_JuneOffReferencePayloadService(),  # type: ignore[arg-type]
    )

    result = service.submit_month(2026, 6)

    assert result.ok is False
    assert "Golden-Master-Abweichung" in result.message
    assert mock.calls == []


def test_uva_service_reuses_persistent_month_snapshot(tmp_path) -> None:
    store = TaxMonthlySnapshotStore(tmp_path / "tax.sqlite")
    mock = MockUvaSoapBackend()
    client = FinanzOnlineClient(AppConfig(), uva_backend=mock)
    first_preview = _PreviewServiceWithCounter()
    first_payload_service = _PayloadServiceWithPreviewCounter()
    first_service = UvaService(
        AppConfig(),
        client,
        preview_service=first_preview,  # type: ignore[arg-type]
        payload_service=first_payload_service,  # type: ignore[arg-type]
        snapshot_store=store,
    )

    first = first_service.calculate_month(2026, 3)

    second_preview = _PreviewServiceWithCounter()
    second_payload_service = _PayloadServiceWithPreviewCounter()
    second_service = UvaService(
        AppConfig(),
        client,
        preview_service=second_preview,  # type: ignore[arg-type]
        payload_service=second_payload_service,  # type: ignore[arg-type]
        snapshot_store=store,
    )
    second = second_service.calculate_month(2026, 3)

    assert first["cache"]["source"] == "live"
    assert second["cache"]["source"] == "persistent"
    assert second["zahlbetrag"] == "90.00"
    assert second_preview.calls == 0
    assert second_payload_service.from_preview_calls == 0


def test_uva_service_refresh_bypasses_persistent_snapshot(tmp_path) -> None:
    store = TaxMonthlySnapshotStore(tmp_path / "tax.sqlite")
    mock = MockUvaSoapBackend()
    client = FinanzOnlineClient(AppConfig(), uva_backend=mock)
    preview_service = _PreviewServiceWithCounter()
    payload_service = _PayloadServiceWithPreviewCounter()
    service = UvaService(
        AppConfig(),
        client,
        preview_service=preview_service,  # type: ignore[arg-type]
        payload_service=payload_service,  # type: ignore[arg-type]
        snapshot_store=store,
    )

    service.calculate_month(2026, 3)
    refreshed = service.calculate_month(2026, 3, refresh=True)

    assert refreshed["cache"]["source"] == "live"
    assert preview_service.calls == 2
    assert payload_service.from_preview_calls == 2


def test_uva_service_ignores_outdated_persistent_snapshot(tmp_path) -> None:
    store = TaxMonthlySnapshotStore(tmp_path / "tax.sqlite")
    store.put_snapshot(2026, 3, {"jahr": 2026, "monat": 3, "zahlbetrag": "1.00"})
    mock = MockUvaSoapBackend()
    client = FinanzOnlineClient(AppConfig(), uva_backend=mock)
    preview_service = _PreviewServiceWithCounter()
    payload_service = _PayloadServiceWithPreviewCounter()
    service = UvaService(
        AppConfig(),
        client,
        preview_service=preview_service,  # type: ignore[arg-type]
        payload_service=payload_service,  # type: ignore[arg-type]
        snapshot_store=store,
    )

    payload = service.calculate_month(2026, 3)

    assert payload["zahlbetrag"] == "90.00"
    assert payload["cache"]["source"] == "live"
    assert preview_service.calls == 1


def test_uva_zm_reconciliation_explains_period_differences() -> None:
    payload = {
        "jahr": 2026,
        "monat": 6,
        "kennzahlen": {"A017": "3668.46", "A021": "147.60"},
        "zm": {
            "rows": [
                {"uid": "DE123456789", "amount_eur_int": 2399, "kind": "delivery"},
                {"uid": "IT12345678901", "amount_eur_int": 120, "kind": "service"},
            ]
        },
    }

    reconciliation = build_uva_zm_reconciliation(payload)

    assert reconciliation["period"] == "2026-06"
    assert reconciliation["delivery_delta"] == "1269.46"
    assert reconciliation["service_delta"] == "27.60"
    assert any("IST" in note and "Soll" in note for note in reconciliation["notes"])


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
