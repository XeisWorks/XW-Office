# Anbieter- und Toolabdeckung

Stand: 14.11.2026. Diese Matrix erfasst Katalogeinträge und technische Reife. Sie belegt weder, dass der Benutzer alle genannten Konten besitzt, noch, dass ein Anbieter Dokumente für das aktuelle Abrechnungsfenster ausgestellt hat. „Verbindung unbekannt“ bedeutet: Keine nutzbare Konto-/Mailbox-Verbindung wurde aus Repository-Konfiguration oder Tests belegt.

## Vom Benutzer ausdrücklich genannte Abos

| Anbieter | Katalog / Konto | Offiziell dokumentierter Weg | Status im Collector | Nächster Nachweis |
| --- | --- | --- | --- | --- |
| BrowserStack | Katalogeintrag vorhanden; Kontoinhaber und Mailbox unbekannt | Anbieter sagt: Rechnung nach erfolgreicher Zahlung per E-Mail; zusätzlich Download unter Billing & Invoices (nur Account Owner). | Mail und Browser `planned`; kein Connector live verifiziert. | Mailroute mit geprüftem Absender und echter PDF; alternativ sichtbarer Owner-Login, Download und idempotenter Wiederholung. |
| Figma | Neu in Registry; Plan/Mandant unbekannt | Admin Billing enthält Invoice History; Figma beschreibt PDF-Download der Einzelrechnung. | Mailroute `planned`; keine Figma-spezifische Portalautomation. | Plan/Adminrechte feststellen; echte Rechnungs-PDF und Datum prüfen, Mail zuerst bevorzugen. |
| Slack | Neu in Registry; Workspace/Owner unbekannt | Billing History zeigt und lädt Billing Statements; jährliche berechtigte Workspaces können auf Rechnung umstellen. | Mailroute `planned`; Dokumentart noch zu prüfen. | Workspace und Owner bestimmen; klären, ob Beleg Rechnung, Kartenabrechnung oder Statement ist. |
| CodeScene | Neu in Registry; Produkt/Plan unbekannt | CodeScene dokumentiert Billing-Kontoseite; beim CodeHealth MCP wird Stripe Customer Portal mit E-Mail-Link für Invoice History verwendet. | Keine automatisierte Route; manueller Import. | Produktvariante und echter Belegtyp feststellen. Magic-Link nicht automatisieren; echten Download manuell importieren. |

## Bestehende Kataloganbieter

Alle unten genannten Konten bleiben bis zur lokalen Einrichtung und Liveprüfung „unbekannt“. Für jede aufgelistete Route ist die Registry-Maturity weiterhin `planned`; leere oder nicht implementierte Mailregeln dürfen nicht als abruffähig erscheinen.

| Anbieter-ID | Anbieter | Katalogrouten | Status |
| --- | --- | --- | --- |
| `mollie_fees` | Mollie Gebühren | Graph-Mail, Mollie API | `planned`; Advanced Access Token oder OAuth mit `invoices.read`; kein Sandbox-Testmodus für Invoices API |
| `google_cloud` | Google Cloud | Graph-Mail | `planned`; Konto/Billing-Export prüfen |
| `anthropic_api` | Anthropic API | Graph-Mail, Browser | `planned` |
| `anthropic_subscription` | Claude / Claude Code | Graph-Mail, Browser | `planned` |
| `stripe_fees` | Stripe eigene Gebühren | Browser | `planned` |
| `railway` | Railway | Browser | `planned` |
| `github` | GitHub | Graph-Mail, Browser | `planned` |
| `perplexity` | Perplexity | Graph-Mail, Browser | `planned` |
| `openai_chatgpt` | ChatGPT Abo | Graph-Mail, Browser | `planned` |
| `openai_api` | OpenAI Platform | Graph-Mail, Browser | `planned` |
| `google_ai_subscription` | Google AI / Gemini / Google One | Graph-Mail | `planned`; Google Login nicht automatisieren |
| `adsense_youtube` | AdSense / YouTube | keine | Einnahmen-/Auszahlungsnachweise; nicht als Ausgabe behandeln |
| `microsoft365` | Microsoft 365 | Graph-Mail, Browser | `planned`; Produkt- und Abrechnungsart prüfen |
| `amazon_business` | Amazon Business | API, Browser | `planned`; bestehendes Invoice-Fetcher-Verhalten bis Parität erhalten |

## Tools und Abonnements als Testmittel

Figma ist fuer diesen Backend-/PySide6-Task ohne Designreferenz kein notwendiges Implementierungswerkzeug. BrowserStack eignet sich nicht fuer die native PySide-Oberflaeche und wurde nicht eingebunden. Die aktuelle oeffentliche Slack-Suche und GitHub-MCP-Issue-/PR-Suche scheiterten am Start-Handshake des `codex_apps`-Servers; die lokale `gh`-Issue-/PR-Suche fuer `invoice collector` ergab keine passenden Treffer. Eine private Slack-Suche wurde nicht ausgefuehrt; keine Slack-Nachricht wurde gesendet. Fuer CodeScene ist in der verfuegbaren Toolliste keine Integration vorhanden. CodeScene und BrowserStack koennen bei einer spaeteren passenden Web-/Portal-Teststrecke erneut geprueft werden. Railway-MCP ist verfuegbar; der Collector bleibt eine lokale PySide6-App mit DPAPI-geschuetztem OAuth-Cache, lokalem Browserprofil und OneDrive-Syncordner. Ein Railway-Deployment ist nicht Teil des spezifizierten Desktop-Releases und ersetzt keine Live-Routenverifikation.

## Verifikationsregeln

- Mail: konkrete Absenderdomain, Mailbox/Alias und PDF-Anhang am echten Konto belegen. Leere Sender-Allowlist muss ablehnen. Eingangszeit ist Provenienz und kein Rechnungsdatum. Der Collector parst derzeit genau ein explizit beschriftetes Datum aus den ersten drei PDF-Textseiten; fehlendes/mehrdeutiges Datum landet unter `_needs_review`, bekannte Daten außerhalb des gewählten Zeitraums werden übersprungen. Vor `verified` muss diese Erkennung mit echten Anbieterbelegen geprüft werden.
- API: dokumentierter Read-Scope, zugelassener Host, echte PDF-Antwort, Account-/Dokumenttyp und wiederholbarer Lauf.
- Browser: Anbieterbedingungen und erlaubte sichtbare Anmeldung prüfen; echter Download ohne CAPTCHA-/MFA-/Bot-Umgehung.
- Pro Route: echtes Dokument, korrekte Mandantenzuordnung, Datumstyp, idempotenter Wiederholungslauf, Auth-Fehlerverhalten und redigierte Logs belegen, bevor `verified` gesetzt wird.
- Pro gespeichertem PDF aus dem Syncordner nur `SYNC_PENDING` anzeigen, bis ein echter Remote-Nachweis vorliegt.

## Quellen

- [BrowserStack: Invoices for payments](https://www.browserstack.com/support/faq/plans-pricing/billing/can-i-get-invoices-for-my-payments)
- [Figma: Manage payment and invoice details](https://help.figma.com/hc/en-us/articles/360040532093-Manage-payment-and-invoice-details)
- [Slack: Manage plan and billing details](https://slack.com/help/articles/218915087-Manage-your-Slack-plan-and-billing-details)
- [CodeScene: Manage or cancel MCP subscription](https://helpcenter.codescene.com/help/articles/8654612-how-to-manage-or-cancel-your-mcp-subscription)
- [CodeScene: Update billing and payment information](https://helpcenter.codescene.com/help/articles/8583447-how-to-update-your-billing-and-payment-information)
