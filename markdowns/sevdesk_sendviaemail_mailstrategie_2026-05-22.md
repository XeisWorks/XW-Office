# sevDesk sendViaEmail als primaerer Mailweg

Stand: 2026-05-22

## Entscheidung

XW-Office soll Rechnungsmails primaer ueber sevDesk `sendViaEmail` versenden. Microsoft Graph bleibt als Fallback und manueller Notanker erhalten.

Begruendung:

- sevDesk `sendViaEmail` ist der offizielle API-Endpunkt fuer den Rechnungsversand per Mail.
- sevDesk setzt beim Versand per Mail den Rechnungsstatus selbst weiter und haengt die Rechnung als PDF an.
- Die Mailkonfiguration liegt damit in sevDesk. Aenderungen an Microsoft 365/OAuth, SMTP und Absenderpflege muessen nicht doppelt in XW-Office gewartet werden.
- Das neue sevDesk-OAuth-2.0-Update fuer Microsoft 365 passt genau zu diesem Ziel: sevDesk ist mit dem Microsoft-365-Konto verbunden und uebernimmt den Versand.
- Legacy hat physische Rechnungsmails bereits ueber sevDesk `sendViaEmail` versendet; XW-Office rueckt damit naeher an den bewahrten Ablauf.

## Zielablauf

### Digital-only-Rechnungen

1. Keine lokale Rechnung drucken.
2. Kein Label drucken.
3. Keine Noten drucken.
4. Kein `sendBy VM` mehr.
5. Rechnung per sevDesk `sendViaEmail` versenden.
6. Wix-Fulfillment fuer digitale Bestellung bestaetigen.
7. Fulfillment-Status `mail_sent=True` setzen.

### Physische Rechnungen im Vollflow

1. Rechnung ueber sevDesk `sendBy VPR` finalisieren bzw. als gedruckten Versandtyp setzen.
2. Rechnungs-PDF holen/rendern.
3. Rechnung lokal drucken.
4. Versandlabel lokal drucken.
5. Noten/Produkt-PDFs ueber das neue interne Printmodul drucken.
6. Wix-Fulfillment setzen.
7. Kundenmail primaer ueber sevDesk `sendViaEmail` versenden.
8. Wenn sevDesk-Mail fehlschlaegt, Microsoft Graph als Fallback verwenden.
9. Fulfillment-Status `mail_sent=True` erst nach erfolgreichem sevDesk- oder Graph-Versand setzen.

### Nur-Rechnungen-Modus

1. Keine lokalen Druckschritte.
2. Rechnung per sevDesk `sendViaEmail` versenden.
3. Graph nur als Fallback verwenden.

## Phasen

### Phase 1: Dokumentation

Status: umgesetzt.

Diese Datei dokumentiert die neue Mailstrategie und die erwarteten Ablaufe.

### Phase 2: Mailpfad umstellen

Status: umgesetzt.

Umsetzung:

- `send_invoice_mail_for_invoice()` versucht zuerst sevDesk `sendViaEmail`.
- Graph wird nur noch verwendet, wenn sevDesk `sendViaEmail` nicht verfuegbar ist oder fehlschlaegt.
- Fehlermeldungen nennen beide Backends, wenn beide scheitern.

### Phase 3: START-Finalisierung anpassen

Status: umgesetzt.

Umsetzung:

- `sendBy VM` wird im START-Pfad nicht mehr verwendet.
- Bei physischen Vollflow-Rechnungen bleibt `sendBy VPR` erhalten.
- Bei digital-only und "Nur Rechnungen" uebernimmt `sendViaEmail` die Finalisierung/Mail.
- `mail_sent=True` wird nicht mehr durch `VM`, sondern durch den erfolgreichen Mailversand gesetzt.

### Phase 4: Tests und Validierung

Status: umgesetzt.

Abgedeckte Faelle:

- Physischer Vollflow: `sendBy VPR`, Rechnung/Labeldruck, sevDesk-Mail, kein Graph.
- Digital-only: kein `sendBy VM`, kein lokaler Druck, sevDesk-Mail.
- Nur-Rechnungen-Modus: sevDesk-Mail statt `sendBy VM`.
- Graph-Fallback: wird verwendet, wenn sevDesk-Mail fehlschlaegt.

Validierung:

```text
$env:PYTHONPATH='src'; .\.venv\Scripts\python.exe -m pytest tests/unit/test_printing_parity_e2e.py tests/unit/test_invoice_processing_service.py tests/unit/test_invoice_processing_fullflow.py
30 passed
```

Erweiterter Rechnungen-/START-Satz:

```text
$env:PYTHONPATH='src'; .\.venv\Scripts\python.exe -m pytest tests/unit/test_printing_parity_e2e.py tests/unit/test_invoice_client.py tests/unit/test_invoice_processing_fullflow.py tests/unit/test_inventory_start_workflow.py tests/unit/test_invoice_processing_service.py tests/unit/test_planned_pdf_printer.py
54 passed
```

Komplette Suite:

```text
$env:PYTHONPATH='src'; .\.venv\Scripts\python.exe -m pytest
232 passed, 12 skipped, 11 failed
```

Die verbleibenden 11 Fehler liegen in `tests/unit/test_daily_business_parity.py` und betreffen alte Parity-Erwartungen zu `AppConfig.products`, mutierbaren frozen Config-Dataclasses, veralteten Service-Konstruktoren, Refund-API-Erwartungen und Default-Druckerpfaden. Der durch die neue Mailstrategie betroffene Test `test_start_all_finalize_step` wurde auf `sendViaEmail` aktualisiert und ist gruen.

## Offener Praxischeck

Vor dem produktiven Versand sollte mit einer Testrechnung geprueft werden, ob sevDesk `sendViaEmail` bei API-Aufruf die in XW-Office uebergebenen Texte verwendet oder ob leere/fehlende Texte die sevDesk-Webvorlage ziehen. XW-Office uebergibt aktuell bewusst Betreff und Text, damit der API-Aufruf deterministisch bleibt.
