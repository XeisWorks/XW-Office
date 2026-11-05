# Refunds aus Wix nach sevDesk und XW-Office – Umbauskizze für GPT 5.6 Luna

Stand: 5. November 2026. **Planung und lesender Produktionsabgleich; keine produktive Änderung und kein sevDesk-Schreibzugriff.**

## Ziel und Entscheidungsvorschlag

Ein Refund wird ausschließlich im Wix-WebUI ausgelöst. `wix-sevdesk-api` erkennt den bestätigten Refund ereignisnah, erzeugt genau **einen passenden Gegenbeleg** in sevDesk, finalisiert eine Gutschrift auf Status **200 (offen)** und stellt den Vorgang XW-Office zur Anzeige bereit. Die Geldbewegung kann zunächst manuell zugeordnet werden. `RECHNUNGEN → START` darf dafür nicht erforderlich sein.

**Fachlich: Stornorechnung oder Gutschrift, niemals beide für denselben Refund.** Nach [sevDesk V2](https://hilfe.sevdesk.de/de/articles/15190963-gutschrift-erstellen) ist die Stornorechnung für eine vollständig aufzuhebende, noch unbezahlte offene/fällige Rechnung vorgesehen; eine bereits bezahlte oder teilweise bezahlte Rechnung erhält eine **Gutschrift wegen Minderleistung**. Auch eine Teilrückerstattung ist eine Gutschrift. `cancelInvoice` erzeugt und bucht die Stornorechnung; `createFromInvoice` erzeugt zunächst einen Gutschriftentwurf. Ein Entwurf der Ursprungsrechnung (100) ist ein eigener Konfliktfall. Bei sevDesk kann eine teilweise bezahlte Rechnung Status 750 haben; alte Teilzahlungen können noch Status 200 anzeigen. Deshalb zusätzlich `getIsPartiallyPaid` und gebuchte Zahlungstransaktionen prüfen. [sevDesk Storno](https://hilfe.sevdesk.de/de/articles/9154465-stornorechnung-erstellen), [Status 750](https://tech.sevdesk.com/api_news/posts/2024_04_08-new-invoice-status/).

**UI-Vorschlag:** Innerhalb von `RECHNUNGEN` ein eigenes Untermenü **Stornos & Gutschriften** für Gegenbelege und offene Prüfungen. Der normale Rechnungsbereich zeigt bei der Ursprungsrechnung einen Korrekturhinweis mit Link. Grund: sevDesk führt Gutschriften unter `CreditNote`, Stornorechnungen unter `Invoice`; beide brauchen andere Spalten/Aktionen als der START-Stapel. Der bestehende Tagesgeschäft-Tab „Refunds“ ist nur eine generische Queue und muss auf dieselben Live-Daten zeigen, sonst entstehen widersprüchliche Anzeigen.

## Ist-Zustand und konkrete Lücken

### `wix-sevdesk-api`

- `src/services/RefundWorker.js`: läuft nach Start erstmals nach 45 Sekunden, dann standardmäßig stündlich. Er ruft Wix-Transaktionen nur für lokale Orders mit bereits gespeichertem `wix_payment_status` `PARTIALLY_REFUNDED`/`FULLY_REFUNDED` ab. Er erstellt keine sevDesk-Belege.
- `src/services/Orders.js`: `published`-Orders werden durch spätere Order-Webhooks nicht erneut geweckt; ihre lokale Zahlungslage bleibt alt. Der Refund-Worker übersieht daher gerade Refunds nach abgeschlossener Rechnungsstellung.
- `src/services/ReconciliationWorker.js`: der Aktualisierungsfeed weckt nur wartende Orders, keine separate Refund-Queue. Er ergänzt die fehlende Erkennung für veröffentlichte Orders nicht.
- `src/routes/webhook.route.js` und `src/validations/webhook.js`: erwarten einen JSON-Order-Payload mit `data.id`, `orderNumber`, `context.metaSiteId`; ein nativer Wix-Refund-Webhook ist ein signiertes JWT in anderem Format. Der derzeitige Header-Secret-Modus ist kein Ersatz für die Wix-JWT-Prüfung. Bestehenden Order-Endpunkt nicht unbesehen umfunktionieren.
- `src/services/Refunds.js` und `refundEligibility.js`: die Tabelle `wix_refunds` existiert bereits, doch `SUCCEEDED` wird auf `manual_review` gesetzt und dieser Zustand beim erneuten Abgleich nicht weiterentwickelt. `amount` nimmt `requestedRefund` statt dem tatsächlich erfolgreichen Betrag. `is_partial` wird aus dem aggregierten Orderstatus abgeleitet; das ist je Refund unzuverlässig. Provider-, Buchungs- und Belegprüfdaten fehlen.
- `src/services/sevdesk.Invoice.js`: Rechnungen entstehen als Entwurf (100). Die Suche über `fulltextSearch` im aktuellen Rechnungs-Finder lieferte beim lesenden Live-Test für beide Oktober-Nummern dieselben neuesten 100 Rechnungen; der Filter `customerInternalNote` lieferte jeweils genau den passenden Beleg. Für Refunds primär die persistierte `sevdesk_invoice_id`, als Fallback nur exakte Referenzsuche mit eindeutiger Ergebnisprüfung verwenden.
- `src/routes/admin.route.js`: zeigt die vorhandenen Refunds, aber ohne Gegenbeleg-Verarbeitung.
- Die alte `markdowns/08-rueckerstattungen-umbauskizze.md` enthält eine Entscheidung vom Juli, sevDesk-Schreibvorgänge XW-Office zuzuordnen. Die **hier vorgeschlagene neue Zuständigkeit ersetzt diese Entscheidung erst nach Freigabe**.

### `XW-Office`

- `src/xw_office/ui/modules/rechnungen/view.py` und `refund_dialog.py`: Aktion „Rückerstattung starten“ führt derzeit `cancel_invoice` **vor** `refund_full_order` in Wix aus. Das kollidiert mit „Refund ausschließlich im Wix-WebUI“, setzt immer ein Storno voraus und kann bei bereits bezahlten Rechnungen scheitern. Nach Umstellung als schreibende Aktion entfernen/deaktivieren; stattdessen Wix und Gegenbeleg nur öffnen.
- `src/xw_office/services/sevdesk/refund_client.py`: enthält `cancelInvoice` und `createFromInvoice`, aber keine Status-/Betragsprüfung und keine Finalisierung der Gutschrift.
- `src/xw_office/services/invoice_processing/service.py`: START lädt nur Rechnungsentwürfe (100), finalisiert Rechnungen und bucht Zahlungen. Der Refund-Prozess muss davon unabhängig bleiben. Vor jeder Gegenbelegentscheidung sevDesk live lesen, denn START kann den Ursprungsbeleg parallel ändern.
- `src/xw_office/services/sevdesk/invoice_client.py`: Rechnungsübersicht liest `/Invoice`, nicht `/CreditNote`; Status 750 fehlt in der UI-Zuordnung. Ein neuer Gegenbeleg erscheint daher derzeit nicht zuverlässig als eigener Datensatz.
- `src/xw_office/services/clearing/`: Stripe-/Mollie-Refunds werden bereits als negative Providertransaktionen gelesen. `REFUND_IMPORT` importiert eine negative Transaktion, ordnet sie aber nicht automatisch der Gutschrift zu. Diese Logik darf bei späterer Automatisierung nicht doppelt buchen.

## Lesender Produktionsbefund: Oktober 2026

Abgleich am 5. November über Wix Order-Transactions und sevDesk-API. Keine neuen Belege erstellt. Die Wix-Order-Suche nach **Erstellungsdatum** fand nur 21666; die Suche nach **Aktualisierungsdatum** fand beide Fälle. Der Nachimport muss daher auch ältere Orders mit Oktober-Refund erfassen.

| Wix-Bestellung | Wix-Refund-ID | Refund | sevDesk-Ursprung | Ergebnis / Vorprüfung |
|---|---|---:|---|---|
| **21126** | `79ed17f3-c8be-4275-bf2c-6e80f3520047` | **174,30 €**, 7.10., `SUCCEEDED`, vollständig | `RE-262185`, ID `132819007`, Status **1000**, brutto **174,30 €** | **volle Gutschrift**, kein Storno. Mollie-Zahlung (`tr_…`), Refund-ID `re_…`; zwei erstattete Artikelpositionen mit zusammen sieben Stück ergeben 174,30 €, Versand 0 €. |
| **21666** | `4b0d75ee-68dc-4128-bb4f-f28203af2134` | **17,90 €**, 31.10., `SUCCEEDED`, teilweise | `RE-262624`, ID `137740945`, Status **1000**, brutto **39,70 €** | **Teilgutschrift über genau 17,90 €** für die erste CD-Position (20 % USt). Zweite CD und 3,90 € Versand bleiben bestehen. Stripe-Zahlung (`pi_…`); die Wix-Provider-Refund-ID ist hier numerisch und darf nicht als Stripe-ID interpretiert werden. |

Der lesende Abruf von `/CreditNote` ergab 27 Einträge, darunter **keine mit `refSrcInvoice` oder Referenz auf diese zwei Ursprungsrechnungen**. Direkt vor einem späteren Schreibzugriff erneut prüfen; unverbundene manuelle Belege sind damit nicht vollständig ausgeschlossen. Der Refund-Betrag allein belegt noch keine in sevDesk gebuchte Auszahlung.

## Sollfluss und Zuständigkeiten

```text
Wix-WebUI: Refund anlegen
  -> Wix-Zahlungsanbieter verarbeitet Refund
  -> signiertes Wix-Event details_updated/refund_completed
  -> API verifiziert und persistiert Event/Order-ID, quittiert zügig
  -> separater Refund-Worker lädt GET /ecom/v1/payments/orders/{orderId}
  -> je Wix-Refund-ID/erfolgreicher Teiltransaktion Zustand und Betrag speichern
  -> nach SUCCEEDED: sevDesk-Ursprungsrechnung, Zahlungslage und bestehende Gegenbelege lesen
  -> eindeutiger Vollstorno einer unbezahlten Rechnung: cancelInvoice
     ODER eindeutiger Refund zu bezahlter/teilbezahlter Rechnung: CreditNote/Factory/createFromInvoice
       -> Positionen auf Refundbetrag prüfen/anpassen -> PDF erzeugen -> sendBy -> Status 200 prüfen
  -> Beleg-IDs und Prüfprotokoll persistieren; XW-Office liest Live-API
  -> Geldbewegung separat manuell oder später idempotent über Provider + sevDesk buchen
```

Wix [Order Transactions Refund Completed](https://dev.wix.com/docs/api-reference/business-solutions/e-commerce/orders/order-transactions/order-transactions-refund-completed) feuert erst, wenn alle Refund-Teiltransaktionen final (`SUCCEEDED` oder `FAILED`) sind, und kann verzögert eintreffen. Für früheres Erkennen zusätzlich `details_updated` abonnieren. Nie allein auf den aggregierten Wix-Orderstatus vertrauen. Der autoritative Lese-Endpunkt ist [List Transactions For Single Order](https://dev.wix.com/docs/api-reference/business-solutions/e-commerce/order-transactions/list-transactions-for-single-order). Der Endpoint zeichnet Zahlungen/Refunds auf, bewegt aber selbst kein Geld. „Umgehend“ bedeutet: nach erfolgreicher Wix-Bestätigung ohne manuellen START, mit möglicher Webhook- und Provider-Latenz.

Native Wix-Webhooks werden als **JWT im Body** geliefert; Signatur mit Wix Public Key prüfen, dann `eventType`, Event-ID, `instanceId`/Site-Zuordnung und Order-ID validieren. Eine **eigene** Refund-Route verwenden; bestehende Order-Route unverändert lassen. Event-ID und Order-ID in dauerhafter DB-Queue speichern, erst danach HTTP 200; langsamere Wix/sevDesk-Aufrufe im Worker. [Wix Self-hosted Webhooks](https://dev.wix.com/docs/build-apps/develop-your-app/develop-a-self-managed-app/webhooks/handle-events-with-webhooks-for-self-hosting-without-the-java-script-sdk).

Fallback: periodische Wix-Suche nach `updatedDate` mit persistiertem Cursor/Wasserstand und Überlappung; auch `published`-Orders erfassen, aber **nur** in den Refund-Prozess einspeisen. Offene/PENDING-Refunds erneut abfragen. Refund-Event darf niemals den Invoice-Worker erneut starten oder eine zweite Ursprungsrechnung erzeugen. Backfill für Oktober mit Datumsfenster auf Refund-`createdDate`, Dry-Run und expliziter Allowlist der beiden Refund-IDs.

## Fachliche Entscheidungsmatrix

| Wix/Provider und sevDesk live | Aktion |
|---|---|
| `PENDING`, `STARTED`, `SCHEDULED` | Warten, erneut lesen; kein Gegenbeleg. Wix `SUCCEEDED` reicht für die Gegenbelegentscheidung; Provider-Daten sind für die spätere Auszahlungsbuchung gesondert zu prüfen. |
| `FAILED`/gemischt/Chargeback | Prüfung, kein automatischer Gegenbeleg. |
| `SUCCEEDED`, ursprüngliche Rechnung 100 (Entwurf) | **Sofort sichtbare Prüfaufgabe.** Keine stillschweigende Abhängigkeit von START; eigener, später freizugebender Pfad für Ursprungsrechnung/Zahlungsbuchung nötig. |
| `SUCCEEDED`, vollständig, offene/fällige und nachweislich unbezahlte Rechnung | `POST /Invoice/{id}/cancelInvoice`; erzeugte Stornorechnung und Ursprungsstatus prüfen. Kein zweiter Beleg. |
| `SUCCEEDED`, vollständig/teilweise, bezahlte oder teilweise bezahlte Rechnung | `POST /CreditNote/Factory/createFromInvoice`, Positionen und Steuern exakt abgleichen, mit `PUT /CreditNote/{id}/sendBy` auf 200 bringen. |
| Teilrefund zu unbezahlter Rechnung; Betrag/Position/Steuer nicht eindeutig; mehrere gestaffelte Refunds | Prüfaufgabe, keine spekulative Vollstornierung. |

**Status 200 ist der Gegenbelegstatus, keine Zahlungsbestätigung.** Bei Gutschriften setzt [sevDesk `sendBy`](https://api.sevdesk.de/) mit `sendType: "VPDF", sendDraft: false` den Entwurf in den offenen Zustand. Vorher PDF wirklich rendern/abrufen und die Zustellstrategie festlegen: `sendBy` protokolliert einen Versandweg; ohne tatsächliche Kundenzustellung darf die UI nicht „per Mail versandt“ behaupten. `sendViaEmail` nur nach separater Entscheidung. sevDesk verlangt Statuswechsel über diese Endpunkte, nicht über direktes Setzen von `status`. [sevDesk Statuswechsel](https://tech.sevdesk.com/api_news/posts/2024_04_04-changing-status-invoices-cretid-notes/).

Für 21666 darf `createFromInvoice` nicht ungeprüft finalisiert werden: es kopiert **alle** Positionen. Den Entwurf so bearbeiten, dass nur die erstattete CD mit ursprünglichem 20-%-Steuersatz und 17,90 € brutto verbleibt. Rundung mit Decimal in Cent und abschließende Prüfung von `sumGross`, Währung, Bezug zur Ursprungsrechnung und Steuern. Die konkrete sevDesk-Update-Payload für Positionsänderungen erst in einer isolierten API-Probe/Tests gegen die aktuelle sevDesk-Version bestätigen; bei Unsicherheit Entwurf stehen lassen und `manual_review` setzen. [sevDesk Gutschriften](https://hilfe.sevdesk.de/de/articles/15190963-gutschrift-erstellen), [sevDesk API](https://api.sevdesk.de/).

## Persistenz und Schutz gegen Doppelbelege

`wix_refunds` weiterverwenden, mit Migration `refunds_v2`: `site_id`, echte erfolgreiche Summe in Cent, Zahlungs-/Refund-Provider-ID, einzelne Transaktionen, Ursprungsbelegstatus, Gegenbeleg-ID/Nummer/Status, `provider_settlement_status`, Buchungsstatus, `locked_at`, `lease_owner`, `next_attempt_at`, `last_checked_at`, Audit-Zeitpunkte. Der lokale Refund-DB-Bestand konnte wegen der nur intern erreichbaren Railway-MySQL-Adresse nicht gelesen werden; vor Migration separat prüfen. Alte `manual_review`-Einträge nur mit expliziter Migrationsregel in neue Zustände überführen.

Eigene Tabelle für eingegangene Wix-Events (`event_id` unique), separate Refund-Jobs; `wix_refund_id` unique bleibt. Worker atomar claimen, Lease nach Crash zurücknehmen. Zustände z. B. `detected → awaiting_provider → ready → creating_draft → draft_verified → open_unpaid → payout_booked`; dazu `manual_review`, `failed_retryable`, `uncertain_write`. Vor jeder sevDesk-Schreibaktion Live-Belege und Bezug (`refSrcInvoice`, exakte Refund-Markierung, Betrag, Datum) erneut prüfen. sevDesk bietet hier keinen belegten serverseitigen Idempotency-Key: bei Timeout nach `createFromInvoice` oder `cancelInvoice` **nicht blind wiederholen**. Zuerst vorhandene Gegenbelege suchen; bei mehreren/unklaren Treffern stoppen und manuell klären. Schreib- und Lesezugriffe so begrenzen, dass mehrere API-Instanzen nicht parallel denselben Refund bearbeiten.

Die Refund-Markierung gehört in eine durchsuchbare Belegreferenz/Notiz, sofern die aktuelle sevDesk-API sie beim Erzeugen zuverlässig übernimmt; sonst `refSrcInvoice` plus lokaler Checkpoint und manueller Unsicherheitszustand. Ein bereits vorhandener manueller Gegenbeleg darf erkannt und zugeordnet, niemals automatisch dupliziert werden. Keine automatischen Löschungen/Stornos erzeugter Gegenbelege beim Rollback.

## XW-Office und Auszahlung

1. Neues Untermenü „Stornos & Gutschriften“ liest `wix_refunds`/Gegenbelegstatus aus einem **authentifizierten, paginierten Read-API** der Serveranwendung und verifiziert Belegdetails optional direkt bei sevDesk. Spalten: Wix-Order, Refund-Datum, Refundbetrag, Grund, Provider, Originalrechnung, Art/Nummer/Status des Gegenbelegs, Auszahlung/Buchung, Fehler/Prüfaufgabe. Link zur Originalrechnung, Gutschrift/Storno und Wix-Order. Zeige Status 200 als **offen/noch nicht ausgeglichen**.
2. Rechnungstabelle behält Ursprungsbeleg und ergänzt Korrekturkennzeichen/Link. START-Entwurfsauswahl bleibt auf normale `Invoice`-Entwürfe beschränkt; Gutschriftentwürfe erscheinen nur im neuen Menü. Bestehende „Rückerstattung starten“-Aktion nach Umstellung nicht mehr schreibend anbieten, damit Refunds wirklich nur in Wix ausgelöst werden.
3. Erstes Release: Gutschrift **offen (200)**, Auszahlungszuordnung manuell. Der vorhandene Clearing-Import kann negative Stripe-/Mollie-Refund-Transaktionen anzeigen/importieren; er verbindet sie noch nicht mit `/CreditNote/{id}/bookAmount`. Doppelimport über Provider-Refund-ID und sevDesk-Transaktions-ID verhindern.
4. Optionale spätere Buchung: Stripe-Refund oder Mollie-Refund **lesend** beim Anbieter anhand stabiler Provider-IDs verifizieren (Betrag, Währung, finaler Status, Zugehörigkeit zur Zahlung). Für Mollie ist `refunded` final; [GET payment refund](https://docs.mollie.com/reference/get-refund). Für Stripe `succeeded`/`refund.updated` beachten. Dann vorhandene negative `CheckAccountTransaction` auf dem richtigen Stripe-/Mollie-Konto finden oder einmal importieren, mit `PUT /CreditNote/{id}/bookAmount` eindeutig zuordnen. Kein „bezahlt“ allein aufgrund von Wix `SUCCEEDED`: Provider-Balance, sevDesk-Konto und Buchungsdatum müssen stimmen. [sevDesk API](https://api.sevdesk.de/), [Mollie-Status](https://docs.mollie.com/docs/refunds).

## Umsetzung in kleinen, prüfbaren Schritten

### P0 – Freigaben und Ist-Prüfung

- Fachentscheidung unten bestätigen; sevDesk-Version, Konten, Steuer-/OSS-Konstellation und Kundenzustellung prüfen. Beide Oktober-Fälle direkt vor Verarbeitung erneut lesend abgleichen.
- Produktions-Flags zunächst `REFUND_DOCUMENT_WRITE_ENABLED=false`, `REFUND_AUTO_BOOK_ENABLED=false`; alle neuen Schreibpfade zusätzlich serverseitig auf Allowlist/Dry-Run begrenzen.

### P1 – API: zuverlässige Erkennung und Read-API

- Native Wix-Refund-Webhooks als JWT verifizieren und durabel speichern; `details_updated` und `refund_completed` getrennt behandeln. Worker per Event sofort wecken; Abgleich mit Cursor/Überlappung ergänzen.
- Wix-Refunds pro ID/Transaktion mit **erfolgreichem** Betrag und Positionen normalisieren. Read-API mit Prozess- und Buchungsstatus; bestehendes Admin-Dashboard anpassen. Legacy-`manual_review` datenerhaltend migrieren.
- Tests: JWT gültig/ungültig, Event-Duplikat, `published`-Order, verpasster Webhook, Oktober-Backfill, Teilrefund, gemischter Status, kein Invoice-Worker-Kick.

### P2 – API: Gegenbelege, zunächst mit Flag aus

- Entscheidungslogik aus obiger Matrix; Live-Prüfung Originalbeleg und bestehender Gegenbelege; eindeutiges Claim/Checkpoint/Recovery implementieren.
- Vollgutschrift und Teilgutschrift korrekt erzeugen, Beträge/Steuersätze prüfen, PDF/`sendBy` und Status 200 verifizieren. Vollstorno nur unbezahlter Rechnung. Draft-Ursprungsfälle zunächst als aktive Prüfaufgabe.
- Tests mit Mock-sevDesk: Status 100/200/750/1000, alte Teilzahlung bei 200, Voll-/Teilbetrag, unterschiedliche Steuersätze, vorhandener Gegenbeleg, Timeout nach POST, parallele Worker, kein zweiter Beleg.

### P3 – XW-Office

- Untermenü und Ursprungsrechnungs-Verknüpfung implementieren; den schreibenden Desktop-Refund-Dialog deaktivieren/ersetzen. Reine Live-Anzeige muss auch ohne START funktionieren.
- UI-Test: beide Oktober-Fälle sichtbar, 21666 mit 17,90 € und 20 % USt, Gegenbelegstatus 200, keine Gutschrift im START-Stapel; Refresh ohne Doppelbeleg.

### P4 – vorsichtiger Produktiv-Rollout

- Erst P1 produktiv lesend; Backfill Oktober Dry-Run. Dann P2 mit Flag **nur** für explizit freigegebene Refund-IDs. Nach jedem Schreibschritt Beleg-ID, Betrag, Status und Ursprungsbezug lesen; Freigabe auf weitere Fälle erst nach Sichtprüfung.
- Metriken/Alarm: ältester `SUCCEEDED` ohne Beleg, Event-zu-Beleg-Latenz, `uncertain_write`, Betragsabweichung, doppelte Bezugstreffer. Bei Problem Flag aus; vorhandene Belege bleiben erhalten.
- Automatische Auszahlungsbuchung erst als **eigene** Freigabe nach P4 und Tests des gemeinsamen Clearing-Pfads.

## Offene Freigabeentscheidungen

1. **Zuständigkeit:** Darf die API künftig allein Gegenbelege in sevDesk schreiben und wird der Desktop-Refund-Button schreibend abgeschaltet? Dies ersetzt die Juli-Entscheidung.
2. **Entwurf (100):** Soll ein bereits erstatteter Auftrag mit noch nicht finalisierter Ursprungsrechnung zunächst manuell bearbeitet werden, oder soll ein eigener automatischer Pfad Rechnung und Zahlung vor der Gutschrift finalisieren? Empfehlung für den ersten Rollout: sichtbare manuelle Prüfung, kein START-Abwarten.
3. **Kundenzustellung:** Soll die Gutschrift mit Status 200 zunächst nur als PDF dokumentiert/markiert oder per sevDesk-Mail wirklich versendet werden? Empfehlung: PDF erzeugen, `sendBy VPDF`, Versand gesondert sichtbar machen.
4. **Oktober-Rückwirkung:** Sollen die beiden Oktober-Korrekturen mit tatsächlichem Ausstellungsdatum im November erstellt werden und wie sind Oktober-UVA/OSS zu behandeln? Kein automatisches Rückdatieren; steuerliche Zuordnung vor Live-Backfill mit Steuerberatung klären. [WKO zur Entgeltminderung](https://www.wko.at/steuern/berichtigung-rechnungen).
5. **Auszahlung:** Empfehlung: vorerst manuell buchen; später Providerbeleg und sevDesk-Transaktion automatisch zuordnen.

**Erst nach Bestätigung dieser konkreten Punkte produktive sevDesk-Belege erzeugen.** Die zwei Oktober-Fälle sind fachlich vorbereitet, aber noch nicht als Test übertragen. Auch `cancelInvoice`, `createFromInvoice`, `sendBy` und `bookAmount` sind produktive Schreibaktionen.

## Implementierungsstand 2026-11-05

- `wix-sevdesk-api`: Refunds werden weiterhin ausschließlich aus Wix gelesen; der Worker verarbeitet `SUCCEEDED`-Refunds ohne den Rechnungs-`START`. Unbezahlte Vollrefunds erzeugen ein sevDesk-Storno, bezahlte/teilbezahlte Fälle eine Gutschrift. Teilgutschriften werden nur bei einem centgenauen Positions-Match finalisiert; unklare Fälle bleiben `manual_review`.
- Der Schreibpfad ist mit `REFUND_DOCUMENT_WRITE_ENABLED=false` standardmäßig aus und muss für einen kontrollierten Produktiv-Rollout explizit aktiviert werden. Der Read-API-Endpunkt `/api/v1/refunds` ist für XW-Office authentifiziert vorgesehen.
- XW-Office besitzt ein eigenes Untermenü `Stornos & Gutschriften` mit Statusanzeige, Gutschrift-PDF und bestätigungspflichtigem Kundenversand. Der Versand verwendet denselben `MailDeliveryService`/Microsoft-Graph-Pfad, die bestehende Template-/Signaturquelle und die vorhandenen `MS_GRAPH_*`-/MSAL-Cache-Einstellungen wie der Rechnungsversand.
- Die beiden Oktober-Fälle wurden nicht automatisch in sevDesk geschrieben. Vor dem Rollout sind sie per Dry-Run nochmals lesend zu prüfen; insbesondere Fall 21666 muss auf die erstattete 17,90-EUR-CD-Position mit 20 % USt begrenzt werden.

## Nachtrag: produktiver Oktober-Abgleich am 05.11.2026

Die beiden ausdrücklich freigegebenen Fälle wurden anschließend kontrolliert in sevDesk angelegt, geprüft und mit den bereits importierten Provider-Refund-Transaktionen verknüpft:

- Bestellung **21126**, Wix-Refund `79ed17f3-c8be-4275-bf2c-6e80f3520047`, Mollie `re_DKTDzTiYz3zEQ8ciGqpXJ`: Gutschrift **GU-2603**, sevDesk-ID `3080738`, **174,30 EUR**, Ursprungsrechnung `RE-262185`/`132819007`, Status **1000 (bezahlt)**.
- Bestellung **21666**, Wix-Refund `4b0d75ee-68dc-4128-bb4f-f28203af2134`, Stripe `re_3UVXOYFVOhfzx9BP2Gfy3ZR8`: Teilgutschrift **GU-2604**, sevDesk-ID `3080740`, **17,90 EUR**, nur die erstattete CD-Position mit **20 % USt**, Ursprungsrechnung `RE-262624`/`137740945`, Status **1000 (bezahlt)**.

Für beide Buchungen musste der signed Refund-Betrag (negative CheckAccountTransaction) an `CreditNote/{id}/bookAmount` übergeben werden. Der positive Betrag verknüpft die Transaktion zwar, lässt sevDesk aber in **750 (teilbezahlt)** stehen. Nach `resetToOpen` und erneuter Buchung mit negativem Betrag meldet sevDesk `fromStatus: 200`, `toStatus: 1000` und den korrekten Buchungsbetrag. Die Provider-IDs, Beträge, Währung, Konten und Wertstellungsdaten wurden vor der Buchung unabhängig verifiziert.

Der alte Satz „nicht automatisch geschrieben“ beschreibt damit nur den Stand vor diesem Nachtrag. Der kontrollierte Backfill ist abgeschlossen; weitere automatische Auszahlungsbuchungen bleiben bis zu einer separaten Freigabe auf eindeutige Provider-/sevDesk-Transaktionsmatches begrenzt.
