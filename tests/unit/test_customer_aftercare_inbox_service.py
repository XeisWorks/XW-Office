"""Tests for the Lieferkorrektur inbox poller (spec §3) — never invoices/labels, always idempotent."""

from __future__ import annotations

from typing import Any

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from xw_office.models.base import Base
from xw_office.repositories.customer_aftercare import CustomerAftercareRepository
from xw_office.services.customer_aftercare.inbox_service import CustomerAftercareInboxService
from xw_office.repositories.customer_aftercare import CustomerAftercareItemInput
from xw_office.services.customer_aftercare.ai_classifier import AiExtractedItem


class _Secrets:
    def __init__(self, *, openai_key: str = "") -> None:
        self.values = {
            "MS_GRAPH_TENANT_ID": "tenant",
            "MS_GRAPH_CLIENT_ID": "client",
            "MS_GRAPH_MAILBOX": "shop@xeisworks.at",
            "OPENAI_API_KEY": openai_key,
        }

    def get_secret(self, key: str) -> str:
        return self.values.get(key, "")


@pytest.fixture
def session_factory() -> sessionmaker[Session]:
    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, autoflush=False, expire_on_commit=False, future=True)


def _message(
    msg_id: str, subject: str, body: str, *, sender: str = "haendler@example.test"
) -> dict[str, Any]:
    return {
        "id": msg_id,
        "subject": subject,
        "bodyPreview": body,
        "body": {"content": body, "contentType": "text"},
        "from": {"emailAddress": {"address": sender}},
        "conversationId": f"thread-{msg_id}",
    }


def test_poll_inbox_creates_pending_review_case_without_invoice_or_label(
    session_factory: sessionmaker[Session], monkeypatch: pytest.MonkeyPatch
) -> None:
    class _GraphClient:
        def __init__(self, **kwargs: Any) -> None:
            pass

        def has_silent_token(self) -> bool:
            return True

        def list_inbox_messages(self, *, days: int, top: int) -> list[dict[str, Any]]:
            return [
                _message(
                    "msg-1",
                    "Falsche Lieferung zu Bestellung 21842",
                    "Wir haben Artikel A statt B erhalten.",
                )
            ]

    monkeypatch.setattr(
        "xw_office.services.customer_aftercare.inbox_service.GraphMailClient", _GraphClient
    )

    repo = CustomerAftercareRepository(session_factory)
    service = CustomerAftercareInboxService(repo, _Secrets())

    result = service.poll_inbox(allow_interactive_auth=False)

    assert result.scanned == 1
    assert result.new_cases == 1
    assert repo.count_pending_review() == 1
    cases = repo.list_by_statuses(("PENDING_REVIEW",))
    assert len(cases) == 1
    assert cases[0].status == "PENDING_REVIEW"
    # AI-01: no sevDesk document / label is ever produced by classification alone —
    # confirmed structurally: the case has no sevdesk_invoice_id and stays PENDING_REVIEW.
    assert cases[0].sevdesk_invoice_id == ""
    assert cases[0].invoice_status == ""


def test_poll_inbox_ignores_non_candidate_mails(
    session_factory: sessionmaker[Session], monkeypatch: pytest.MonkeyPatch
) -> None:
    class _GraphClient:
        def __init__(self, **kwargs: Any) -> None:
            pass

        def has_silent_token(self) -> bool:
            return True

        def list_inbox_messages(self, *, days: int, top: int) -> list[dict[str, Any]]:
            return [_message("msg-2", "Newsletter Anmeldung", "Bitte in den Verteiler aufnehmen.")]

    monkeypatch.setattr(
        "xw_office.services.customer_aftercare.inbox_service.GraphMailClient", _GraphClient
    )

    repo = CustomerAftercareRepository(session_factory)
    service = CustomerAftercareInboxService(repo, _Secrets())

    result = service.poll_inbox(allow_interactive_auth=False)

    assert result.scanned == 0
    assert result.new_cases == 0
    assert repo.count_pending_review() == 0


def test_poll_inbox_is_idempotent_across_repeated_polls(
    session_factory: sessionmaker[Session], monkeypatch: pytest.MonkeyPatch
) -> None:
    class _GraphClient:
        def __init__(self, **kwargs: Any) -> None:
            pass

        def has_silent_token(self) -> bool:
            return True

        def list_inbox_messages(self, *, days: int, top: int) -> list[dict[str, Any]]:
            return [
                _message("msg-3", "Lieferkorrektur benoetigt", "Falsch geliefert, bitte pruefen.")
            ]

    monkeypatch.setattr(
        "xw_office.services.customer_aftercare.inbox_service.GraphMailClient", _GraphClient
    )

    repo = CustomerAftercareRepository(session_factory)
    service = CustomerAftercareInboxService(repo, _Secrets())

    first = service.poll_inbox(allow_interactive_auth=False)
    second = service.poll_inbox(allow_interactive_auth=False)

    assert first.new_cases == 1
    assert second.new_cases == 0  # IDEMP-01: same Graph message id -> no second case
    assert repo.count_pending_review() == 1


def test_ai_can_only_select_authoritative_invoice_candidates() -> None:
    candidates = [
        CustomerAftercareItemInput(
            role="ORIGINAL_CANDIDATE",
            name="Tenor Stimme",
            sku="TEN-1",
            quantity=10,
            parent_sku="CHOR-1",
            component_id="tenor",
        ),
        CustomerAftercareItemInput(
            role="ORIGINAL_CANDIDATE",
            name="Bass Stimme",
            sku="BASS-1",
            quantity=10,
            parent_sku="CHOR-1",
            component_id="bass",
        ),
    ]

    selected = CustomerAftercareInboxService._select_ai_suggestions(  # noqa: SLF001
        candidates,
        [AiExtractedItem(name="Tenorstimme", quantity="3"), AiExtractedItem(name="Erfunden")],
    )

    assert selected[0].role == "MISSING_TO_SEND"
    assert selected[0].quantity == 3
    assert selected[1].role == "ORIGINAL_CANDIDATE"
    assert {item.sku for item in selected} == {"TEN-1", "BASS-1"}
