"""Detailed print-profile summary with a route into the shared editor."""
from __future__ import annotations

from dataclasses import asdict

from PySide6.QtWidgets import (
    QDialog, QDialogButtonBox, QLabel, QPlainTextEdit, QPushButton, QVBoxLayout, QWidget,
)

from xw_office.core.config import PrintingSection
from xw_office.core.shared_paths import resolve_shared_path
from xw_office.print_center.models import PrintArticle
from xw_office.services.printing.planned_pdf_printer import resolve_plan_targets

_SETTING_LABELS = {
    "id": "Profil-ID", "label": "Bezeichnung", "printer_name": "Drucker", "dpi": "DPI",
    "placement_mode": "Platzierung", "page_size": "Papierformat", "orientation": "Ausrichtung",
    "scale_mode": "Skalierungsmodus", "scale_percent": "Skalierung (%)",
    "alignment": "Positionierung", "x_offset_mm": "Horizontaler Versatz (mm)",
    "y_offset_mm": "Vertikaler Versatz (mm)", "rotate_degrees": "Drehung (Grad)",
    "normalize_page_size": "Seitennormalisierung", "max_upscale_percent": "Max. Vergroesserung (%)",
    "render_color_mode": "Farbmodus", "black_enhancement": "Schwarzoptimierung",
    "black_threshold": "Schwarz-Schwellenwert", "backend": "Druckverfahren",
    "native_pdf_exe": "PDF-XChange-Programm",
}


def describe_print_settings(article: PrintArticle, printing: PrintingSection) -> str:
    lines = [
        article.name,
        "Zentrales Produkt" if article.source in {"official", "unreleased"} else "Eigener Druckartikel",
        f"\nDruckpfad:\n{article.pdf_path or '(nicht zugeordnet)'}",
    ]
    resolved = resolve_shared_path(article.pdf_path)
    if resolved and resolved != article.pdf_path:
        lines.append(f"\nPfad auf diesem PC:\n{resolved}")
    steps = [(step.range, step.profile_id) for step in article.print_plan]
    if not steps and article.profile_id:
        steps = [("Alle Seiten", article.profile_id)]
    if not steps:
        lines.append("\nKein Druckprofil zugeordnet.")
    for index, (page_range, profile_id) in enumerate(steps, start=1):
        lines.append(f"\nDruckschritt {index}: {page_range}\nProfil: {profile_id}")
        # The shared resolver also understands historic profile aliases.
        try:
            targets = resolve_plan_targets(printing, profile_id=profile_id)
        except RuntimeError as exc:
            lines.append(f"Profil nicht verfuegbar: {exc}")
            continue
        if not targets:
            lines.append("Profil/Drucker nicht verfuegbar.")
            continue
        profile = printing.resolve_profile(profile_id)
        settings = asdict(profile) if profile is not None else asdict(targets[0])
        for key, value in settings.items():
            if key != "range_text":
                lines.append(f"{_SETTING_LABELS.get(key, key)}: {value}")
    if article.notes:
        lines.append(f"\nNotiz:\n{article.notes}")
    return "\n".join(lines)


class PrintDetailsDialog(QDialog):
    def __init__(
        self, article: PrintArticle, printing: PrintingSection, parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle(f"Druckpfad und Einstellungen - {article.name}")
        self.resize(720, 560)
        self.edit_requested = False
        root = QVBoxLayout(self)
        root.addWidget(QLabel(
            "Druckpfad und Druckplan sind bearbeitbar; die Druckprofile selbst bleiben zentral."
        ))
        self.settings_text = QPlainTextEdit(describe_print_settings(article, printing))
        self.settings_text.setReadOnly(True)
        root.addWidget(self.settings_text)
        self.edit_button = QPushButton("Druckpfad / Einstellungen bearbeiten")
        self.edit_button.clicked.connect(self._edit)
        root.addWidget(self.edit_button)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)

    def _edit(self) -> None:
        self.edit_requested = True
        self.accept()
