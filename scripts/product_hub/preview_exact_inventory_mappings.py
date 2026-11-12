"""Preview safe exact-SKU sevDesk mappings for the inventory cutover.

This command is read-only.  It never creates or changes a channel mapping and
does not write to sevDesk.  Only one-to-one matches between active physical Hub
variants and sevDesk Part numbers are reported.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from xw_office.core.config import load_config  # noqa: E402
from xw_office.core.database import create_session_factory  # noqa: E402
from xw_office.services.http_client import build_sevdesk_connection  # noqa: E402
from xw_office.services.product_hub.inventory_mapping_audit import (  # noqa: E402
    exact_sevdesk_mapping_candidates,
)
from xw_office.repositories.product_hub import ProductFilter, ProductHubRepository  # noqa: E402
from xw_office.services.sevdesk.part_client import PartClient  # noqa: E402


class _EnvironmentSecrets:
    def get_secret(self, name: str) -> str:
        return str(os.getenv(name) or "")


def build_preview(*, max_pages: int = 100) -> dict[str, object]:
    config = load_config()
    if not (config.database_url or "").strip():
        raise RuntimeError("DATABASE_URL ist erforderlich.")
    if not (config.sevdesk.api_token or "").strip():
        raise RuntimeError("SEVDESK_API_TOKEN ist erforderlich.")
    factory = create_session_factory(config)
    repository = ProductHubRepository(factory)
    products = repository.list_products(ProductFilter(status="live", active=True))
    products = [product for product in products if product.product_type == "physical"]
    variants = repository.list_variants_for_products([product.id for product in products])
    mappings = repository.list_channel_mappings_for_entities(
        [product.id for product in products], entity_type="product"
    )
    mappings.extend(
        repository.list_channel_mappings_for_entities([variant.id for variant in variants], entity_type="variant")
    )
    parts = PartClient(build_sevdesk_connection(config)).list_parts(
        max_pages=max(1, int(max_pages)), refresh_cache=True
    )
    candidates = exact_sevdesk_mapping_candidates(products, variants, parts, mappings)
    return {
        "read_only": True,
        "products": len(products),
        "variants": len(variants),
        "sevdesk_parts": len(parts),
        "exact_candidates": len(candidates),
        "candidates": [candidate.as_dict() for candidate in candidates],
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--max-pages", type=int, default=100)
    parser.add_argument(
        "--summary",
        action="store_true",
        help="Nur Zähler ausgeben; ohne Option werden die Kandidaten mit ausgegeben.",
    )
    args = parser.parse_args(argv)
    try:
        payload = build_preview(max_pages=args.max_pages)
        if args.summary:
            payload.pop("candidates", None)
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    except Exception as exc:  # noqa: BLE001 - stable operational failure output
        print(f"Exact-Mapping-Preview fehlgeschlagen: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
