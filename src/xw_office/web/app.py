"""Minimal, secure-by-default FastAPI foundation for the Content Studio."""
from __future__ import annotations

from collections.abc import Generator
from dataclasses import dataclass
import os
from pathlib import Path
import secrets
import uuid

from fastapi import Depends, FastAPI, HTTPException, status
from fastapi.responses import HTMLResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from fastapi.staticfiles import StaticFiles
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.responses import Response
from starlette.types import Scope

from xw_office import __version__
from xw_office.content import BrandProfile, BrandProfileCatalog
from xw_office.core.database import session_scope
from xw_office.repositories.product_hub import ProductHubRepository
from xw_office.repositories.product_hub_inventory import InventoryRepository
from xw_office.repositories.product_hub_sharing import SharingRepository
from xw_office.repositories.product_hub_sync import SyncRepository
from xw_office.services.product_hub.content_generation import ContentGenerationService
from xw_office.services.product_hub.editing import EditingService
from xw_office.services.product_hub.inventory import InventoryV2Service
from xw_office.services.product_hub.outbox_worker import OutboxWorker
from xw_office.services.product_hub.sharing import SharingService
from xw_office.services.product_hub.wix_push import WixPushService, wix_push_handler
from xw_office.services.wix.product_details_client import WixProductDetailsClient
from xw_office.web.routers.inventory import build_inventory_router
from xw_office.web.routers.products import build_products_router
from xw_office.web.routers.share_public import build_share_public_router
from xw_office.web.routers.sharing_admin import build_sharing_admin_router
from xw_office.web.routers.sync import build_sync_router

_REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
_bearer = HTTPBearer(auto_error=False)


class _EnvSecretSource:
    """Minimal ``SecretService``-shaped adapter reading straight from the process
    environment — this lean web service has no DB-backed encrypted secret store
    (that's desktop-only, see ``services/secrets/service.py``), and deliberately does
    *not* fall back to bare ``os.getenv`` inside ``WixProductDetailsClient`` itself
    (that was tried and reverted: it made the *shared* client's "no credentials"
    behavior depend on ambient env vars, breaking tests and risking picking up the
    wrong tenant's Wix credentials for any other caller constructed without this
    adapter). Passing this in explicitly keeps that opt-in and web-service-local."""

    def get_secret(self, name: str) -> str:
        return os.getenv(name, "").strip()


def _env_flag(name: str, *, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        return default
    return raw.strip().lower() in {"1", "true", "yes", "ja", "on"}


@dataclass(frozen=True)
class ContentWebSettings:
    """Small environment boundary for the Phase-1 web service."""

    bootstrap_token: str = ""
    public_url: str = "http://127.0.0.1:8000"
    environment: str = "development"
    brand_config_path: Path = _REPOSITORY_ROOT / "config" / "content_brands.yaml"
    #: Railway's internal Postgres URL. Empty means "no DB" — Product Hub endpoints
    #: then fail closed with 503, same pattern as the bootstrap token below.
    database_url: str = ""
    #: Kill switch independent of code changes; see docs/product_hub/ build-plan §4.
    #: Defaults to on *given* a configured database_url, since PR07 is the first
    #: consumer of `product_hub.catalog_read_enabled` — the desktop AppConfig's own
    #: copy of this flag (core/config.py) defaults to off for the same reason in
    #: reverse: nothing read it before this PR existed.
    product_hub_catalog_read_enabled: bool = True
    #: Separate kill switch for the PR09 edit API (PATCH/POST/PUT/DELETE routes) —
    #: defaults to *off*, unlike the read flag above, since this is the first
    #: write-capable HTTP surface this service exposes. Flip on deliberately once the
    #: WebUI editing flow has been exercised against a real deploy.
    product_hub_edit_enabled: bool = False
    #: PR11: gates WixPushService actually calling Wix (patch_product_field_with_
    #: conflict_detection). Defaults off, same reasoning as product_hub_edit_enabled —
    #: this is the first outbound-write channel this service has. When off,
    #: push_product() is a pure no-op (no HTTP calls), which is what the outbox
    #: worker needs so disabled-push events still resolve to a clean terminal state
    #: instead of retrying forever.
    sync_push_enabled: bool = False
    #: Built PR08 React/PWA bundle (`npm run build` output of web/product-hub/).
    #: Served same-origin at /app/ when present; absent in plain-API deployments
    #: and in most local dev setups, where the mount below is simply skipped.
    product_hub_web_dist: Path = _REPOSITORY_ROOT / "web" / "product-hub" / "dist"

    @classmethod
    def from_environment(cls) -> "ContentWebSettings":
        return cls(
            bootstrap_token=os.getenv("XW_CONTENT_BOOTSTRAP_TOKEN", "").strip(),
            public_url=os.getenv("XW_CONTENT_PUBLIC_URL", "http://127.0.0.1:8000").strip(),
            environment=os.getenv("XW_CONTENT_ENVIRONMENT", "development").strip(),
            database_url=os.getenv("DATABASE_URL", "").strip(),
            product_hub_catalog_read_enabled=_env_flag(
                "XW_PRODUCT_HUB_CATALOG_READ_ENABLED", default=True
            ),
            product_hub_edit_enabled=_env_flag("XW_PRODUCT_HUB_EDIT_ENABLED", default=False),
            sync_push_enabled=_env_flag("XW_PRODUCT_HUB_SYNC_PUSH_ENABLED", default=False),
            product_hub_web_dist=Path(
                os.getenv("XW_PRODUCT_HUB_WEB_DIST", "").strip()
                or (_REPOSITORY_ROOT / "web" / "product-hub" / "dist")
            ),
        )


class _SPAStaticFiles(StaticFiles):
    """Serves the built PR08 bundle, falling back to index.html for client-side
    routes (e.g. /app/products/<id>) so React Router - not a 404 - handles them."""

    async def get_response(self, path: str, scope: Scope) -> Response:
        try:
            return await super().get_response(path, scope)
        except StarletteHTTPException as exc:
            if exc.status_code == status.HTTP_404_NOT_FOUND:
                return await super().get_response("index.html", scope)
            raise


def _landing_page(settings: ContentWebSettings) -> str:
    protected = "konfiguriert" if settings.bootstrap_token else "noch nicht konfiguriert"
    return f"""<!doctype html>
<html lang=\"de\">
<head>
  <meta charset=\"utf-8\">
  <meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">
  <title>XeisWorks Content Studio</title>
  <style>
    :root {{ color-scheme: light; font-family: Inter, system-ui, sans-serif; }}
    body {{ margin: 0; background: #f4f1ea; color: #20221f; }}
    main {{ max-width: 44rem; margin: 0 auto; padding: 12vh 1.25rem 3rem; }}
    .eyebrow {{ color: #6a5224; font-weight: 700; letter-spacing: .08em; text-transform: uppercase; }}
    h1 {{ font-size: clamp(2.2rem, 9vw, 4.5rem); line-height: .96; margin: .4rem 0 1.25rem; }}
    p {{ font-size: 1.08rem; line-height: 1.65; }}
    .card {{ margin-top: 2rem; padding: 1.25rem; border: 1px solid #d6cbb6; border-radius: 1rem;
             background: rgba(255,255,255,.72); box-shadow: 0 .8rem 2.5rem rgba(64,48,20,.08); }}
    .status {{ display: inline-block; padding: .35rem .7rem; border-radius: 999px;
               background: #dcebd8; color: #244d27; font-weight: 700; }}
    a {{ color: #664814; }}
  </style>
</head>
<body>
  <main>
    <div class=\"eyebrow\">Phase 1 · Web-Fundament</div>
    <h1>XeisWorks<br>Content Studio</h1>
    <p>Die gemeinsame Weboberfläche für Content-Anlässe, Entwürfe und spätere Freigaben wird
       schrittweise aufgebaut. Operative Rechnungs- und Druckabläufe bleiben in XW-Office Desktop.</p>
    <section class=\"card\">
      <span class=\"status\">Dienst aktiv</span>
      <p>Der öffentliche Dienst enthält noch keine Geschäftsdaten. Der vorläufige API-Schutz ist
         <strong>{protected}</strong>.</p>
      <a href=\"/health\">Technischen Healthcheck öffnen</a>
    </section>
  </main>
</body>
</html>"""


def create_app(settings: ContentWebSettings | None = None) -> FastAPI:
    """Create an isolated app instance for Railway and tests."""
    resolved = settings or ContentWebSettings.from_environment()
    catalog = BrandProfileCatalog(resolved.brand_config_path)
    app = FastAPI(
        title="XeisWorks Content Studio API",
        version=__version__,
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
    )

    def require_bootstrap_token(
        credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
    ) -> None:
        expected = resolved.bootstrap_token
        if not expected:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Content API protection is not configured",
            )
        supplied = credentials.credentials if credentials is not None else ""
        if credentials is None or credentials.scheme.lower() != "bearer" or not secrets.compare_digest(
            supplied, expected
        ):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid or missing bearer token",
                headers={"WWW-Authenticate": "Bearer"},
            )

    # -- Product Hub (PR07): DB session factory, gated by database_url + the kill switch --

    _engine = create_engine(resolved.database_url, pool_pre_ping=True, future=True) if resolved.database_url else None
    _session_factory: sessionmaker[Session] | None = (
        sessionmaker(bind=_engine, autoflush=False, expire_on_commit=False, future=True)
        if _engine is not None
        else None
    )

    def require_product_hub_enabled() -> None:
        if _session_factory is None or not resolved.product_hub_catalog_read_enabled:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Product Hub API is not configured/enabled",
            )

    def get_product_repo() -> Generator[ProductHubRepository, None, None]:
        assert _session_factory is not None  # guarded by require_product_hub_enabled above
        with session_scope(_session_factory) as session:
            yield ProductHubRepository(session)

    def get_editing_service() -> EditingService:
        assert _session_factory is not None  # guarded by require_product_hub_enabled above
        return EditingService(_session_factory)

    def require_product_hub_edit_enabled() -> None:
        if not resolved.product_hub_edit_enabled:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Product Hub edit API is not enabled",
            )

    _content_generation_service = ContentGenerationService(
        api_key=_EnvSecretSource().get_secret("OPENAI_API_KEY")
    )

    def get_content_generation_service() -> ContentGenerationService:
        return _content_generation_service

    app.include_router(
        build_products_router(
            get_product_repo,
            get_editing_service,
            require_product_hub_edit_enabled,
            get_content_generation_service,
        ),
        dependencies=[Depends(require_bootstrap_token), Depends(require_product_hub_enabled)],
    )

    # -- Product Hub (PR11): Wix push + outbox worker --------------------------------

    _wix_client = WixProductDetailsClient(secret_service=_EnvSecretSource())  # type: ignore[arg-type]
    _wix_push_service = (
        WixPushService(
            _session_factory,
            wix_client=_wix_client,
            push_enabled=lambda: resolved.sync_push_enabled,
        )
        if _session_factory is not None
        else None
    )
    _outbox_worker = OutboxWorker(_session_factory) if _session_factory is not None else None
    if _outbox_worker is not None and _wix_push_service is not None:
        assert _session_factory is not None  # both constructed only when this holds
        _handler_repo = ProductHubRepository(_session_factory)
        _handler = wix_push_handler(_wix_push_service, _handler_repo)
        _outbox_worker.register_handler("product.updated", _handler)
        _outbox_worker.register_handler("price.changed", _handler)

    def get_sync_repo() -> Generator[SyncRepository, None, None]:
        assert _session_factory is not None  # guarded by require_product_hub_enabled below
        with session_scope(_session_factory) as session:
            yield SyncRepository(session)

    def get_outbox_worker() -> OutboxWorker:
        assert _outbox_worker is not None  # guarded by require_product_hub_enabled below
        return _outbox_worker

    def resolve_sync_conflict(conflict_id: uuid.UUID, resolution: str) -> None:
        assert _wix_push_service is not None  # guarded by require_product_hub_enabled below
        _wix_push_service.resolve_conflict(conflict_id, resolution=resolution)

    app.include_router(
        build_sync_router(get_sync_repo, get_outbox_worker, resolve_sync_conflict),
        dependencies=[
            Depends(require_bootstrap_token),
            Depends(require_product_hub_enabled),
            Depends(require_product_hub_edit_enabled),
        ],
    )

    # -- Product Hub (PR12): dealer sharing -------------------------------------------

    def get_sharing_service() -> SharingService:
        assert _session_factory is not None  # guarded by require_product_hub_enabled below
        return SharingService(
            ProductHubRepository(_session_factory), SharingRepository(_session_factory)
        )

    app.include_router(
        build_sharing_admin_router(get_sharing_service, public_base_url=resolved.public_url),
        dependencies=[
            Depends(require_bootstrap_token),
            Depends(require_product_hub_enabled),
            Depends(require_product_hub_edit_enabled),
        ],
    )
    app.include_router(
        build_share_public_router(get_sharing_service),
        dependencies=[Depends(require_product_hub_enabled)],
    )

    # -- Product Hub (PR13/PR14): Inventory V2 shadow mode ----------------------------

    def get_inventory_repo() -> Generator[InventoryRepository, None, None]:
        assert _session_factory is not None  # guarded by require_product_hub_enabled below
        with session_scope(_session_factory) as session:
            yield InventoryRepository(session)

    def get_inventory_service() -> InventoryV2Service:
        assert _session_factory is not None  # guarded by require_product_hub_enabled below
        return InventoryV2Service(_session_factory, public_base_url=resolved.public_url)

    app.include_router(
        build_inventory_router(
            get_inventory_repo, get_inventory_service, require_product_hub_edit_enabled
        ),
        dependencies=[Depends(require_bootstrap_token), Depends(require_product_hub_enabled)],
    )

    if resolved.product_hub_web_dist.is_dir():
        app.mount(
            "/app",
            _SPAStaticFiles(directory=resolved.product_hub_web_dist, html=True),
            name="product-hub-web",
        )

    @app.get("/", response_class=HTMLResponse, include_in_schema=False)
    def landing() -> str:
        return _landing_page(resolved)

    @app.get("/health", include_in_schema=False)
    def health() -> dict[str, str]:
        return {
            "status": "ok",
            "service": "xw-content-web",
            "version": __version__,
        }

    @app.get(
        "/api/v1/content/brands",
        response_model=list[BrandProfile],
        dependencies=[Depends(require_bootstrap_token)],
    )
    def list_brands() -> tuple[BrandProfile, ...]:
        return catalog.load()

    return app


app = create_app()
