# ZM/U13-Integration nach UVA

Stand: 2026-06-17

## Ziel

Die Zusammenfassende Meldung soll direkt nach erfolgreicher U30-UVA im selben
PySide6-Ablauf an FinanzOnline uebermittelt werden. Die Berechnung ist bewusst
eine Soll-Berechnung auf Basis des sevDesk-Rechnungsdatums.

## Offizielle Grundlage

- BMF-Datenstromuebermittlung verlangt XML-Dateien gemaess veroeffentlichter
  Struktur.
- Der FinanzOnline FileUpload-Webservice nutzt `upload(tid, benid, id, art,
  uebermittlung, data)`.
- Fuer die Zusammenfassende Meldung ist das Anbringen `U13`.
- Die ZM verwendet `FASTNR` als Identifikationsbegriff.
- Seit Uebermittlungsstichtag 06.03.2025 werden `SOLEI` und `DREIECK` mit `J`
  uebermittelt.
- Eine ZM muss mindestens eine Meldezeile enthalten; ohne ZM-Zeilen wird daher
  nichts hochgeladen.

Quellen:

- BMF: Informationen fuer die Datenstromuebermittlung
- BMF: Sonstige Erklaerungen und Antraege > Zusammenfassende Meldung
- BMF: File-Upload-Webservice, Stand 04.03.2026
- BMF: Dokumentenversion Zusammenfassende Meldung, gueltig ab 06.03.2025

## Legacy-Abgleich

Gepruefte Legacy-Datei:

- `C:\Users\bernh\GitHub\sevDesk\Zusammenfassende Meldung.py`

Uebernommen:

- Monatliche Auswahl ueber `invoiceDate` statt Zahlungsdatum.
- Nur finalisierte Rechnungen (`status >= 100`).
- EU-/innergemeinschaftliche Klassifikation ueber `taxType=eu` oder
  `taxRule=3`.
- UID-Normalisierung.
- UID-Pruefung mit `python-stdnum`.
- Netto-Basis `sumNet`, Fallback `sumNetAccounting`.
- Kaufmaennische Rundung auf ganze Euro.
- Gruppierung und Summierung je UID.

Verbessert:

- U13-XML-Builder mit XSD-Validierung.
- `SOLEI=J` fuer sonstige Leistungen/Reverse-Charge-Faelle.
- `DREIECK=J` vorbereitet, wenn der Steuertext Dreiecksgeschaeft markiert.
- Blockierende UID-Fehler stoppen nur die ZM, nicht die bereits erfolgreiche U30.
- Der bestehende Button sendet jetzt `UVA + ZM`; die ZM wird nur nach
  erfolgreicher U30 gestartet.

## Umsetzung

- `src/xw_office/services/finanzonline/zm_service.py`
  - berechnet ZM-Zeilen aus sevDesk-Rechnungen nach Soll-Prinzip
- `src/xw_office/services/finanzonline/u13_xml.py`
  - baut und validiert U13-XML
- `src/xw_office/services/finanzonline/uva_soap.py`
  - FileUpload-Backend sendet `U30` und `U13`
- `src/xw_office/services/finanzonline/uva_service.py`
  - orchestriert U30 zuerst, dann ZM
- `src/xw_office/ui/modules/taxes/view.py`
  - Button und Rueckmeldung zeigen `UVA + ZM`

## Betriebsregel

Solange `finanzonline.test_mode=true` bzw. `FON_SOAP_TEST_MODE` nicht explizit auf
false gesetzt wird, werden U30 und U13 mit `uebermittlung=T` gesendet. Das ist ein
FinanzOnline-Testupload und gilt nicht als eingebracht.

## Testprotokoll 17.06.2026

Automatisierte Tests:

```text
.venv\Scripts\python.exe -m pytest tests/unit/test_uva_soap_mock.py tests/unit/test_zm_service.py -q
18 passed

.venv\Scripts\python.exe -m pytest tests/unit/test_tax_services.py tests/ui/test_main_window_smoke.py tests/unit/test_uva_soap_mock.py tests/unit/test_uva_phase1_preview.py tests/unit/test_zm_service.py -q
34 passed

.venv\Scripts\python.exe -m ruff check src/xw_office/services/finanzonline src/xw_office/core/config.py src/xw_office/bootstrap.py src/xw_office/ui/modules/taxes/view.py tests/unit/test_uva_soap_mock.py tests/unit/test_zm_service.py
All checks passed

.venv\Scripts\python.exe -m mypy src/xw_office/services/finanzonline --ignore-missing-imports
Success: no issues found
```

Live-Lesetest Mai 2026:

- gelesene Rechnungen: 127
- ZM-relevante Rechnungen: 10
- ZM-Zeilen: 4
- Summe gerundet: 2.733 EUR
- blockierende UID-Fehler: 0

Live-FinanzOnline-Testupload Mai 2026:

- Modus: `fileupload/test`
- U30: `rc=0`, XML validiert, Testupload nicht eingebracht
- U13/ZM: `rc=0`, XML validiert, 4 ZM-Zeilen, Testupload nicht eingebracht
