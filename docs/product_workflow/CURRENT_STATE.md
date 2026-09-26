# T01 – Iststand und Verbraucher

Stand: 2026-09-26
Geprüfter Stand: `main` bei `4ee2c54` (`unify products`); `git pull --ff-only origin main`
war ohne neue Commits. Diese Bestandsaufnahme führt keine Produkt- oder Provider-Schreibaktion aus.

## Belegte Produktquellen und Verbraucher

| Bereich | Aktueller Einstieg | Befund |
| --- | --- | --- |
| Hub-Stamm | `models/product_hub.py`, `repositories/product_hub.py`, Migrationen `009`–`017` | Persistenter Product Hub mit Produkt, Variante, Preis, Asset, Channel-Mapping, Alias sowie Sync-/Konflikt- und Inventar-Erweiterungen. Aktueller Alembic-Head: `017_wix_reconciliation_disposition`. |
| Hub-Web/API | `web/app.py`, `web/routers/products.py`, `web/product-hub/` | FastAPI und React/PWA lesen denselben Hub. Lesen ist per `XW_PRODUCT_HUB_CATALOG_READ_ENABLED` steuerbar; die Schreib-API ist standardmäßig aus (`XW_PRODUCT_HUB_EDIT_ENABLED=false`). |
| Desktop-Produkte | `ui/modules/products/view.py` | Die PySide-Ansicht liest und schreibt noch `InventoryService`/`ProductCatalogService`; sie ist noch kein Hub-API-Client und führt lokale Inventar- sowie Wix-/sevDesk-nahe Abläufe aus. |
| Legacy-Katalog | `services/products/catalog.py` | Liest `settings_kv`-Key `inventory.products` und titelbezogene Druckkonfigurationen; zudem existieren kompatible, externe Altdatei-Fallbacks. Dies ist parallel zum Hub und darf erst nach einer nachweisbaren Migration schreibgeschützt werden. |
| Inventar und Druck | `services/inventory/service.py`, `services/products/print_decision.py`, `services/printing/` | Bestandsbewegungen und Druckentscheidungen hängen weiter am settingsbasierten Inventar. PDF-Pfade werden über `core/shared_paths.py` lokal zwischen OneDrive-Windows-Profilen aufgelöst. Hub-`PRINT_PDF`-Assets sind derzeit auf `NETWORK_PATH` beschränkt. |
| Hub-Inventar | `services/product_hub/inventory.py`, `repositories/product_hub_inventory.py` | V2 ist als Shadow-Modus vorhanden; `inventory_master_enabled` ist standardmäßig aus. Die Desktop-Bridge ist in `bootstrap.py` nur bei `product_hub.inventory_shadow_enabled` aktiv. |
| Onboarding | `services/product_hub/onboarding.py`, Routen in `web/routers/products.py` | Der existierende Produkt-/Varianten-Wizard persistiert Hub-Daten, ruft danach aber unmittelbar sevDesk und Wix auf und speichert Mappings. Das verletzt den neuen Zielvertrag „Hub-Transaktion + Outbox vor Provider-Write“ und ist gezielt erst in T12 umzubauen. |
| Outbox | `models/product_hub_sync.py`, `repositories/product_hub_sync.py`, `services/product_hub/outbox_worker.py` | Transaktionale Events, Claiming, Retry/Backoff und Dead-Letter sind vorhanden. Der Web-Prozess registriert derzeit Wix- und Konflikt-Handler, aber Railway startet nur den Web-Prozess – keinen separaten dauerhaften Worker. |
| Wix- und Konflikt-Rückabgleich | `services/product_hub/wix_push.py`, `services/product_hub/wix_snapshot.py`, `services/product_hub/conflicts/` | Feldbezogener Wix-Push, Snapshots und Konfliktwizard existieren, alle produktiven Schreibpfade bleiben hinter Flags. sevDesk- und Amazon-Rückabgleich sind nicht gleichwertig implementiert. |
| Microsoft Graph | `services/mailing/graph_client.py` | Vorhanden ist ein MSAL-Device-Flow-Mailclient mit lokalem Token-Cache und Mail-Berechtigungen. Es gibt keinen serverseitigen OneDrive-DriveItem-Adapter, keine sichere serverseitige Tokenablage und keine persistente Drive-/Item-ID-Verknüpfung. |
| OpenAI | `services/product_hub/content_generation.py` | Ein Responses-API-Service erzeugt editierbare Beschreibungs-/Bullet-Drafts aus Hub-Feldern; der Entwurf schreibt nicht selbst. Die Prompt- und Kontextgrenzen aus dem neuen Bauplan sind in T15 nachzuschärfen. |

## Deployment und Betriebsgrenzen

`railway.toml` baut `Dockerfile.web`; `Procfile` und Container starten ausschließlich
Uvicorn für `xw_office.web.app`. Das Image enthält das gebaute Product-Hub-Webbundle,
nicht jedoch einen separaten Outbox-/Render-Worker oder private Font-/Asset-Ressourcen.
`/health` meldet aktuell Dienst und Version, aber weder DB-, Worker-, Graph- noch
Provider-Status. `DATABASE_URL`, die Hub-Flags und Wix/OpenAI/Graph-Secrets kommen aus
der Umgebung; reale Railway-Variablen und Providerzugänge wurden nicht ausgelesen oder
verändert.

## Konsequenzen für die Umstellung

1. T02 muss alle Einträge von `inventory.products`, Druckpfade, Titel-Overrides und SKU-Aliase gegen Hub-Produkte und Varianten abgleichen; mehrdeutige Treffer bleiben offen.
2. T03/T04 müssen einen versionierten Hub-Lesevertrag für Desktop-Druck und -Bestand liefern, bevor der alte Katalog deaktiviert wird. Rechnungs-, Bestands- und Druckabläufe bleiben bis dahin unverändert.
3. OneDrive, Cover-Fonts, dauerhaftes Asset-Rendering, der persistente Worker und reale Provider-/Graph-Einrichtung sind noch externe bzw. spätere Teilaufgaben. Es wurde keine Live-Funktion behauptet.
