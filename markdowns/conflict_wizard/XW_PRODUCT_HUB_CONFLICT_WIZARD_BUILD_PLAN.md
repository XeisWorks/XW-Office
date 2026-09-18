# XW Product Hub – Conflict Resolution Wizard
## Bauplan für schrittweise Datenbereinigung über Wochen

**Zielrepo:** `XeisWorks/XW-Office`  
**Stand:** 2026-09-17  
**Ziel:** Einen dauerhaften Wizard bauen, mit dem hunderte Widersprüche zwischen Product Hub, sevdesk, Wix und Amazon schrittweise, auditierbar und mit selektiver Synchronisation geklärt werden können.

## Umsetzungsstand 2026-09-17

Die erste produktive Version (CW00–CW07) ist umgesetzt. Sie übernimmt vorhandene
`sync_conflict`-Signale in persistente Wizard-Fälle, dedupliziert aktive Fälle,
normalisiert Vergleichswerte, speichert Entscheidungen, erzeugt eine Impact-Vorschau,
wendet sichere Product-Hub-Felder mit Optimistic Locking und Audit an und stellt
selektive Wix-Korrekturen ausschließlich in die bestehende Outbox.

Zwei Präzisierungen gegenüber der ursprünglichen Skizze:

- `dedupe_key` ist nicht global eindeutig. Sonst könnte ein später erneut auftretender,
  bereits abgeschlossener Konflikt keinen neuen Fall erzeugen. Eindeutig ist nun
  `(dedupe_key, occurrence)`; für aktive Fälle wird per `dedupe_key` gesucht.
- CW08/CW09 bleiben sichtbar gesperrt, bis für sevdesk bzw. Amazon echte, testbare
  Write- und Readback-Adapter existieren. Die Oberfläche behauptet dort keinen
  Scheinsupport.

Die vier Feature Flags bleiben getrennt: Wizard lesen, Scan ausführen, automatische
Regeln und externe Channel-Writes. Ein externes Apply erfordert weiterhin eine zuvor
persistierte Vorschau und erfolgreiche Readback-Verifikation.

---

# 1. Grundidee

Der XW Product Hub bleibt die kanonische interne Produktdatenbank.

Externe Systeme sind Channels bzw. Fremdsysteme:

- Wix
- sevdesk
- Amazon
- später ggf. VLB / weitere Händlerplattformen

Ein Unterschied zwischen Systemen ist **nicht automatisch ein Fehler**.

Beispiele:

- ein sevdesk-only Dienstleistungsartikel darf bewusst nicht in Wix existieren;
- ein Digitalprodukt darf in sevdesk vorhanden, aber in Amazon nicht vorgesehen sein;
- ein Preisunterschied kann korrekt sein, wenn unterschiedliche Preislisten gemeint sind;
- ein Titelunterschied kann lediglich alte Schreibweise oder echter Datenfehler sein.

Der Wizard soll daher nicht einfach "alles angleichen", sondern:

```text
SCAN
  ↓
NORMALISIEREN
  ↓
KLASSIFIZIEREN
  ↓
AUTO-RESOLVABLE?
  ├─ ja → Regel anwenden + Audit
  └─ nein
       ↓
   CONFLICT CASE
       ↓
   Benutzerentscheidung
       ↓
   Diff-/Impact-Vorschau
       ↓
   selektive Channel-Writes
       ↓
   Verifikation
       ↓
   RESOLVED
```

---

# 2. Wichtigstes UX-Prinzip

Der Benutzer soll **niemals einen kompletten Rohdatensatz mit 70 Feldern vergleichen müssen**.

Der Wizard zeigt jeweils eine kleine, konkrete Entscheidung.

Beispiel:

> **XW-102.5 – Volksmusik #2 - Tuba in B**  
> Feld: `price_gross`

| Quelle | Wert |
|---|---:|
| Product Hub | 9,90 € |
| sevdesk | 9,90 € |
| Wix | 8,90 € |
| Amazon | — |

Auswahl:

- Product Hub ist richtig
- sevdesk ist richtig
- Wix ist richtig
- individuellen Wert eingeben
- Unterschied ist beabsichtigt
- später entscheiden

Danach:

```text
Geplante Änderung:

Product Hub   keine Änderung
sevdesk       keine Änderung
Wix           8,90 € → 9,90 €   ☑
Amazon        keine Aktion

[Änderungen ausführen]
```

---

# 3. Der Wizard ist dauerhaft, nicht session-basiert

Der Wizard muss über Wochen oder Monate benutzt werden können.

Jeder Conflict Case wird persistent gespeichert.

Status:

- `OPEN`
- `IN_PROGRESS`
- `WAITING`
- `PARTIALLY_RESOLVED`
- `RESOLVED`
- `IGNORED`
- `OBSOLETE`

Zusätzliche Felder:

- Priorität
- Kategorie des Konflikts
- Produkt / Variante
- betroffene Felder
- betroffene Channels
- Zeitpunkt erkannt
- zuletzt bearbeitet
- bearbeitet von
- Notiz
- Wiedervorlage-Datum optional

Der Wizard soll nach Browser-Neustart genau dort weitergehen können.

---

# 4. Konflikte in drei Ebenen trennen

## 4.1 Product-Level

Beispiele:

- Produktname
- Marke
- Kategorie
- Beschreibung
- Tags
- Aktivstatus
- Produktfamilie
- Besetzung / Scoring, sofern parentweit

## 4.2 Variant-Level

Beispiele:

- SKU
- Format
- Preis
- Bestand
- Instrument / Stimmung
- Besetzung bei Variantendimension
- variantenspezifische Channel-Mappings

## 4.3 Identifier-/Channel-Level

Beispiele:

- ISBN
- ASIN
- FNSKU
- Wix Product ID
- sevdesk Part ID
- Amazon Seller SKU
- Mapping fehlt / doppelt / widersprüchlich

---

# 5. Konflikttypen

Mindestens folgende Typen vorsehen:

## Identität

- `DUPLICATE_SKU`
- `SKU_ALIAS_REQUIRED`
- `POSSIBLE_DUPLICATE_PRODUCT`
- `WRONG_PRODUCT_MAPPING`
- `IDENTIFIER_COLLISION`
- `MISSING_CHANNEL_MAPPING`

## Titel / Content

- `TITLE_DRIFT`
- `DESCRIPTION_DRIFT`
- `BULLET_DRIFT`
- `BRAND_DRIFT`
- `CATEGORY_DRIFT`
- `TAG_DRIFT`

## Verkauf / Preis

- `PRICE_DRIFT`
- `VAT_DRIFT`
- `FORMAT_DRIFT`
- `ACTIVE_STATUS_DRIFT`
- `PUBLISH_ELIGIBILITY_DRIFT`

## Bestand

- `STOCK_DRIFT`
- `STOCK_ENABLED_DRIFT`

## Musikalische Metadaten

- `ENSEMBLE_DRIFT`
- `SCORING_DRIFT`
- `INSTRUMENT_DRIFT`
- `TRANSPOSITION_DRIFT`

## Amazon-spezifisch

- `ASIN_CONFLICT`
- `FNSKU_CONFLICT`
- `SELLER_SKU_CONFLICT`
- `AMAZON_LISTING_MISSING`
- `AMAZON_LISTING_UNEXPECTED`

---

# 6. Schweregrad

Jeder Fall erhält automatisch einen Severity-Level:

## INFO

Kein echter Fehler.

Beispiele:

- Channel bewusst nicht vorgesehen
- reine Schreibweisenabweichung ohne fachliche Relevanz

## LOW

Leicht lösbar, geringe Auswirkung.

Beispiele:

- fehlendes Tag
- fehlender Kurzname
- Beschreibung fehlt

## MEDIUM

Fachliche Entscheidung erforderlich.

Beispiele:

- Titel
- Kategorie
- Marke
- Publikationsstatus

## HIGH

Finanzielle oder vertriebliche Auswirkung.

Beispiele:

- Preis
- USt.
- Bestand
- Wix-Veröffentlichung

## CRITICAL

Identitäts-/Mapping-Problem.

Beispiele:

- gleiche SKU für zwei verschiedene Produkte
- ASIN/ISBN doppelt
- Wix Product ID auf falschem Product
- falsches sevdesk Mapping

Critical niemals automatisch auflösen.

---

# 7. Automatische Vorverarbeitung

Vor dem Erstellen eines Conflict Case sollen bekannte Unterschiede normalisiert werden.

Beispiele:

- Whitespace trimmen
- Unicode normalisieren
- bekannte SKU-Aliase auflösen
- `B` statt `Bb`
- `Es` statt `Eb`
- bekannte Titelkonventionen anwenden
- Groß-/Kleinschreibung für Vergleich normalisieren
- Netto/Brutto bei 10 % USt. deterministisch umrechnen
- Dezimal-Rundung berücksichtigen
- `[PRINT]`, Emoji etc. nicht als fachlichen Titelunterschied werten
- nicht relevante Channel-Felder ignorieren

Nur nach dieser Normalisierung echte Konflikte erzeugen.

---

# 8. Auto-Resolution Rules

Der Wizard soll regelbasierte automatische Entscheidungen unterstützen.

Beispiel:

```text
Wenn:
  SKU beginnt mit XW-1 oder XW-2
  und Feld = brand

Dann:
  Product Hub Wert = XeisWorks
```

Oder:

```text
Wenn:
  wix_publish_eligible = false
  und Wix Mapping fehlt

Dann:
  kein Conflict Case
```

Oder:

```text
Wenn:
  price_gross == round(price_net * 1.10, 2)

Dann:
  kein VAT-/Preis-Konflikt
```

Regeln können sein:

- systemweit
- nur für Marke
- nur für Kategorie
- nur für SKU-Präfix
- nur für Produktfamilie
- nur für Channel
- nur für einen konkreten Artikel

---

# 9. "Diese Entscheidung künftig automatisch anwenden"

Sehr wichtig für hunderte Fälle.

Nach einer manuellen Entscheidung kann der Wizard optional anbieten:

> Diese Entscheidung scheint einem Muster zu folgen.  
> Soll zukünftig automatisch gelten:
>
> `XW-1xx.* + Kategorie → Zusatzstimme`?

Optionen:

- nur diesen Fall
- gleiche Produktfamilie
- gleiche SKU-Regel
- alle zukünftigen passenden Fälle
- Regel nicht erstellen

Neue Regeln dürfen **nicht** stillschweigend angelegt werden.

Immer:

1. Vorschlag anzeigen
2. Regel in Klartext anzeigen
3. Benutzer bestätigt
4. Regel speichern
5. Regelversion und Audit-Log führen

---

# 10. Wizard Queue

Der Benutzer soll nicht einfach "nächster Konflikt" bekommen.

Queues / Filter:

- Kritische Konflikte
- SKU / Mapping
- Preise
- Titel / Namen
- Kategorien / Marken
- Wix
- sevdesk
- Amazon
- Bestand
- Nur MusikHeroes
- Nur Blechhaufn
- Nur Mnozil Brass
- Schnell lösbar
- Wiedervorlage
- zuletzt begonnen

Zusätzlich:

```text
Heute 10 schnelle Fälle lösen
```

oder:

```text
nur Konflikte mit Severity HIGH
```

---

# 11. Konflikt-Case UI

## Kopf

- SKU / Parent-Produkt
- Produktname
- Kategorie
- Marke
- Severity
- Conflict Type
- seit wann offen
- Fortschritt innerhalb dieses Produkts

## Vergleichsmatrix

Beispiel:

| Feld | Product Hub | Wix | sevdesk | Amazon |
|---|---|---|---|---|
| Titel | Volksmusik #2 - Tuba in B | Volksmusik Band 2 Zusatzstimme... | ZST VM#2... | — |
| Preis brutto | 9,90 | 9,90 | 9,90 | — |
| Aktiv | ja | ja | ja | — |

Nicht unterschiedliche Felder bunt vermischen.

Der aktive Konflikt wird deutlich hervorgehoben.

## Entscheidung

Buttons:

- Product Hub übernehmen
- Wix übernehmen
- sevdesk übernehmen
- Amazon übernehmen
- eigenen Wert eingeben
- Unterschied beabsichtigt
- ignorieren
- später

---

# 12. Unterschied beabsichtigt

Sehr wichtig.

Nicht jeder Channel muss denselben Wert haben.

Beispiele:

- Amazon-Titel darf aus SEO-Gründen anders sein
- Händlerpreis kann abweichen
- sevdesk-only Artikel
- Wix nicht vorgesehen

Dafür:

```text
Resolution = INTENTIONAL_DIFFERENCE
```

mit optionaler Scope-Regel:

- nur dieses Feld
- nur dieses Produkt
- nur dieser Channel
- dauerhaft

So darf derselbe Unterschied beim nächsten Scan nicht erneut als Conflict auftauchen.

---

# 13. Impact Preview vor jedem Write

Kein externer Write direkt beim Anklicken einer Quelle.

Immer zweistufig:

## Schritt A – Entscheidung

Beispiel:

```text
Masterwert = 9,90 €
```

## Schritt B – geplante Aktionen

```text
Product Hub:
  keine Änderung

Wix:
  Preis 8,90 → 9,90 ☑

sevdesk:
  keine Änderung

Amazon:
  nicht vorgesehen
```

Benutzer kann Channels einzeln an-/abwählen.

Erst danach:

```text
[Jetzt synchronisieren]
```

---

# 14. Sync-Ausführung

Bestehende Product-Hub-Outbox-/Sync-Infrastruktur wiederverwenden.

Keine direkte API-Schreiblogik aus dem Wizard heraus bauen.

Wizard erzeugt:

1. kanonische Product-Hub-Änderung
2. gewünschte Channel-Sync-Intents
3. Outbox Events
4. Worker führt aus
5. Ergebnis wird zurück in den Conflict Case geschrieben

Mögliche Resultate:

- alle erfolgreich → `RESOLVED`
- nur einige erfolgreich → `PARTIALLY_RESOLVED`
- Write fehlgeschlagen → offen lassen + Retry
- externer Zustand inzwischen verändert → neuer Diff / `STALE`

---

# 15. Optimistic Concurrency / Stale Detection

Zwischen Scannen und Entscheiden können sich externe Daten ändern.

Darum jeder Case mit Snapshot:

- Product Hub row_version
- Wix revision / updated_at / payload hash
- sevdesk updatedAt / hash, soweit verfügbar
- Amazon snapshot time / hash

Vor Write prüfen:

```text
Ist der Vergleichszustand noch aktuell?
```

Falls nein:

```text
Dieser Fall hat sich seit dem Öffnen verändert.
Bitte Werte neu laden.
```

Kein blindes Überschreiben.

---

# 16. Verifikation nach Sync

Ein Case wird erst `RESOLVED`, wenn der gewünschte Endzustand nochmals gelesen/validiert wurde.

Flow:

```text
WRITE
  ↓
CHANNEL READBACK
  ↓
NORMALIZE
  ↓
COMPARE
  ↓
MATCH? → RESOLVED
NO MATCH → PARTIALLY_RESOLVED / ERROR
```

---

# 17. Undo

Kein "magisches Rückgängig", das externe Systeme ungeprüft zurückschreibt.

Stattdessen:

- vollständige Decision History
- vorherige Werte gespeichert
- Button `Korrekturfall erzeugen`

Damit wird Undo als neuer, auditierbarer Conflict Case behandelt.

---

# 18. Datenmodell

Neue Tabellen bevorzugt additiv.

## conflict_case

Persistenter fachlicher Fall.

Wichtige Felder:

- id
- product_id
- variant_id nullable
- conflict_type
- severity
- status
- priority_score
- title
- summary
- detected_at
- last_seen_at
- started_at
- resolved_at
- snoozed_until
- assigned_to nullable
- resolution_type nullable
- resolution_note
- source_scan_id
- row_version
- created_at
- updated_at

## conflict_field

Ein Case kann mehrere zusammenhängende Feldkonflikte enthalten.

- id
- conflict_case_id
- field_path
- normalized_hub_value
- selected_value
- selected_source
- resolution
- status

## conflict_observation

Wert einer Quelle zum Scan-Zeitpunkt.

- id
- conflict_field_id
- source
- raw_value JSONB
- normalized_value JSONB
- source_external_id
- source_revision
- source_hash
- observed_at

## conflict_action

Geplante / ausgeführte Änderung.

- id
- conflict_case_id
- channel
- action_type
- field_path
- before_value
- after_value
- selected
- status
- outbox_event_id
- error
- attempted_at
- verified_at

## resolution_rule

Explizit vom Benutzer bestätigte Regel.

- id
- code
- name
- enabled
- priority
- scope JSONB
- conditions JSONB
- action JSONB
- risk_level
- auto_apply
- created_from_case_id
- created_by
- created_at
- updated_at

## conflict_scan

Ein Reconcile-Lauf.

- id
- started_at
- finished_at
- source_scope
- product_scope
- products_scanned
- differences_found
- cases_created
- cases_updated
- auto_resolved
- error_summary

---

# 19. Bestehende sync_conflict-Struktur

Vor einer neuen Migration zuerst die existierende `sync_conflict`-Tabelle und deren aktuelle Verwendung prüfen.

Bevorzugte Strategie:

- vorhandene `sync_conflict` nicht einfach löschen;
- entweder gezielt erweitern,
- oder als technische Low-Level-Sync-Konflikttabelle weiterverwenden und `conflict_case` als fachliche Wizard-Schicht darüber setzen.

Der Wizard braucht mehr Persistenz und UX-Zustand als ein einzelner technischer Sync-Konflikt.

---

# 20. Conflict Detection Service

Neue Service-Schicht:

```text
services/product_hub/conflicts/
  detector.py
  normalizer.py
  classifier.py
  rule_engine.py
  resolution.py
  impact_preview.py
  verifier.py
```

Aufgabe `detector.py`:

- Product Hub + Channels vergleichen
- Feld für Feld
- nur relevante Felder je Channel
- Intentional-Difference-Regeln beachten
- bestehende offene Cases deduplizieren
- verschwundene Konflikte als `OBSOLETE` markieren

---

# 21. Deduplizierung

Ein Scan darf nicht jede Woche denselben Konflikt neu anlegen.

Business-Key z. B.:

```text
product_id
variant_id
conflict_type
field_path
channel_set
```

Wenn bereits ein offener Case existiert:

- `last_seen_at` aktualisieren
- Observations aktualisieren
- kein neuer Case

Wenn ein gelöster Konflikt später erneut auftritt:

- neuen Case erzeugen
- `reopened_from_case_id` setzen

---

# 22. Priorisierung

Automatischer `priority_score`.

Beispiel:

```text
CRITICAL identity conflict     +100
Preisabweichung                +60
Bestand                        +60
Amazon live listing            +40
Wix live product               +30
B2B-tagged                     +20
AUTO_DRAFT content              +5
```

Damit erscheinen die wichtigsten Fälle zuerst.

Keine fachliche Entscheidung anhand des Scores treffen; nur Sortierung.

---

# 23. Scan-Modi

## Full Scan

Gesamter Katalog.

Nicht bei jedem Seitenaufruf.

## Incremental Scan

Nur seit letztem Cursor geänderte Channel-Daten.

## Single Product Scan

Direkt von Produktdetailseite.

Button:

```text
[Channels jetzt vergleichen]
```

## Post-Sync Verify Scan

Nur betroffener Artikel / Felder.

---

# 24. Wizard Dashboard

Startseite:

```text
Offen                 284
Kritisch               12
Preise                  41
SKU / Mapping           18
Wix                      76
sevdesk                  94
Amazon                   39
Schnell lösbar           63
Wiedervorlage             8
```

Zusätzlich:

- Fortschritt letzte 7 Tage
- insgesamt gelöst
- Auto-Resolved
- teilweise gelöst
- fehlgeschlagene Syncs

---

# 25. Wizard-Navigation

Buttons:

```text
← Voriger
Speichern & später
Überspringen
Entscheidung prüfen →
```

Nach erfolgreichem Abschluss:

```text
✓ Fall abgeschlossen

[Nächster Fall]
[Zur Queue]
```

Keyboard Shortcuts optional später.

---

# 26. Batch Decisions

Erst nach stabiler Einzelfallversion.

Beispiel:

```text
37 Konflikte entsprechen exakt derselben Regel:
Marke bei XW-1xx = XeisWorks

[37 Fälle gemeinsam lösen]
```

Immer Preview aller betroffenen SKUs und Dry Run.

Keine Batch-Auflösung für CRITICAL.

---

# 27. AI-Unterstützung

AI darf:

- Konflikt zusammenfassen
- wahrscheinlich zusammengehörige Werte erklären
- eine Empfehlung mit Begründung erzeugen
- Regelvorschläge formulieren

AI darf **nicht**:

- kritische Konflikte automatisch entscheiden
- ohne deterministische Regel externe Writes auslösen
- eine SKU-Zusammenführung eigenmächtig durchführen
- Preise / Identifier halluzinieren

In der UI klar kennzeichnen:

```text
KI-Vorschlag – nicht automatisch übernommen
```

---

# 28. API-Skizze

```text
GET  /api/v1/conflicts
GET  /api/v1/conflicts/summary
GET  /api/v1/conflicts/{id}
POST /api/v1/conflicts/scan
POST /api/v1/conflicts/{id}/start
POST /api/v1/conflicts/{id}/decision
POST /api/v1/conflicts/{id}/preview
POST /api/v1/conflicts/{id}/apply
POST /api/v1/conflicts/{id}/snooze
POST /api/v1/conflicts/{id}/ignore
POST /api/v1/conflicts/{id}/refresh
GET  /api/v1/conflict-rules
POST /api/v1/conflict-rules
PATCH /api/v1/conflict-rules/{id}
```

Writes zu Channels bleiben intern über vorhandene Sync-/Outbox-Services.

---

# 29. UI-Routen

```text
/app/conflicts
/app/conflicts/wizard
/app/conflicts/{id}
/app/conflicts/rules
```

Produktdetailseite zusätzlich:

```text
Konflikte (3)
[Im Wizard öffnen]
[Channels vergleichen]
```

---

# 30. Feature Flags

Neue Flags:

```text
product_hub.conflict_wizard_enabled
product_hub.conflict_scan_enabled
product_hub.conflict_auto_resolution_enabled
product_hub.conflict_channel_apply_enabled
```

Initial:

```text
wizard_enabled = false
scan_enabled = false
auto_resolution_enabled = false
channel_apply_enabled = false
```

Schrittweise aktivieren.

---

# 31. Rollout in Bauphasen

## Phase CW00 – Bestandsaufnahme

- existierende `sync_conflict`
- Wix reconcile
- Outbox Worker
- Channel Mappings
- Inventory drift
- Audit Log
- aktuelle APIs

Keine Runtime-Änderung.

## Phase CW01 – Datenmodell

- conflict_case
- conflict_field
- conflict_observation
- conflict_action
- conflict_scan
- resolution_rule

Migration + Repository + Tests.

## Phase CW02 – Normalizer / Detector

Nur read-only.

- Product Hub gegen bekannte Channel Snapshots
- Konflikte erkennen
- deduplizieren
- klassifizieren

Keine Channel Writes.

### CW02B – Wix-Quellsnapshot und Produktbilder

Für bereits über `channel_mapping` zugeordnete Produkte wird Wix read-only eingelesen.
Der Snapshot archiviert Rohprodukt, Varianten und Bestand nur bei geänderten Payloads.
Wix-Bilder werden nicht heruntergeladen oder zurückgeschrieben: das erste Bild wird als
`COVER`, weitere Bilder als `GALLERY_IMAGE` mit Wix-URL und Herkunft gespeichert.
Verschwundene Remote-Bilder bleiben als `stale` erhalten. Die verifizierbaren Felder
`name`, `description` und `visible` erzeugen/aktualisieren anschließend `sync_conflict`
und damit Wizard-Cases. Unzugeordnete Wix-Produkte bleiben bewusst außerhalb dieses Scans.

## Phase CW03 – Wizard Read UI

- Dashboard
- Queue
- Case Detail
- Quellenvergleich
- Weiter/Später

Noch keine Writes.

## Phase CW04 – Decision Persistence

Benutzer kann Entscheidungen speichern.

- selected source
- custom value
- intentional difference
- snooze
- ignore

Noch keine Channel Writes.

## Phase CW05 – Impact Preview

- Hub change
- Wix action
- sevdesk action
- Amazon action
- Dry Run

Keine Ausführung.

## Phase CW06 – Product Hub Apply

Zuerst nur kanonische interne Änderungen.

- optimistic locking
- audit
- outbox intent optional noch disabled

## Phase CW07 – Wix Apply

Vorhandenen Wix Push / reconcile wiederverwenden.

- selektiv
- verify readback
- partial status

## Phase CW08 – sevdesk Apply

Analog Wix.

Falls noch kein vollständiger Product Push vorhanden:
separat und klein implementieren.

## Phase CW09 – Amazon Apply

Erst nachdem Amazon Write API / Credentials / Mapping eindeutig verfügbar sind.

Kein Fake-Support.

## Phase CW10 – Rules Engine

- Regelvorschläge
- explizite Freigabe
- auto-resolution für sichere Fälle
- Rule audit/versioning

## Phase CW11 – Batch Resolution

Nur LOW/MEDIUM + deterministische Regel.

## Phase CW12 – AI Assist

Optional.

Keine Auto-Writes.

---

# 32. Tests

## Unit

- Normalisierung
- Konfliktklassifikation
- dedupe key
- severity
- priority
- rule matching
- intentional difference
- stale detection
- action planning

## Repository

- Case persistence
- resume after restart
- status transitions
- optimistic locking
- history
- reopened conflict

## Integration

- scan → case
- decision → preview
- apply hub only
- apply wix via fake handler
- one channel fails → PARTIALLY_RESOLVED
- readback differs → not resolved
- repeated scan does not duplicate case

## Frontend

- wizard resumes
- source selection
- custom value
- intentional difference
- channel checkbox
- impact preview
- next case
- snooze
- filter queue
- critical warning
- stale case refresh

---

# 33. Harte Sicherheitsregeln

1. Kein externer Write ohne Impact Preview.
2. Kein kritischer Konflikt automatisch lösen.
3. Kein Fuzzy Match automatisch committen.
4. Kein Preis automatisch aus fremdem Channel übernehmen, außer bestätigte deterministische Regel.
5. Kein Identifier-Konflikt automatisch lösen.
6. Kein fehlendes Wix-Produkt als Fehler, wenn Wix nicht vorgesehen ist.
7. Kein Case als RESOLVED markieren, bevor Readback/Verification erfolgreich war.
8. Jeder Write auditieren.
9. Outbox / bestehende Sync Services wiederverwenden.
10. Wizard muss jederzeit unterbrechbar und später fortsetzbar sein.

---

# 34. Definition of Done für erste produktive Version

Die erste produktive Version ist ausreichend, wenn:

- Conflict Scan persistente Cases erzeugt
- wiederholter Scan keine Dubletten erzeugt
- Queue / Filter vorhanden
- Benutzer Fälle über Wochen weiterbearbeiten kann
- Feldwerte aus Hub/Wix/sevdesk/Amazon vergleichbar angezeigt werden
- Entscheidung gespeichert wird
- Impact Preview existiert
- Product Hub intern aktualisiert werden kann
- Wix selektiv über bestehenden Sync aktualisiert werden kann
- fehlgeschlagene Teil-Syncs den Case nicht fälschlich schließen
- vollständiges Audit vorhanden
- intentional differences dauerhaft ignoriert werden können
- Channel-Writes per Feature Flag global abschaltbar sind

sevdesk-/Amazon-Writes dürfen später folgen, ohne das Datenmodell neu zu entwerfen.

---

# 35. Empfehlung für Claude Code

Nicht den gesamten Wizard in einem Durchlauf bauen.

Pro Session genau eine CW-Phase bzw. ein kleines PR-Paket.

Vor jedem Paket:

1. `docs/product_hub/PROGRESS.md` lesen
2. aktuellen `main` prüfen
3. bestehende Sync-/Conflict-/Outbox-Implementierung erneut inspizieren
4. Migration Head prüfen
5. Tests des betroffenen Bereichs identifizieren

Nach jedem Paket:

```bash
python -m pytest
python -m ruff check src tests
python -m mypy src/xw_office
```

Frontend zusätzlich vorhandene npm lint/test/build-Kommandos ausführen.

`docs/product_hub/PROGRESS.md` nach jedem Paket aktualisieren.
