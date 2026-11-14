# Doppler fuer XW-Office auf Windows-PCs

XW-Office und das Druckcenter laden ihre Desktop-Umgebung beim Start aus dem
Doppler-Projekt `xw-office-desktop`, Config `prd`. Das Startmenue und die
Konsolen-Startskripte verwenden `doppler run --no-fallback`. In der Repository-Kopie ist
keine `.env` erforderlich.

## Einmalig je PC

1. Doppler CLI installieren: `winget install --id Doppler.doppler --exact --source winget`.
2. Ein neues Terminal oeffnen und `doppler login` ausfuehren. Die Anmeldung
   erfolgt im Browser. Zugang auf `xw-office-desktop/prd` muss freigeschaltet sein.
3. Die virtuelle Python-Umgebung und Startmenue-Verknuepfungen wie im
   [Multi-PC-Leitfaden](multi_pc_betriebsleitfaden.md) einrichten.
4. `doppler run --no-fallback --project xw-office-desktop --config prd --
   .\.venv\Scripts\python.exe scripts\verify_doppler_import.py`
   prueft nur das Vorhandensein der Startwerte und gibt sie nicht aus.

Die normale Startmenue-Verknuepfung startet `scripts/xw_doppler_bootstrap.pyw`
ohne Konsolenfenster. Der Debug-Start nutzt `run_xw_office_debug.cmd` und zeigt
Doppler-Fehler im Terminal. Fuer direkte Python-Aufrufe muss der Befehl ebenfalls
mit `doppler run --no-fallback --project xw-office-desktop --config prd --` beginnen.
Bei Doppler-Starts liest `load_config()` keine lokale `.env`.

## Geheimnisse verwalten

- Eine lokale `.env` nicht automatisch nach Doppler hochladen. Die zentralen
  Desktop-Werte sind die verbindliche Quelle; abweichende lokale Werte zuerst pruefen.
- Gemeinsame Desktop-Startwerte wie `DATABASE_PUBLIC_URL` und
  `FERNET_MASTER_KEY` in Doppler pflegen. Der Fernet-Schluessel muss zur
  bestehenden verschluesselten Datenbank passen; ein Austausch ohne
  Umschluesselung macht die gespeicherten Tokens unlesbar.
- API-Tokens, die in XW-Office-Einstellungen gespeichert wurden, liegen
  verschluesselt in PostgreSQL. `SecretService` liest diese **vor** Doppler-
  Umgebungswerten. Diese Tokens deshalb bis zu einer expliziten Migration in
  den Einstellungen rotieren. Doppler-Werte gelten nur, wenn kein DB-Wert
  vorhanden ist. Nach einer Aenderung neu starten, damit Prozesswerte und
  der Secret-Cache aktualisiert werden.
- Railway-Dienstvariablen bleiben dienstbezogen in Railway. GitHub Actions
  benoetigt aktuell keine Produktions-Secrets. Eine spaetere Doppler-Railway-
  Synchronisierung braucht eine eigene Config mit nur den jeweiligen
  Dienst-Secrets.

Die Desktop-Starts verwenden `--no-fallback`: Sie lesen die aktuelle Doppler-
Konfiguration bei jedem Start und schlagen bei fehlendem API-Zugriff fehl.
Die Doppler-Anmeldung pro PC ist weiterhin erforderlich.
