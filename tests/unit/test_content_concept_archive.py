"""Guard the historical Content Studio concept against accidental edits."""
from hashlib import sha256
from pathlib import Path


_EXPECTED_SHA256 = "216aee02df554f5dc60f5e0dcbf31d597bfc2c973569a10b8d2b1f89190fbdc6"
_ARCHIVE_NAME = "XeisWorks_Content_Studio_Originalkonzept_2026-07-19_UNVERAENDERT.md"


def test_original_content_concept_is_unchanged() -> None:
    archive = Path(__file__).resolve().parents[2] / "markdowns" / _ARCHIVE_NAME

    # Git may materialize CRLF on Windows and LF on Railway/Linux. Protect the
    # document content while deliberately ignoring that platform detail.
    normalized = archive.read_text(encoding="utf-8").replace("\r\n", "\n")
    digest = sha256(normalized.encode("utf-8")).hexdigest()

    assert digest == _EXPECTED_SHA256, (
        "Das archivierte Content-Studio-Originalkonzept wurde verändert. "
        "Bitte stattdessen die Zielarchitektur fortschreiben."
    )
