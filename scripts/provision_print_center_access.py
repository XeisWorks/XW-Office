"""Provision a least-privilege Railway login; store its URL only in local .env."""
from __future__ import annotations

import argparse
import logging
import os
from pathlib import Path
import secrets

from dotenv import set_key
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url

from xw_office.core.config import load_config

logger = logging.getLogger(__name__)
ROLE = "xw_print_center"
VARIABLE = "XW_PRINT_CENTER_DATABASE_URL"
OFFICIAL_TABLES = ("setting_kv", "product", "product_variant", "product_asset", "print_rule")


def provision_access(env_path: Path) -> None:
    if not env_path.is_file():
        raise ValueError("Die lokale .env fehlt. Bitte zuerst XW-Office konfigurieren.")
    config = load_config()
    if not config.database_url:
        raise ValueError("Die Office-Datenbank ist nicht konfiguriert.")
    engine = create_engine(config.database_url, pool_pre_ping=True, hide_parameters=True)
    if engine.dialect.name != "postgresql":
        engine.dispose()
        raise ValueError("Das eingeschraenkte Druckcenter-Konto benoetigt PostgreSQL.")
    existing_url = os.getenv(VARIABLE, "").strip()
    created = False
    try:
        with engine.begin() as connection:
            exists = connection.scalar(
                text("SELECT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = :name)"),
                {"name": ROLE},
            )
            if exists:
                if not existing_url:
                    raise ValueError(
                        "Das Druckcenter-Konto existiert bereits. Die zugehoerige URL muss "
                        "sicher in der lokalen .env hinterlegt werden; das Passwort wird "
                        "nicht automatisch rotiert."
                    )
                url = make_url(existing_url)
                if (
                    url.username != ROLE or url.host != engine.url.host
                    or url.port != engine.url.port or url.database != engine.url.database
                ):
                    raise ValueError("Die Druckcenter-URL passt nicht zur Office-Datenbank.")
            else:
                password = secrets.token_urlsafe(40)
                connection.execute(
                    text(f"CREATE ROLE {ROLE} LOGIN PASSWORD :password"),
                    {"password": password},
                )
                url = engine.url.set(username=ROLE, password=password)
                created = True
            connection.execute(text(f"GRANT USAGE ON SCHEMA public, print_center TO {ROLE}"))
            for table in OFFICIAL_TABLES:
                connection.execute(text(f"GRANT SELECT ON TABLE public.{table} TO {ROLE}"))
            connection.execute(text(f"REVOKE INSERT, UPDATE, DELETE ON public.setting_kv FROM {ROLE}"))
            # SECURITY DEFINER constrains the standalone account to the one
            # settings key consumed by the central product-print pipeline.
            connection.execute(text("""
                CREATE OR REPLACE FUNCTION public.xw_print_center_set_inventory_products(payload text)
                RETURNS void
                LANGUAGE sql
                SECURITY DEFINER
                SET search_path = pg_catalog, public
                AS $function$
                    INSERT INTO public.setting_kv (key, value_json)
                    VALUES ('inventory.products', payload)
                    ON CONFLICT (key) DO UPDATE
                    SET value_json = EXCLUDED.value_json, updated_at = CURRENT_TIMESTAMP
                $function$
            """))
            connection.execute(text(
                "REVOKE ALL ON FUNCTION public.xw_print_center_set_inventory_products(text) FROM PUBLIC"
            ))
            connection.execute(text(
                f"GRANT EXECUTE ON FUNCTION public.xw_print_center_set_inventory_products(text) TO {ROLE}"
            ))
            connection.execute(text(
                f"GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE print_center.article TO {ROLE}"
            ))
        restricted = create_engine(url, pool_pre_ping=True, hide_parameters=True)
        try:
            with restricted.connect() as connection:
                for table in OFFICIAL_TABLES:
                    writable = connection.scalar(text(
                        "SELECT has_table_privilege(current_user, :table, 'INSERT') "
                        "OR has_table_privilege(current_user, :table, 'UPDATE') "
                        "OR has_table_privilege(current_user, :table, 'DELETE')"
                    ), {"table": f"public.{table}"})
                    if writable:
                        raise ValueError(f"Das Druckcenter-Konto hat Schreibrechte auf {table}.")
                if not connection.scalar(text(
                    "SELECT has_function_privilege(current_user, "
                    "'public.xw_print_center_set_inventory_products(text)', 'EXECUTE')"
                )):
                    raise ValueError("Schreibrecht fuer zentrale Druckkonfigurationen fehlt.")
                for permission in ("SELECT", "INSERT", "UPDATE", "DELETE"):
                    if not connection.scalar(text(
                        "SELECT has_table_privilege(current_user, 'print_center.article', :permission)"
                    ), {"permission": permission}):
                        raise ValueError("Schreibrechte fuer eigene Druckartikel fehlen.")
        finally:
            restricted.dispose()
        set_key(str(env_path), VARIABLE, url.render_as_string(hide_password=False))
        logger.info(
            "Druckcenter-Konto %s; Druckkonfigurationen und eigene Artikel read/write, "
            "uebrige offizielle Tabellen readonly. "
            "Verbindungsdaten wurden nur in der lokalen .env gespeichert.",
            "angelegt" if created else "geprueft",
        )
    finally:
        engine.dispose()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--apply", action="store_true",
        help="Konto/Grants auf Railway anlegen und die lokale .env aktualisieren.",
    )
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO)
    if not args.apply:
        parser.error("Die Provisionierung benoetigt die ausdrueckliche Option --apply.")
    root = Path(__file__).resolve().parent.parent
    provision_access(root / ".env")


if __name__ == "__main__":
    main()
