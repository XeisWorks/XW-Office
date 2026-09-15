from pathlib import Path

from xw_office.services.layout.service import _insert_side_watermark, _watermark_output_path


def test_watermark_output_replaces_gesamt_token(tmp_path: Path) -> None:
    source = tmp_path / "Test Piece GESAMT.pdf"

    result = _watermark_output_path(source, tmp_path, "Anna Example")

    assert result == tmp_path / "Test Piece - Anna Example.pdf"


def test_watermark_output_uses_collision_suffix(tmp_path: Path) -> None:
    source = tmp_path / "Test Piece GESAMT.pdf"
    (tmp_path / "Test Piece - Anna Example.pdf").write_bytes(b"old")

    result = _watermark_output_path(source, tmp_path, "Anna Example")

    assert result == tmp_path / "Test Piece - Anna Example (2).pdf"


def test_side_watermark_default_font_size_is_eleven_points() -> None:
    calls: list[dict[str, object]] = []

    class _Page:
        rect = type("Rect", (), {"width": 595.0, "height": 842.0})()

        def insert_text(self, point: object, text: str, **kwargs: object) -> None:
            calls.append(kwargs)

    fitz = type(
        "Fitz",
        (),
        {"get_text_length": staticmethod(lambda text, fontname, fontsize: 100.0)},
    )()

    _insert_side_watermark(fitz, [_Page()], "Anna Example")

    assert [call["fontsize"] for call in calls] == [11.0, 11.0]
