"""Tests for SearchBar debounce and typeahead behavior."""
from __future__ import annotations

from xw_office.ui.widgets.search_bar import SearchBar


def test_search_bar_min_chars_gate(qtbot: object) -> None:
    bar = SearchBar(debounce_ms=1, min_chars=3)
    qtbot.addWidget(bar)  # type: ignore[attr-defined]

    received: list[str] = []
    bar.search_changed.connect(received.append)

    bar.setText("ab")
    qtbot.wait(20)  # type: ignore[attr-defined]
    assert received
    assert received[-1] == ""

    bar.setText("abc")
    qtbot.wait(20)  # type: ignore[attr-defined]
    assert received[-1] == "abc"


def test_search_bar_typeahead_suggestions(qtbot: object) -> None:
    bar = SearchBar(debounce_ms=1, min_chars=3, max_suggestions=3)
    qtbot.addWidget(bar)  # type: ignore[attr-defined]
    bar.set_suggestion_provider(
        lambda _q: ["Alpha", "Alpine", "Alpha", "Alphabet", "Albatros"]
    )

    bar.setText("alp")
    qtbot.wait(20)  # type: ignore[attr-defined]
    assert bar.suggestion_items() == ["Alpha", "Alpine", "Alphabet"]

    bar.setText("al")
    qtbot.wait(20)  # type: ignore[attr-defined]
    assert bar.suggestion_items() == []
