"""Public dealer share routes (PR12): ``/share/{token}`` + CSV/XLSX export.

Deliberately **not** behind the bootstrap-token dependency the rest of this API uses
— the whole point of a share is that a dealer needs only the opaque token in the URL.
Still fails closed (503) when the Product Hub isn't configured/enabled at all, via the
same ``require_product_hub_enabled`` dependency the read API uses, and applies its own
per-token rate limit and revocation/expiry checks on every request.

HTML, CSV and XLSX all call the exact same
:meth:`~xw_office.services.product_hub.sharing.SharingService.query_catalog` — see
that module's docstring for why.
"""
from __future__ import annotations

import csv
import html
import io
from collections.abc import Callable

from fastapi import APIRouter, HTTPException, Response, status
from openpyxl import Workbook

from xw_office.models.product_hub_sharing import SharedCatalogView
from xw_office.services.product_hub.sharing import (
    RateLimitExceededError,
    ShareInactiveError,
    ShareNotFoundError,
    SharingService,
)

SharingDependency = Callable[[], SharingService]

_COLUMN_LABELS = {
    "cover_url": "Cover",
    "sku": "SKU",
    "isbn": "ISBN",
    "name": "Name",
    "description": "Beschreibung",
    "price_uvp": "UVP",
    "price_b2b": "B2B-Preis",
    "available": "Verfügbar",
}


def _resolve_or_404(sharing: SharingService, token: str) -> SharedCatalogView:
    try:
        return sharing.resolve_token(token)
    except ShareNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Unknown share") from exc
    except ShareInactiveError as exc:
        raise HTTPException(status_code=status.HTTP_410_GONE, detail=str(exc)) from exc
    except RateLimitExceededError as exc:
        raise HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail=str(exc)) from exc


def _render_html(title: str, columns: list[str], rows: list[dict[str, object]]) -> str:
    header_cells = "".join(f"<th>{html.escape(_COLUMN_LABELS.get(c, c))}</th>" for c in columns)
    body_rows = []
    for row in rows:
        cells = []
        for column in columns:
            value = row.get(column)
            if column == "cover_url" and value:
                cells.append(
                    f'<td><img src="{html.escape(str(value))}" alt="" loading="lazy" '
                    f'style="max-width:64px;max-height:64px;"></td>'
                )
            elif column == "available":
                cells.append(f"<td>{'Ja' if value else 'Nein'}</td>")
            else:
                cells.append(f"<td>{html.escape('' if value is None else str(value))}</td>")
        body_rows.append(f"<tr>{''.join(cells)}</tr>")
    return f"""<!doctype html>
<html lang="de">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{html.escape(title)}</title>
  <style>
    :root {{ color-scheme: light; font-family: system-ui, sans-serif; }}
    body {{ margin: 0; background: #f5f6f8; color: #1f2430; }}
    main {{ max-width: 72rem; margin: 0 auto; padding: 2rem 1.25rem; }}
    h1 {{ font-size: 1.5rem; }}
    table {{ width: 100%; border-collapse: collapse; background: white; }}
    th, td {{ text-align: left; padding: 0.5rem 0.75rem; border-bottom: 1px solid #dde1e6; font-size: 0.9rem; }}
    th {{ background: #eceef1; }}
  </style>
</head>
<body>
  <main>
    <h1>{html.escape(title)}</h1>
    <table>
      <thead><tr>{header_cells}</tr></thead>
      <tbody>{"".join(body_rows)}</tbody>
    </table>
  </main>
</body>
</html>"""


def build_share_public_router(get_sharing: SharingDependency) -> APIRouter:
    router = APIRouter(tags=["product-hub-sharing-public"])

    @router.get("/share/{token}", response_class=Response)
    def view_share(token: str) -> Response:
        sharing = get_sharing()
        share = _resolve_or_404(sharing, token)
        rows = sharing.query_catalog(share)
        columns = [c for c in _COLUMN_LABELS if any(c in row for row in rows)] or [
            str(f) for f in share.field_whitelist
        ]
        page = _render_html(share.title, columns, rows)
        return Response(content=page, media_type="text/html")

    @router.get("/share/{token}/export.csv")
    def export_csv(token: str) -> Response:
        sharing = get_sharing()
        share = _resolve_or_404(sharing, token)
        if not share.allow_csv:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="CSV export not allowed")
        rows = sharing.query_catalog(share)
        columns = [c for c in _COLUMN_LABELS if any(c in row for row in rows)]
        buffer = io.StringIO()
        writer = csv.writer(buffer)
        writer.writerow([_COLUMN_LABELS.get(c, c) for c in columns])
        for row in rows:
            writer.writerow([row.get(c, "") for c in columns])
        sharing.record_export(share, export_format="csv", row_count=len(rows))
        return Response(
            content=buffer.getvalue(),
            media_type="text/csv",
            headers={"Content-Disposition": 'attachment; filename="catalog.csv"'},
        )

    @router.get("/share/{token}/export.xlsx")
    def export_xlsx(token: str) -> Response:
        sharing = get_sharing()
        share = _resolve_or_404(sharing, token)
        if not share.allow_xlsx:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="XLSX export not allowed")
        rows = sharing.query_catalog(share)
        columns = [c for c in _COLUMN_LABELS if any(c in row for row in rows)]

        workbook = Workbook()
        sheet = workbook.active
        sheet.title = "Katalog"
        sheet.append([_COLUMN_LABELS.get(c, c) for c in columns])
        for row in rows:
            sheet.append([row.get(c, "") for c in columns])
        buffer = io.BytesIO()
        workbook.save(buffer)
        sharing.record_export(share, export_format="xlsx", row_count=len(rows))
        return Response(
            content=buffer.getvalue(),
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            headers={"Content-Disposition": 'attachment; filename="catalog.xlsx"'},
        )

    return router
