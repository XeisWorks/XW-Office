# Inventory-Worker

Der Worker aktualisiert den Drei-Monats-Alarmbestand und verarbeitet externe sevDesk-Rechnungen/Gutschriften idempotent. Er benötigt dieselben Laufzeitvariablen wie der Webdienst (`DATABASE_URL`, `SEVDESK_API_TOKEN` und die vorhandene sevDesk-Konfiguration).

Für Railway wird ein eigener Worker-Service mit demselben Repository und Image angelegt:

```text
PYTHONPATH=/app/src python -m xw_office.services.product_hub.inventory_worker_cli --interval-seconds 86400
```

Der Rechnungsfeed überlappt standardmäßig 30 Tage, damit Neustarts und verspätete sevDesk-Freigaben keine Position auslassen; Ledger- und Legacy-Mirror-Schlüssel sind idempotent. Ein Fehler in einem Zyklus beendet den Dienst nicht, sondern wird geloggt und beim nächsten Intervall erneut versucht. Für eine einmalige manuelle Prüfung:

```text
PYTHONPATH=src python -m xw_office.services.product_hub.inventory_worker_cli --once
```

Der Worker aktiviert niemals `inventory_master_enabled`; der bestehende Cutover-Gate bleibt maßgeblich.
