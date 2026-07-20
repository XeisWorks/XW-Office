# XeisWorks Content Studio – Analyse, Zielarchitektur und Umbauplan

**Stand:** 20. Juli 2026  
**Status:** verbindliche Arbeitsgrundlage  
**Historische Quelle:** `XeisWorks_Content_Studio_Originalkonzept_2026-07-19_UNVERAENDERT.md`

---

## 1. Zweck dieses Dokuments

Dieses Dokument bewertet das ursprüngliche Gesamtkonzept, gleicht es mit dem bestehenden
XW-Studio ab und ersetzt dessen Umsetzungsempfehlung durch einen schrittweisen, wirtschaftlich
vertretbaren Umbauplan.

Das Originalkonzept bleibt absichtlich unverändert erhalten. Es ist die Ideensammlung und
langfristige Vision, aber kein unmittelbar abzuarbeitendes Pflichtenheft.

Die verbindliche Leitentscheidung lautet:

> Das Content Studio wird als separat deploybarer Webbereich im bestehenden XW-Studio-Repository
> aufgebaut. Es ersetzt nicht die PySide6-Anwendung und übernimmt keine drucker- oder
> arbeitsplatzgebundenen Abläufe.

---

## 2. Gesamtbewertung

### 2.1 Was fachlich sehr gut ist

Das Konzept löst das richtige Problem: Nicht das Formulieren eines einzelnen Beitrags ist der
größte Engpass, sondern das Erkennen, Festhalten und strukturierte Weiterverarbeiten von
Content-Anlässen.

Besonders tragfähig sind:

- quellenbasierte Beiträge statt frei erfundener Marketingtexte,
- mobile Schnellaufnahme von Foto, Text und später Sprache,
- getrennte Markenprofile für XeisWorks und MusikHeroes,
- menschliche Freigabe vor jeder Veröffentlichung,
- Wiederverwendung tatsächlich vorhandener Verlagsarbeit,
- zunächst nur ein bis zwei hochwertige Vorschläge pro Woche,
- Export als robuster Fallback vor direkter Plattformintegration,
- Datenschutz- und Consent-Prüfung bei Personen- und insbesondere Schülerbildern.

### 2.2 Was im ursprünglichen MVP zu groß ist

Das ursprüngliche MVP kombiniert bereits die Merkmale einer kleinen Social-Media-SaaS-Plattform:

- mehrere Benutzerrollen,
- zwölf größere Fachentitäten,
- neun als Agenten bezeichnete Komponenten,
- mehrere KI-Anbieter mit Router und Jury,
- Redis und permanente Worker,
- RAG und Vektorsuche,
- Meta-, Wix-, GitHub-, Outlook- und Desktop-Integration,
- Kampagnen, Analytics, Audit und automatische Lernschleifen.

Diese Zielvision ist nicht grundsätzlich falsch. Als erster Umsetzungsschritt würde sie jedoch
hohe Bau- und Wartungskosten verursachen, bevor der zentrale Arbeitsablauf im Alltag validiert ist.

### 2.3 Wirtschaftliche Leitlinie

Jede Phase muss eine im Alltag prüfbare Verbesserung liefern. Eine neue Infrastrukturkomponente
wird erst eingeführt, wenn ein konkreter Engpass sie rechtfertigt.

Insbesondere gilt:

- Provider-Schnittstelle ja, mehrere Provider im Startbetrieb nein.
- Strukturierte Workflows ja, frei handelnde Agenten nein.
- PostgreSQL ja, pgvector erst bei ausreichend großem Archiv.
- Zeitgesteuerte Railway-Jobs ja, Redis erst bei belastbarer Queue-Anforderung.
- Exportworkflow zuerst, Meta-Publishing danach.
- Ein Owner zuerst, vollständiges Rollenmodell erst bei realem Teamzugang.

---

## 3. Einordnung in das bestehende XW-Studio

### 3.1 Das Content Studio ist eine Erweiterung

XW-Studio enthält bereits:

- ein Marketing-Menü mit Ideen- und Content-Planung,
- eine zwischen PCs geteilte Marketing-Ideenliste,
- PostgreSQL auf Railway,
- SQLAlchemy und Alembic,
- verschlüsselte API-Secrets,
- OpenAI-Konfiguration,
- Wix-Produkt- und Bestellclients,
- Pydantic-Vertragsmodelle,
- Outlook-/XW-Copilot-Grundlagen,
- etablierte Test-, Service- und Adaptermuster.

Ein vollständig separates Repository würde diese Grundlagen duplizieren oder künstlich über eine
zweite Integrationsschicht anbinden. Das ist für die derzeitige Größe nicht sinnvoll.

### 3.2 Was gemeinsam genutzt wird

Gemeinsam nutzbar sind:

- Repository, CI und Versionsverwaltung,
- Python-Fachlogik,
- PostgreSQL-Instanz und Alembic-Migrationskette,
- Secret- und Konfigurationsprinzipien,
- Wix-Clients und später weitere reine Python-Services,
- Content-Datenmodell,
- Prompt- und Providerlogik,
- Audit- und Kosteninformationen.

### 3.3 Was strikt getrennt bleibt

Nicht in den Webdienst gehören:

- PySide6-Widgets,
- QThread-basierte UI-Worker,
- QPrinter und lokale Druckersteuerung,
- Windows-spezifische Automatisierung,
- lokale OneDrive-Pfade,
- der nur an `127.0.0.1` gebundene Outlook-Copilot-Ingress,
- Rechnungs-, Etiketten- und Produktdruck.

Der Webdienst importiert keine UI-Module. Gemeinsame Logik muss Qt-unabhängig unterhalb der
Oberflächen liegen.

---

## 4. Desktop oder Web nach Funktionsbereich

| Bereich | Primäre Oberfläche | Begründung |
|---|---|---|
| Rechnungen und Fulfillment | PySide6 | lokaler Druck, PDF- und Hardwareintegration |
| Produkt- und Etikettendruck | PySide6 | definierte Druckstation, stille Druckabläufe |
| Steuern und FinanzOnline | vorerst PySide6 | sensibler, seltener Spezialablauf |
| Produkte pflegen | PySide6, später ergänzende Webansicht | bestehende leistungsfähige Arbeitsoberfläche |
| CRM | vorerst PySide6 | kein mobiler Kernnutzen nachgewiesen |
| Statistik | PySide6, später optional read-only im Web | mobile Übersicht denkbar, nicht prioritär |
| Marketing und Content | Web/PWA | geräteübergreifende Aufnahme, Freigabe und Planung |

Ein Browser ist beim Drucken ein Nachteil: Browserdruck, Downloads, lokale Drucker und Papierformat
erfordern zusätzliche Übergaben oder einen lokalen Print-Agent. Beim Marketing ist die
Ortsunabhängigkeit dagegen der eigentliche Produktnutzen.

---

## 5. Empfohlene Zielarchitektur

### 5.1 Überblick

```text
Smartphone / Tablet / Browser
             |
             | HTTPS
             v
   Content Web / PWA
             |
             | gleiche Origin oder interne API
             v
      FastAPI-Webdienst
       |      |      |
       |      |      +-- KI-Provider-Adapter
       |      +--------- Objektspeicher für Medien
       +---------------- PostgreSQL
             ^
             |
     optionale REST-Aufrufe
             |
   bestehendes PySide6 XW-Studio
```

### 5.2 Repository-Struktur

Die Struktur wird evolutionär erweitert, nicht in ein neues Groß-Monorepo umgebaut:

```text
src/xw_studio/
├── content/              # Qt-unabhängiges Content-Fachmodell
├── web/                  # FastAPI-Einstieg und serverseitige API
├── services/             # vorhandene und neue Integrationen
├── models/               # gemeinsame SQLAlchemy-Modelle
├── migrations/           # eine Migrationshistorie
└── ui/                   # bestehende PySide6-Oberfläche

web/                      # späterer React-/Next.js-Client, falls erforderlich
config/content_brands.yaml
```

Für die erste Phase wird bewusst noch kein Node-/Next.js-Projekt erzeugt. Zuerst werden
Deployment, Sicherheitsgrenze und API-Vertrag validiert. Die Entscheidung zwischen einer
kleinen serverseitigen Oberfläche und Next.js fällt vor Phase 2 anhand des benötigten Editors und
der PWA-Funktionen.

### 5.3 Backend

- Python 3.11 oder neuer,
- FastAPI,
- Pydantic für Ein- und Ausgaben,
- SQLAlchemy und Alembic,
- HTTPX für externe Dienste,
- Uvicorn als Railway-Prozess.

Der API-Prozess darf keine PySide6-Klassen importieren.

### 5.4 Frontend

Anforderungen an die spätere mobile Oberfläche:

- responsive ab etwa 360 Pixel Breite,
- Kamera-/Dateiupload,
- sehr wenige Pflichtfelder,
- Markenwahl mit gutem Standardwert,
- Entwurfsvorschau je Kanal,
- Autosave,
- installierbares PWA-Manifest,
- klare Zustände bei langsamen KI-Läufen,
- barrierearme Bedienung und große Touch-Ziele.

Next.js bleibt eine gute Zieloption, ist aber kein Selbstzweck. Wenn der Kernworkflow mit
serverseitigem HTML und kleinen JavaScript-Komponenten wartbarer bleibt, ist diese einfachere
Variante zulässig.

### 5.5 Datenbank

Die vorhandene Railway-PostgreSQL-Datenbank wird verwendet. Content-Tabellen erhalten einen
klaren Präfix oder ein eigenes Schema. Das bestehende `setting_kv` bleibt für kleine Einstellungen,
nicht aber als dauerhafte Ablage für Drafts, Bilder und Statusmaschinen.

Vorgesehener erster Fachdatenkern:

- `content_brand`,
- `content_source`,
- `content_media_asset`,
- `content_idea`,
- `content_draft`,
- `content_publication`,
- `content_model_run`.

Approval kann bei einem einzigen Owner zunächst als Status und Zeitstempel am Draft gespeichert
werden. Eine eigene mehrstufige Approval-Tabelle folgt erst mit mehreren Benutzern.

### 5.6 Medien

Originalbilder gehören langfristig in einen S3-kompatiblen Objektspeicher. Die Datenbank speichert
nur Metadaten, Prüfsumme, Consent-Status und Storage-Key.

Regeln:

- Originale nie überschreiben,
- EXIF-Entfernung nur auf Derivaten oder nach ausdrücklicher Regel,
- Dateityp und Größe serverseitig prüfen,
- Personen-/Schülerbilder ohne geklärten Status nicht zur Veröffentlichung freigeben,
- signierte, kurzlebige URLs verwenden.

### 5.7 KI

Die erste produktive Implementierung verwendet einen Provider. Die Fachlogik kennt dennoch keine
fest verdrahteten Modellnamen.

```text
ContentSource
  -> ausgewählte Quellen und Markenprofil
  -> generate_angles
  -> generate_draft
  -> deterministische Regeln
  -> optionaler KI-Review
  -> menschliche Freigabe
```

Maschinell weiterverarbeitete Ausgaben werden schema-validiert. Ein „Fact Check“ bedeutet im
ersten Ausbau nur „durch bereitgestellte Quellen gestützt“, nicht eine unabhängige
Wahrheitsprüfung.

### 5.8 Hintergrundverarbeitung

Zunächst:

- kurze KI-Aufträge als nachvollziehbarer API-Job,
- wöchentliche Vorschläge über Railway Cron,
- Status in PostgreSQL,
- kontrollierte Wiederholung einzelner fehlgeschlagener Aufträge.

Redis wird erst ergänzt, wenn mindestens eine dieser Bedingungen eintritt:

- mehrere parallele, lange Medienjobs,
- hohe Webhook-Frequenz,
- garantierte Queue-Abarbeitung mit Dead Letter Queue,
- mehrere Workerinstanzen,
- Publishing-Retries lassen sich mit DB-Jobs nicht mehr sauber beherrschen.

### 5.9 Sicherheit

- Öffentliche Healthchecks enthalten keine Secrets oder Datenbankdetails.
- Fachendpunkte sind ab der ersten Phase geschützt.
- Der Bootstrap-Bearer-Token aus Phase 1 ist nur eine Übergangslösung.
- Vor Speicherung realer Content-Daten wird eine Owner-Anmeldung mit sicherer Session umgesetzt.
- API- und Meta-Tokens gelangen nie ins Browser-JavaScript.
- CORS wird nicht pauschal mit `*` geöffnet.
- Upload, Prompt und Logdaten werden nach Sensitivität behandelt.
- Veröffentlichungen benötigen immer einen freigegebenen, unveränderten Draft-Stand.

---

## 6. Subdomain und Railway

### 6.1 Namensentscheidung

`web.xeisworks.at` ist technisch möglich und als allgemeiner Einstieg in zukünftige
XeisWorks-Webwerkzeuge verständlich. Für ein ausschließliches Content Studio ist der Name aber
wenig selbsterklärend.

Empfehlung:

1. **`studio.xeisworks.at`** als dauerhafte Benutzeroberfläche des Content Studios.
2. Alternativ **`content.xeisworks.at`**, wenn der Marketingzweck ausdrücklich sichtbar sein soll.
3. **`web.xeisworks.at`** nur dann, wenn dort später mehrere XW-Studio-Webmodule unter einem
   gemeinsamen Portal zusammengeführt werden sollen.

Da die Anwendung „XW-Studio“ heißt und später weitere mobile Werkzeuge aufnehmen könnte, ist
`studio.xeisworks.at` die ausgewogenste Wahl. Technisch funktioniert die Implementierung mit
jeder der drei Domains; konfiguriert wird sie über `XW_CONTENT_PUBLIC_URL`.

### 6.2 Railway-Einrichtung

Im Railway-Webservice:

1. Repository `XW-Studio` und Branch `main` verbinden.
2. Startkommando aus `railway.toml` verwenden.
3. `PORT` nicht statisch erzwingen; Railway stellt den Wert bereit.
4. Zunächst eine Railway-Domain erzeugen und `/health` prüfen.
5. Unter Public Networking die gewählte Custom Domain hinzufügen.
6. Den von Railway ausgegebenen CNAME exakt beim DNS-Provider eintragen.
7. Den von Railway ausgegebenen TXT-Verifizierungseintrag ebenfalls exakt eintragen.
8. Auf Railway-Verifizierung und das automatisch ausgestellte HTTPS-Zertifikat warten.
9. `XW_CONTENT_PUBLIC_URL=https://studio.xeisworks.at` setzen.
10. Einen langen zufälligen Wert als `XW_CONTENT_BOOTSTRAP_TOKEN` setzen.

Die konkreten CNAME- und TXT-Werte dürfen nicht vorab geraten werden; Railway erzeugt sie für den
jeweiligen Dienst. Ohne gültigen TXT-Eintrag kann die Domain trotz aufgelöstem CNAME mit 404
antworten.

---

## 7. Umbauphasen

## Phase 0 – Konzept konsolidieren und Original sichern

**Ziel:** Eine verbindliche, realistische Arbeitsgrundlage schaffen.

Umfang:

- Originalkonzept eindeutig als Archiv umbenennen,
- Archivhinweis ergänzen,
- Änderungsschutz über Repository-Regel und SHA-256-Test,
- Zielarchitektur und Phasenplan dokumentieren,
- Subdomain- und Deploymentstrategie festlegen.

**Definition of Done:** Original und neue Arbeitsgrundlage sind klar getrennt; versehentliche
Änderungen am Original fallen in CI auf.

**Status:** umgesetzt am 20. Juli 2026.

## Phase 1 – Sicheres Web-/API-Fundament

**Ziel:** Einen minimalen, direkt auf Railway startbaren Webdienst im bestehenden Repository
bereitstellen, ohne operative Desktop-Funktionen anzutasten.

Umfang:

- FastAPI-Anwendung unter `xw_studio.web`,
- Railway-kompatibler Start über `0.0.0.0:$PORT`,
- öffentliche Routen `/` und `/health` ohne Geschäftsdaten,
- versionierte API unter `/api/v1`,
- vorläufiger Bearer-Schutz für Fachendpunkte,
- validierte Markenprofile aus `config/content_brands.yaml`,
- geschützter Endpunkt zum Lesen der Markenprofile,
- sichere Standardkonfiguration ohne offenen Fachzugriff,
- Unit- und API-Tests,
- CI- und README-Ergänzung,
- Railway-Healthcheck-Konfiguration.

Nicht enthalten:

- Datenbankänderungen,
- Login-Oberfläche,
- Speicherung von Content,
- Bild-Upload,
- KI-Aufrufe,
- Meta-Publishing.

**Definition of Done:** Der Dienst startet lokal und auf Railway; `/health` antwortet; der
Markenendpunkt lehnt fehlende oder falsche Tokens ab; Tests und Ruff laufen.

**Status:** umgesetzt am 20. Juli 2026.

## Phase 2 – Owner-Anmeldung und mobile Content Inbox

**Ziel:** Einen echten Content-Anlass sicher mobil speichern können.

Umfang:

- Owner-Login mit sicherer HTTP-only Session,
- MFA-Vorbereitung oder externer Identity-Provider,
- Tabellen für Brand, ContentSource und MediaAsset,
- Migration der zwei bestehenden Brandprofile,
- mobile Eingabe für Text und Bild,
- Sensitivitäts- und Consent-Status,
- Objektstorage mit signierten URLs,
- Inbox-Status `neu`, `bearbeitet`, `archiviert`,
- Import der bisherigen Marketingideen,
- Lösch- und Aufbewahrungsregeln.

**Definition of Done:** Ein Foto plus kurzer Text kann am Smartphone erfasst, am PC gesehen und
wieder bearbeitet werden. Ohne Anmeldung sind keine Daten sichtbar.

## Phase 3 – Ein-Provider-Ideen- und Draft-Erzeugung

**Ziel:** Aus einer gespeicherten Quelle einen brauchbaren Entwurf erzeugen.

Umfang:

- kleine providerunabhängige Schnittstelle,
- ein OpenAI-Adapter,
- strukturierte Idea- und Draft-Schemas,
- Instagram- und Facebook-Variante,
- Quellenreferenzen,
- deterministische Brand-Regeln,
- Kosten- und Laufzeitprotokoll,
- Bearbeiten, Versionieren, Freigeben und Zurückstellen,
- Exportpaket mit Text und Medien.

**Definition of Done:** Mindestens 70 Prozent eines vereinbarten Golden Sets sind nach höchstens
zehn Minuten manueller Bearbeitung veröffentlichbar.

## Phase 4 – Alltagstest und UX-Härtung

**Ziel:** Nachweisen, dass das System tatsächlich Arbeit spart.

Umfang:

- vier bis sechs Wochen echter Betrieb,
- Messung von Aufnahme- und Bearbeitungszeit,
- Autosave und Fehlerszenarien,
- mobile PWA-Installation,
- gegebenenfalls Push- oder E-Mail-Hinweise,
- Golden Set auf Basis realer Freigaben erweitern,
- Entscheidung serverseitige UI versus Next.js endgültig treffen.

**Gate:** Keine neue große Integration, bevor der Kernworkflow regelmäßig verwendet wird.

## Phase 5 – Wix und proaktive Wochenvorschläge

**Ziel:** Vorhandene Verlagsdaten automatisch als Content-Anlässe nutzbar machen.

Umfang:

- read-only Übernahme ausgewählter Wix-Produkte,
- Produktbilder, URLs und freigegebene Beschreibungen,
- Railway-Cron für wöchentliche Kandidaten,
- einfache Regeln für Saison, Content-Säule und Wiederholung,
- maximal zwei Vorschläge je Woche,
- Benachrichtigung über bereitstehende Entwürfe.

## Phase 6 – Meta-Publishing

**Ziel:** Freigegebene, unveränderte Drafts kontrolliert veröffentlichen.

Umfang:

- aktuell passende Meta-Login-Variante,
- minimal benötigte Berechtigungen,
- verschlüsselte Token und Ablaufüberwachung,
- Medienvalidierung,
- Idempotency Key,
- Publishingstatus und kontrollierte Retries,
- manueller Export als permanenter Fallback,
- App-Review-Unterlagen.

**Gate:** Umsetzung nur, wenn professionelles Konto, gewünschte Formate und App-Review-Weg vorab
mit der dann aktuellen Meta-Dokumentation verifiziert wurden.

## Phase 7 – Archiv, Ähnlichkeit und einfache Analytics

**Ziel:** Erfolgreiche Inhalte auffindbar und sinnvoll wiederverwendbar machen.

Umfang:

- Import veröffentlichter Altbeiträge,
- zunächst Volltext- und Metadatensuche,
- lexikalische Ähnlichkeitsprüfung,
- einfache manuelle Qualitätsbewertung,
- ausgewählte Meta-Insights,
- erst danach Entscheidung über pgvector.

## Phase 8 – Weitere Integrationen nur nach Nutzen

Mögliche Kandidaten:

- Outlook-Aktion „Als Content-Anlass senden“,
- Desktop-Button zur Übergabe eines Produkts oder Ereignisses,
- Newsletter- und Blogvarianten,
- Canva,
- zweiter KI-Provider,
- Teamrollen.

Jeder Kandidat erhält vor Umsetzung eine eigene Nutzen-/Aufwandsentscheidung.

---

## 8. Bewusst verworfene Startentscheidungen

Für die ersten Phasen werden nicht umgesetzt:

- neues separates Content-Studio-Repository,
- Web-Umbau des Rechnungs- und Druckbereichs,
- Redis ohne Queue-Last,
- Celery/Dramatiq/RQ ohne nachgewiesenen Bedarf,
- drei KI-Provider,
- LLM-Jury,
- autonomes Publishing,
- automatisches Durchsuchen privater E-Mails,
- automatische Verwendung einzelner Bestellungen,
- Fine-Tuning,
- Vektorsuche ohne ausreichend großes Archiv,
- statistische Selbstoptimierung bei kleinen Datenmengen.

---

## 9. Abnahmekennzahlen für den Gesamtnutzen

Der Ausbau ist erfolgreich, wenn nach Phase 4:

- eine mobile Schnellaufnahme weniger als eine Minute benötigt,
- ein fertiger Beitrag durchschnittlich höchstens zehn bis zwanzig Minuten Gesamtaufwand braucht,
- mindestens ein Beitrag pro Woche tatsächlich veröffentlicht wird,
- mindestens 70 Prozent der Vorschläge grundsätzlich verwendbar sind,
- keine Veröffentlichung ohne menschliche Freigabe stattfindet,
- keine ungeklärten Personen-/Schülerbilder veröffentlicht werden,
- das System freiwillig verwendet und nicht als zusätzliche Verwaltungslast empfunden wird.

Technische Kennzahlen sind diesen Prozesszielen untergeordnet.

---

## 10. Entscheidungsprotokoll

| Datum | Entscheidung | Begründung |
|---|---|---|
| 2026-07-20 | Originalkonzept archivieren | Ideenhistorie erhalten, Arbeitsplan klar trennen |
| 2026-07-20 | bestehendes Repository verwenden | vorhandene DB-, Secret-, Wix- und Testbasis nutzen |
| 2026-07-20 | Desktop nicht durch Web ersetzen | Druck und Hardware bleiben lokal überlegen |
| 2026-07-20 | FastAPI-Webfundament zuerst | Deployment- und Sicherheitsgrenze früh validieren |
| 2026-07-20 | zunächst kein Redis | Railway Cron und DB-Aufträge reichen für geringe Last |
| 2026-07-20 | zunächst ein KI-Provider | Qualität des Kernworkflows vor Routing optimieren |
| 2026-07-20 | `studio.xeisworks.at` empfohlen | eindeutig, markennah und für spätere Webmodule offen |

---

## 11. Technische Referenzen

- Railway Public Networking und Custom Domains: https://docs.railway.com/networking/public-networking
- Railway Domain-Konfiguration: https://docs.railway.com/networking/domains/working-with-domains
- Railway Cron/Worker/Queue-Entscheidung: https://docs.railway.com/guides/cron-workers-queues
- Next.js PWA Guide: https://nextjs.org/docs/app/guides/progressive-web-apps
- Meta Instagram API: https://www.postman.com/meta/workspace/instagram/documentation/23987686-9386f468-7714-490f-9bfc-9442db5c8f00

Bei externen Plattformen ist vor jeder Integrationsphase erneut die aktuelle offizielle
Dokumentation maßgeblich.
