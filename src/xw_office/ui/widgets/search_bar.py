"""Debounced search input with clear button."""
from __future__ import annotations

from collections.abc import Callable, Sequence

from PySide6.QtCore import QTimer, Qt, QStringListModel, Signal
from PySide6.QtWidgets import QCompleter, QLineEdit, QWidget


class SearchBar(QLineEdit):
    """Debounced search input with min-length gate and typeahead dropdown."""

    search_changed = Signal(str)

    def __init__(
        self,
        placeholder: str = "Suchen...",
        debounce_ms: int = 250,
        min_chars: int = 3,
        max_suggestions: int = 10,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setPlaceholderText(placeholder)
        self.setClearButtonEnabled(True)
        self.setMinimumHeight(36)
        self.setStyleSheet("padding: 6px 12px; font-size: 14px;")
        self.setToolTip(f"Mindestens {min_chars} Zeichen fuer Suchempfehlungen")

        self._min_chars = max(1, int(min_chars))
        self._max_suggestions = max(1, int(max_suggestions))
        self._provider: Callable[[str], Sequence[str]] | None = None
        self._model = QStringListModel([])
        self._completer = QCompleter(self._model, self)
        self._completer.setCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
        self._completer.setFilterMode(Qt.MatchFlag.MatchContains)
        self._completer.setCompletionMode(QCompleter.CompletionMode.PopupCompletion)
        self.setCompleter(self._completer)

        self._timer = QTimer()
        self._timer.setSingleShot(True)
        self._timer.setInterval(debounce_ms)
        self._timer.timeout.connect(self._emit_debounced)
        self.textChanged.connect(lambda _: self._timer.start())

    def set_suggestion_provider(self, provider: Callable[[str], Sequence[str]] | None) -> None:
        """Set callback returning suggestions for current query text."""
        self._provider = provider
        self.refresh_suggestions()

    def refresh_suggestions(self) -> None:
        self._update_suggestions(self.text().strip())

    def suggestion_items(self) -> list[str]:
        """Expose current suggestion list (useful for tests/debugging)."""
        return self._model.stringList()

    def _emit_debounced(self) -> None:
        query = self.text().strip()
        if not query:
            self._update_suggestions("")
            self.search_changed.emit("")
            return
        if len(query) < self._min_chars:
            self._update_suggestions("")
            self.search_changed.emit("")
            return
        self._update_suggestions(query)
        self.search_changed.emit(query)

    def _update_suggestions(self, query: str) -> None:
        if not query or len(query) < self._min_chars or self._provider is None:
            self._model.setStringList([])
            return

        raw = self._provider(query)
        seen: set[str] = set()
        items: list[str] = []
        for item in raw:
            txt = str(item).strip()
            if not txt:
                continue
            key = txt.lower()
            if key in seen:
                continue
            seen.add(key)
            items.append(txt)
            if len(items) >= self._max_suggestions:
                break
        self._model.setStringList(items)
        if items and self.hasFocus():
            self._completer.complete()
