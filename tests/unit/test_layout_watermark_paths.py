from pathlib import Path

from xw_studio.services.layout.service import _watermark_output_path


def test_watermark_output_replaces_gesamt_token(tmp_path: Path) -> None:
    source = tmp_path / "Test Piece GESAMT.pdf"

    result = _watermark_output_path(source, tmp_path, "Anna Example")

    assert result == tmp_path / "Test Piece - Anna Example.pdf"


def test_watermark_output_uses_collision_suffix(tmp_path: Path) -> None:
    source = tmp_path / "Test Piece GESAMT.pdf"
    (tmp_path / "Test Piece - Anna Example.pdf").write_bytes(b"old")

    result = _watermark_output_path(source, tmp_path, "Anna Example")

    assert result == tmp_path / "Test Piece - Anna Example (2).pdf"
