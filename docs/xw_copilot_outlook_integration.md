# XW-Copilot + Outlook Add-in Integrationsskizze (verbessert)

Basis:
- Uebernommen aus externem Plan: `copilot-ready_xw-office_plan_e4946c1d.plan.md`
- Diese Datei erweitert den Plan um konkrete Architekturentscheidungen fuer Outlook-Add-in Integration.

## Warum ein eigenes XW-Copilot Panel sinnvoll ist

Ja, das ist sinnvoll, weil:
- Add-in-Einstellungen zentral pro Firma/PC gepflegt werden koennen.
- Prompt-Bausteine und Standardtexte nicht im Code landen.
- Dry-Run und Live-Modus klar trennbar sind.
- Multi-PC Betrieb ueber DB-Settings konsistent bleibt.

## Bereits umgesetzt

- Neues Untermenue `XW-Copilot` in der Sidebar.
- Neues Modul mit drei Tabs:
  - Einstellungen (Outlook IDs, Webhook, Modus)
  - Bausteine (JSON basierte Prompt-/Mailbausteine)
  - Integration (Betriebshinweise)
- Persistenz ueber `SettingKvRepository`:
  - `xw_copilot.config`
  - `xw_copilot.templates`
- Dry-Run Contract fuer Add-in Requests:
  - Typed Request/Response Modelle (tenant, mailbox, action, payload_version)
  - Korrelation-ID Handling und strukturierte Fehlerantworten
  - Dry-Run Simulation fuer erste Actions (`crm.lookup_contact`, `invoice.read_status`, `inventory.start_preflight`)
- Dry-Run Tab im XW-Copilot Panel fuer manuelle Payload-Validierung und Vorschauantwort.

## Verbesserte Zielarchitektur

1. Add-in -> API Eingang
- Outlook Add-in sendet strukturierte Requests an einen API-Endpunkt.
- Pflichtfelder: tenant, mailbox, action, payload_version.
- Request signing (HMAC) als Mindestschutz fuer Webhook-Modus.

2. XW-Copilot Orchestrator in XW-Office
- Mapping: Action -> Service-Aufruf (Rechnungen, CRM, Produkte, etc).
- Modus-Schalter:
  - `dry_run`: nur Vorschau + Logging
  - `live`: schreibt in Zielsysteme

3. Audit & Nachvollziehbarkeit
- Jede Add-in Aktion erzeugt Audit-Log mit Correlation-ID.
- Fehlerantworten strukturiert (code/message/hint).

4. Prompt-Bausteine
- Typen: `mail`, `snippet`, `workflow`.
- Optionale Variablen: `{{kunde}}`, `{{rechnung}}`, `{{datum}}`.

## Empfohlene naechste Schritte

1. API-Vertrag definieren
- DONE: Basisschema als Pydantic-Contract in App integriert.
- Offen: formales JSON-Schema fuer externes Add-in-Paket exportieren.

2. Dry-Run Endpoint bauen
- DONE: Dry-Run Service validiert Request und liefert strukturierte Vorschauantwort.
- Offen: optionaler HTTP-Eingangspunkt fuer Add-in (lokal/remote).

3. Live-Aktionen schrittweise aktivieren
- Start mit risikoarmen Aktionen (z. B. CRM Lookup, Rechnung lesen).
- Danach schreibende Aktionen freischalten.

4. Security
- HMAC Signaturpruefung.
- Optional IP-Allowlist fuer Webhooks.
- Keine Secrets in Klartext im Repo.

## DoD fuer Outlook-Integration Phase 1

- Add-in Request kommt in XW-Office an und wird validiert.
- Dry-Run Antwort mit nachvollziehbarer Vorschau.
- Konfiguration komplett im XW-Copilot Panel pflegbar.
- Testabdeckung fuer Config/Bausteine + Request-Validation.
