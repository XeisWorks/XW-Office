from __future__ import annotations

import subprocess
from pathlib import Path


def test_printing_code_does_not_reference_external_pdf_viewers() -> None:
    root = Path(__file__).resolve().parents[2]
    printing_sources = list((root / "src" / "xw_studio" / "services" / "printing").glob("*.py"))
    printing_sources.append(root / "src" / "xw_studio" / "ui" / "modules" / "rechnungen" / "print_dialog.py")
    content = "\n".join(path.read_text(encoding="utf-8") for path in printing_sources)
    forbidden = [
        "Acrobat",
        "AcroRd32",
        "Adobe",
        "SumatraPDF",
        "sumatra",
        "os.startfile",
        "subprocess.Popen",
        "ShellExecute",
        "printto",
    ]

    assert not any(token in content for token in forbidden)


def test_planned_pdf_printer_does_not_shell_out(monkeypatch) -> None:
    from xw_studio.core.config import PrintingSection
    from xw_studio.services.printing.planned_pdf_printer import print_pdf_by_plan

    calls: list[object] = []

    class QueueStub:
        def enqueue(self, job: object) -> str:
            calls.append(job)
            return "job"

    monkeypatch.setattr(subprocess, "Popen", lambda *_args, **_kwargs: calls.append("popen"))

    print_pdf_by_plan(
        "C:/tmp/test.pdf",
        PrintingSection(print_profiles=[{"id": "p", "label": "P", "printer_name": "Printer"}]),
        profile_id="p",
        print_queue=QueueStub(),  # type: ignore[arg-type]
    )

    assert calls and "popen" not in calls
