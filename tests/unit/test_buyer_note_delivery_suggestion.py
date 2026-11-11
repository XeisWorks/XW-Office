from __future__ import annotations

import pytest

from xw_office.services.sendungen import delivery_note
from xw_office.services.sendungen.delivery_note import DeliveryNoteContext, DeliveryNoteService


def _context() -> DeliveryNoteContext:
    return DeliveryNoteContext("RE-1", "21768", "Kundin", ("Hauptstraße 1",), (), "Bitte prüfen.")


def test_ai_suggestion_uses_only_optional_manual_text(monkeypatch: object) -> None:
    requests: list[dict[str, object]] = []

    class _Response:
        def raise_for_status(self) -> None:
            pass

        def json(self) -> dict[str, object]:
            return {"output": [{"content": [{"type": "output_text", "text": "Bitte vor Versand prüfen."}]}]}

    class _Client:
        def __init__(self, **_kwargs: object) -> None:
            pass

        def __enter__(self) -> _Client:
            return self

        def __exit__(self, *_args: object) -> None:
            pass

        def post(self, _url: str, **kwargs: object) -> _Response:
            requests.append(kwargs)
            return _Response()

    monkeypatch.setattr(delivery_note.httpx, "Client", _Client)  # type: ignore[attr-defined]
    assert DeliveryNoteService().suggest_manual_note(_context(), "test-key") == "Bitte vor Versand prüfen."
    assert "Bitte prüfen." in str(requests[0]["json"])
    assert requests[0]["headers"]["Authorization"] == "Bearer test-key"  # type: ignore[index]


def test_ai_suggestion_requires_key() -> None:
    with pytest.raises(RuntimeError, match="OPENAI_API_KEY"):
        DeliveryNoteService().suggest_manual_note(_context(), "")
