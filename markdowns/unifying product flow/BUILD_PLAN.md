# XW Product Workflow – verbindlicher Bauplan
Stand: 26.09.2026. Auftrag: Planungsdateien für Codex 5.6 Luna; noch keine Implementierung oder Veröffentlichung.

## 1. Ziel und bestätigte Entscheidungen
Ein Product Hub mit einer zentralen API ist der einzige schreibende Produktstamm. React-WebUI und PySide6 greifen darauf zu. Der Anlage-Wizard wird einmal in React gebaut und aus PySide6 eingebettet oder im Systembrowser geöffnet. Lokales Drucken und lokale Dateiauflösung bleiben native Funktionen. Die alte parallele Produktpflege wird nach überprüfter Migration stillgelegt.

Produktanlage funktioniert bei ausgeschaltetem Büro-PC. OneDrive bleibt die Quelle der Noten. Der Server liest ausgewählte Dateien über Microsoft Graph. Ein Produkt kann von Grund auf, aus einer Vorlage oder durch Kopieren entstehen. Erste Vorlagen: Mnozil-Einzeltitel, MusikHeroes-Heft, Zusatzstimme. Brutto-EUR-Preis je verkaufbarer Variante; Netto abgeleitet mit Decimal und bestehender Steuerlogik. Steuersätze sind bestätigte Vorlagenwerte, keine automatische steuerliche Klassifikation. SKU vorschlagen und editierbar halten.

Variante bedeutet Wix-Produktoption, insbesondere Besetzung, mit eigener SKU und eigenem Preis. Nicht pauschal mit physisch/digital gleichsetzen. Beispiel aus Screenshot: Cabernet Polka, Besetzung Blechhauf’n, XW-457, 27,90 EUR; Kleine Besetzung, XW-6015, 31,90 EUR. Diese Werte sind historische Referenzen, kein Auftrag für SKU-Umbenennungen. Der Screenshot beweist nicht die Wix-Parent-ID: bestehende IDs vor Zusammenfassung live lesen.

Beispielseiten: anklickbare PDF-Miniaturen, je Seite Wasserzeichen wählbar, 1000 px Zielhöhe und maximal 200 KB JPG. Cover ausschließlich Shopbild; vorhandener Hintergrund enthält Schild, Schatten und schwarzen Balken. Nur Text darüberlegen. Hintergründe aus konfigurierbarem Ordner mit Miniaturen auswählen. OpenAI darf Beschreibungen aus bestätigten Daten vorschlagen. Externe Änderungen werden zum Rückabgleich angeboten. Amazon später inklusive neuer Artikel, ausschließlich Deutschland.

## 2. Geprüfte Ausgangsbasis
XW-Office untersucht bei 4c8280e8127b3c56ee695e3aa300dd44a903c6f6. Main erneut geprüft: aff6b85e54be3a5fb7eed88812225ec702ed3084; der zusätzliche Commit ändert nur Sendungsdialog und dessen Test. Legacy sevDesk: 0e15a691fccdbf0c027235780807f0a6e9c58403. Live-Deployment, Zugangsdaten und aktive Wix-Katalogversion wurden nicht verifiziert.

| Einstieg | Verwendung |
|---|---|
| src/xw_office/ui/modules/products/view.py | Alte Desktop-Produkteansicht und direkte Provider-Aufrufe ablösen |
| src/xw_office/services/products/catalog.py | Settings-basierter Katalog, Druckauflösung und Kompatibilität gezielt migrieren |
| src/xw_office/models/product_hub.py | Bestehende Produkte, Varianten, Preise, Assets und ChannelMappings erweitern |
| src/xw_office/repositories/product_hub.py | Bestehende Persistenz wiederverwenden |
| src/xw_office/services/product_hub/onboarding.py | Bestehende Anlage in Hub/sevDesk/Wix in dauerhafte Aufträge überführen |
| src/xw_office/services/product_hub/outbox_worker.py | Vorhandene Outbox erweitern, keinen zweiten Sync-Worker erfinden |
| src/xw_office/services/product_hub/wix_push.py | Bisher name/description/price/visible; künftig feldgenaue Kanaladapter |
| src/xw_office/services/product_hub/conflicts/service.py | Vorhandene Konfliktfälle und Entscheidungen wiederverwenden |
| src/xw_office/services/product_hub/content_generation.py | Vorhandenen OpenAI-httpx-Responses-Service verwenden |
| src/xw_office/services/wix/product_details_client.py | V1/V3-Erkennung, Anlage und Variantenpflege wiederverwenden |
| src/xw_office/web/routers/products.py | API integrieren |
| web/product-hub/src/pages/ProductOnboardingPage.tsx | Bestehenden Wizard erweitern |
| web/product-hub/src/pages/VariantOnboardingPage.tsx | Optionen/Varianten mit gemeinsamem Wizard harmonisieren |
| src/xw_office/services/layout/sample_pages_service.py | PyMuPDF/JPG/Wasserzeichen-Renderer extrahieren bzw. wiederverwenden |
| sevDesk: sevdesk_wix_fulfillment/graphics/cover_creator.py | Nur Renderideen übernehmen; feste Fonts/Layout und doppelte Hintergrundformen ersetzen |

Die Bestandsdokumentation verlangt Outbox-Writes, die aktuelle Neuanlage schreibt jedoch direkt zu Providern. Diese Abweichung gezielt schließen. Ein vorhandenes ChannelMapping bedeutet bislang teilweise schon „synced“: künftig tatsächlichen Readback und bestätigte Felder verlangen.

## 3. Architektur und Datenvertrag
React und Desktop sprechen dieselbe authentifizierte Hub-API an. Nur Backend/Worker schreiben Produktdaten und Provider. Keine produktbezogenen Direktwrites aus Desktop oder zweite schreibende Settings-Liste. Ein Offline-Lesecache ist möglich, Offline-Änderungen sind nicht Teil dieser Version.

Bestehende Tabellen erweitern, keine Parallelwelt: Produkt = gemeinsame Redaktion; Option = z.B. Besetzung; OptionValue = konkrete Auswahl; Variante = verkaufbare Kombination mit stabiler UUID, SKU, Brutto/Netto/Steuer und eigenen Assets. Vorhandene Familienbeziehungen beibehalten. Jede Variante erhält ihr sevDesk-Part-Mapping; Wix-Parent- und Variant-ID getrennt führen. Mehrere Wix-Parents innerhalb einer Familie erlauben, wo Produkttypgrenzen das erfordern. Kombinationen gezielt auswählen; nicht ungefragt das ganze kartesische Produkt anlegen.

Draft enthält current_step, schema_version, row_version, completed_steps und Daten. Autosave mit Version/If-Match, 409 bei veraltetem Stand; niemals ältere Antworten über neuere Eingaben schreiben. Unvollständige Entwürfe zulassen; Publish-Validierung separat. SKU-Eindeutigkeit atomar in DB prüfen; Vorschläge sind keine Reservierung. Bestehende Aliasregeln erhalten, keine erneute globale SKU-Normalisierung.

Kopieren: Produkttexte, Optionen und Vorlageneinstellungen übernehmen; neue UUIDs und SKUs, keine Channel-IDs, Synczustände, ASIN-Zuordnungen, Bestände oder Audit-Historie. Assets nur als ausdrücklich gewählte Referenzen übernehmen, fertiges Cover als zu erneuern kennzeichnen. Ein neues Produkt darf beim Kopieren nicht versehentlich die externen Originale verändern.

## 4. OneDrive und Assets
Ein Windows-Pfad ist keine Serveradresse. Pro Datei persistieren: provider=onedrive, drive_id, item_id, etag, checksum_sha256, relative_path und original_filename. Keine kurzlebige downloadUrl als dauerhafte Identität. IDs bevorzugen; Pfad zum erstmaligen Auflösen/Anzeigen. Bei Verschieben innerhalb desselben Drives ID prüfen; bei Drivewechsel explizit neu zuordnen. Kein ratenweises Matching nur nach Dateiname.

Lokaler Standardroot: OneDrive - XeisWorks. Relative Referenz z.B. 02 XeisWorks/05 Noten/07 da Blechhaufn/30er-Polka BH .pdf. Leerzeichen vor .pdf erhalten. Root über vorhandenen Shared-Path-Resolver, OneDrive-Umgebungsvariable oder konfigurierten Gerätepfad ermitteln. Benutzer bernh, Bernhard Holl, XeisWorks als begrenzte Migrationskandidaten unterstützen, nicht als dauerhafte ID verwenden. Bei mehreren Treffern nicht still wählen. Lokales Files-on-Demand vor Druck prüfen/hydrieren; Server benötigt keine lokale Synchronisierung.

Bestehende Microsoft-Anmeldung/Graph-Integration zuerst prüfen; Desktop-Tokencache nicht blind auf Server kopieren. Serverseitigen delegierten OAuth-Zugriff mit minimal passenden Leserechten, geschützter Tokenablage, Refresh und Reconnect einrichten. Browser erhält keine Graph-Secrets. Zugriff auf ausgewählte Noten-/Coverordner begrenzen. Graph-Dateidownloads kurzzeitig privat für Renderer puffern; Cache nach Ablauf löschen. Abgeleitete Bilder dauerhaft im bereits vorhandenen geeigneten Asset-Speicher halten; falls nicht vorhanden, konfigurierbaren privaten Objektspeicher mit separater Freigabe für Shopbilder vorsehen. Kein neues dauerhaftes Voll-PDF-Archiv als Standard.

Rollen: PRINT_PDF (privat), DOWNLOAD_FILE (explizit für Käufer), SAMPLE_PAGE und COVER (nach Bestätigung für Shop), COVER_BACKGROUND (Vorlage), WATERMARK. Die bisherige NETWORK_PATH-Regel für PRINT_PDF bewusst additiv um ONEDRIVE erweitern; bestehende Pfade kompatibel halten. Authentifizierte kurzlebige PDF-Preview ist neu erlaubt; öffentliche Share-Routen dürfen vollständige Noten weiter nicht ausliefern. Digitale Verkaufsdateien niemals automatisch aus PRINT_PDF veröffentlichen.

Asset-Aufträge erhalten Hash aus Quelldateiversion, Rezept, Renderer- und Fontversion. Gleicher Auftrag verwendet Ergebnis wieder. Neue PDF-Version markiert alte Ableitungen als veraltet, ersetzt aber nicht ungefragt veröffentlichte Bilder. Unterstützen: OneDrive-Auswahl und expliziter temporärer Browserupload. Letzterer ist keine dauerhafte OneDrive-Verknüpfung und erhält eine klare Quellenanzeige.

## 5. Wizard und Bedienung
0 Start: Neu / Kopieren / Vorlage, optionale Zielkanäle.
1 Stammdaten: title_full/title_short/code_short nach vorhandenen Regeln, Komponist, Arrangeur, Marke, Besetzung und weitere bestätigte Musikattribute.
2 Optionen: Namen/Werte und gewählte Kombinationen, SKU und Bruttopreis pro Variante. Gemeinsame Angaben vererbbar, Abweichungen sichtbar.
3 PDF/Medien: Datei je Produkt/Variante wählen, Miniaturen anklicken, Wasserzeichen wählen, Coverhintergrund und Texte prüfen. Vorschau und Export stammen vom selben Renderer.
4 Wix: gemeinsame und abweichende Variantendarstellung, Beschreibung, Marke, Kategorien/Collections, Infobereiche, Hörprobe/Playalong-Link, SEO, Bildreihenfolge/Alttexte. Bestehende Kategorien abrufen, interne Kategorien getrennt mappen.
5 sevDesk: Kategorie/Einheit aus echten Optionen, Artikeltext, Steuersatz und berechneter Preis, Bestandsverhalten. Nicht einfach stockEnabled=false als Beweis für digital benutzen.
6 Prüfen: Zielsysteme, Pflichtfelder, Medienstatus und Änderungen vorführen. Standard Wix verborgen. „Anlegen“ startet dauerhafte Aufträge und zeigt pro Kanal und Variante Ergebnis.
7 Abschluss: Wix-Editor / Shop / sevDesk öffnen, „Externe Änderungen abgleichen“. Öffentliche Shop-Links erst als öffentlich erreichbar bezeichnen, wenn sichtbar/verifiziert. Kein automatisches Social-Posting.

OpenAI: vorhandenen ContentGenerationService erweitern. Kontext aus bestätigten Feldern, u.a. Besetzung. Keine erfundenen Schwierigkeitsgrade, Dauer, enthaltenen Stücke oder Rechte. Die vorhandene Prompt-Ausnahme „allgemein ... üblich“ entfernen. Vorschläge editierbar und separat übernehmen; vorhandene Texte bei API-Fehler behalten. Keine Voll-PDFs ungefragt für Textgenerierung senden.

## 6. Cover exakt nach Vorgaben
Siehe COVER_SPEC.yaml und Referenzbilder. Originalvorlage 1527 x 2047, Referenzexport 746 x 1000. Hintergrund proportional auf 1000 px Höhe skalieren; kein Strecken. Schild, Schatten, Balken NICHT zeichnen. Einheitlicher Textanker für alle Vorlagen; inkompatible Vorlagen melden.

Book Antiqua tatsächlich über geladene Font-Metadaten prüfen, nicht über den legacy-Dateinamen BOOKOS.TTF vermuten. Deneane ebenfalls prüfen. Fontdateien fehlen im Anhang: als private Laufzeitressourcen konfigurieren. Ohne passende Fonts darf ein Entwurf gespeichert werden, Coverexport meldet aber „Schrift fehlt“ statt stillen Ersatz. Keine kommerziellen Fonts in öffentliches XW-Office-Repo committen.

Kapitälchen sind keine reinen Großbuchstaben: echte OpenType-smcp/c2sc-Unterstützung verwenden, falls verfügbar; sonst kontrolliert verkleinerte Großbuchstaben für ursprüngliche Kleinbuchstaben mit vereinheitlichter Grundlinie. Quelldaten in normaler Schreibweise behalten. Label „Arrangement:“ mit Unterstreichung; Edition weiß auf vorhandenem Balken.

Punktwerte benötigen eine definierte Rasterkonvention. Start: virtuelle 96 dpi bei 1000 px Referenzhöhe; renderer_px = pt * 96/72 * output_height/1000 * template_calibration. Referenzvergleich zur endgültigen Kalibrierung verpflichtend; die gewünschten pt-Werte nicht still verändern. Positionen in YAML sind aus Bildern abgeleitete Startwerte, keine vermeintlich pixelgenau gemessene Freigabe.

Titel einzeilig 36 pt, für zwei/drei Zeilen Startwerte 31/26 pt (Implementierungsvorschlag). Manuelle Zeilenumbrüche priorisieren. Text nach echter Glyphenbreite UND Gesamthöhe in fester Titelbox einpassen; keine Überschneidung mit Komponist/Arrangement/Edition. Bis drei Zeilen, ab Mindestgröße klarer Hinweis statt Abschneiden. Zentrieren mit tatsächlichen Bounding-Box-Offsets. Lange Komponisten/Arrangeure ebenfalls in eigenen Boxen prüfen.

## 7. Kanalsynchronisation und Rückabgleich
Hub-Transaktion speichert Daten und Outbox gemeinsam. Jobtypen für Ensure-Produkt, Varianten, Upload-Medien, Kategorien, Inhalte und Readback. Eindeutiger Jobschlüssel aus Draft/Product, Channel, Operation und gewünschter Revision. Pro Entity serialisieren. Remote-Erfolg und lokales Mapping sind nicht atomar: bei Timeout nach möglichem Erfolg erst providerseitig eindeutig nachsehen; keinen blinden zweiten Create. Mehrdeutige SKU-Treffer werden Konfliktfälle. Retry mit Backoff, Dead-Letter und sichtbarem Fortsetzen.

Wix-V1/V3-Adapter strikt nach erkannter Site-Version wählen. V1 digitale Neuanlage nicht simulieren. V3 benötigt für verkaufbare Digitalprodukte zugeordnete digitale Datei; Produktanlage allein reicht nicht. V3-Bestand separat berücksichtigen. Produktoptionen und Varianten atomar soweit Provider möglich aktualisieren; bestehende Varianten-IDs erhalten. Kein löschen/neu anlegen als Standard. Medienupload fertigstellen/pollen, dann zuordnen. Je Variante eigenes Cover; falls Katalog konkrete Zuweisung nicht unterstützt, Gallery plus erklärter manueller Schritt.

sevDesk: ein Part je verkaufbarer SKU; Kategorien und Unity-IDs echt auflösen statt unity=1 ungeprüft übernehmen. Nach Create/Patch zurücklesen und Preise/Steuer/Kategorie/Einheit prüfen. Keine historische Rechnungsänderung. Bestandsführung aus vorhandener Hub-Inventory-Architektur übernehmen; nicht im Wizard neue Bestandslogik duplizieren.

Feldregeln: Hub führt gemeinsame Stammdaten, SKU und Standardpreis; explizite Kanalüberschreibungen für Text/Preis möglich. Wix ist Quelle für Kanalstatus/URLs; sevDesk für Part-ID. Externe Änderungen via Drei-Wege-Vergleich: letzter bestätigter Snapshot / Hub-Wunsch / aktueller Provider. Gleichzeitige Änderungen -> vorhandener Konfliktwizard. Entscheidungen „extern übernehmen“, „Hub senden“, „bewusste Kanalabweichung“. Ein Mapping oder HTTP 200 allein ist kein vollständiger Syncnachweis.

Editor-Links aus getesteter konfigurierbarer Site-/Produkt-ID-Strategie, keine erfundenen Deep Links. Aktuelle Wix-/sevDesk-Links einmal mit realem Produkt prüfen; Fallback auf Übersicht + SKU kopieren. Wix selbst übernimmt „Produkt bewerben“; der Hub postet nicht eigenmächtig.

## 8. Migration und Betrieb
Inventur vor Umstellung: Produktzahlen, SKUs, Aliase, Channel-IDs, Druckpfade, Profile, Titel-spezifische Druckkonfigurationen, Bestände und Verbraucher der alten Services erfassen. Settings-Katalog zu bestehenden Hub-IDs matchen, Konflikte in Queue; keine pauschalen Überschreibungen. Druckadapter liest danach Hub-Snapshot und resolved lokalen Pfad; alter Settings-Katalog nur archivierte Rückfallquelle.

Shadow-Read und Vergleich, anschließend pro Gerät Umschaltung. Rollback-Flag darf UI zurückschalten, aber keine zweite schreibende Quelle reaktivieren. Rückmigration neuer Daten nicht automatisch. Additive Migrationen, Backup und getestetes Wiederherstellen. Migration-Nummer erst am aktuellen Alembic-Head bestimmen. Produktionsschreibaktionen nur über normalen ausdrücklichen Wizard-Auftrag; Implementierungstests mit Fakes/Sandbox.

Serverbetrieb: API, persistente DB und eigener Outbox/Render-Worker; Version/API-Vertrag und Build-SHA sichtbar. Railway-Konfiguration als Deploymentziel prüfen; keine Neuanlage/Veröffentlichung im Rahmen dieses Plans. Restart während Job, Tokenablauf und Provider-Rate-Limit abfangen. Health zeigt DB/Worker/Graph/Provider ohne Secrets.

## 9. Amazon Deutschland als eigene Phase
Bestehende Angebote UND neue Katalogartikel unterstützen. Verkäufer-/Marktplatzkonfiguration prüfen und fest auf DE begrenzen. Produktart für tatsächliches Notenprodukt anhand Product Type Definitions bestimmen, nicht pauschal BOOKS. EAN/ISBN/GTIN oder gültige Ausnahme abfragen; niemals Identifier oder ASIN erfinden. Existierende Katalogtreffer von neuer Katalogeinreichung trennen. Neue ASIN-Vergabe liegt bei Amazon und ist nicht garantiert.

Aktuelle Pflichtfelder/Schemas pro DE-Produkttyp laden, lokale Validierung plus VALIDATION_PREVIEW soweit unterstützt. Nur bewusst freigegebene Daten senden. Submission-Akzeptanz ≠ verkaufbares Listing; Issues/Status nachladen, erforderliche Korrekturen im Wizard anzeigen. Variantenfamilien nur bei unterstütztem Variation-Theme; Wix-Option Besetzung nicht ungeprüft auf Amazon übertragen. Amazon-Bildanforderungen separat prüfen; gestaltetes Wix-Cover nicht blind als zulässiges Amazon-Hauptbild voraussetzen. Teilupdates bevorzugen, vollständige PUTs gegen unbeabsichtigtes Entfernen bestehender Attribute absichern.

## 10. Abnahme und Grenzen
Erfolg: Produkt unterwegs bei ausgeschaltetem Büro-PC anlegen; Web und Desktop zeigen gleiche UUID/SKU/Preise; nach Browserneustart Entwurf fortsetzen; Cabernet-Beispiel mit zwei Besetzungen, eigenen SKUs/Preisen/Covern; OneDrive-PDF auf allen drei Benutzerprofilen korrekt drucken; keine doppelte Provideranlage nach Timeout; externe sevDesk-Korrektur als Konflikt/Übernahme sichtbar; 1/2/3-zeilige Cover ohne Überschneidung; neue Amazon-DE-Einreichung mit nachvollziehbaren Issues.

Noch im Implementierungs-Setup zu ermitteln, ohne Gesamtprojekt zu blockieren: echte Wix-Katalogversion/Parent-IDs, Microsoft-Tenant und Server-Auth, Hintergrundordner-ID, Fontdateien, echte Editor-Links, Amazon-Rollen und Identifier. Erst die betreffende Teilfunktion als „Einrichtung erforderlich“ markieren. Kein Erfolg vortäuschen.

## 11. Quellen (geprüft 26.09.2026)
- Repo: https://github.com/XeisWorks/XW-Office/tree/aff6b85e54be3a5fb7eed88812225ec702ed3084
- Legacy: https://github.com/XeisWorks/sevDesk/blob/0e15a691fccdbf0c027235780807f0a6e9c58403/sevdesk_wix_fulfillment/graphics/cover_creator.py
- Microsoft Graph Download: https://learn.microsoft.com/en-us/graph/api/driveitem-get-content?view=graph-rest-1.0
- Microsoft Graph Dateiidentität: https://learn.microsoft.com/en-us/graph/api/driveitem-get?view=graph-rest-1.0
- Wix V1: https://dev.wix.com/docs/api-reference/business-solutions/stores/catalog-v1/catalog/product-object
- Wix V3: https://dev.wix.com/docs/api-reference/business-solutions/stores/catalog-v3/products-v3/introduction
- Wix Social: https://support.wix.com/en/article/wix-stores-sharing-products-on-social-media
- sevDesk API: https://api.sevdesk.de/
- Amazon Listings: https://developer-docs.amazon.com/sp-api/lang-en_EN/docs/manage-product-listings-guide
- Amazon Schemas: https://developer-docs.amazon.com/sp-api/lang-en_EN/docs/retrieve-a-product-type-definition
- Amazon Workflow: https://developer-docs.amazon.com/sp-api/lang-de_DE/docs/building-listings-management-workflows-guide
