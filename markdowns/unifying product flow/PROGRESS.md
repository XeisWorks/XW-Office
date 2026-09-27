# Unified Product Flow – Fortschritt

## T08 – OneDrive (2026-09-27)

- Erledigt: serverseitiger Graph-Zugriff mit langlebigen Drive-/Item-IDs,
  Root-Grenzpruefung und privatem Ordner-Browser im fortsetzbaren Produktentwurf.
- Sicherheit: Browser und API liefern ausschliesslich Metadaten; keine Graph-Token,
  Download-URLs oder oeffentlichen PDF-Links. Elemente ausserhalb des konfigurierten
  Root-Unterbaums werden abgewiesen.
- Lokale Tests: 8 gezielte Tests fuer Graph-Client, Asset-Service und die
  geraeteunabhaengige OneDrive-Pfadauflösung; Ruff und Web-Produktionsbuild bestanden.
- Produktionschecks: Graph-Root lesbar, 24 Root-Eintraege gelistet und eine private
  Datei erfolgreich gelesen (64.844 Bytes). Es wurden keine Datei-IDs oder Inhalte geloggt.

## Offener Infrastrukturpunkt fuer T09

- Status: erledigt am 2026-09-27 durch einen neuen, bucket-spezifischen R2-Token.
- Cloudflare R2 ist erreichbar, aber der hinterlegte Zugriffsschluessel verweigert
  `PutObject` und `DeleteObject`. Der kontrollierte Test hat kein Objekt hinterlassen.
  Fuer die persistente Render-Pipeline braucht der R2-API-Token mindestens Object
  Read & Write fuer den vorgesehenen Bucket.

## T09 – Asset-Auftraege und Beispielseiten (2026-09-27)

- Erledigt: persistente, idempotente Sample-Page-Jobs mit Rezept-Hash aus
  OneDrive-Quellversion, Seitenauswahl, optionalem Wasserzeichen und Renderer-Version.
  Der bestehende Outbox-Worker setzt fehlgeschlagene Jobs nach einem Neustart fort.
- Ausgabe: bestehender `SamplePageExportService` rendert auf 1000 px und maximal
  200 KB; Quelldateien und Zwischenbilder liegen ausschliesslich in einem temporaeren
  Verzeichnis. Fertige JPGs liegen privat in R2.
- Zugriff: nur authentifizierte Vorschau-Endpunkte fuer erzeugte `SAMPLE_SCORE`-Bilder;
  kein Endpoint liefert eine Quelldatei, einen R2-Link oder eine PDF aus.
- Tests: 20 gezielte Tests fuer Job-Deduplizierung, Outbox, Root-Schutz,
  Renderer und R2-Pfadbegrenzung bestanden; Web-Build und Ruff bestanden.
- Produktion: R2-Schreib-/Lese-/Löschtest erfolgreich, Deploy erfolgreich,
  Datenbankmigration `019_product_asset_jobs` auf Head und Healthcheck gruen.
