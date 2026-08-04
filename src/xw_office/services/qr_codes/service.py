"""Batch orchestration for the QR-code series generator.

Owns global settings persistence (SettingKvRepository, one JSON blob - the
app has no QSettings usage anywhere, see DigitalLicenseService's
``_COMPLETED_KEY`` pattern), collision precheck, threaded-friendly batch
generation with progress/cancel callbacks, manifest writing, and the optional
decode-verification step (reusing ``opencv-python-headless``, already a
project dependency - see tests/unit/test_payment_qr.py).
"""
from __future__ import annotations

import csv
import json
import logging
import os
from collections.abc import Callable, Sequence
from dataclasses import asdict, replace
from pathlib import Path
from typing import TYPE_CHECKING

from xw_office.services.qr_codes.models import (
    CollisionPolicy,
    QrBatchRequest,
    QrBatchSummary,
    QrGenerationResult,
    QrModuleError,
    QrOutputError,
    QrRecord,
    QrRenderSettings,
    QrVerificationError,
)
from xw_office.services.qr_codes.renderer import SegnoLogoQrRenderer

if TYPE_CHECKING:
    from xw_office.repositories.settings_kv import SettingKvRepository

logger = logging.getLogger(__name__)

_SETTINGS_KEY = "qr_codes.settings"
_MANIFEST_FILENAME = "qr_manifest.csv"


class QrCodeService:
    """Global QR settings, batch precheck, and batch PNG generation."""

    def __init__(
        self,
        *,
        settings_repo: "SettingKvRepository | None" = None,
        renderer: SegnoLogoQrRenderer | None = None,
    ) -> None:
        self._settings_repo = settings_repo
        self._renderer = renderer or SegnoLogoQrRenderer()

    # ------------------------------------------------------------------
    # Settings
    # ------------------------------------------------------------------

    def load_settings(self) -> QrRenderSettings:
        if self._settings_repo is None:
            return QrRenderSettings()
        raw = self._settings_repo.get_value_json(_SETTINGS_KEY)
        if not raw:
            return QrRenderSettings()
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            logger.warning("qr_codes.settings enthaelt kein gueltiges JSON, verwende Standardwerte.")
            return QrRenderSettings()
        defaults = asdict(QrRenderSettings())
        merged = {**defaults, **{k: v for k, v in data.items() if k in defaults}}
        return QrRenderSettings(**merged)

    def save_settings(self, settings: QrRenderSettings) -> None:
        if self._settings_repo is None:
            return
        self._settings_repo.set_value_json(
            _SETTINGS_KEY, json.dumps(asdict(settings), ensure_ascii=False, sort_keys=True)
        )

    def render_preview(self, payload: str, settings: QrRenderSettings) -> bytes:
        """Render one example QR PNG for the live settings preview. Raises QrModuleError."""
        return self._renderer.render(payload, settings)

    # ------------------------------------------------------------------
    # Precheck (used to annotate the live preview table before generation)
    # ------------------------------------------------------------------

    def precheck_output_directory(self, output_directory: Path) -> None:
        if output_directory.exists() and not output_directory.is_dir():
            raise QrOutputError(f"Der Ausgabepfad ist kein Ordner:\n{output_directory}")
        if not output_directory.exists():
            try:
                output_directory.mkdir(parents=True, exist_ok=True)
            except OSError as exc:
                raise QrOutputError(
                    f"Der Ausgabeordner konnte nicht angelegt werden:\n{output_directory}\n\n{exc}"
                ) from exc
        if not os.access(str(output_directory), os.W_OK):
            raise QrOutputError(f"Der Ausgabeordner ist schreibgeschuetzt:\n{output_directory}")

    def precheck_records(
        self,
        records: Sequence[QrRecord],
        output_directory: Path,
    ) -> tuple[QrRecord, ...]:
        """Annotate records with a human-readable warning (duplicate/existing file)."""
        seen: dict[str, int] = {}
        annotated: list[QrRecord] = []
        directory_usable = output_directory.exists() and output_directory.is_dir()
        for record in records:
            key = record.output_filename.lower()
            warning = ""
            if key in seen:
                warning = f"Doppelter Dateiname im Batch (auch Nr. {seen[key]})."
            else:
                seen[key] = record.ordinal
                if directory_usable and (output_directory / record.output_filename).exists():
                    warning = "Datei existiert bereits im Ausgabeordner."
            annotated.append(replace(record, warning=warning) if warning else record)
        return tuple(annotated)

    # ------------------------------------------------------------------
    # Batch generation
    # ------------------------------------------------------------------

    def generate_batch(
        self,
        request: QrBatchRequest,
        *,
        progress: Callable[[int, int, str], None] | None = None,
        should_cancel: Callable[[], bool] | None = None,
    ) -> QrBatchSummary:
        self.precheck_output_directory(request.output_directory)
        if request.collision_policy == "abort":
            self._raise_on_collisions(request.records, request.output_directory)

        total = len(request.records)
        used_names: set[str] = set()
        results: list[QrGenerationResult] = []
        cancelled = False

        for index, record in enumerate(request.records, start=1):
            if should_cancel is not None and should_cancel():
                cancelled = True
                break
            if progress is not None:
                progress(index, total, record.logical_id)

            target_path = self._resolve_target_path(
                record, request.output_directory, request.collision_policy, used_names
            )
            used_names.add(target_path.name.lower())
            try:
                png_bytes = self._renderer.render(record.payload_url, request.render_settings)
                target_path.write_bytes(png_bytes)
                if request.render_settings.verify_after_generation:
                    self._verify(target_path, record.payload_url)
                results.append(QrGenerationResult(record=record, output_path=target_path, success=True))
            except (QrModuleError, OSError) as exc:
                logger.error("QR-Erzeugung fehlgeschlagen fuer %s: %s", record.logical_id, exc, exc_info=True)
                results.append(
                    QrGenerationResult(record=record, output_path=None, success=False, error_message=str(exc))
                )

        manifest_path = self._write_manifest(results, request.output_directory) if results else None
        return QrBatchSummary(
            results=tuple(results),
            output_directory=request.output_directory,
            manifest_path=manifest_path,
            cancelled=cancelled,
        )

    def _raise_on_collisions(self, records: Sequence[QrRecord], output_directory: Path) -> None:
        seen: set[str] = set()
        for record in records:
            key = record.output_filename.lower()
            if key in seen:
                raise QrOutputError(
                    f"Doppelter Dateiname im Batch: {record.output_filename}\n"
                    "Kollisionsregel 'Abbrechen' - es wurde nichts erzeugt."
                )
            seen.add(key)
            if (output_directory / record.output_filename).exists():
                raise QrOutputError(
                    f"Datei existiert bereits: {record.output_filename}\n"
                    "Kollisionsregel 'Abbrechen' - es wurde nichts erzeugt."
                )

    def _resolve_target_path(
        self,
        record: QrRecord,
        output_directory: Path,
        collision_policy: CollisionPolicy,
        used_names: set[str],
    ) -> Path:
        base_name = record.output_filename
        target = output_directory / base_name
        if collision_policy != "rename":
            return target
        if not target.exists() and base_name.lower() not in used_names:
            return target
        stem, dot, ext = base_name.rpartition(".")
        stem, ext = (stem, f".{ext}") if dot else (base_name, "")
        counter = 2
        while True:
            candidate_name = f"{stem}_{counter}{ext}"
            candidate = output_directory / candidate_name
            if not candidate.exists() and candidate_name.lower() not in used_names:
                return candidate
            counter += 1

    def _write_manifest(self, results: Sequence[QrGenerationResult], output_directory: Path) -> Path:
        manifest_path = output_directory / _MANIFEST_FILENAME
        with manifest_path.open("w", newline="", encoding="utf-8-sig") as fh:
            writer = csv.writer(fh, delimiter=";")
            writer.writerow(
                ["ordinal", "source_key", "logical_id", "payload_url", "output_filename", "status", "error"]
            )
            for result in results:
                writer.writerow(
                    [
                        result.record.ordinal,
                        result.record.source_key,
                        result.record.logical_id,
                        result.record.payload_url,
                        result.record.output_filename,
                        "success" if result.success else "failed",
                        result.error_message,
                    ]
                )
        return manifest_path

    def _verify(self, path: Path, expected_payload: str) -> None:
        import cv2

        image = cv2.imread(str(path))
        if image is None:
            raise QrVerificationError(f"Datei konnte zur Rueckleseprüfung nicht geoeffnet werden: {path}")
        decoded, _points, _ = cv2.QRCodeDetector().detectAndDecode(image)
        if decoded != expected_payload:
            raise QrVerificationError(
                f"Rueckleseprüfung fehlgeschlagen fuer {path.name}: "
                f"erwartet '{expected_payload}', gelesen '{decoded}'"
            )
