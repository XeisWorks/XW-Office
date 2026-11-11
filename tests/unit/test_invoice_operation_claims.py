from __future__ import annotations

import json

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from xw_office.models.base import Base
from xw_office.models.settings_kv import SettingKV
from xw_office.repositories.settings_kv import SettingKvRepository
from xw_office.services.products.catalog import Product, ProductCatalogService
from xw_office.services.products.print_decision import PieceBlock, PrintDecisionEngine
from xw_office.services.invoice_processing.operation_claims import InvoiceOperationClaimStore
from xw_office.services.invoice_processing.service import InvoiceProcessingService
from scripts.invoice_processing.reconcile_claim import build_parser, run_command


def _repository() -> SettingKvRepository:
    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(engine, tables=[SettingKV.__table__])
    factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False, future=True)
    return SettingKvRepository(factory)


def test_claim_is_shared_between_store_instances_and_blocks_replay() -> None:
    repository = _repository()
    first_store = InvoiceOperationClaimStore(repository)
    claim = first_store.acquire("invoice-1", "invoice_mail")
    assert claim.acquired is True
    assert claim.state == "running"

    second_store = InvoiceOperationClaimStore(repository)
    competing = second_store.acquire("invoice-1", "invoice_mail")
    assert competing.acquired is False
    assert competing.operation_id == claim.operation_id

    assert first_store.finish(claim, "succeeded") is True
    replay = second_store.acquire("invoice-1", "invoice_mail")
    assert replay.acquired is False
    assert replay.state == "succeeded"


def test_failed_claim_can_retry_with_the_same_operation_id() -> None:
    repository = _repository()
    store = InvoiceOperationClaimStore(repository)
    claim = store.acquire("invoice-2", "invoice_mail")
    assert store.finish(claim, "failed", error="confirmed unsent") is True

    retry = InvoiceOperationClaimStore(repository).acquire("invoice-2", "invoice_mail")

    assert retry.acquired is True
    assert retry.operation_id == claim.operation_id


def test_unknown_claim_blocks_automatic_retry() -> None:
    repository = _repository()
    store = InvoiceOperationClaimStore(repository)
    claim = store.acquire("invoice-3", "invoice_mail")
    assert store.finish(claim, "unknown", error="sevDesk readback timeout") is True

    retry = InvoiceOperationClaimStore(repository).acquire("invoice-3", "invoice_mail")

    assert retry.acquired is False
    assert retry.state == "unknown"


def test_unknown_claims_can_be_listed_and_reconciled_with_audited_evidence() -> None:
    repository = _repository()
    store = InvoiceOperationClaimStore(repository)
    first = store.acquire("invoice-unknown", "invoice_mail")
    assert store.finish(first, "unknown", error="mail readback timeout") is True
    known = store.acquire("invoice-known", "invoice_mail")
    assert store.finish(known, "succeeded") is True

    unknown = store.list_unknown()
    assert [(claim.invoice_id, claim.operation, claim.operation_id) for claim in unknown] == [
        ("invoice-unknown", "invoice_mail", first.operation_id)
    ]
    reconciled = store.reconcile_unknown(
        "invoice-unknown",
        "invoice_mail",
        first.operation_id,
        "succeeded",
        reconciled_by="operator@example.test",
        evidence="sevDesk readback confirms sent mail",
    )

    assert reconciled.state == "succeeded"
    assert reconciled.error == "mail readback timeout"
    assert store.list_unknown() == []
    assert InvoiceOperationClaimStore(repository).acquire(
        "invoice-unknown", "invoice_mail"
    ).state == "succeeded"
    raw = repository.get_value_json(store._key("invoice-unknown", "invoice_mail"))
    assert raw is not None
    payload = json.loads(raw)
    history = json.loads(payload["reconciliation_history"])
    assert history[0]["state"] == "succeeded"
    assert history[0]["reconciled_by"] == "operator@example.test"
    assert history[0]["evidence"] == "sevDesk readback confirms sent mail"
    assert payload["reconciled_at"] == history[0]["reconciled_at"]


def test_unknown_claim_listing_splits_ids_from_the_last_key_separator() -> None:
    store = InvoiceOperationClaimStore(_repository())
    claim = store.acquire("external:invoice-42", "invoice_mail")
    assert store.finish(claim, "unknown", error="readback unavailable") is True

    listed = store.list_unknown()

    assert len(listed) == 1
    assert listed[0].invoice_id == "external:invoice-42"
    assert listed[0].operation == "invoice_mail"


def test_unknown_claim_reconciliation_requires_exact_current_operation_id() -> None:
    repository = _repository()
    store = InvoiceOperationClaimStore(repository)
    claim = store.acquire("invoice-reconcile-id", "credit_note_mail")
    assert store.finish(claim, "unknown", error="timeout") is True

    try:
        store.reconcile_unknown(
            claim.invoice_id,
            claim.operation,
            "stale-operation-id",
            "succeeded",
            reconciled_by="operator",
            evidence="confirmed by external record",
        )
    except ValueError as exc:
        assert "stimmt nicht" in str(exc)
    else:
        raise AssertionError("stale operation id was accepted")
    assert store.get(claim.invoice_id, claim.operation).state == "unknown"  # type: ignore[union-attr]


def test_failed_reconciliation_allows_retry_without_losing_audit_history() -> None:
    repository = _repository()
    store = InvoiceOperationClaimStore(repository)
    claim = store.acquire("invoice-reconcile-failed", "invoice_mail")
    assert store.finish(claim, "unknown", error="send result unclear") is True
    store.reconcile_unknown(
        claim.invoice_id,
        claim.operation,
        claim.operation_id,
        "failed",
        reconciled_by="operator",
        evidence="provider confirms no message was accepted",
    )

    retry = store.acquire(claim.invoice_id, claim.operation)

    assert retry.acquired is True
    assert retry.operation_id == claim.operation_id
    payload = json.loads(
        repository.get_value_json(store._key(claim.invoice_id, claim.operation)) or "{}"
    )
    assert json.loads(payload["reconciliation_history"])[0]["state"] == "failed"


def test_unknown_claim_reconciliation_rejects_replay_and_missing_evidence() -> None:
    store = InvoiceOperationClaimStore(_repository())
    claim = store.acquire("invoice-reconcile-guard", "invoice_mail")
    assert store.finish(claim, "unknown") is True
    for state, operator, evidence, expected in (
        ("succeeded", "operator", "short", "mindestens 8"),
        ("running", "operator", "external readback confirms", "Status muss"),
        ("succeeded", "", "external readback confirms", "Operator ist"),
    ):
        try:
            store.reconcile_unknown(
                claim.invoice_id,
                claim.operation,
                claim.operation_id,
                state,  # type: ignore[arg-type]
                reconciled_by=operator,
                evidence=evidence,
            )
        except ValueError as exc:
            assert expected in str(exc)
        else:
            raise AssertionError(f"invalid reconciliation was accepted: {expected}")

    store.reconcile_unknown(
        claim.invoice_id,
        claim.operation,
        claim.operation_id,
        "succeeded",
        reconciled_by="operator",
        evidence="external readback confirms success",
    )
    try:
        store.reconcile_unknown(
            claim.invoice_id,
            claim.operation,
            claim.operation_id,
            "failed",
            reconciled_by="operator",
            evidence="external readback confirms failure",
        )
    except ValueError as exc:
        assert "Nur ein unknown" in str(exc)
    else:
        raise AssertionError("reconciliation replay was accepted")


def test_reconcile_cli_lists_unknown_and_requires_explicit_matching_confirmation(
    capsys,
) -> None:
    repository = _repository()
    store = InvoiceOperationClaimStore(repository)
    claim = store.acquire("invoice-cli", "invoice_mail")
    assert store.finish(claim, "unknown", error="provider readback timeout") is True
    parser = build_parser()

    listing = parser.parse_args(["list-unknown"])
    assert run_command(listing, repository) == 0
    assert claim.invoice_id in capsys.readouterr().out

    mismatched = parser.parse_args(
        [
            "reconcile",
            "--invoice-id",
            claim.invoice_id,
            "--operation",
            claim.operation,
            "--operation-id",
            claim.operation_id,
            "--state",
            "failed",
            "--reconciled-by",
            "operator",
            "--evidence",
            "provider confirms message was not accepted",
            "--confirm-operation-id",
            "different-id",
        ]
    )
    try:
        run_command(mismatched, repository)
    except ValueError as exc:
        assert "muss exakt" in str(exc)
    else:
        raise AssertionError("CLI accepted mismatched confirmation id")
    assert store.get(claim.invoice_id, claim.operation).state == "unknown"  # type: ignore[union-attr]


def test_new_print_run_uses_new_id_after_success_but_serializes_other_workstations() -> None:
    repository = _repository()
    first_store = InvoiceOperationClaimStore(repository)
    first = first_store.acquire_new_run("part-1", "physical_product_print")
    assert first.acquired is True

    competing = InvoiceOperationClaimStore(repository).acquire_new_run(
        "part-1", "physical_product_print"
    )
    assert competing.acquired is False
    assert competing.state == "running"

    assert first_store.finish(first, "succeeded") is True
    deliberate_reprint = InvoiceOperationClaimStore(repository).acquire_new_run(
        "part-1", "physical_product_print"
    )
    assert deliberate_reprint.acquired is True
    assert deliberate_reprint.operation_id != first.operation_id
    assert first_store.finish(deliberate_reprint, "succeeded") is True


def test_unknown_print_run_requires_manual_reconciliation() -> None:
    repository = _repository()
    store = InvoiceOperationClaimStore(repository)
    claim = store.acquire_new_run("part-2", "physical_product_print")
    assert store.finish(claim, "unknown", error="printer result uncertain") is True

    retry = InvoiceOperationClaimStore(repository).acquire_new_run(
        "part-2", "physical_product_print"
    )

    assert retry.acquired is False
    assert retry.state == "unknown"


def test_print_decision_engine_persists_product_print_claims() -> None:
    repository = _repository()

    class PartClient:
        def get_part_stock(self, _part_id: str) -> int:
            return 0

        def set_part_stock(self, _part_id: str, _stock: int) -> None:
            return None

        def find_part_by_sku(self, _sku: str):
            return None

    piece = PieceBlock(
        sku="XW-1",
        name="Testprodukt",
        qty_needed=1,
        product=Product(
            id="product-1", sku="XW-1", name="Testprodukt", sevdesk_part_id="part-1"
        ),
    )
    engine = PrintDecisionEngine(
        ProductCatalogService(), PartClient(), settings_repo=repository  # type: ignore[arg-type]
    )
    second_engine = PrintDecisionEngine(
        ProductCatalogService(), PartClient(), settings_repo=repository  # type: ignore[arg-type]
    )

    first = engine.acquire_product_print_claim(piece)
    competing = second_engine.acquire_product_print_claim(piece)
    assert first.acquired is True
    assert competing.acquired is False

    assert engine.finish_product_print_claim(first, "succeeded") is True
    deliberate_reprint = second_engine.acquire_product_print_claim(piece)
    assert deliberate_reprint.acquired is True
    assert deliberate_reprint.operation_id != first.operation_id


def test_credit_note_mail_claim_blocks_duplicate_after_success() -> None:
    repository = _repository()
    service = InvoiceProcessingService.__new__(InvoiceProcessingService)
    service._operation_claims = InvoiceOperationClaimStore(repository)

    class Mailer:
        calls = 0

        def send_mail(self, **kwargs: object) -> None:
            self.calls += 1
            attachment = kwargs["attachments"]
            assert attachment[0].content == b"pdf"  # type: ignore[index,union-attr]

        @staticmethod
        def plain_text_to_html(value: str) -> str:
            return value

    mailer = Mailer()
    service._mail_service = mailer
    kwargs = {
        "recipient": "customer@example.test",
        "credit_note_number": "G-100",
        "subject": "Gutschrift",
        "text_body": "Hallo",
        "pdf_bytes": b"pdf",
    }
    service.send_credit_note_mail("credit-100", **kwargs)

    try:
        service.send_credit_note_mail("credit-100", **kwargs)
    except RuntimeError as exc:
        assert "bereits beansprucht" in str(exc)
    else:
        raise AssertionError("duplicate credit-note mail was allowed")
    assert mailer.calls == 1


def test_unclear_credit_note_mail_result_blocks_retry() -> None:
    repository = _repository()
    service = InvoiceProcessingService.__new__(InvoiceProcessingService)
    service._operation_claims = InvoiceOperationClaimStore(repository)

    class Mailer:
        calls = 0

        def send_mail(self, **_kwargs: object) -> None:
            self.calls += 1
            raise TimeoutError("transport timed out after submission")

        @staticmethod
        def plain_text_to_html(value: str) -> str:
            return value

    mailer = Mailer()
    service._mail_service = mailer
    kwargs = {
        "recipient": "customer@example.test",
        "credit_note_number": "G-101",
        "subject": "Gutschrift",
        "text_body": "Hallo",
        "pdf_bytes": b"pdf",
    }
    for expected in ("unklar", "bereits beansprucht"):
        try:
            service.send_credit_note_mail("credit-101", **kwargs)
        except RuntimeError as exc:
            assert expected in str(exc)
        else:
            raise AssertionError("unclear credit-note mail result was retried")
    assert mailer.calls == 1

