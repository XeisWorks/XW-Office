"""The clearing feed must include every refund before choosing a document."""
from __future__ import annotations

import pytest

from xw_office.services.flow_api.refunds import FlowRefundsClient


def test_refund_feed_reads_all_pages(monkeypatch: pytest.MonkeyPatch) -> None:
    offsets: list[int] = []

    def page(_self: object, *, limit: int, offset: int) -> list[dict[str, str]]:
        offsets.append(offset)
        return [
            {"wix_refund_id": f"synthetic-{index}"}
            for index in range(offset, min(offset + limit, 501))
        ]

    monkeypatch.setattr(FlowRefundsClient, "list_refunds", page)
    client = object.__new__(FlowRefundsClient)
    rows = client.list_all_refunds()
    assert len(rows) == 501
    assert offsets == [0, 500]


def test_refund_feed_rejects_duplicate_across_pages(monkeypatch: pytest.MonkeyPatch) -> None:
    def page(_self: object, *, limit: int, offset: int) -> list[dict[str, str]]:
        return ([{"wix_refund_id": f"synthetic-{index}"} for index in range(limit)]
                if offset == 0 else [{"wix_refund_id": "synthetic-1"}])

    monkeypatch.setattr(FlowRefundsClient, "list_refunds", page)
    client = object.__new__(FlowRefundsClient)
    with pytest.raises(RuntimeError, match="instabil"):
        client.list_all_refunds()
