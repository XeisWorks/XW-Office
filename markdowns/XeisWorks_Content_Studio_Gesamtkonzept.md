# XeisWorks Content Studio
## Vollständiges Software-, Architektur- und Umsetzungskonzept

**Arbeitstitel:** XeisWorks Content Studio  
**Alternativname:** XeisWorks Publisher AI  
**Dokumentversion:** 1.0  
**Stand:** 19. Juli 2026  
**Adressaten:** Bernhard Holl, Codex-Agent in VS Code, GitHub Copilot, externe Entwickler  
**Status:** Umsetzungsgrundlage

---

# 1. Executive Summary

Das XeisWorks Content Studio ist eine zentrale, KI-gestützte Webanwendung für die Planung, Erzeugung, Prüfung, Freigabe, Veröffentlichung und Wiederverwendung von Inhalten des XeisWorks Musikverlags und der Marke MusikHeroes.

Das System löst nicht primär ein Schreibproblem. Es löst ein Prozessproblem:

- Im Verlag entstehen laufend verwertbare Inhalte.
- Diese Inhalte liegen verteilt in Fotos, E-Mails, Projektordnern, GitHub-Repositories, Wix, Produktdaten, Notensatzprojekten, Kundenrückmeldungen und persönlichen Notizen.
- Der Aufwand, aus diesen Rohinformationen regelmäßig gute Social-Media-Beiträge zu machen, ist zu hoch.
- Externe Social-Media-Betreuung scheitert ebenfalls, wenn der fachliche Rohstoff nicht strukturiert bereitsteht.

Das Content Studio wandelt die alltägliche Verlagsarbeit in einen kontrollierten Content-Prozess um:

> Rohmaterial erfassen → Kontext ergänzen → Ideen erzeugen → Entwürfe erstellen → prüfen → freigeben → veröffentlichen → Ergebnisse auswerten → erfolgreiche Inhalte wiederverwenden.

Die Anwendung wird als **responsive Web-App** gebaut. Sie funktioniert am Büro-PC und am Smartphone. Eine zusätzliche PySide6-Anwendung ist für das MVP nicht erforderlich. Die bestehende PySide6-Verlags-App kann später über eine API angebunden werden.

Die KI-Architektur ist bewusst **anbieterunabhängig**. OpenAI, Google Gemini und Anthropic Claude werden über austauschbare Provider-Adapter angesprochen. Die Anwendung entscheidet je nach Aufgabe, Kostenrahmen, Qualität und Verfügbarkeit, welches Modell eingesetzt wird.

Die Veröffentlichung erfolgt niemals unkontrolliert. Der Standard ist immer:

> KI-Entwurf → menschliche Freigabe → Veröffentlichung.

Für Instagram und Facebook wird die offizielle Meta Graph API integriert. Das System muss dabei mit professionellen Instagram-Konten, App-Review, Berechtigungen, Token-Laufzeiten und API-Limits umgehen.

---

# 2. Projektziele

## 2.1 Primärziele

1. Zwei hochwertige, veröffentlichungsbereite Content-Vorschläge pro Woche erzeugen.
2. Den manuellen Aufwand auf idealerweise 10–20 Minuten pro Woche reduzieren.
3. Alle Ideen, Bilder, Entwürfe und veröffentlichten Beiträge zentral verwalten.
4. Den Stil von XeisWorks und MusikHeroes konsistent abbilden.
5. Vorhandene Arbeit in Content umwandeln, statt künstlich ständig neue Themen erfinden zu müssen.
6. Instagram und Facebook direkt oder geplant bespielen.
7. Inhalte kanalübergreifend wiederverwenden.
8. Die Anwendung so modular bauen, dass Newsletter, Blog, Händlerkommunikation und Produkttexte später ergänzt werden können.

## 2.2 Sekundärziele

- Historische Posts durchsuchbar machen.
- Wiederholungen vermeiden.
- Saisonale Chancen erkennen.
- Neue Produkte, Arrangements und Projekte automatisch als Content-Anlass erkennen.
- Kundenfeedback und häufige Fragen in Beiträge umwandeln.
- Einfache Auswertung nach Thema, Format, Marke und Resonanz ermöglichen.
- KI-Kosten nachvollziehbar begrenzen.
- Alle wichtigen Aktionen auditierbar machen.

## 2.3 Nicht-Ziele des MVP

Das MVP soll zunächst nicht:

- automatisch ohne Freigabe veröffentlichen,
- vollautomatisch Videos schneiden,
- beliebige Social-Media-Netzwerke gleichzeitig unterstützen,
- ein vollständiges Digital-Asset-Management-System ersetzen,
- eine Marketingagentur simulieren,
- rechtlich heikle Aussagen eigenständig freigeben,
- fremde urheberrechtlich geschützte Inhalte automatisch verwenden,
- private E-Mails ungeprüft als Marketingmaterial verwerten.

---

# 3. Leitprinzipien

## 3.1 Human-in-the-loop

Kein Beitrag wird ohne ausdrückliche Freigabe veröffentlicht.

## 3.2 Niederschwellige Bedienung

Der Benutzer muss aus einem Foto, einem Satz oder einer Sprachnotiz einen Content-Vorschlag erzeugen können.

## 3.3 Kein leeres Eingabefeld

Die Anwendung zeigt aktiv Ideen, Anlässe, wiederverwendbare Inhalte und offene Aufgaben.

## 3.4 Quellenbasierte Inhalte

Jeder Entwurf soll nachvollziehbar auf konkreten Quellen beruhen:

- Produkt,
- Bild,
- Projekt,
- Notiz,
- Kundenstimme,
- Kalenderereignis,
- veröffentlichter Altbeitrag,
- GitHub-Ereignis,
- Wix-Datensatz.

## 3.5 Modulare Architektur

Jede externe Plattform wird über einen Adapter angebunden. Anbieterwechsel dürfen keine vollständige Neuentwicklung erfordern.

## 3.6 Privacy by Design

Es werden nur notwendige Daten verarbeitet. Personenbezogene Daten werden minimiert, klassifiziert und bei Bedarf anonymisiert.

## 3.7 Fehlerfreundlichkeit

Webhook-Duplikate, API-Ausfälle, Zeitüberschreitungen, Modellfehler und unvollständige Daten müssen erwartet und kontrolliert behandelt werden.

## 3.8 Beobachtbarkeit

Jeder automatische Schritt schreibt Status, Laufzeit, Modell, Kosten, Ergebnis und Fehler in ein Protokoll.

---

# 4. Markenmodell

Das System wird von Anfang an multi-brand-fähig aufgebaut.

## 4.1 Marke: XeisWorks

Mögliche kommunikative Eigenschaften:

- österreichisch,
- fachlich fundiert,
- nahbar,
- musikpraktisch,
- bodenständig,
- humorvoll, aber nicht beliebig,
- professionell ohne sterile Konzernsprache,
- direkte Nähe zu Musikern, Arrangeuren, Ensembles und Musikvereinen.

Typische Inhalte:

- neue Notenausgaben,
- Arrangements,
- Einblicke in Verlagsarbeit,
- Notensatz,
- Herstellung,
- Kundenfragen,
- Ensemble-Projekte,
- Versand und Veröffentlichung,
- Geschichten hinter Ausgaben,
- Branchenwissen.

## 4.2 Marke: MusikHeroes

Mögliche kommunikative Eigenschaften:

- motivierend,
- jung,
- spielerisch,
- praxisnah,
- für Musikschulen, Jugendorchester und Lehrkräfte,
- gemeinschaftlich,
- klar verständlich,
- visuell lebendig,
- nicht kindisch.

Typische Inhalte:

- Unterrichtsideen,
- Warm-ups,
- Playalongs,
- Hefte,
- Illustrationen,
- Probentipps,
- Schülererlebnisse,
- Entstehung neuer Reihen,
- Übungen,
- Einblicke von Christian Wieder, Bernhard Holl und Rupert Hörbst.

## 4.3 Brand Profile

Jede Marke erhält ein strukturiertes Profil:

```yaml
brand:
  id: musikheroes
  display_name: MusikHeroes
  language: de-AT
  tone:
    primary: motivierend
    secondary:
      - locker
      - praxisnah
      - humorvoll
  forbidden_traits:
    - marktschreierisch
    - belehrend
    - künstliche Jugendsprache
  preferred_terms:
    - gemeinsam musizieren
    - ausprobieren
    - Probe
    - Musikschule
  avoid_terms:
    - revolutionär
    - bahnbrechend
    - garantiert
  emoji_policy:
    allowed: true
    maximum_per_post: 4
  hashtag_policy:
    maximum: 8
  legal_footer_rules: []
```

## 4.4 Stiltraining ohne Fine-Tuning

Im MVP wird kein Modell feinjustiert. Stattdessen werden verwendet:

- Brand Profile,
- ausgewählte gute Altbeiträge,
- Negativbeispiele,
- Beispieltexte,
- Tonalitätsregeln,
- Glossar,
- Produktwissen,
- Prompt-Versionen.

Fine-Tuning ist erst sinnvoll, wenn genügend hochwertige, freigegebene Texte mit klarer Qualitätsbewertung vorliegen.

---

# 5. Benutzerrollen

## 5.1 Owner

Vollzugriff auf:

- Marken,
- Benutzer,
- API-Schlüssel,
- Veröffentlichung,
- Kostenlimits,
- Integrationen,
- Löschung,
- Audit-Protokolle.

## 5.2 Editor

Kann:

- Quellen erfassen,
- Ideen bearbeiten,
- Entwürfe erzeugen,
- Texte und Medien bearbeiten,
- Freigabe anfordern.

## 5.3 Approver

Kann:

- Entwürfe freigeben,
- ablehnen,
- Korrekturen verlangen,
- Veröffentlichung planen.

## 5.4 Viewer

Kann Inhalte und Statistiken ansehen, aber nichts verändern.

## 5.5 MVP-Vereinfachung

Zu Beginn kann eine einzige Owner-Rolle genügen. Das Datenmodell soll Rollen dennoch bereits vorsehen.

---

# 6. Kern-Workflows

## 6.1 Schnellaufnahme eines Content-Anlasses

1. Benutzer öffnet die mobile Web-App.
2. Er lädt ein Foto hoch.
3. Er spricht oder tippt: „Heute erste Probe mit WarmUps #2, die Bassgruppe hatte besonders Spaß.“
4. Die Anwendung transkribiert bei Bedarf die Sprachnotiz.
5. Der Input wird als `Content Source` gespeichert.
6. Die KI schlägt zwei bis vier mögliche Blickwinkel vor.
7. Der Benutzer wählt einen Blickwinkel.
8. Die KI erzeugt Instagram- und Facebook-Varianten.
9. Der Benutzer korrigiert oder genehmigt.
10. Der Beitrag wird geplant oder veröffentlicht.

## 6.2 Automatische Wochenvorschläge

1. Scheduler startet einmal pro Woche.
2. Content Scout analysiert:
   - neue Quellen,
   - alte unverwendete Bilder,
   - neue Produkte,
   - saisonale Themen,
   - lange nicht beworbene Reihen,
   - geplante Veröffentlichungen,
   - offene Projekte.
3. Er erzeugt eine Liste potenzieller Themen.
4. Ein Ranking bewertet Relevanz, Aktualität, Vielfalt und Wiederholungsrisiko.
5. Für die zwei besten Themen werden Entwürfe erzeugt.
6. Benutzer erhält eine Benachrichtigung.
7. Beide Vorschläge erscheinen im Freigabe-Postfach.

## 6.3 Wiederverwendung eines Altbeitrags

1. System erkennt, dass ein Beitrag vor 12–18 Monaten gut funktioniert hat.
2. Es prüft, ob Fakten, Preise, Produktstatus und Links aktuell sind.
3. Es schlägt eine neue Perspektive vor.
4. Der Beitrag wird nicht kopiert, sondern neu erzählt.
5. Benutzer entscheidet über Freigabe.

## 6.4 Produkteinführung

1. Produkt wird aus Wix oder manuell importiert.
2. Produktdaten, Cover, Hörprobe, Zielgruppe und Autoren werden zusammengeführt.
3. System erzeugt eine Content-Serie:
   - Teaser,
   - Hintergrund,
   - Produktvorstellung,
   - Detailpost,
   - Kunden- oder Probenbezug,
   - Erinnerung.
4. Beiträge werden als Kampagne gespeichert.

## 6.5 Kundenfrage als Content

1. Häufige Kundenfrage wird manuell markiert oder anonymisiert importiert.
2. KI entfernt personenbezogene Daten.
3. Sie formuliert daraus:
   - FAQ,
   - Social Post,
   - Blogentwurf,
   - Händlerhinweis.
4. Benutzer prüft die fachliche Richtigkeit.

---

# 7. Informationsarchitektur der Weboberfläche

## 7.1 Hauptnavigation

- Dashboard
- Inbox
- Ideen
- Kalender
- Entwürfe
- Freigabe
- Veröffentlicht
- Medien
- Kampagnen
- Wissen
- Analysen
- Einstellungen

## 7.2 Dashboard

Das Dashboard beantwortet sofort:

- Was muss ich heute entscheiden?
- Welche zwei Vorschläge sind diese Woche bereit?
- Was ist geplant?
- Welche Inhalte fehlen?
- Welche Quelle wurde noch nicht verarbeitet?
- Gibt es Integrationsfehler?
- Wie hoch sind die KI-Kosten im laufenden Monat?

## 7.3 Inbox

Die Inbox sammelt unstrukturierte Eingänge:

- Fotos,
- Texte,
- Links,
- Sprachmemos,
- E-Mails,
- GitHub-Ereignisse,
- Wix-Ereignisse,
- manuelle Ideen.

Jeder Eingang erhält einen Status:

`neu → analysiert → als Idee übernommen → ignoriert → archiviert`

## 7.4 Ideenboard

Kanban-Spalten:

- Eingang
- interessant
- ausarbeiten
- Entwurf vorhanden
- zurückgestellt
- verworfen

## 7.5 Freigabeansicht

Die Freigabeansicht zeigt:

- Vorschau je Plattform,
- verwendete Quelle,
- Brand,
- Zielgruppe,
- Text,
- Hashtags,
- Medien,
- Risiken,
- Faktenprüfung,
- Ähnlichkeit zu früheren Posts,
- geplanten Zeitpunkt,
- Änderungsverlauf.

Aktionen:

- Freigeben
- Freigeben und planen
- Bearbeiten
- neue Variante
- kürzer
- weniger werblich
- humorvoller
- sachlicher
- ablehnen
- zurückstellen

---

# 8. Wireframes

## 8.1 Desktop-Dashboard

```text
┌─────────────────────────────────────────────────────────────────┐
│ XeisWorks Content Studio     Marke: [Alle ▼]      Bernhard      │
├──────────────┬──────────────────────────────────────────────────┤
│ Dashboard    │ Diese Woche                                     │
│ Inbox  5     │ ┌─────────────────┐ ┌─────────────────┐          │
│ Ideen  12    │ │ 2 zur Freigabe │ │ 1 geplant       │          │
│ Kalender     │ └─────────────────┘ └─────────────────┘          │
│ Entwürfe  4  │                                                  │
│ Freigabe  2  │ Vorschläge                                       │
│ Medien       │ ┌──────────────────────────────────────────────┐ │
│ Wissen       │ │ MusikHeroes: WarmUps #2 – Probenmoment      │ │
│ Analysen     │ │ [Vorschau] [Bearbeiten] [Freigeben]         │ │
│ Einstellungen│ └──────────────────────────────────────────────┘ │
│              │ ┌──────────────────────────────────────────────┐ │
│              │ │ XeisWorks: Blick hinter den Notensatz       │ │
│              │ │ [Vorschau] [Bearbeiten] [Freigeben]         │ │
│              │ └──────────────────────────────────────────────┘ │
└──────────────┴──────────────────────────────────────────────────┘
```

## 8.2 Mobile Schnellaufnahme

```text
┌──────────────────────────┐
│ + Neuer Content-Anlass   │
├──────────────────────────┤
│ [ Foto aufnehmen ]       │
│ [ Bild auswählen ]       │
│ [ Sprachmemo ]           │
│                          │
│ Worum geht es?           │
│ _______________________  │
│ _______________________  │
│                          │
│ Marke: MusikHeroes ▼     │
│ [ Speichern & Ideen ]    │
└──────────────────────────┘
```

## 8.3 Freigabekarte

```text
┌─────────────────────────────────────┐
│ Instagram – MusikHeroes             │
│ Bild 1/3                            │
│                                     │
│ Heute wurde aus einer Übung ...     │
│                                     │
│ #MusikHeroes #Blasmusik ...         │
│                                     │
│ Fakten: geprüft                     │
│ Wiederholungsrisiko: niedrig        │
│                                     │
│ [Bearbeiten] [Neu] [Freigeben]      │
└─────────────────────────────────────┘
```

---

# 9. Technische Zielarchitektur

## 9.1 Empfehlung

Für das Projekt wird eine modulare Web-Architektur empfohlen:

### Frontend

- Next.js oder React mit TypeScript
- Responsive Design
- Progressive Web App
- Komponentenbibliothek, z. B. shadcn/ui
- Formulare mit Schema-Validierung
- plattformnahe Post-Vorschau

### Backend

Empfehlung: **Python mit FastAPI**

Begründung:

- vorhandene Python-/PySide6-Erfahrung,
- gute KI- und Medienbibliotheken,
- klare API-Struktur,
- automatische OpenAPI-Dokumentation,
- einfache Hintergrundjobs,
- gute Testbarkeit.

Alternativ ist ein vollständiger TypeScript-Stack möglich. Wegen der bestehenden PySide6-App und möglicher späterer Wiederverwendung von Python-Code ist FastAPI jedoch strategisch sinnvoll.

### Datenbank

- PostgreSQL
- `pgvector` für semantische Suche
- Alembic für Migrationen

### Hintergrundjobs

- Redis
- Celery, Dramatiq oder RQ
- Scheduler für Wochenvorschläge, Token-Erneuerung, Analysen und Wiederholungsprüfungen

### Dateispeicher

- S3-kompatibler Objektspeicher
- in Entwicklung: MinIO oder lokaler Storage
- Produktion: Railway Volume, Cloudflare R2, AWS S3 oder kompatibler Dienst

### Deployment

Für das MVP:

- Railway
- ein Web-Service für FastAPI,
- ein Worker-Service,
- PostgreSQL,
- Redis,
- Objektspeicher extern oder Volume,
- Frontend wahlweise separat oder gemeinsam bereitgestellt.

## 9.2 Systemdiagramm

```text
Browser / Smartphone
        │
        ▼
Frontend (Next.js)
        │ HTTPS
        ▼
Backend API (FastAPI)
        │
        ├── PostgreSQL + pgvector
        ├── Redis / Job Queue
        ├── Object Storage
        ├── AI Provider Router
        │      ├── OpenAI
        │      ├── Gemini
        │      └── Anthropic
        ├── Meta Adapter
        ├── Wix Adapter
        ├── GitHub Adapter
        ├── Mail/Outlook Adapter
        └── Existing PySide6 App Adapter
```

## 9.3 Monorepo-Struktur

```text
xeisworks-content-studio/
├── apps/
│   ├── web/
│   ├── api/
│   └── worker/
├── packages/
│   ├── domain/
│   ├── prompts/
│   ├── schemas/
│   └── ui/
├── integrations/
│   ├── meta/
│   ├── wix/
│   ├── github/
│   ├── openai/
│   ├── gemini/
│   ├── anthropic/
│   └── outlook/
├── docs/
│   ├── architecture/
│   ├── adr/
│   ├── api/
│   └── operations/
├── tests/
├── infra/
├── scripts/
├── .github/
│   └── workflows/
├── AGENTS.md
├── README.md
└── docker-compose.yml
```

---

# 10. Datenmodell

## 10.1 Zentrale Entitäten

### Brand

- id
- name
- slug
- default_language
- tone_profile
- visual_profile
- active

### ContentSource

Ein Rohmaterial oder Anlass.

- id
- brand_id
- source_type
- title
- raw_text
- source_url
- occurred_at
- imported_at
- sensitivity
- processing_status
- metadata
- created_by

Mögliche `source_type`-Werte:

- manual_note
- photo
- video
- voice_note
- email
- wix_product
- wix_order_pattern
- github_event
- calendar_event
- customer_feedback
- published_post
- document

### MediaAsset

- id
- brand_id
- storage_key
- original_filename
- mime_type
- width
- height
- duration
- checksum
- copyright_status
- consent_status
- alt_text
- detected_text
- metadata

### Idea

- id
- brand_id
- source_id
- title
- angle
- audience
- content_pillar
- relevance_score
- novelty_score
- effort_score
- seasonal_score
- status
- generated_by_run_id

### Draft

- id
- idea_id
- brand_id
- platform
- format
- language
- body
- headline
- hashtags
- call_to_action
- status
- version
- parent_draft_id
- model_run_id
- factual_review_status
- brand_review_status

### Publication

- id
- draft_id
- platform
- external_post_id
- scheduled_at
- published_at
- status
- error_code
- error_message
- response_payload

### Campaign

- id
- brand_id
- name
- objective
- starts_at
- ends_at
- status
- product_id
- metadata

### PromptTemplate

- id
- name
- task_type
- version
- system_prompt
- user_template
- output_schema
- active
- evaluation_notes

### ModelRun

- id
- provider
- model
- task_type
- prompt_version
- input_tokens
- output_tokens
- estimated_cost
- latency_ms
- status
- request_id
- error
- created_at

### Approval

- id
- draft_id
- reviewer_id
- decision
- comment
- created_at

### AnalyticsSnapshot

- id
- publication_id
- collected_at
- impressions
- reach
- likes
- comments
- shares
- saves
- clicks
- video_views
- metadata

### AuditEvent

- id
- actor_type
- actor_id
- action
- entity_type
- entity_id
- timestamp
- payload

## 10.2 Relationen

```text
Brand
 ├── ContentSource
 │     ├── MediaAsset
 │     └── Idea
 │           └── Draft
 │                 ├── Approval
 │                 └── Publication
 │                       └── AnalyticsSnapshot
 ├── Campaign
 ├── PromptTemplate
 └── KnowledgeItem
```

## 10.3 Statusmaschinen

### Draft

```text
generated
  → editing
  → review_requested
  → approved
  → scheduled
  → published

review_requested
  → changes_requested
  → editing

approved
  → revoked
```

### Publication

```text
pending
  → queued
  → publishing
  → published

publishing
  → retryable_error
  → queued

publishing
  → permanent_error
```

---

# 11. Wissensbasis und semantische Suche

## 11.1 Wissensarten

- Markenregeln
- Produktinformationen
- Autoren und Ensembles
- Reihen und Ausgaben
- Zielgruppen
- gute Altbeiträge
- negative Beispiele
- FAQ
- Händlerkonditionen
- wiederkehrende Begriffe
- sachliche Fakten
- Veröffentlichungsdaten
- Kampagnenwissen

## 11.2 RAG-Prinzip

Vor der Texterzeugung werden passende Wissenselemente gesucht:

1. Anfrage analysieren.
2. Brand und Content-Typ bestimmen.
3. relevante Wissenselemente filtern.
4. semantisch ähnliche Inhalte abrufen.
5. Quellen in den Prompt geben.
6. strukturiertes Ergebnis verlangen.
7. Behauptungen mit Quellenreferenzen speichern.

## 11.3 Chunking

Dokumente werden nicht blind in gleich große Abschnitte geteilt. Sinnvolle Einheiten:

- Produktbeschreibung,
- FAQ-Eintrag,
- Projektstatus,
- Autorenprofil,
- Post,
- Presseaussendung,
- Kapitel,
- E-Mail-Zusammenfassung.

## 11.4 Quellenreferenzen

Jede KI-generierte Aussage kann intern auf `source_ids` verweisen. In der Freigabeansicht wird sichtbar:

- „Produktname aus Wix“
- „Zitat aus freigegebener Kundenstimme“
- „Veröffentlichungsdatum aus Produktdatensatz“
- „Probeninformation aus Notiz vom 18.07.2026“

---

# 12. Agentenarchitektur

Die Bezeichnung „Agent“ darf nicht zu unnötiger Komplexität führen. Viele Aufgaben sind deterministische Workflows mit einzelnen Modellaufrufen.

## 12.1 Content Scout

Aufgabe:

- neue Quellen analysieren,
- mögliche Content-Anlässe erkennen,
- Themenlücken finden,
- saisonale Chancen melden,
- unverwendetes Material aufspüren.

Output:

```json
{
  "ideas": [
    {
      "title": "WarmUps #2 erstmals im Einsatz",
      "angle": "Blick hinter die Kulissen",
      "audience": ["Musikpädagog:innen", "Jugendorchester"],
      "source_ids": ["src_123"],
      "reason": "aktueller Probenmoment mit authentischem Bild",
      "scores": {
        "relevance": 0.92,
        "novelty": 0.81,
        "effort": 0.20
      }
    }
  ]
}
```

## 12.2 Story Finder

Ermittelt mögliche Erzählwinkel:

- Problem → Lösung
- Entstehungsgeschichte
- Aha-Moment
- Blick hinter die Kulissen
- Person im Mittelpunkt
- Detail, das kaum jemand kennt
- Vorher/Nachher
- praktische Anwendung
- häufige Frage
- humorvolle Alltagsszene

## 12.3 Copywriter

Erzeugt plattformspezifische Varianten, nicht bloß denselben Text mit anderer Länge.

## 12.4 Brand Guardian

Prüft:

- Tonalität,
- Wortwahl,
- künstliche Werbesprache,
- unpassende Jugendbegriffe,
- zu viele Emojis,
- übertriebene Behauptungen,
- Verwechslung der Marken.

## 12.5 Fact Checker

Prüft nur gegen interne Quellen und optional freigegebene externe Recherche. Er darf fehlende Fakten nicht erfinden.

Ergebnis:

- verified
- partially_verified
- unsupported
- contradictory

## 12.6 Similarity Guard

Vergleicht Entwurf mit früheren Beiträgen. Er erkennt:

- gleiche Einstiegssätze,
- wiederholte Themen,
- gleiche Bildauswahl,
- zu ähnliche Hashtags,
- wiederholte Calls-to-Action.

## 12.7 Channel Adapter

Passt Inhalt an:

### Instagram

- visuell orientiert,
- kompakter Einstieg,
- klare Bild-/Carousel-Logik,
- begrenzte Hashtags,
- optional Reel-Skript.

### Facebook

- mehr Kontext möglich,
- stärker erzählerisch,
- Links sinnvoll einsetzbar,
- Zielgruppe oft älter und vereinsnah.

### Später: Newsletter

- Betreff,
- Preheader,
- längerer Kontext,
- klarer CTA,
- Segmentierung.

## 12.8 Publishing Agent

Dieser Agent ist kein frei handelndes Sprachmodell. Er ist ein deterministischer Dienst mit klarer Rechteprüfung:

1. Approval prüfen.
2. Medien validieren.
3. Plattformregeln prüfen.
4. Idempotency Key setzen.
5. API-Aufruf durchführen.
6. Ergebnis speichern.
7. Fehler klassifizieren.
8. bei temporären Fehlern kontrolliert wiederholen.

## 12.9 Analytics Interpreter

Erklärt Ergebnisse vorsichtig:

- welche Themen überdurchschnittlich waren,
- welche Formate gut funktionierten,
- welche Aussagen noch keine belastbare Schlussfolgerung erlauben.

Keine voreiligen Marketingbehauptungen bei kleinen Datenmengen.

---

# 13. Multi-LLM-Strategie

## 13.1 Grundsatz

Provider und Modelle werden nicht hart im Fachcode verdrahtet.

```python
class LLMProvider(Protocol):
    async def generate(
        self,
        task: LLMTask,
        messages: list[Message],
        response_schema: dict | None,
        options: GenerationOptions,
    ) -> LLMResult:
        ...
```

Provider:

- OpenAIProvider
- GeminiProvider
- AnthropicProvider
- optional später LocalProvider

## 13.2 Modell-Router

Der Router entscheidet anhand von:

- task_type,
- benötigter Modalität,
- gewünschter Qualität,
- Budget,
- Latenz,
- Datenschutzklasse,
- aktueller Verfügbarkeit,
- Provider-Fehlerquote,
- Ergebnisqualität früherer Läufe.

Beispielkonfiguration:

```yaml
routing:
  social_idea_generation:
    primary: gemini_creative
    fallback:
      - openai_balanced
      - anthropic_balanced

  factual_rewrite:
    primary: openai_balanced
    fallback:
      - anthropic_balanced

  long_form_strategy:
    primary: anthropic_reasoning
    fallback:
      - openai_reasoning

  image_understanding:
    primary: gemini_multimodal
    fallback:
      - openai_vision
```

## 13.3 Keine statische Aussage „Modell X ist immer besser“

Modelle ändern sich schnell. Deshalb:

- Fähigkeiten werden konfiguriert.
- Modellnamen liegen in Umgebungsvariablen oder Admin-Einstellungen.
- automatische Evaluierungen vergleichen Ergebnisse.
- Modelle können ohne Codeänderung deaktiviert werden.

## 13.4 Provider-Ensemble

Mehrere Modelle werden nur bei wertvollen Aufgaben parallel eingesetzt, nicht standardmäßig.

Sinnvoll bei:

- Kampagnenkonzept,
- Markenclaim,
- Produktlaunch,
- schwieriger Tonalität,
- strategischer Content-Serie.

Nicht sinnvoll bei:

- Hashtag-Normalisierung,
- einfacher Kürzung,
- Metadatenextraktion,
- Klassifizierung.

## 13.5 Jury-Verfahren

1. Zwei Modelle erzeugen unabhängig Varianten.
2. Ein dritter Lauf bewertet nach festem Rubric.
3. Die Anwendung zeigt Sieger und Alternativen.
4. Bewertung und Benutzerentscheidung fließen in spätere Provider-Statistiken ein.

## 13.6 Strukturierte Ausgaben

Alle maschinenverarbeiteten Antworten müssen gegen JSON Schema validiert werden.

Bei Schemafehler:

1. einmalige Reparaturanfrage,
2. falls erneut fehlerhaft: Fallback-Modell,
3. falls weiterhin fehlerhaft: Lauf als gescheitert markieren.

## 13.7 Kostenkontrolle

- Monatslimit gesamt
- Limit je Provider
- Limit je Marke
- Limit je Task
- Warnung bei 70 %, 90 % und 100 %
- teure Ensemble-Läufe nur nach Regel oder manueller Auswahl
- Prompt-Caching, wo unterstützt
- Batch-Verarbeitung für nicht dringende Aufgaben
- Speicherung geschätzter und tatsächlicher Kosten

## 13.8 Wichtiger Abo-Hinweis

ChatGPT Plus, Gemini-App-Abos und Claude Pro sind nicht automatisch dasselbe wie API-Zugang. Das Content Studio benötigt eigene API-Schlüssel und eine gesonderte nutzungsabhängige Abrechnung. Ein zusätzliches Chat-Abo ist für die Anwendung nicht erforderlich.

Empfehlung:

- bestehendes ChatGPT Plus für persönliche Arbeit behalten,
- GitHub Copilot für Inline-Unterstützung behalten,
- API-Konten nur für die Anwendung einrichten,
- Gemini- oder Claude-Chat-Abo nur abschließen, wenn diese Tools auch persönlich als zweite Meinung genutzt werden sollen,
- nicht wegen des Content Studios allein ein zusätzliches Chat-Abo kaufen.

---

# 14. Prompt-System

## 14.1 Prompt-Schichten

Jeder Lauf setzt sich zusammen aus:

1. globale Sicherheitsregeln,
2. Markenprofil,
3. Aufgabenvorlage,
4. relevante Wissensquellen,
5. Kanalregeln,
6. konkrete Benutzereingabe,
7. Ausgabe-Schema.

## 14.2 Prompt-Versionierung

Prompts werden wie Code behandelt:

- eindeutiger Name,
- semantische Version,
- Änderungsnotiz,
- Testfälle,
- Qualitätswerte,
- Aktivierungsstatus,
- Rollback.

## 14.3 Beispiel: Social Draft

```text
SYSTEM:
Du schreibst für die Marke {{brand.name}}.
Halte dich strikt an das Markenprofil.
Erfinde keine Fakten.
Verwende ausschließlich Fakten aus SOURCES.
Kennzeichne intern jede sachliche Aussage mit source_ids.
Vermeide generische Werbesprache.

TASK:
Erstelle einen {{platform}}-Beitrag zum Blickwinkel {{angle}}.

AUDIENCE:
{{audience}}

SOURCES:
{{retrieved_sources}}

OUTPUT:
Antworte ausschließlich im vorgegebenen JSON-Schema.
```

## 14.4 Qualitätsrubric

Jeder Entwurf wird mit 0–5 bewertet:

- Markentreue
- Verständlichkeit
- Authentizität
- Originalität
- Faktenbasis
- Plattformtauglichkeit
- Werbedruck
- Handlungsimpuls
- Wiederholungsrisiko

Ein Entwurf mit Faktenbasis unter 4 darf nicht automatisch zur Freigabe gelangen.

---

# 15. Content-Säulen

## 15.1 XeisWorks

1. Neue Produkte
2. Blick hinter die Kulissen
3. Notensatz und Verlagsarbeit
4. Ensembles und Künstler
5. Praxiswissen für Musiker
6. Geschichten hinter Arrangements
7. Kundenfragen
8. Archiv und Wiederentdeckungen
9. Veranstaltungen und Termine
10. Humor aus dem Verlagsalltag

## 15.2 MusikHeroes

1. Probenpraxis
2. Unterrichtsimpulse
3. Produktreihen
4. Playalongs
5. Illustrationen
6. Entstehungsprozess
7. Team
8. Schüler- und Lehrerperspektive
9. Mini-Übungen
10. Motivation und gemeinsames Musizieren

## 15.3 Verteilungsregeln

Beispiel:

- maximal zwei direkte Produktverkaufsposts hintereinander,
- mindestens jeder dritte Beitrag mit praktischem oder erzählerischem Mehrwert,
- keine identische Content-Säule häufiger als zweimal in vier Wochen,
- saisonale Regeln haben Vorrang,
- neue Produkte erhalten definierte Kampagnenfrequenz.

---

# 16. Medien-Workflow

## 16.1 Upload

Beim Upload:

- Dateityp prüfen,
- Virenscan,
- Prüfsumme bilden,
- Duplikate erkennen,
- EXIF-Daten optional entfernen,
- Vorschauen erzeugen,
- Bildmaße erkennen,
- sensible Inhalte markieren,
- Copyright-/Consent-Status abfragen.

## 16.2 Bildanalyse

KI kann beschreiben:

- sichtbare Personen,
- Instrumente,
- Noten,
- Umgebung,
- Stimmung,
- mögliche Bildausschnitte,
- Eignung je Plattform.

Die Analyse darf keine Identität raten.

## 16.3 Consent

Für Bilder mit Schülern oder erkennbaren Personen:

- Einwilligungsstatus speichern,
- Verwendungszweck speichern,
- Ablaufdatum optional,
- Veröffentlichung blockieren, wenn Status unklar ist.

## 16.4 Derivate

Originale bleiben unverändert. Für Plattformen werden Derivate erzeugt:

- Instagram Hochformat,
- Quadrat,
- Facebook Querformat,
- Thumbnail,
- komprimierte Vorschau.

## 16.5 Canva

Canva kann später angebunden werden, sollte aber nicht das MVP blockieren. Zunächst genügen:

- Bildauswahl,
- Zuschnitt,
- einfache Text-Overlays,
- definierte Vorlagen.

---

# 17. Meta Graph API

## 17.1 Ziel

- Instagram-Posts veröffentlichen,
- Reels und Carousels je nach API-Unterstützung,
- Facebook-Seitenposts veröffentlichen,
- Veröffentlichungsstatus speichern,
- ausgewählte Insights abrufen.

## 17.2 Voraussetzungen

- Meta Developer App,
- professionelle Instagram-Konten,
- korrekte Verbindung mit Facebook-Seite,
- benötigte Berechtigungen,
- App Review für produktive Verwendung,
- Datenschutz-URL,
- Löschanweisungen,
- OAuth-Flow,
- sichere Token-Speicherung.

## 17.3 Publish Flow

```text
Approved Draft
   │
   ├── validate media
   ├── validate token
   ├── create media container
   ├── poll container status if needed
   ├── publish container
   ├── save external ID
   └── fetch final permalink/status
```

## 17.4 Token Management

- Token verschlüsselt speichern,
- Ablaufdatum speichern,
- vor Ablauf warnen,
- Erneuerung dokumentieren,
- Provider-Fehler klar anzeigen,
- niemals Tokens im Frontend oder Log ausgeben.

## 17.5 Idempotenz

Jeder Veröffentlichungsauftrag erhält einen stabilen Schlüssel:

```text
publication:{publication_id}:{draft_version}
```

Vor jedem erneuten Versuch wird geprüft, ob bereits eine externe Post-ID existiert.

## 17.6 AI-Kennzeichnung

Das Datenmodell soll eine optionale Kennzeichnung für KI-generierte oder KI-bearbeitete Inhalte vorsehen, da Plattformregeln und API-Felder sich ändern können.

## 17.7 Fallback

Falls direktes Veröffentlichen nicht verfügbar ist:

- „Exportpaket“ erzeugen,
- finalen Text kopierbar anzeigen,
- Medien in korrekter Reihenfolge bereitstellen,
- Deep Link oder klare manuelle Anleitung anbieten,
- Status `manual_publish_required`.

---

# 18. Wix-Integration

## 18.1 Mögliche Daten

- Produkte,
- Produktbilder,
- neue Veröffentlichungen,
- Bestelltrends,
- Kategorien,
- Verfügbarkeit,
- URLs,
- Preise,
- Sonderaktionen.

## 18.2 Datenschutzregel

Einzelne Bestellungen und Kundendaten werden nicht automatisch als Content verwendet.

Erlaubt sind aggregierte Muster, z. B.:

- „Diese Woche besonders gefragt“
- „Viele Anfragen zu …“

Nur ab ausreichend großer Menge und ohne Rückschluss auf Personen.

## 18.3 Webhooks

Wix-Webhooks können doppelt oder verspätet eintreffen. Daher:

- Event-ID speichern,
- Verarbeitung idempotent machen,
- sofort 2xx antworten,
- eigentliche Verarbeitung in Job Queue,
- Reihenfolge nicht blind voraussetzen,
- Datensatz bei Bedarf über API nachladen.

## 18.4 Produkt-Synchronisation

Ein periodischer Abgleich bleibt zusätzlich sinnvoll:

- täglich geänderte Produkte abrufen,
- fehlende Webhook-Ereignisse erkennen,
- archivierte Produkte aktualisieren,
- Bildänderungen nachvollziehen.

---

# 19. GitHub-Integration

## 19.1 Zweck

GitHub soll nicht automatisch Quellcode als Marketinginhalt veröffentlichen. Es dient als Signalquelle.

Beispiele:

- neues Release,
- abgeschlossene Funktion,
- neue Website-Funktion,
- größere Produktaktualisierung,
- Dokumentationsänderung,
- Meilenstein.

## 19.2 GitHub App statt Personal Access Token

Empfohlen:

- GitHub App mit minimalen Rechten,
- Installation nur auf ausgewählten Repositories,
- Webhook Secret,
- Signaturprüfung,
- Ereignisfilter,
- keine unnötigen Schreibrechte.

## 19.3 Content-Relevanzfilter

Nicht jeder Commit ist interessant. Regeln:

- Merge auf Hauptbranch allein ist kein Post.
- Issue/PR mit Label `content-worthy` wird bevorzugt.
- Releases und manuell markierte Meilensteine sind stark.
- Dateinamen, Secrets, Kundendaten und interner Code werden nicht in Prompts übernommen.
- KI erhält eine abstrahierte Zusammenfassung, keine vollständigen privaten Repositories.

---

# 20. Outlook- und E-Mail-Integration

## 20.1 Sinnvolle Funktionen

- wöchentliche Vorschläge als E-Mail-Zusammenfassung,
- Freigabelink,
- Export eines Beitrags als Outlook-Entwurf,
- markierte Kundenfragen anonymisiert in die Inbox übernehmen,
- Händlernewsletter später als Entwurf erzeugen.

## 20.2 Kein automatisches Durchsuchen aller E-Mails im MVP

Stattdessen:

- Benutzer markiert oder leitet relevante Nachricht weiter,
- Outlook-Add-in erhält Aktion „Als Content-Anlass senden“,
- personenbezogene Daten werden vor Speicherung angezeigt und entfernt.

## 20.3 Bestehender Outlook-Copilot

Der vorhandene Copilot kann später einen Button erhalten:

`An XeisWorks Content Studio übergeben`

Payload:

- Betreff,
- ausgewählter Text,
- optionale Benutzerzusammenfassung,
- Brand,
- Sensitivitätsstufe.

---

# 21. Anbindung der bestehenden PySide6-App

## 21.1 Ziel

Die Verlags-App kann Content-Anlässe liefern:

- neues Produkt angelegt,
- Rechnung/Bestellungsmuster,
- Veröffentlichung abgeschlossen,
- Sonderprojekt,
- häufige Kundenfrage,
- neues Arrangement.

## 21.2 Integration

Die PySide6-App sendet an eine interne REST-API:

```http
POST /api/v1/content-sources
Authorization: Bearer <service-token>
Idempotency-Key: <uuid>
```

Beispiel:

```json
{
  "brand": "xeisworks",
  "source_type": "internal_event",
  "title": "Neue Ausgabe veröffentlicht",
  "raw_text": "Produkt XY wurde heute im Shop freigeschaltet.",
  "metadata": {
    "product_id": "wix_123",
    "internal_reference": "..."
  }
}
```

## 21.3 Sicherheitsregel

Die PySide6-App erhält einen eigenen Service-Account mit eng begrenztem Scope:

`content_source:create`

---

# 22. Redaktionskalender und Planung

## 22.1 Kalenderfunktionen

- Wochen- und Monatsansicht,
- Drag-and-drop,
- Filter nach Marke,
- Filter nach Plattform,
- Kampagnenansicht,
- Statusfarben,
- Konflikthinweise,
- saisonale Marker.

## 22.2 Posting-Frequenz

Startempfehlung:

- 1–2 hochwertige Beiträge pro Woche,
- keine künstliche tägliche Frequenz,
- zusätzliche Posts nur bei echten Anlässen.

## 22.3 Zeitvorschläge

Das System darf Zeiten vorschlagen, aber nicht als universelle Wahrheit behandeln. Es lernt aus eigenen historischen Ergebnissen.

## 22.4 Content-Balance

Der Kalender zeigt Warnungen:

- zu viele Produktposts,
- Marke seit längerer Zeit inaktiv,
- gleiche Zielgruppe zu oft,
- gleiche Bildart wiederholt,
- Kampagne ohne Abschlussbeitrag.

---

# 23. Analytics

## 23.1 Metriken

Je nach Plattformverfügbarkeit:

- Reichweite,
- Impressionen,
- Likes,
- Kommentare,
- Shares,
- Saves,
- Klicks,
- Videoaufrufe,
- Engagement-Rate.

## 23.2 Vergleichslogik

Vergleiche nur sinnvoll innerhalb ähnlicher Gruppen:

- gleiche Plattform,
- ähnliches Format,
- ähnliche Reichweite,
- ähnliche Veröffentlichungsphase,
- gleiche Marke.

## 23.3 Lernschleife

Nach Veröffentlichung:

1. Metriken nach definierten Zeitpunkten abrufen.
2. mit Baseline vergleichen.
3. Content-Säule und Format bewerten.
4. qualitative Benutzernotiz erlauben.
5. Erkenntnisse als Empfehlung speichern.

## 23.4 Keine automatische Selbstoptimierung ohne Kontrolle

Prompts werden nicht allein aufgrund eines erfolgreichen Posts geändert. Änderungen benötigen:

- ausreichend Daten,
- nachvollziehbare Hypothese,
- A/B- oder Vergleichstest,
- manuelle Aktivierung.

---

# 24. Sicherheit und Datenschutz

## 24.1 Datenklassifikation

- public
- internal
- confidential
- personal_data
- restricted

## 24.2 Provider-Regeln

Pro Task wird festgelegt, welche Daten an externe KI-Provider gesendet werden dürfen.

Beispiel:

- öffentliche Produktbeschreibung: erlaubt,
- interne Projektnotiz: erlaubt nach Richtlinie,
- Kundendaten: vorher anonymisieren,
- Zahlungsdaten: nie senden,
- API-Schlüssel: nie senden,
- Schülerdaten: grundsätzlich blockieren oder streng anonymisieren.

## 24.3 Secret Management

- lokale Entwicklung: `.env`, nicht committen,
- Produktion: Railway Secrets,
- Rotation,
- getrennte Schlüssel je Umgebung,
- keine Secrets in Logs,
- Secret-Scanning in CI.

## 24.4 Authentifizierung

MVP:

- sichere E-Mail-/Passwort-Anmeldung oder OAuth,
- Multi-Faktor-Authentifizierung für Owner,
- kurze Sessions für sensible Einstellungen.

## 24.5 Autorisierung

Serverseitige Prüfung bei jeder Aktion. UI-Ausblendung allein genügt nicht.

## 24.6 Audit

Auditpflichtig:

- Freigabe,
- Veröffentlichung,
- Löschung,
- API-Schlüsseländerung,
- Rollenänderung,
- Export,
- Consent-Änderung,
- Prompt-Aktivierung.

## 24.7 DSGVO

Erforderlich:

- Verzeichnis verarbeiteter Daten,
- Auftragsverarbeitungsverträge prüfen,
- Speicherfristen,
- Auskunft/Löschung,
- Datenminimierung,
- dokumentierte Rechtsgrundlagen,
- EU-/Drittlandtransfer bewerten,
- Consent für Personenbilder.

Dieses Konzept ersetzt keine individuelle Rechtsberatung.

---

# 25. Zuverlässigkeit und Fehlerbehandlung

## 25.1 Fehlerklassen

- validation_error
- authentication_error
- permission_error
- rate_limit
- provider_outage
- timeout
- malformed_model_output
- media_processing_error
- permanent_publish_error
- retryable_publish_error

## 25.2 Retry-Strategie

- exponentielles Backoff,
- Jitter,
- maximale Versuche,
- keine Wiederholung bei Berechtigungs- oder Validierungsfehlern,
- Dead Letter Queue,
- manuelle Wiederaufnahme.

## 25.3 Circuit Breaker

Wenn ein KI-Provider wiederholt ausfällt:

- Provider temporär sperren,
- Fallback verwenden,
- Administrator informieren,
- keine Endlosschleifen.

## 25.4 Health Checks

- API,
- Datenbank,
- Redis,
- Worker,
- Storage,
- Provider-Konfiguration,
- Meta-Token-Status.

---

# 26. Tests und Qualitätssicherung

## 26.1 Unit Tests

- Scoring,
- Statusmaschinen,
- Berechtigungen,
- Provider-Routing,
- Kostenberechnung,
- Textnormalisierung,
- Idempotenz.

## 26.2 Integration Tests

- PostgreSQL,
- Redis,
- Objektspeicher,
- Provider-Mocks,
- Meta-Sandbox/Testkonto,
- Wix-Webhook-Signaturen,
- GitHub-Webhook-Signaturen.

## 26.3 Contract Tests

Jeder Provider-Adapter muss dieselben internen Schemas erfüllen.

## 26.4 Prompt Tests

Testdatensatz mit typischen Fällen:

- Produktvorstellung,
- Probenfoto,
- fehlende Fakten,
- zu werblicher Ausgangstext,
- Bild mit Schülern,
- ähnliche Altbeiträge,
- gemischte Marke,
- österreichische Sprachvariante.

## 26.5 Golden Set

Mindestens 30 von Bernhard freigegebene Beispielinputs mit Zielqualität. Jeder Prompt- oder Modellwechsel wird dagegen getestet.

## 26.6 End-to-End

- Quelle anlegen,
- Idee erzeugen,
- Draft erstellen,
- bearbeiten,
- freigeben,
- planen,
- Mock-Veröffentlichung,
- Analytics importieren.

---

# 27. CI/CD und Entwicklungsprozess

## 27.1 GitHub Actions

Bei Pull Requests:

- Linting,
- Type Checking,
- Unit Tests,
- Migration Check,
- Security Scan,
- Frontend Build,
- Backend Build,
- Prompt-Schema-Tests.

Bei Main:

- Staging Deployment,
- Smoke Tests,
- manuelle Freigabe Produktion.

## 27.2 Branching

- `main` stabil,
- kurze Feature-Branches,
- Pull Requests,
- keine direkten Produktionsänderungen.

## 27.3 ADRs

Wichtige Entscheidungen als Architecture Decision Records:

- ADR-001 FastAPI + Next.js
- ADR-002 PostgreSQL + pgvector
- ADR-003 Multi-Provider LLM
- ADR-004 Human Approval Required
- ADR-005 GitHub App
- ADR-006 Meta Publishing Strategy
- ADR-007 Railway Deployment

---

# 28. MVP-Umfang

## 28.1 Muss-Funktionen

- Login
- Markenprofile
- manuelle Schnellaufnahme
- Bild-Upload
- Ideen-Generierung
- Draft-Generierung für Instagram und Facebook
- Brand- und Faktenprüfung
- Freigabe-Workflow
- Kalender
- Exportpaket
- Meta-Veröffentlichung, sofern App-Freigabe verfügbar
- Modell-Router mit mindestens OpenAI und Gemini
- Kostenprotokoll
- Audit-Protokoll
- einfache Suche
- responsive Bedienung

## 28.2 Soll-Funktionen

- Altposts importieren
- semantische Ähnlichkeitsprüfung
- Wochenvorschläge
- Meta-Analytics
- Wix-Produkte synchronisieren
- GitHub-Releases als Signal
- Sprachmemos
- Benachrichtigungs-E-Mail

## 28.3 Später

- Claude als dritter Provider
- Outlook-Add-in-Integration
- PySide6-Integration
- Newsletter
- Blog
- Canva
- Video-/Reel-Assistent
- Händlerkommunikation
- automatische Kampagnen
- Teamzugänge

---

# 29. Roadmap

## Phase 0 – Projektgrundlage

- Repository anlegen
- AGENTS.md
- lokale Entwicklungsumgebung
- Architekturentscheidungen
- Datenmodell
- CI
- Secret-Konzept
- Teststrategie

**Ergebnis:** stabiles Fundament.

## Phase 1 – Content Inbox

- Auth
- Brands
- Quellen
- Upload
- Inbox
- mobile Schnellaufnahme
- Storage

**Ergebnis:** Rohmaterial kann zuverlässig gesammelt werden.

## Phase 2 – KI-Erzeugung

- Provider-Interface
- OpenAI-Adapter
- Gemini-Adapter
- Prompt-Versionierung
- Ideen
- Drafts
- strukturierte Ausgaben
- Kostenlogging

**Ergebnis:** aus Quellen entstehen kontrollierte Entwürfe.

## Phase 3 – Freigabe und Kalender

- Draft-Editor
- Review
- Approval
- Versionen
- Kalender
- Exportpaket

**Ergebnis:** vollständiger manueller Content-Workflow.

## Phase 4 – Meta

- OAuth
- Kontenzuordnung
- Token-Verwaltung
- Publishing
- Retry
- Insights
- App Review

**Ergebnis:** freigegebene Inhalte können direkt veröffentlicht werden.

## Phase 5 – Automatische Content Scouts

- Wochenjob
- Ranking
- Wiederverwendung
- Ähnlichkeitsprüfung
- saisonale Regeln
- Benachrichtigungen

**Ergebnis:** System liefert proaktiv Vorschläge.

## Phase 6 – Verlagssystem-Integrationen

- Wix
- GitHub
- PySide6
- Outlook

**Ergebnis:** Content entsteht aus bestehender Arbeit.

## Phase 7 – Erweiterte Kanäle

- Newsletter
- Blog
- Händlerkommunikation
- Kampagnen
- Canva

---

# 30. Priorisierte Backlog-Epics

## Epic 1: Foundation

- Monorepo
- Docker Compose
- FastAPI
- Next.js
- PostgreSQL
- Redis
- Migrationen
- CI

## Epic 2: Identity and Brands

- Benutzer
- Rollen
- Markenprofile
- Tone-of-Voice-Editor

## Epic 3: Content Sources

- manuelle Notiz
- Foto
- Sprachmemo
- Metadaten
- Inbox

## Epic 4: AI Core

- Provider-Abstraktion
- Router
- JSON Schema
- Prompt Registry
- ModelRun
- Kostenlimits

## Epic 5: Ideas and Drafts

- Ideenboard
- Generator
- Varianten
- Versionierung
- Editor

## Epic 6: Quality

- Brand Guardian
- Fact Checker
- Similarity Guard
- Risk Flags

## Epic 7: Approval

- Review Inbox
- Freigabe
- Kommentar
- Audit

## Epic 8: Publishing

- Meta Adapter
- Token
- Queue
- Idempotenz
- Status

## Epic 9: Analytics

- Snapshot
- Dashboard
- Content-Säulen
- Vergleich

## Epic 10: Integrations

- Wix
- GitHub
- Outlook
- PySide6

---

# 31. Konkrete erste Arbeitspakete für den Codex-Agenten

## Ticket 1: Repository Bootstrap

**Ziel:** ausführbares Monorepo.

**Akzeptanzkriterien:**

- `docker compose up` startet PostgreSQL, Redis, API und Web.
- API liefert `/health`.
- Web zeigt Login-Platzhalter.
- Tests laufen in GitHub Actions.
- README enthält Setup.
- `.env.example` vollständig.
- keine Secrets im Repository.

## Ticket 2: Domain Models

**Ziel:** erste Datenbankstruktur.

Implementieren:

- User
- Brand
- ContentSource
- MediaAsset
- Idea
- Draft
- ModelRun
- AuditEvent

Akzeptanzkriterien:

- Alembic-Migration,
- CRUD-Tests,
- serverseitige Validierung,
- UTC-Zeitstempel,
- Soft Delete, wo sinnvoll.

## Ticket 3: Content Source API

Endpoints:

```text
POST   /api/v1/content-sources
GET    /api/v1/content-sources
GET    /api/v1/content-sources/{id}
PATCH  /api/v1/content-sources/{id}
POST   /api/v1/content-sources/{id}/media
```

## Ticket 4: Provider Interface

- internes Task-Schema,
- OpenAI-Adapter,
- Gemini-Adapter,
- FakeProvider für Tests,
- Timeouts,
- Kostenlogging,
- strukturierte Ausgabe,
- Fallback.

## Ticket 5: Idea Generator

Input:

- Source ID
- Brand ID
- gewünschte Anzahl

Output:

- validierte Ideen,
- Quellenreferenzen,
- Scores.

## Ticket 6: Draft Generator

- Instagram Feed
- Facebook Feed
- zwei Varianten
- Brand-Profil
- Quellen
- JSON Schema
- kein Fakten-Erfinden.

## Ticket 7: Approval Workflow

- Statusmaschine,
- Berechtigungen,
- Änderungsverlauf,
- Audit,
- UI.

---

# 32. AGENTS.md für Codex und andere Coding Agents

Im Root des Repositories sollte folgende Datei entstehen:

```markdown
# AGENTS.md

## Mission
Build the XeisWorks Content Studio according to the architecture documents.

## Non-negotiable rules
- Never expose secrets.
- Never publish social content without an approved Approval record.
- All external side effects must be idempotent.
- All AI outputs used by code must be schema validated.
- Do not hard-code model names in domain logic.
- Do not send personal, payment, student or secret data to AI providers.
- Add or update tests for every behavior change.
- Use database migrations for schema changes.
- Keep provider-specific code behind adapters.
- Log model usage and estimated cost.
- Preserve auditability.

## Before coding
1. Read relevant docs and ADRs.
2. Inspect existing patterns.
3. State affected modules.
4. Implement the smallest coherent slice.
5. Run tests, lint and type checks.
6. Summarize changed files and unresolved risks.

## Definition of done
- Acceptance criteria met.
- Tests pass.
- No new security warnings.
- Documentation updated.
- Error paths handled.
- User-facing text in German unless technically required otherwise.
```

---

# 33. Empfohlene Extension- und Tool-Strategie

## 33.1 VS Code bleibt die Zentrale

Für dieses Projekt ist VS Code sehr gut geeignet, weil:

- bestehende Arbeitsweise,
- GitHub-Repositories,
- Terminal,
- Docker,
- Tests,
- Datenbanktools,
- Codex-Agent,
- GitHub Copilot,
- flexible Erweiterungen.

## 33.2 Codex

Primärer Umsetzungsagent für:

- repositoryweite Änderungen,
- neue Features,
- Tests,
- Refactoring,
- API-Integrationen,
- Fehleranalyse.

## 33.3 GitHub Copilot

Behalten für:

- Inline-Vervollständigung,
- kleine Funktionen,
- Testskelett,
- lokale Erklärungen,
- schnelle Änderungen.

## 33.4 Claude Code

Optional als zweite technische Meinung bei:

- großen Architekturumbauten,
- schwierigen Refactorings,
- Code Reviews,
- langen, zusammenhängenden Analysen.

Es ist kein Muss für den Start.

## 33.5 Gemini

Gemini soll im Produkt als API-Provider getestet werden. Dafür ist kein separates Gemini-Chat-Abo erforderlich.

Ein persönliches Gemini-Abo ist nur sinnvoll, wenn Bernhard Gemini zusätzlich außerhalb der Anwendung regelmäßig für kreative Gegenentwürfe oder Recherche einsetzen möchte.

## 33.6 Empfehlung

Zunächst keine weitere monatliche Coding-Extension abonnieren.

Budget stattdessen einsetzen für:

- API-Nutzung,
- Railway,
- Storage,
- Meta-App-Setup,
- Tests,
- eventuell einmalige externe Security-/Architecture-Review.

---

# 34. Betriebs- und Kostenmodell

## 34.1 Fixkosten

- Hosting
- PostgreSQL
- Redis
- Storage
- Domain/Subdomain
- Monitoring

## 34.2 Variable Kosten

- KI-Tokens
- Transkription
- Bildanalyse
- optionale Medienverarbeitung
- E-Mail-Versand

## 34.3 Kostenarme Betriebsweise

- kleine Modelle für Klassifikation,
- starke Modelle nur für Finaltexte,
- Embeddings nur bei neuen/geänderten Inhalten,
- Wochenverarbeitung als Batch,
- Caching wiederholter Markenprompts,
- Deduplizierung vor KI-Aufruf,
- harte Monatslimits.

## 34.4 Admin-Anzeige

```text
Juli 2026
OpenAI       € 8,20
Gemini       € 3,10
Anthropic    € 0,00
Transkription € 0,80
Gesamt       €12,10 / Limit €40
```

---

# 35. Erfolgskennzahlen

## 35.1 Prozess

- Minuten manueller Aufwand pro Woche
- Anzahl verwertbarer Vorschläge
- Anteil freigegebener Vorschläge
- durchschnittliche Änderungen vor Freigabe
- Zeit von Quelle bis Veröffentlichung
- Zahl unverarbeiteter Quellen

## 35.2 Qualität

- Markentreue
- Faktenfehler
- Wiederholungsrate
- Benutzerbewertung
- Anteil direkt freigegebener Entwürfe

## 35.3 Marketing

- regelmäßige Wochen mit mindestens einem Post
- Reichweite pro Format
- Saves/Shares
- Klicks
- Reaktionen auf Produktserien
- qualitative Rückmeldungen

## 35.4 Technisch

- Publish-Erfolgsrate
- Provider-Ausfallrate
- Job-Laufzeit
- Kosten pro freigegebenem Post
- Fehler bis zur Behebung
- Testabdeckung kritischer Module

---

# 36. Risiken und Gegenmaßnahmen

## Risiko: KI klingt künstlich

Gegenmaßnahmen:

- echte Quellen,
- gute Beispielposts,
- Brand Guardian,
- mehrere Varianten,
- menschliche Freigabe.

## Risiko: System erzeugt mehr Arbeit

Gegenmaßnahmen:

- MVP klein halten,
- Schnellaufnahme,
- nur zwei Vorschläge pro Woche,
- keine Pflichtfelder ohne Nutzen,
- Defaults,
- klare Inbox.

## Risiko: API-Änderungen

Gegenmaßnahmen:

- Adapter,
- Versionierung,
- Monitoring,
- Export-Fallback,
- Changelog-Prüfung.

## Risiko: Meta App Review verzögert sich

Gegenmaßnahmen:

- Exportworkflow zuerst,
- Veröffentlichung als separate Phase,
- saubere Screencasts und Datenschutzseiten,
- Testkonto.

## Risiko: Kosten steigen

Gegenmaßnahmen:

- Limits,
- kleine Modelle,
- Batch,
- Kosten-Dashboard,
- Ensemble nur gezielt.

## Risiko: sensible Daten gelangen in Prompts

Gegenmaßnahmen:

- Datenklassifikation,
- DLP-Filter,
- Anonymisierung,
- Blocklisten,
- Tests,
- getrennte Logs.

## Risiko: zu große Erstversion

Gegenmaßnahmen:

- strikt nach Phasen,
- keine Canva-/Newsletter-/Video-Integration vor funktionierendem Kernworkflow,
- Definition of Done je Epic.

---

# 37. Entscheidungsempfehlungen

1. **Web-App statt neuer PySide6-App.**
2. **FastAPI + PostgreSQL + Next.js** als Zielstack.
3. **Railway** für das MVP.
4. **OpenAI + Gemini** im ersten Provider-Set.
5. **Claude** später ergänzen, nicht als Blocker.
6. **Meta-Veröffentlichung erst nach stabilem Freigabe-Workflow.**
7. **GitHub, Wix, Outlook und PySide6 nacheinander anbinden.**
8. **Kein Fine-Tuning im MVP.**
9. **Keine autonome Veröffentlichung.**
10. **Keine zusätzliche Chat-Subscription allein für die API-Integration.**
11. **Codex als Hauptagent, Copilot als tägliche Ergänzung.**
12. **Pro Woche zunächst nur zwei hochwertige Vorschläge.**

---

# 38. Startprompt für den Codex-Agenten

```text
Du arbeitest im Repository „xeisworks-content-studio“.

Lies zuerst vollständig:
1. README.md
2. AGENTS.md
3. docs/CONCEPT.md
4. docs/adr/

Ziel des ersten Umsetzungsschritts:
Erstelle die technische Grundlage des XeisWorks Content Studio als lokales, getestetes Monorepo.

Technische Zielrichtung:
- Frontend: Next.js + TypeScript
- Backend: FastAPI + Python
- Datenbank: PostgreSQL
- Queue/Cache: Redis
- lokale Umgebung: Docker Compose
- Tests und CI: GitHub Actions

Arbeite agentisch und repositoryweit, aber halte den Scope strikt auf Phase 0.
Implementiere noch keine echte Meta-, Wix- oder KI-Integration.

Mindestumfang:
- saubere Verzeichnisstruktur
- lauffähige Backend-Health-Route
- lauffähige Frontend-Startseite
- PostgreSQL- und Redis-Verbindung
- Konfigurationssystem mit .env.example
- Linting und Type Checking
- erste Unit Tests
- GitHub-Actions-Workflow
- README mit exakten lokalen Setup-Schritten
- AGENTS.md gemäß Konzept
- ADR-001 für die Stack-Entscheidung

Qualitätsregeln:
- keine Secrets committen
- robuste Fehlerbehandlung
- Type Hints
- kleine, verständliche Module
- keine unnötige Abstraktion
- Tests tatsächlich ausführen
- am Ende alle geänderten Dateien, Testresultate und offene Risiken nennen

Stoppe nach einem vollständigen, funktionierenden Phase-0-Fundament.
```

---

# 39. Quellen und technische Referenzen

Die Implementierung muss stets die jeweils aktuellen offiziellen Dokumentationen prüfen. Besonders relevant:

- Meta for Developers: Instagram Platform, Content Publishing, Permissions, App Review, Changelog
- OpenAI Platform Documentation und Help Center
- Google AI for Developers: Gemini API, Interactions API, Structured Outputs, Changelog
- Anthropic Claude Platform Documentation
- Wix Developers: APIs, Events and Webhooks, eCommerce Orders
- GitHub Docs: GitHub Apps, Webhooks, Security Best Practices
- Railway Documentation
- PostgreSQL und pgvector
- FastAPI
- Next.js
- OWASP ASVS und OWASP API Security Top 10

Wichtige, zum Konzeptzeitpunkt geprüfte Feststellungen:

- Die Meta Instagram API unterstützt die Veröffentlichung von Medien für professionelle Konten, abhängig von Kontotyp, Berechtigungen und App Review.
- Die Berechtigung `instagram_content_publish` ist für organische Veröffentlichungen relevant.
- Meta erweitert die Plattform laufend; das Changelog muss beobachtet werden.
- Wix-Webhooks können doppelt oder außerhalb der erwarteten Reihenfolge eintreffen.
- GitHub empfiehlt minimale Event-Abonnements, Webhook Secrets, HTTPS, schnelle Antworten und Delivery-ID-Prüfung.
- Gemini unterstützt strukturierte JSON-Ausgaben; für neue Agentenprojekte ist die jeweils aktuell empfohlene API zu prüfen.
- Claude unterstützt Prompt-Caching und Batch-Verarbeitung.
- Chat-Abos und API-Abrechnung sind bei OpenAI und Anthropic getrennte Produkte; bei Gemini ist die Entwicklerabrechnung ebenfalls separat zu planen.

---

# 40. Schlussbild

Das XeisWorks Content Studio soll nicht versuchen, aus dem Nichts dauerhaft „kreativ“ zu sein. Es soll die bereits vorhandene Substanz des Verlags sichtbar machen.

Der entscheidende Produktgedanke lautet:

> Nicht mehr Content erfinden, sondern vorhandene Arbeit erkennen, strukturieren und in veröffentlichbare Geschichten verwandeln.

Der erste reale Erfolg ist erreicht, wenn Bernhard an einem Sonntag die Anwendung öffnet und dort bereits zwei glaubwürdige, markengerechte und fachlich korrekte Vorschläge findet, die mit wenigen Klicks freigegeben werden können.

Alles Weitere – Newsletter, Blog, Händlerkommunikation, Produkttexte und Kampagnen – baut auf genau diesem Kern auf.
