"""Minimal, secure-by-default FastAPI foundation for the Content Studio."""
from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
import secrets

from fastapi import Depends, FastAPI, HTTPException, status
from fastapi.responses import HTMLResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from xw_office import __version__
from xw_office.content import BrandProfile, BrandProfileCatalog

_REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
_bearer = HTTPBearer(auto_error=False)


@dataclass(frozen=True)
class ContentWebSettings:
    """Small environment boundary for the Phase-1 web service."""

    bootstrap_token: str = ""
    public_url: str = "http://127.0.0.1:8000"
    environment: str = "development"
    brand_config_path: Path = _REPOSITORY_ROOT / "config" / "content_brands.yaml"

    @classmethod
    def from_environment(cls) -> "ContentWebSettings":
        return cls(
            bootstrap_token=os.getenv("XW_CONTENT_BOOTSTRAP_TOKEN", "").strip(),
            public_url=os.getenv("XW_CONTENT_PUBLIC_URL", "http://127.0.0.1:8000").strip(),
            environment=os.getenv("XW_CONTENT_ENVIRONMENT", "development").strip(),
        )


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
