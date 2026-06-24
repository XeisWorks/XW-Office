# Post Label Center Webservice: Bauplan

Stand: 2026-06-24

## Entscheidung

XW-Studio soll die **Post-Labelcenter-Webservice-Schnittstelle** als neuen Standardweg fuer PLC-Labels integrieren. Der bisherige Dateiimport bleibt waehrend der Einfuehrung als expliziter Fallback erhalten und wird erst nach einem belastbaren Parallelbetrieb deaktiviert.

Der Webservice ist fuer XW-Studio sinnvoll, weil `ImportShipment` das erzeugte Label als `pdfData` direkt in der synchronen Antwort liefert. Das beseitigt die Wartezeit durch Ondot Data Exchange, das den Importordner zyklisch abarbeitet. Die verbleibende Zeit besteht nur aus Webservice-Antwort und lokalem Druckauftrag, typischerweise Sekunden statt bis zu fuenf Minuten.

Die aktuelle Klickflaeche in der Aktionsspalte bleibt unveraendert. Das linke Post-Icon oeffnet weiterhin den PLC-Dialog. Innerhalb dieses Dialogs wird der Senden-Schritt von Dateiimport auf Webservice umgestellt.

## Abgleich mit lokaler PLC-API-Spezifikation

Am 2026-06-24 wurden die lokalen Dateien unter `resources/api_specs/plc` gegen den Bauplan abgeglichen:

- `PLC_API_Beschreibung.xlsx`, Version **2.0 vom 26.02.2025**, ist die fachliche Referenz. Sie bestaetigt `ImportShipment` mit `ShipmentRow`, `pdfData`, `zplLabelData`, `shipmentDocuments`, `errorCode` und `errorMessage`.
- `request.txt` zeigt den produktiven Datenvertrag mit `ClientID`, `OrgUnitID`, `OrgUnitGuid`, `DeliveryServiceThirdPartyID`, Empfaenger/Absender, `ColloList` und `PrinterObject`.
- Gültige Druckwerte sind `LanguageID=PDF`, `LabelFormatID=100x200` und unter anderem `PaperLayoutID=100x200` oder `2xA5inA4`. XW-Studio verwendet fuer den Direktdruck ein einzelnes `100x200`-PDF; der Drucker ist separat konfigurierbar.
- `PLC-Test-Label.pdf` ist A5. Das bestaetigt, dass das von PLC gelieferte PDF unmittelbar an die lokale Druckwarteschlange gehen kann.
- Die Spezifikation nennt fuer Nicht-EU seit 2019 zwingend: Telefon oder E-Mail von Absender **und** Empfaenger sowie pro Artikel Inhalt, Ursprung, Waehrung, Warenwert, Zolltarifnummer, Nettogewicht und Menge. `DeclarationOfOrigin` ist am Artikelobjekt ein Pflichtfeld.
- Die Fehlercodes differenzieren fachliche Ablehnung und technischen Transportfehler. Insbesondere darf ein Timeout nicht wie eine sichere Ablehnung behandelt werden.

Folgerungen fuer den Bauplan: Die direkte PDF-Rueckgabe ist eindeutig der richtige Standard. Die Nicht-EU-Validierung wurde gegenueber dem ersten Bauplan verschaerft; der Dialog erfasst deshalb Empfaenger-Telefon und -E-Mail editierbar. Eine Antwort mit `errorCode`/`errorMessage` erzeugt keinen Druckauftrag.

## Umsetzungsstand

Die Phasen 1 bis 3 sind im Arbeitsstand umgesetzt:

- Kanonisches Modell `PlcShipmentDraft` fuer Adresse, Paket, Zollartikel und Referenz; die Datei- und SOAP-Adapter verwenden dieselbe Validierung.
- Zentrale ISO-2-Normalisierung: etwa `AUSTRIA` wird zu `AT`; ein ausgeschriebener Landesname kann nicht mehr in `CountryID` gelangen.
- Direkter `ImportShipment`-Client mit Zeep, produktivem/Test-WSDL, strikter PDF-Validierung, Trackingcode-Extraktion und redigierten strukturierten Logs.
- Die Standardauswahl im bestehenden PLC-Dialog ist **Webservice (direkt)**. `Dateiimport (Ondot-Fallback)` bleibt bewusst sichtbar und muss aktiv ausgewaehlt werden.
- Das SOAP-PDF wird ohne Ordner-Polling in die bestehende lokale Druckwarteschlange eingereiht. Der PLC-Drucker ist separat konfigurierbar und faellt ohne Ueberschreibung auf das bestehende Label-Druckprofil zurueck.
- Persistente Idempotenz/Audit-Tabelle `plc_shipment` inklusive Alembic-Migration `004_plc_shipment_audit`: gleiche erfolgreiche Requests werden blockiert; ein Transporttimeout wird als `unknown` gesperrt, nicht automatisch erneut gesendet.
- Neue PLC-Einstellungen speichern Organisationskennung und Absenderdaten verschluesselt ueber `SecretService`.

Offen bleiben ausschliesslich die zugangs- und vertragsabhaengigen Abnahmeschritte: reale PLC-Kennungen eintragen, TEST-Label senden, Druckformat am realen Labeldrucker bestaetigen und danach kontrolliert in LIVE testen.

## Rechercheergebnis

### Offizielle PLC-Schnittstelle

- Die Post beschreibt das Post-Labelcenter als Versandsoftware mit Datenuebernahme aus Warenwirtschaftssystemen und mehreren Anbindungsvarianten. Eine Freischaltung/Vereinbarung mit der Post ist erforderlich. [Post-Labelcenter fuer Geschaeftskund*innen](https://www.post.at/g/c/paket-versandsoftware-geschaeftlich)
- Der produktive SOAP-WSDL-Endpunkt ist `https://plc.post.at/Post.Webservice/ShippingService.svc?wsdl`; der im WSDL angegebene sichere SOAP-Endpunkt ist `https://plc.post.at/Post.Webservice/ShippingService.svc/secure`.
- Die Testumgebung ist `https://abn-plc.post.at/DataService/Post.Webservice/ShippingService.svc?wsdl` bzw. der sichere Pfad `/secure`.
- Der WSDL bietet unter anderem `ImportShipment`, `ImportShipmentAndGenerateBarcode`, `CancelShipments`, `GetAllowedServicesForCountry` und `PerformEndOfDay`.
- `ImportShipment` antwortet mit Sendungsdaten sowie `pdfData`, `zplLabelData`, `shipmentDocuments`, `errorCode` und `errorMessage`. Fuer XW-Studio ist `pdfData` der direkte Weg zum Drucker.
- Die Zugangskennung fuer den Versand besteht aus `ClientID`, `OrgUnitID` (in Fremdsystemen auch UnitID genannt) und `OrgUnitGuid`. Sie ist im PLC unter **Geraetekonfiguration -> Organisation -> API** abrufbar. [Einrichtungsreferenz](https://docs.reybex.com/kb/anbindung-post-oesterreich/)
- Der WSDL verlangt HTTPS, aber kein Client-Zertifikat. Die Mandantenkennung liegt im `ShipmentRow`-Payload, nicht in XW-Studio-Quellcode oder Logausgaben.

### Legacy-Polling: verifizierter Ist-Zustand

Der Legacy-Dialog erstellt keine direkte Netzwerkanfrage an die Post. Er:

1. ermittelt Rechnung, Wix-Analyse, Lieferadresse, Gewicht, Zollartikel und PLC-Produkt;
2. erzeugt eine `PostDefaultPort`-CSV mit `S`-, `C`-, optional `A`- und `D`-Saetzen;
3. schreibt sie atomar zuerst als `.tmp` und verschiebt sie dann nach `C:\ondot\ShipmentImport` bzw. `C:\ondot\ShipmentImport_TEST`;
4. meldet danach bereits erfolgreich an PLC uebergeben, obwohl Data Exchange die Datei erst spaeter abholen und den Druck ausloesen muss.

Die Dateien [plc_polling.py](../../sevDesk/sevdesk_wix_fulfillment/integrations/plc_polling.py) und [plc_label_dialog.py](../../sevDesk/sevdesk_wix_fulfillment/ui/plc_label_dialog.py) belegen diesen Ablauf. Die Legacy-Logs enthalten nur `PLC Export ...`; es gibt keine Bestaetigung, wann Ondot importiert oder ein Label gedruckt hat. Genau dadurch kann die beobachtete Wartezeit nicht kontrolliert werden.

Erhaltenswerte Legacy-Regeln:

- Trennung von LIVE und TEST.
- Referenz: Wix-Bestellnummer bevorzugen; stabile Rechnung-/Tagesfallbacks verwenden.
- Produktcodes: aktuell nachweisbar `10` fuer Paket Oesterreich und `45` fuer Premium International; Konfiguration darf nicht hart im UI stecken.
- Geschaeftsname vor Personenname in der Empfaengeradresse.
- ISO-2-Laendercodes, vollstaendige Zollartikel fuer Nicht-EU, atomare Fehlerbehandlung.
- PLC-Erfolg erst nach einer fachlich verwertbaren Antwort bestaetigen.

## Zielarchitektur

```text
Aktionsspalte (Post-Icon)
  -> PLC-Dialog mit Vorschau und explizitem Senden
  -> PlcShipmentBuilder (eine kanonische Validierung und Datenabbildung)
       -> PlcWebserviceClient (Standard) -> PDF/ZPL + Trackingnummer
       -> PlcPollingExportClient (temporärer Fallback) -> Import-CSV
  -> PrintQueueService (PLC-PDF an den konfigurierten PLC-Drucker)
  -> PlcShipmentRepository (Audit, Idempotenz, Storno/Retry)
```

`PlcShipmentBuilder` ist der zentrale Baustein. Er verhindert zwei getrennte Welten: Dateiimport und Webservice bekommen exakt dieselben validierten fachlichen Daten. Nur die Transportadapter unterscheiden sich.

## Konfiguration und Geheimnisse

### Neue Geheimnisse

In `SecretService.SUPPORTED_SECRET_KEYS` aufnehmen und verschluesselt in `api_secret` speichern:

- `PLC_CLIENT_ID`
- `PLC_ORG_UNIT_ID`
- `PLC_ORG_UNIT_GUID`

Ergaenzt fuer die zentrale Absenderadresse und den Direktdruck:

- `PLC_SHIPPER_NAME1`, `PLC_SHIPPER_STREET`, `PLC_SHIPPER_HOUSE_NUMBER`, `PLC_SHIPPER_POSTAL_CODE`, `PLC_SHIPPER_CITY`, `PLC_SHIPPER_COUNTRY`
- `PLC_SHIPPER_PHONE`, `PLC_SHIPPER_EMAIL`, optional `PLC_SHIPPER_EORI`
- optional `PLC_LABEL_PRINTER`

Keine PLC-Kennungen in YAML, Logs, Screenshots oder in die Versionskontrolle schreiben.

### Nicht-geheime Betriebswerte

Die offizielle LIVE-/TEST-WSDL ist im Code als sicherer Standard hinterlegt. Nur bei einer von der Post vorgegebenen Abweichung kann sie mit `PLC_WSDL_URL` bzw. `PLC_TEST_WSDL_URL` ueberschrieben werden. `PLC_TIMEOUT_SECONDS` ist standardmaessig `45`.

Das Profil `plc_label` ist in `config/default.yaml` angelegt; ohne expliziten `PLC_LABEL_PRINTER` faellt es auf den bestehenden Labeldrucker zurueck. Der Brother-LBX-Druck ist dabei kein Ersatz: Es wird das von PLC gelieferte PDF gedruckt.

## Datenvertrag fuer `ImportShipment`

Der SOAP-Aufruf nutzt das `ShipmentRow`-Modell aus dem produktiven WSDL:

| PLC-Feld | Quelle in XW-Studio | Regel |
|---|---|---|
| `ClientID`, `OrgUnitID`, `OrgUnitGuid` | verschluesselte PLC-Geheimnisse | vor dem Versand vollstaendig validieren |
| `Number` | Wix-Ordernummer, sonst deterministischer Fallback | Idempotenzschluessel, max. 40 Zeichen |
| `DeliveryServiceThirdPartyID` | Produktregel nach ISO-Land | Produkt 10 (AT), 45 (EU), 70 (Nicht-EU); PLC-Antwort ist die fachliche Autoritaet |
| `OUShipperAddress` | zentrale XeisWorks-Absenderadresse | ISO-2 `AT`, inkl. EORI falls erforderlich |
| `OURecipientAddress` | Wix-Lieferadresse + manuelle Dialogkorrektur | immer ISO-2, nie `AUSTRIA` oder `GERMANY` |
| `ColloList` | Gewicht, Menge, optionale Dimensionen | Gewicht als Dezimalzahl in kg |
| `ColloArticleList` | Wix-Positionen | nur Nicht-EU; SKU, Menge, Ursprung, HS-Code, Wert, Waehrung |
| `OUShipperReference1/2` | Wix-Order und Rechnungsnummer | fuer Suche, Support und Abgleich |
| `PrinterObject` | `PDF`, `100x200`, `100x200` | lokaler API-Abgleich; erzwingt Rueckgabe von `pdfData` |
| `CustomerProduct` | `XW-Studio` + Version | Support-/Audit-Kennung |

Vor dem ersten LIVE-Aufruf ist das reale WSDL gegen die freigeschalteten Versandprodukte zu pruefen. Produktcode `45` ist nicht pauschal fuer jede EU-Sendung korrekt; die Webservice-Antwort ist die fachliche Autoritaet.

## Persistenz und Idempotenz

Neue Tabelle `plc_shipment` per Alembic-Migration:

| Spalte | Zweck |
|---|---|
| `id` | technische UUID |
| `invoice_id`, `wix_order_reference`, `invoice_number` | Zuordnung |
| `request_key` | eindeutiger Idempotenzschluessel, UNIQUE |
| `mode`, `transport`, `product_code` | fachlicher Kontext |
| kein Adresspayload | bewusst nicht gespeichert; Audit bleibt datensparsam |
| `tracking_numbers` | aus `ImportShipmentResult` |
| `label_sha256`, `print_job_id` | Labelinhalt wird nicht dauerhaft gespeichert; Zuordnung zum lokalen Druckauftrag |
| `status` | `draft`, `sending`, `created`, `printed`, `failed`, `cancelled` |
| `error_code`, `error_message`, `created_at`, `updated_at` | Recovery/Audit |

Regeln:

1. Vor Netzaufruf atomar `sending` mit `request_key` reservieren.
2. Bei vorhandenem `created` niemals erneut `ImportShipment` senden.
3. Nach erfolgreicher SOAP-Antwort zuerst Sendung/Tracking persistieren, danach PDF drucken.
4. Druckfehler bedeutet `created`, nicht fehlgeschlagene Sendung. Der direkte PDF-Druck wird getrennt vom Versand protokolliert.
5. API-Timeout nach gesendetem Request ist unklarer Zustand: vor Retry anhand `request_key`, PLC-Suche/Support und Audit entscheiden; nicht blind neu senden.

## Umsetzungsphasen

### Phase 0 – Zugang und Vertragscheck

1. In PLC LIVE und TEST unter Geraetekonfiguration/API die drei Kennungen beschaffen.
2. Mit der Post klaeren: freigeschaltete Produkte, `PerformEndOfDay`-Pflicht, Storno-Semantik, Retouren, Zoll-/EORI-Felder und erlaubte Labelgroessen.
3. Einen Testdrucker und zwei Testadressen festlegen: AT sowie EU/Nicht-EU nach Vertrag.
4. Zugangsdaten verschluesselt in der App speichern; Verbindungstest nur mit Testumgebung.

Abnahmekriterium: `GetAllowedServicesForCountry` funktioniert in TEST und liefert erwartete Dienste.

### Phase 1 – Fachliches Modell ohne Versand

1. `services/plc/models.py`: Pydantic-Modelle fuer Adresse, Paket, Zollartikel, Druckoptionen und ShipmentDraft.
2. `services/plc/shipment_builder.py`: Legacy-Regeln migrieren; Wix-Adresse in ISO-2 normalisieren; manuelle Dialogaenderungen als hoechste Prioritaet.
3. Aktuellen Fehler beheben: Laendernamen duerfen nicht als PLC-ISO-Code in die Sendung gelangen.
4. Unit-Tests aus Legacy-Beispielen ableiten: Firmenadresse, c/o, Hausnummernzusatz, AT/EU/Nicht-EU, Referenzfallback, Mehrpaket, Zoll.

Abnahmekriterium: Der Builder erzeugt fuer vorhandene Legacy-Beispiele semantisch gleiche Sendungsdaten; keine Datei und kein Webservice-Aufruf.

### Phase 2 – Webservice-Adapter und Testsandbox

1. `services/plc/webservice_client.py` mit vorhandenem `zeep` implementieren; WSDL-Client in Worker-Thread, strikte Timeouts, keine UI-Blockade.
2. `ImportShipment` implementieren; `pdfData` Base64-dekodieren, `zplLabelData`, Trackingnummern, Fehlercode und Fehlermeldung sauber mappen.
3. `GetAllowedServicesForCountry` mit kurzlebigem Cache einsetzen; `CancelShipments` als vorbereitete, aber noch nicht sichtbare Servicefunktion implementieren.
4. Fixtures aus WSDL-/SOAP-Antworten erstellen; keine echten Kennungen in Tests.
5. TEST-Call mit bewusstem Versandprodukt, PDF-Dekodierung und Datei-/PDF-Sanity-Check ausfuehren.

Abnahmekriterium: TEST liefert eine valide PDF-Antwort, Trackingdaten und eine persistierte `created`-Sendung.

### Phase 3 – Drucken, UI und Audit

1. Eigenes Druckprofil `plc_label` anlegen und PDF ueber `PrintQueueService` drucken; Abschluss abwarten.
2. PLC-Dialog umbauen: Vorschau zuerst, Senden startet Worker, Status zeigt `Sende`, `Label erstellt`, `Drucke`, `Gedruckt` oder konkret `Fehler`.
3. Post-Icon unveraendert lassen. Nach erfolgreichem Versand Trackingnummer und Zeit im Rechnungsdetail anzeigen.
4. `plc_shipment`-Repository und Alembic-Migration integrieren; Wiederholungsdruck/Retry als getrennte Aktionen.
5. Strukturierte Logs ohne Adress- oder Geheimnisdaten: `invoice_id`, `request_key`, `mode`, `product`, `webservice_ms`, `print_ms`, `tracking_count`, `status`.

Abnahmekriterium: Ein PLC-Klick erzeugt und druckt ein TEST-Label ohne Ordner-Polling; UI bleibt bedienbar; erneuter Klick erzeugt keine Duplikatsendung.

### Phase 4 – Kontrollierter Parallelbetrieb

1. Produktionsflag zunaechst auf `polling`, Webservice pro Rechnung manuell aktivierbar.
2. Zehn bis zwanzig repräsentative Sendungen in LIVE durch den Webservice leiten und gegen Legacy vergleichen: Adresse, Produkt, Gewicht, Tracking, Label, Druckzeit.
3. Bei API- oder Druckproblemen darf der Dialog explizit auf den bestehenden Dateiimport umschalten; automatische Fallbacks nach einem moeglicherweise erfolgreichen API-Timeout sind verboten.
4. Monitoring auswerten: API-Erfolgsquote, mediane Webservicezeit, Druckzeit, Doppelsendungsversuche, Fehlercodes.

Abnahmekriterium: Keine Duplikate, keine falschen ISO-Laender, keine fehlenden Trackingnummern und stabile Druckzeiten.

### Phase 5 – Standardwechsel und Rueckbau

1. `transport: webservice` als Standard setzen.
2. Ondot Data Exchange nur fuer den expliziten Fallback behalten; die Fallback-Nutzung protokollieren.
3. Nach vier Wochen ohne fachlichen Bedarf Dateiimport und dessen Ordnerabhaengigkeit aus der Standardoberflaeche entfernen.
4. End-of-Day/Cancel-Funktionen erst aktivieren, wenn die Post die Vertrags- und Betriebsregeln bestaetigt hat.

## Testmatrix

| Fall | Erwartung |
|---|---|
| AT, Privatkunde, Produkt 10 | PDF sofort, ISO `AT`, keine Zollartikel |
| EU, Produkt 45 | PDF sofort, erlaubter Dienst, Gewicht vorhanden |
| Nicht-EU | Zollartikel, HS-Code, Ursprung, Wert und EORI validiert |
| Mehrere Pakete | mehrere `ColloRow`, alle Trackingnummern persistiert |
| Webservice-Fachfehler | keine Druckausgabe, konkrete Meldung, `failed` auditierbar |
| API-Timeout | kein automatisches Resend, manueller Recovery-Pfad |
| Drucker offline nach API-Erfolg | Sendung bleibt `created`, Wiederholungsdruck ohne neue Sendung |
| Wiederholung gleicher Rechnung | keine zweite PLC-Sendung |
| TEST/LIVE | getrennte URLs, getrennte Kennungen, sichtbarer Modus |

## Risiken und Gegenmassnahmen

- **Doppelsendung bei Timeout:** persistente Idempotenz vor API-Aufruf; nie blind retryen.
- **Falsches Versandprodukt:** dynamische Plausibilisierung per `GetAllowedServicesForCountry` und manuelle Vorschau.
- **Falsches Land:** zentrale ISO-Normalisierung im Builder; keine UI-Stringheuristik.
- **Druckerfehler:** Versand und Druck als getrennte Zustandsuebergaenge behandeln.
- **Credential-Leak:** nur SecretService/Fernet, Log-Redaktion, keine Dump-Ausgaben von SOAP.
- **Vertragliche Abweichungen:** Phase 0 mit PLC-Support abschliessen, bevor LIVE aktiviert wird.

## Nicht-Ziele dieser Umstellung

- Keine automatische Versandbuchung beim START-Button.
- Keine Veraenderung der Klickflaeche in der Rechnungsliste.
- Kein Entfernen des funktionierenden Dateiimports vor erfolgreichem Parallelbetrieb.
