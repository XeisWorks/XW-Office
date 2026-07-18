# FinanzOnline-UVA-Anschluss: Recherche, Legacy-Analyse und Umbau

Stand: 2026-06-17

## Ziel

Die neue PySide6-App soll die bereits berechnete IST-UVA als U30 an FinanzOnline
uebermitteln koennen. Die Berechnung bleibt die einzige IST-Monatsberechnung aus
XW-Studio; fuer FinanzOnline wird keine zweite Berechnung eingefuehrt.

## Offizielle Recherche

Relevante BMF-Grundlagen:

- FinanzOnline-Datenstrom erfordert XML-Dateien gemaess veroeffentlichten Strukturen.
- Fuer Webservice-Uebermittlung werden SOAP/WSDL-Services verwendet, keine REST-API.
- Session-Webservice:
  - `login(tid, benid, pin, herstellerid)` liefert eine Session-ID.
  - `logout(tid, benid, id)` beendet die Session.
- File-Upload-Webservice:
  - `upload(tid, benid, id, art, uebermittlung, data)`
  - fuer UVA ist `art=U30`
  - `uebermittlung=T` fuer Test, `P` fuer Produktion
  - `data` enthaelt das U30-XML
- Das U30-XSD erlaubt als Identifikationsbegriff fuer die UVA `FASTNR`; eine UID kann
  die FASTNR im U30-XML nicht ersetzen.

## Legacy-Analyse

Gepruefte Dateien:

- `C:\Users\bernh\GitHub\sevDesk\Finanzonline`
- `C:\Users\bernh\GitHub\sevDesk\finanzonline_uva.py`
- `C:\Users\bernh\GitHub\sevDesk\finanzonline_zm.py`
- `C:\Users\bernh\GitHub\sevDesk\FINANZONLINE.md`

Uebernommen:

- U30-XML-Struktur mit `ERKLAERUNGS_UEBERMITTLUNG`.
- `FASTNR` in `INFO_DATEN` und `ALLGEMEINE_DATEN`.
- Kennzahlen-Mapping `A/B/C` bzw. `KZ000`, `KZ011`, `KZ017`, `KZ021`,
  `KZ022`, `KZ029`, `KZ006`, `KZ057`, `KZ070`, `KZ072`, `KZ060`, `KZ065`,
  `KZ066`.
- Lokale XSD-Validierung gegen das offizielle U30-XSD.
- Session -> Upload -> Logout als technischer Ablauf.

Nicht uebernommen:

- Legacy-Databox-Download als Pflichtbestandteil des ersten Anschlusses.
- separate ZM-Uebermittlung; die ZM bleibt fachlich vorbereitet, aber nicht Teil dieses
  UVA-Schritts.
- monolithische Legacy-Receipt-/Dateiablage.

## Umsetzung in XW-Studio

Neue/erweiterte Anschlussstellen:

- `src/xw_studio/services/finanzonline/u30_xml.py`
  - baut U30-XML aus dem berechneten UVA-Payload
  - validiert gegen U30-XSD
- `src/xw_studio/services/finanzonline/uva_soap.py`
  - `FinanzOnlineFileUploadBackend`
  - Login, Upload, Logout
- `src/xw_studio/services/finanzonline/client.py`
  - liest Credentials aus SecretService/.env
  - aktiviert FileUpload-Backend bei vollstaendiger U30-Konfiguration
- `src/xw_studio/core/config.py`
  - Session-/Upload-WSDL
  - FASTNR
  - Hersteller-ID
  - U30-XSD-Pfad
- `src/xw_studio/ui/modules/taxes/view.py`
  - nutzt weiterhin `submit_month()`, damit exakt die berechneten Kennzahlen gesendet
    werden.

## Konfiguration

Erforderlich:

- `FON_TEILNEHMER_ID`
- `FON_BENUTZER_ID`
- `FON_PIN`
- `FINANZONLINE_UID`
- `FINANZONLINE_FASTNR`, `FINANZONLINE_STEUERNUMMER` oder `FON_STEUERNUMMER`

Hinweis:

`FINANZONLINE_UID` wird als Hersteller-ID/FON_HERSTELLER_ID verwendet. Fuer das U30-XML
ist sie nicht ausreichend, weil das XSD `FASTNR` verlangt.

## Umbauphasen

### Phase 1: Recherche und Legacy-Abgleich

- [x] BMF-Datenstrom-/Webservice-Unterlagen pruefen.
- [x] Legacy-U30-XML und Session/FileUpload-Ablauf pruefen.
- [x] Klaeren, dass U30 eine FASTNR benoetigt.

### Phase 2: XML-Schicht

- [x] U30-XML-Builder implementieren.
- [x] XSD-Validierung integrieren.
- [x] Tests gegen lokales Legacy-XSD.

### Phase 3: SOAP/FileUpload-Schicht

- [x] Session-Login implementieren.
- [x] U30-Upload implementieren.
- [x] Logout im `finally` absichern.
- [x] Testmodus `T` und Produktivmodus `P` aus Config steuern.

### Phase 4: PySide6-Service-Anbindung

- [x] `submit_month()` nutzt FileUpload-Backend.
- [x] UI zeigt Konfigurationsstatus.
- [x] Fehlende FASTNR stoppt vor Login/Upload.

### Phase 5: Tests

- [x] Unit-Tests fuer XML/XSD.
- [x] Unit-Tests fuer Login/Upload/Logout.
- [x] Unit-Tests fuer Config-/Secret-Aufloesung.
- [x] Live-Konfigurationscheck ohne Upload.
- [x] Live-Login/Logout gegen FinanzOnline ohne Upload.

## Testprotokoll 17.06.2026

Automatisierte Tests:

```text
.venv\Scripts\python.exe -m pytest tests/unit/test_uva_soap_mock.py tests/unit/test_uva_phase1_preview.py -q
27 passed

.venv\Scripts\python.exe -m pytest tests/unit/test_tax_services.py tests/ui/test_main_window_smoke.py tests/unit/test_uva_soap_mock.py tests/unit/test_uva_phase1_preview.py -q
30 passed

.venv\Scripts\python.exe -m ruff check src/xw_studio/services/finanzonline src/xw_studio/core/config.py tests/unit/test_uva_soap_mock.py tests/unit/test_uva_phase1_preview.py
All checks passed

.venv\Scripts\python.exe -m mypy src/xw_studio/services/finanzonline --ignore-missing-imports
Success: no issues found
```

Live-Konfigurationscheck vor FASTNR-Nachtrag:

- Backend-Modus aktuell: `mock/off`, weil die FASTNR fehlt
- Login-Credentials: vorhanden
- Hersteller-ID/UID: vorhanden
- FASTNR: fehlt
- U30-XML mit Test-FASTNR gegen XSD validiert: erfolgreich
- Upload: nicht ausgefuehrt

Live-FinanzOnline-Sessiontest:

- `login`: `rc=0`
- Session-ID erhalten: 24 Zeichen
- `logout`: `rc=0`
- Upload: nicht ausgefuehrt

Damit war der technische FinanzOnline-Zugang grundsaetzlich funktionsfaehig. Zu diesem
Zeitpunkt fehlte fuer eine echte U30-Testuebermittlung nur noch die 9-stellige FASTNR.

## Nachtrag 17.06.2026: `FON_STEUERNUMMER`

`FON_STEUERNUMMER` wurde als zusaetzlicher FASTNR-Alias integriert:

- `load_config()` liest `FON_STEUERNUMMER` in `finanzonline.fastnr`.
- `FinanzOnlineClient.fastnr()` liest den Alias aus SecretService und `.env`.
- Fehlermeldungen nennen den Alias explizit.
- Unit-Test prueft, dass `FON_STEUERNUMMER` das FileUpload-Backend aktiviert.

Live-Konfigurationscheck nach FASTNR-Nachtrag:

- Backend-Modus: `fileupload/test`
- Login-Credentials: vorhanden
- FinanzOnline-U30-Sendung: vollstaendig konfiguriert
- FASTNR: 9-stellig erkannt und maskiert ausgegeben

Live-U30-Testuebermittlung fuer Mai 2026:

- Berechnungsquelle: IST-Monatsberechnung aus sevDesk-Zahlungsdaten
- Upload-Modus: `uebermittlung=T`
- XML-XSD-Validierung: erfolgreich
- FinanzOnline-Rueckmeldung: `rc=0`
- FinanzOnline-Text: XML-File wurde gesendet, 1 Erklaerung wurde uebermittelt,
  nur fuer Testzwecke; die Daten gelten nicht als eingebracht.

## Betriebsregel

Solange `finanzonline.test_mode=true` bzw. `FON_SOAP_TEST_MODE` nicht explizit auf
false gesetzt wird, sendet XW-Studio mit `uebermittlung=T`. Fuer eine produktive
UVA-Sendung muss vorher die berechnete Monats-UVA fachlich geprueft und die FASTNR
konfiguriert sein.
