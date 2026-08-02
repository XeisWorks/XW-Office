"""Brand profile validation for the shared Content Studio domain."""
from pathlib import Path

import pytest

from xw_office.content import BrandProfileCatalog


def test_repository_brand_profiles_are_valid() -> None:
    path = Path(__file__).resolve().parents[2] / "config" / "content_brands.yaml"

    brands = BrandProfileCatalog(path).load()

    assert [brand.id for brand in brands] == ["xeisworks", "musikheroes"]
    assert all(brand.language == "de-AT" for brand in brands)


def test_duplicate_brand_ids_are_rejected(tmp_path: Path) -> None:
    path = tmp_path / "brands.yaml"
    path.write_text(
        """brands:
  - &brand
    id: duplicate
    display_name: First
    language: de-AT
    tone: {primary: klar}
  - <<: *brand
    display_name: Second
""",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="unique"):
        BrandProfileCatalog(path).load()
