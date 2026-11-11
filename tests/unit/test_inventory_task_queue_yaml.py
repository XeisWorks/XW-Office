from __future__ import annotations

from pathlib import Path

import yaml


def test_inventory_task_queue_is_valid_yaml_with_complete_package_index() -> None:
    path = (
        Path(__file__).resolve().parents[2]
        / "markdowns"
        / "rechnungen_inventur_bestand_5_6_luna_task_queue_2026-11-08.yaml"
    )

    document = yaml.safe_load(path.read_text(encoding="utf-8"))

    assert document["schema_version"] == 1
    assert document["plan_id"] == "xw_office_inventory_invoice_release_2026_11_08"
    assert [package["id"] for package in document["packages"]] == [
        "P00",
        "P01",
        "P02",
        "P03",
        "P04",
        "P05",
        "P06",
        "P07",
        "P08",
    ]
    assert all(package.get("title") and package.get("status") for package in document["packages"])
