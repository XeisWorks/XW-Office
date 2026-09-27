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
- Der vorherige Zugriffsschluessel verweigerte `PutObject` und `DeleteObject`; der
  neue Token mit Object Read & Write wurde danach erfolgreich per kontrolliertem
  Schreib-/Lese-/Löschtest verifiziert. Es gibt keinen offenen R2-Blocker.

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

## T10 – Vorlagenordner und Fontverwaltung (2026-09-27)

- Erledigt: Der Product Hub liest die versionierte `COVER_SPEC.yaml` zur
  Laufzeit, validiert die feste 1527×2047-zu-746×1000-Geometrie und verweigert
  Spezifikationen, die Karte, Schatten oder schwarzen Balken neu zeichnen
  wollten. Ein Hintergrund wird ausschliesslich proportional skaliert; ein
  inkompatibles Seitenverhaeltnis wird erklaert statt gestreckt.
- Sicherheit: Die authentifizierten Cover-Endpunkte listen nur Vorlagen aus dem
  explizit konfigurierten OneDrive-Unterordner. Miniaturen werden serverseitig
  aus dem Bild abgeleitet und mit `private, no-store` ausgeliefert; weder Graph-
  Token, Download-URLs noch das Originalbild gelangen in den Browser.
- Bedienung: Der fortsetzbare Entwurf zeigt Miniaturen, speichert nur die
  stabile Vorlagen-ID, ETag und Metadaten und bleibt auch bei fehlenden
  Schriften speicherbar. Die UI erklaert dann klar, dass der Coverexport
  blockiert ist.
- Fonts: Private TTF/OTF-Dateien werden nur ueber ihre eingebettete
  Familienmetadaten geprueft. Die laut Spec verlangten Familien `Book Antiqua`
  und `Deneane` werden nicht durch Systemfonts ersetzt.
- Betrieb: `Dockerfile.web` nimmt ausschliesslich die geometrische
  `COVER_SPEC.yaml` ins Laufzeitimage auf, niemals Vorlagen oder Fontdateien.
  In Railway fehlen weiterhin die bewusst nicht versionierten Werte
  `XW_COVER_TEMPLATE_FOLDER_ID` und `XW_COVER_FONT_FOLDER_ID`; bis zu deren
  Einrichtung antwortet die Cover-API kontrolliert mit Konfigurationsfehler.
- Tests: 25 gezielte Python-Tests fuer Cover, OneDrive, Assets, Render-Jobs und
  Sample-Renderer bestanden; Ruff, Compileall, TypeScript, ESLint, Vitest
  (7 Tests) und der Vite-Produktionsbuild bestanden.
- Naechster Task: T11 – Textlayout und Vorschau. Dafuer fehlen noch die echte
  Cabernet-Referenz samt den privaten Fonts fuer den verpflichtenden visuellen
  Vergleich; es wurde kein Provider-Write und kein Produkt-Test erzeugt.

## T11 – Textlayout und Vorschau (2026-09-27, Implementierung erledigt; Abnahme offen)

- Renderer: Der Server erzeugt eine private JPG-Vorschau ausschliesslich aus
  dem gewaehlten OneDrive-Hintergrund und den per eingebetteter Familienmetadaten
  verifizierten privaten Fonts. Feste Boxen, Punkt-zu-Pixel-Konvention,
  Breiten-/Hoehenpruefung, Titelumbruch bis drei Zeilen, Unterstreichung und
  die kontrollierte Kapitaelchen-Behandlung folgen `COVER_SPEC.yaml`. Es gibt
  weder Systemfont-Fallback noch nachgezeichnete Karte, Schatten oder Balken.
- API/UI: `POST /api/v1/covers/preview` akzeptiert nur Text und eine bereits
  konfigurierte Vorlagen-ID, gibt ausschliesslich `private, no-store`-JPGs
  zurueck und blockiert bei fehlenden Fonts nachvollziehbar. Der Wizard
  speichert Komponist:in, Arrangeur:in und Edition im Draft und ruft denselben
  Renderer fuer die Browservorschau auf. Die ausgewählte Besetzung liefert nur
  einen editierbaren Editionsvorschlag und überschreibt keine manuelle Eingabe.
- Tests: 9 gezielte Cover-Tests bestanden (einschliesslich fehlender Fonts,
  realer Laufzeitfont als Testeingabe, Umlaut/Apostroph und privater
  Preview-Antwort); Ruff und Compileall sowie ESLint, TypeScript und
  Vite-Produktionsbuild bestanden.
- Abnahmeblocker: Weder lokale `.env` noch Railway enthalten die privaten
  Cover-/Font-Ordner-IDs, und die Cabernet-Referenz ist nicht im Repo. Deshalb
  bleibt T11 `in_progress`: Der visuelle Cabernet-Vergleich und die Abnahme
  von 1/2/3 Zeilen mit den echten kommerziellen Fonts stehen noch aus. Es
  wurden keine Provider-Writes ausgefuehrt.
