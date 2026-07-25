"""CRM matching tests."""
from xw_studio.services.crm.matching import (
    classify_match_reason,
    contact_match_score,
    find_duplicate_candidates,
)
from xw_studio.services.crm.types import ContactRecord, MatchReason


def test_identical_records_high_score() -> None:
    a = ContactRecord(id="1", name="ACME GmbH", email="e@acme.test")
    b = ContactRecord(id="2", name="ACME GmbH", email="e@acme.test")
    assert contact_match_score(a, b) >= 90


def test_find_duplicate_candidates() -> None:
    rows = [
        ContactRecord(id="1", name="Musik Verlag Nord", email="a@example.test"),
        ContactRecord(id="2", name="Musikverlag Nord", email="a@example.test"),
    ]
    dups = find_duplicate_candidates(rows, threshold=70)
    assert dups


def test_classify_match_reason_prefers_exact_email() -> None:
    a = ContactRecord(id="1", name="Musik Verlag Nord", email="Kontakt@Beispiel.test")
    b = ContactRecord(id="2", name="Ganz Anderer Name", email="kontakt@beispiel.test")
    assert classify_match_reason(a, b) is MatchReason.EMAIL_EXACT


def test_classify_match_reason_falls_back_to_fuzzy_name() -> None:
    a = ContactRecord(id="1", name="Musik Verlag Nord", email="a@example.test")
    b = ContactRecord(id="2", name="Musikverlag Nord", email="b@example.test")
    assert classify_match_reason(a, b) is MatchReason.FUZZY_NAME


def test_find_duplicate_candidates_carries_match_reason() -> None:
    rows = [
        ContactRecord(id="1", name="Musik Verlag Nord", email="a@example.test"),
        ContactRecord(id="2", name="Voellig anderer Name", email="a@example.test"),
    ]
    dups = find_duplicate_candidates(rows, threshold=10)
    assert dups
    assert dups[0].reason is MatchReason.EMAIL_EXACT
