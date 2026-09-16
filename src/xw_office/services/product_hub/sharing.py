"""Dealer sharing: revocable, field-whitelisted catalog views (PR12).

Security model per the build plan:
- The plaintext share token is generated here, returned to the caller exactly once
  (at creation), and never stored — only its SHA-256 hash goes to the DB
  (``SharedCatalogView.token_hash``). Losing the plaintext means the share must be
  revoked and recreated; there is no "show token again" path, by design.
- ``field_whitelist`` can never contain anything outside
  :data:`~xw_office.models.product_hub_sharing.ALLOWED_SHARE_FIELDS` — checked here at
  creation time, independent of whatever a caller's request body claims.
- HTML, CSV and XLSX all call the *same* :meth:`SharingService.query_catalog`, per the
  build plan's "HTML/CSV/XLSX verwenden dieselbe serverseitige Query" requirement, so
  there is exactly one place that decides what data a share can see.
- A minimal in-memory sliding-window rate limiter guards the public ``/share/{token}``
  routes — no Redis, matching this project's "no microservices/Redis without proven
  need" constraint; fine for a single Railway instance, would need revisiting if this
  service ever scales to multiple replicas.
"""
from __future__ import annotations

import datetime
import hashlib
import secrets
import threading
import uuid
from collections import deque
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from decimal import Decimal

from xw_office.models.product_hub import PriceList, ProductVariant
from xw_office.models.product_hub_sharing import ALLOWED_SHARE_FIELDS, ExportLog, SharedCatalogView
from xw_office.repositories.product_hub import ProductFilter, ProductHubRepository
from xw_office.repositories.product_hub_sharing import SharingRepository

#: Standardfilter per the build plan: B2B tag + live + active. Stored verbatim as a
#: share's default ``filter_definition`` — the query builder below only understands
#: this fixed shape for now (no free-form filter DSL yet).
DEFAULT_FILTER_DEFINITION = {"tag": "B2B", "status": "live", "active": True}
DEFAULT_FIELD_WHITELIST = list(ALLOWED_SHARE_FIELDS)

_RATE_LIMIT_WINDOW = datetime.timedelta(minutes=1)
_RATE_LIMIT_MAX_REQUESTS = 60


class ShareNotFoundError(LookupError):
    """No share matches the given token."""


class ShareInactiveError(RuntimeError):
    """Share exists but is revoked or expired."""


class InvalidFieldWhitelistError(ValueError):
    """A requested field isn't in ``ALLOWED_SHARE_FIELDS``."""


class RateLimitExceededError(RuntimeError):
    """Too many requests for this share token in the current window."""


def _hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class SharedCatalogRow:
    """One product row, already projected to only its share's whitelisted fields."""

    sku: str
    name: str
    isbn: str | None
    description: str | None
    cover_url: str | None
    price_uvp: str | None
    price_b2b: str | None
    available: bool

    def whitelisted(self, field_whitelist: Sequence[str]) -> dict[str, object]:
        full = {
            "sku": self.sku,
            "name": self.name,
            "isbn": self.isbn,
            "description": self.description,
            "cover_url": self.cover_url,
            "price_uvp": self.price_uvp,
            "price_b2b": self.price_b2b,
            "available": self.available,
        }
        return {k: v for k, v in full.items() if k in field_whitelist}


class _RateLimiter:
    """Sliding-window request counter, keyed by token hash — process-local, no store."""

    def __init__(self, *, window: datetime.timedelta, max_requests: int) -> None:
        self._window = window
        self._max_requests = max_requests
        self._hits: dict[str, deque[datetime.datetime]] = {}
        self._lock = threading.Lock()

    def check(self, key: str) -> None:
        now = datetime.datetime.now(datetime.timezone.utc)
        with self._lock:
            hits = self._hits.setdefault(key, deque())
            while hits and now - hits[0] > self._window:
                hits.popleft()
            if len(hits) >= self._max_requests:
                raise RateLimitExceededError("Too many requests for this share")
            hits.append(now)


class SharingService:
    """Create/resolve/query dealer catalog shares."""

    def __init__(self, product_repo: ProductHubRepository, sharing_repo: SharingRepository) -> None:
        self._products = product_repo
        self._shares = sharing_repo
        self._rate_limiter = _RateLimiter(
            window=_RATE_LIMIT_WINDOW, max_requests=_RATE_LIMIT_MAX_REQUESTS
        )

    # -- lifecycle --------------------------------------------------------------------

    def create_share(
        self,
        *,
        title: str,
        filter_definition: Mapping[str, object] | None = None,
        field_whitelist: Sequence[str] | None = None,
        price_list_code: str | None = None,
        allow_csv: bool = True,
        allow_xlsx: bool = True,
        allow_images: bool = True,
        expires_at: datetime.datetime | None = None,
        created_by: uuid.UUID | None = None,
    ) -> tuple[SharedCatalogView, str]:
        whitelist = list(field_whitelist) if field_whitelist is not None else DEFAULT_FIELD_WHITELIST
        unknown = set(whitelist) - set(ALLOWED_SHARE_FIELDS)
        if unknown:
            raise InvalidFieldWhitelistError(
                f"Field(s) not allowed in a share: {', '.join(sorted(unknown))}"
            )

        price_list_id: uuid.UUID | None = None
        if price_list_code:
            price_list = self._products.get_price_list_by_code(price_list_code)
            if price_list is None:
                raise KeyError(f"Price list '{price_list_code}' does not exist")
            price_list_id = price_list.id

        token = secrets.token_urlsafe(32)
        share = self._shares.create_share(
            title=title,
            token_hash=_hash_token(token),
            filter_definition=filter_definition or DEFAULT_FILTER_DEFINITION,
            field_whitelist=whitelist,
            price_list_id=price_list_id,
            allow_csv=allow_csv,
            allow_xlsx=allow_xlsx,
            allow_images=allow_images,
            expires_at=expires_at,
            created_by=created_by,
        )
        return share, token

    def list_shares(self) -> list[SharedCatalogView]:
        return self._shares.list_shares()

    def revoke(self, share_id: uuid.UUID) -> SharedCatalogView:
        return self._shares.revoke_share(share_id)

    def resolve_token(self, token: str, *, rate_limit: bool = True) -> SharedCatalogView:
        """Look up + validate a share by its plaintext token; touches ``last_access_at``.

        Raises :class:`ShareNotFoundError` for an unknown token,
        :class:`ShareInactiveError` for a revoked/expired one, and
        :class:`RateLimitExceededError` if this token hash has been used too often.
        """
        token_hash = _hash_token(token)
        if rate_limit:
            self._rate_limiter.check(token_hash)
        share = self._shares.get_share_by_token_hash(token_hash)
        if share is None:
            raise ShareNotFoundError("Unknown share token")
        if share.status == "revoked":
            raise ShareInactiveError("This share has been revoked")
        expires_at = share.expires_at
        if expires_at is not None:
            # SQLite (unlike Postgres) drops tzinfo on round-trip; treat a naive
            # value as UTC, matching this codebase's storage convention everywhere.
            if expires_at.tzinfo is None:
                expires_at = expires_at.replace(tzinfo=datetime.timezone.utc)
            if expires_at <= datetime.datetime.now(datetime.timezone.utc):
                raise ShareInactiveError("This share has expired")
        self._shares.touch_last_access(share.id)
        # touch_last_access opens its own session (repo is factory-backed), so the
        # object above never sees the update it just made - re-fetch for a caller
        # that actually reflects the new last_access_at.
        refreshed = self._shares.get_share(share.id)
        return refreshed if refreshed is not None else share

    # -- the one query every HTML/CSV/XLSX render calls --------------------------------

    def query_catalog(self, share: SharedCatalogView) -> list[dict[str, object]]:
        """Apply ``share.filter_definition``, project to ``share.field_whitelist``.

        Only understands the build plan's "Standardfilter" shape today
        (``{"tag": ..., "status": ..., "active": ...}``) — a richer filter DSL is a
        future extension, not needed for the first dealer-share use case.
        """
        filters = share.filter_definition or {}
        status = str(filters.get("status") or "live")
        active = bool(filters.get("active", True))
        tag_code = filters.get("tag")

        products = self._products.list_products(ProductFilter(status=status, active=active))

        tag_id: uuid.UUID | None = None
        if tag_code:
            tag = self._products.find_tag_by_code(str(tag_code))
            tag_id = tag.id if tag is not None else None
            if tag_id is None:
                return []  # tag doesn't exist -> nothing can match, not an error

        uvp_price_list = self._products.get_price_list_by_code("RETAIL_EUR")
        b2b_price_list = (
            self._products.get_price_list(share.price_list_id)
            if share.price_list_id is not None
            else self._products.get_price_list_by_code("B2B_EUR")
        )

        rows: list[dict[str, object]] = []
        for product in products:
            if tag_id is not None:
                product_tag_ids = {t.tag_id for t in self._products.list_product_tags(product.id)}
                if tag_id not in product_tag_ids:
                    continue

            variant = self._products.get_default_variant(product.id)
            available = bool(variant is not None and variant.active)

            cover_url: str | None = None
            for asset in self._products.list_assets(product.id):
                if asset.role == "COVER" and asset.storage_kind != "NETWORK_PATH":
                    cover_url = asset.uri
                    break

            isbn: str | None = None
            for identifier in self._products.list_identifiers(product_id=product.id):
                if identifier.scheme in ("ISBN13", "ISBN10"):
                    isbn = identifier.value
                    break

            price_uvp = self._current_gross_price(variant, uvp_price_list)
            price_b2b = self._current_gross_price(variant, b2b_price_list)

            row = SharedCatalogRow(
                sku=product.sku,
                name=product.name,
                isbn=isbn,
                description=product.short_description or product.description,
                cover_url=cover_url,
                price_uvp=price_uvp,
                price_b2b=price_b2b,
                available=available,
            )
            rows.append(row.whitelisted([str(f) for f in share.field_whitelist]))
        return rows

    def record_export(
        self, share: SharedCatalogView, *, export_format: str, row_count: int
    ) -> ExportLog:
        query_hash = hashlib.sha256(
            f"{share.id}:{share.filter_definition}:{share.field_whitelist}".encode("utf-8")
        ).hexdigest()
        return self._shares.record_export(
            shared_view_id=share.id,
            export_format=export_format,
            row_count=row_count,
            query_hash=query_hash,
        )

    def _current_gross_price(
        self, variant: ProductVariant | None, price_list: PriceList | None
    ) -> str | None:
        if variant is None or price_list is None:
            return None
        for price in self._products.list_prices(variant.id):
            if price.price_list_id == price_list.id and price.valid_until is None:
                if price.gross_amount is None:
                    return None
                return f"{Decimal(price.gross_amount):.2f}"
        return None
