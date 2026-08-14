"""Generate and print calibrated A5 customs-form trials.

This is a temporary operator calibration helper. It keeps the source form
vector-based, marks every print prominently, and varies only renderer scale
and offset after recreating the geometry of the previously preferred TEST N.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from pathlib import Path

import fitz

from xw_office.services.printing.pdf_backends import QtRasterBackend
from xw_office.services.printing.print_jobs import PdfPrintJob


MM_TO_PT = 72.0 / 25.4
A5_WIDTH_PT = 148.0 * MM_TO_PT
A5_HEIGHT_PT = 210.0 * MM_TO_PT
SOURCE_CONTENT = fitz.Rect(14.173, 13.171, 581.102, 459.919)


@dataclass(frozen=True)
class Trial:
    code: str
    description: str
    proportional: bool
    scale_percent: float
    x_offset_mm: float
    y_offset_mm: float


TRIALS = (
    Trial("AA", "N-GEOMETRIE 103% OFFSET -2,0", False, 103.0, -2.0, -2.0),
    Trial("AB", "N-GEOMETRIE 106% OFFSET -4,5", False, 106.0, -4.5, -4.5),
    Trial("AC", "N-GEOMETRIE 106% OFFSET 0", False, 106.0, 0.0, 0.0),
    Trial("AD", "ECHTE PROPORTION VOLLSTAENDIG", True, 106.0, -4.5, -4.5),
)


def _create_trial(source_path: Path, output_path: Path, trial: Trial) -> None:
    source = fitz.open(source_path)
    output = fitz.open()
    try:
        page = output.new_page(width=A5_WIDTH_PT, height=A5_HEIGHT_PT)
        if trial.proportional:
            # The rotated source is about 157.6 x 200 mm. Width is therefore
            # the limiting A5 dimension; the remaining lower strip is real
            # aspect-ratio difference, not a printer margin.
            rotated_width = SOURCE_CONTENT.height
            rotated_height = SOURCE_CONTENT.width
            target_height = A5_WIDTH_PT * rotated_height / rotated_width
            target = fitz.Rect(0, 0, A5_WIDTH_PT, target_height)
            page.show_pdf_page(
                target,
                source,
                0,
                clip=SOURCE_CONTENT,
                rotate=90,
                keep_proportion=True,
                overlay=True,
            )
        else:
            # Recreate TEST N on an exact Windows A5 canvas (148 x 210 mm).
            target = fitz.Rect(0, 0, 144.0 * MM_TO_PT, 206.0 * MM_TO_PT)
            page.show_pdf_page(
                target,
                source,
                0,
                clip=SOURCE_CONTENT,
                rotate=90,
                keep_proportion=False,
                overlay=True,
            )

        label_rect = fitz.Rect(8 * MM_TO_PT, 1.5 * MM_TO_PT, A5_WIDTH_PT - 8 * MM_TO_PT, 10 * MM_TO_PT)
        page.insert_textbox(
            label_rect,
            f"TEST {trial.code} - {trial.description}",
            fontsize=9,
            fontname="hebo",
            color=(1, 0, 0),
            align=fitz.TEXT_ALIGN_CENTER,
            overlay=True,
        )
        page.insert_textbox(
            fitz.Rect(20 * MM_TO_PT, 80 * MM_TO_PT, A5_WIDTH_PT - 20 * MM_TO_PT, 135 * MM_TO_PT),
            f"DRUCKTEST {trial.code}\nNICHT ALS ZOLLDOKUMENT VERWENDEN",
            fontsize=16,
            fontname="hebo",
            color=(1, 0, 0),
            align=fitz.TEXT_ALIGN_CENTER,
            overlay=True,
            fill_opacity=0.32,
        )
        output.save(output_path, garbage=4, deflate=True)
    finally:
        output.close()
        source.close()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--printer", default="Zollformular")
    parser.add_argument("--print", action="store_true", dest="print_trials")
    args = parser.parse_args()

    args.output_dir.mkdir(parents=True, exist_ok=True)
    backend = QtRasterBackend()
    for trial in TRIALS:
        output_path = args.output_dir / f"Zollerklaerung_TEST_{trial.code}.pdf"
        _create_trial(args.source, output_path, trial)
        print(f"created {output_path}")
        if args.print_trials:
            backend.print(
                PdfPrintJob(
                    pdf_path=str(output_path),
                    printer_name=args.printer,
                    page_size="A5",
                    orientation="portrait",
                    placement_mode="paper_origin",
                    scale_mode="fit",
                    scale_percent=trial.scale_percent,
                    alignment="top_left",
                    x_offset_mm=trial.x_offset_mm,
                    y_offset_mm=trial.y_offset_mm,
                    job_kind="plc_customs",
                    render_color_mode="rgb",
                    black_enhancement="none",
                )
            )
            print(
                f"printed TEST {trial.code}: scale={trial.scale_percent}% "
                f"offset=({trial.x_offset_mm}, {trial.y_offset_mm}) mm"
            )


if __name__ == "__main__":
    main()
