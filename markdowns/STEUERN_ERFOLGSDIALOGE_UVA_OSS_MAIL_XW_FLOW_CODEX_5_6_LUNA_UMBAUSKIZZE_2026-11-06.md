# Steuern: kompakte Ergebnisdialoge, Steuerberichte und Zahlungsübergabe an XW-Flow

## Umbauskizze für Codex 5.6 Luna

Stand: 6. November 2026

Analysierte Stände:

- XW-Office: `main@b33df9e2d3ce4e6e14a4a366d8fcd9b6858f76ed`
- XW-Flow: `main@8bb06069661b4721dee3614740921a6b41200de8`

Betroffene Repositories:

- `C:\Users\XeisWorks\GitHub\XW-Office`
- `C:\Users\XeisWorks\GitHub\XW-Flow`

Dieses Dokument ist eine Analyse und spätere Umsetzungsplanung. Es implementiert noch keinen
Mailversand, erzeugt noch keinen Steuerbericht und verändert XW-Flow nicht.

---

## 1. Kurzentscheidung

Die vorhandenen langen `QMessageBox`-Texte werden durch einen kleinen, einheitlichen
Ergebnisdialog ersetzt. Der Dialog zeigt nur:

- ein klares positives, neutrales oder negatives Symbol;
- einen kurzen Ergebnissatz;
- höchstens eine kompakte Kontextzeile;
- einen großen Häkchen-Button zum Schließen;
- nur die für genau dieses Ergebnis zulässigen Folgeaktionen.

Die technische FinanzOnline-Antwort, Referenzen, XML und Fehlerdetails bleiben verfügbar, werden
aber aus der Hauptmeldung entfernt. Sie gehören in einen einklappbaren Bereich **Technische
Details** und in strukturierte Logs ohne Geheimnisse.

Die gewünschte Mailweitergabe ist möglich, aber nur unter folgenden fachlichen Grenzen:

1. **U30/UVA:** Nach einer echten erfolgreichen Produktivübermittlung kann XW-Office einen neu zu
   bauenden UVA-PDF-Bericht an `autobox@sevdesk.email` senden. Bei einer positiven Zahllast kann es
   zusätzlich einen strukturierten Zahlungsauftrag an `transfer@xeisworks.at` senden.
2. **U13/ZM:** Die ZM löst keine eigene Überweisung aus. Nach erfolgreicher U13-Übermittlung darf
   daher niemals automatisch ein Zahlungsfall erzeugt werden. Optional kann ein eigener
   U13-Bericht an sevDesk angeboten werden; ein alter oder nur zeitgleich sichtbarer UVA-Betrag darf
   nicht wiederverwendet werden.
3. **EU-OSS:** Ein erfolgreich gespeichertes XML ist noch keine Portalabgabe. Direkt nach dem Export
   darf die Zahlung nur **vorbereitet** werden. Der endgültige Versand an `transfer@xeisworks.at`
   wird erst nach der bestehenden Aktion **Im Portal abgegeben markieren** angeboten und verlangt
   die im Portal beziehungsweise zur zugrunde liegenden Erklärung bestätigten Zahlungsdaten.
4. Beide Mails müssen technisch über Microsoft Graph von `office@xeisworks.at` versendet werden.
   Ist genau diese Absenderidentität nicht nachweisbar konfiguriert, wird nicht auf eine andere
   Mailbox zurückgefallen.
5. Der Transfer-Mailversand ist keine Banktransaktion. Er erzeugt in XW-Flow einen offenen,
   prüfbaren Zahlungsfall. Die Überweisung und der Abschluss bleiben bewusst manuell.

---

## 2. Ist-Ablauf in XW-Office

### 2.1 UVA/U30

`src/xw_office/ui/modules/taxes/view.py` startet die U30-Übermittlung in einem
`BackgroundWorker` über `UvaService.submit_uva_month()`.

Der Dienst:

1. berechnet oder lädt den Monatssnapshot;
2. blockiert nur bei U30-relevanten Datenqualitätsfehlern;
3. baut den U30-Payload;
4. validiert und übermittelt das XML;
5. gibt ein `UvaSubmitResult` mit Antwort, Referenz, Payload und XML zurück;
6. speichert bei erfolgreicher Produktivübermittlung den lokalen Abgabestatus.

Der aktuelle Ergebnisdialog `_show_uva_submit_result()` zeigt Haupttext, Antwort, Referenz, Modus,
XML-Status, lokalen Ablagestatus und auf Wunsch den vollständigen Payload sowie das vollständige XML.
Das ist für eine technische Diagnose wertvoll, als tägliche Erfolgsmeldung aber deutlich zu lang.

### 2.2 U13/Zusammenfassende Meldung

Die U13 wird im selben Tab, aber über einen getrennten Ablauf gesendet:

1. ZM-Daten werden vorbereitet;
2. ungültige EU-UIDs können korrigiert und in sevDesk gespeichert werden;
3. die ZM wird neu berechnet;
4. das U13-XML wird gesendet;
5. `_show_zm_submit_result()` zeigt erneut eine lange technische Meldung.

Wichtig: `submit_zm_month()` kann mit `ok=True` zurückkehren, obwohl gar keine Übermittlung nötig
war, wenn keine ZM-relevanten Zeilen existieren. Dieser Zustand ist **neutral** und darf nicht als
„erfolgreich an FinanzOnline übermittelt“ bezeichnet werden.

### 2.3 EU-OSS

Im Reiter EU-OSS wird zunächst ein Quartal berechnet. Beim Export:

1. wird ein Zielpfad gewählt;
2. aus dem letzten Ergebnis oder einer Neuberechnung ein `OssXmlExport` gebaut;
3. das XML validiert;
4. die Datei im Worker geschrieben;
5. anschließend eine `QMessageBox.information()` mit Pfad und Portalhinweis geöffnet.

Fehler werden derzeit ebenfalls mit `QMessageBox.information()` angezeigt. Das falsche Symbol und
der fehlende handlungsorientierte nächste Schritt sollen korrigiert werden.

Der Export kennt das berechnete Quartal und alle Steuerzeilen. `OssXmlExport` enthält derzeit aber
weder den Gesamtsteuerbetrag noch einen unveränderlichen Snapshot-/Berechnungsschlüssel. Für eine
zuverlässige Zahlungsvorbereitung muss der Export eindeutig an das konkrete `OssQuarterResult`
gebunden werden.

### 2.4 Bereits vorhandene Mailtechnik

`MailDeliveryService` und `GraphMailClient` können bereits HTML-/Text-Mails und Binäranhänge über
Microsoft Graph versenden. Der Graph-Client setzt bei einer konfigurierten Mailbox auch das
`from`-Feld und verwendet den Endpunkt dieser Mailbox.

Der vorhandene Dienst lädt jedoch die globale Einstellung `MS_GRAPH_MAILBOX`. In der
Beispielkonfiguration ist diese `shop@xeisworks.at`. Der aktuelle Code garantiert deshalb nicht,
dass eine Steuermail wirklich von `office@xeisworks.at` kommt. Für den neuen Ablauf ist eine
explizite, fail-closed Absenderwahl erforderlich.

### 2.5 Noch nicht vorhanden

Im aktuellen Steuerbereich fehlen:

- ein UVA-/U13-PDF-Bericht;
- ein EU-OSS-Zahlungsdatensatz;
- ein Ergebnisdialog mit Folgeaktionen;
- ein persistenter Versandstatus beziehungsweise Idempotenzschutz;
- eine steuerbezogene Absender- und Empfänger-Allowlist;
- geprüfte Zahlungsempfänger-, IBAN-, BIC- und Verwendungszweckprofile;
- ein Cross-Repo-Vertrag, den XW-Flow ohne KI sicher auslesen kann.

---

## 3. Ist-Ablauf „Offene Überweisungen“ in XW-Flow

XW-Flow behandelt Nachrichten an `transfer@xeisworks.at` nicht mehr als normale Task. Der aktuelle
Ablauf ist:

```text
XW-Office sendet Mail an transfer@xeisworks.at
                         |
                         v
XW-Flow pollt die Shared Mailbox über Microsoft Graph
                         |
                         v
mail_task_sync erkennt den Alias "transfer"
                         |
                         v
eigenständiger PaymentCase, kein Task
                         |
                         v
deterministische Extraktion aus Mail/PDF, optional KI-Fallback
                         |
                         v
Prüfbarer Fall in „Offene Überweisungen“
                         |
                         v
EPC-QR aus Empfänger + gültiger IBAN + positivem Betrag
                         |
                         v
manuell bezahlen und „Überweisung durchgeführt“
```

Konkrete Eigenschaften:

- Die Shared Mailbox wird bei gesetzter `mail_alias_domain` direkt gelesen.
- Dedupliziert wird derzeit primär über die unveränderliche Graph-Message-ID.
- Ein `PaymentCase` speichert Empfänger, IBAN, optional BIC, Betrag, Währung,
  Verwendungszweck, Rechnungsnummer und Fälligkeit.
- Ein PDF-Anhang wird bis maximal 15 MiB übernommen; XW-Flow behält höchstens einen PDF-Anhang pro
  Zahlungsfall im privaten Objektspeicher.
- IBAN und BIC werden lokal geprüft.
- Der EPC-QR wird nur erzeugt, wenn Empfänger, gültige IBAN und Betrag vorhanden sind.
- Der Verwendungszweck wird auf 140 Zeichen begrenzt; der Empfänger im EPC-Payload auf 70 Zeichen.
- Eine mögliche Dublette wird derzeit nur markiert, nicht blockiert.
- XW-Flow führt keine Überweisung aus. Der Benutzer prüft die Daten, öffnet das Banking, erzeugt den
  QR-Code und markiert den Fall anschließend als durchgeführt.

### 3.1 Relevante Lücke im aktuellen Mailparser

Der aktuelle deterministische Parser erkennt aus Mailtext:

- IBAN;
- BIC;
- Beträge bei Bezeichnungen wie `Gesamtbetrag` oder `Zahlbetrag`;
- Rechnungs-/Belegnummer;
- Verwendungszweck/Referenz;
- Zahlungsfrist.

Er erkennt einen ausdrücklich beschrifteten `Empfänger:` im Mailtext derzeit **nicht**
deterministisch. Ohne PDF-Layout bleibt dafür nur der KI-Fallback oder manuelle Eingabe. Damit ist
ein ausschließlich per Textmail übergebener Steuerzahlungsfall heute noch nicht garantiert
QR-fähig.

Außerdem schützt die Graph-Message-ID nur gegen die erneute Verarbeitung derselben Mail. Sendet
XW-Office nach einem unklaren Timeout dieselbe fachliche Zahlung als neue Mail noch einmal, entstehen
zwei verschiedene Message-IDs. Die bestehende Dublettenheuristik meldet das zwar möglicherweise,
ist aber kein fachlicher Idempotenzschlüssel.

### 3.2 Notwendige XW-Flow-Erweiterung

Vor Freischaltung des XW-Office-Buttons muss XW-Flow daher:

1. `Empfänger:` beziehungsweise `Zahlungsempfänger:` deterministisch erkennen;
2. einen maschinenlesbaren Vertragsmarker erkennen, zum Beispiel
   `XW-Payment-Version: 1`;
3. einen fachlichen Schlüssel `XW-Payment-Key` speichern und eindeutig behandeln;
4. strukturierte Steuerzahlungs-Mails nur dann als vertrauenswürdigen Maschinenvertrag behandeln,
   wenn der reale Absender `office@xeisworks.at` ist;
5. bei fehlender oder widersprüchlicher Pflichtinformation `needs_review` setzen und keinen
   scheinbar fertigen QR versprechen;
6. die reguläre Verarbeitung anderer Rechnungs- und Transfermails unverändert erhalten.

Empfohlener eindeutiger Schlüssel:

```text
tax:<art>:<periode>:<calculation_hash>
```

Beispiele:

```text
tax:uva:2026-09:4e0f...
tax:eu-oss:2026-Q3:b781...
```

Ein bereits vorhandener Schlüssel führt nicht zu einem zweiten offenen Fall. XW-Flow gibt dem
Bestandsfall den Vorrang und protokolliert nur den erneuten Eingang wertfrei.

---

## 4. Fachlich korrigiertes Zielbild

### 4.1 U30/UVA

Nur alle folgenden Bedingungen ergeben den grünen produktiven Erfolg:

- `res.ok is True`;
- `res.test_mode is False`;
- der Antworttyp ist gültig;
- der U30-Payload enthält Periode, Berechnungsschlüssel und Betrag;
- die Übermittlung wurde von FinanzOnline angenommen.

Der lokale Abgabestatus kann separat fehlschlagen. Dann bleibt die Abgabe fachlich erfolgreich,
aber der Dialog erhält einen knappen gelben Hinweis und die empfohlene Aktion **Status erneut
speichern**. Eine bereits erfolgreiche U30 darf wegen eines lokalen Speicherfehlers nicht blind
erneut an FinanzOnline gesendet werden.

Zahlungslogik:

- `zahlbetrag > 0`: Zahllast; Transferaktion ist zulässig.
- `zahlbetrag == 0`: Nullbetrag; kein Zahlungsfall.
- `zahlbetrag < 0`: Gutschrift/Vorsteuerüberhang; kein Zahlungsfall und niemals Betrag absolut
  setzen.

### 4.2 U13/ZM

Zustände:

- produktiv übermittelt: grün;
- Testübermittlung: neutral/blau und klar als Test bezeichnet;
- keine ZM-Zeilen: neutral, **keine Meldung erforderlich**;
- abgelehnt/technischer Fehler: rot;
- UID- oder Datenproblem: gelb/rot mit Aktion **Daten prüfen**.

Die U13 besitzt keinen Zahlbetrag. Der Ergebnisdialog bietet keinen Transferbutton. Wenn ein
U13-PDF für die Buchhaltungsablage gewünscht ist, muss er aus genau dem U13-Payload erzeugt und als
**U13-/ZM-Bericht** bezeichnet werden. Er darf nicht als UVA-Bericht ausgegeben werden.

### 4.3 EU-OSS

Es gibt drei getrennte Meilensteine:

1. **XML erfolgreich gespeichert** – lokale technische Aktion;
2. **Erklärung im Portal erfolgreich abgegeben** – manuell bestätigte fachliche Aktion;
3. **Zahlungsauftrag an XW-Flow übergeben** – nach vollständiger Zahlungsprüfung.

Diese Zustände dürfen weder im Text noch im Datenmodell zusammenfallen.

Nach dem XML-Export ist der Betrag aus dem unveränderten Quartalsergebnis berechenbar. Für eine
zahlbare Übergabe sind zusätzlich nötig:

- Zahlungsempfänger;
- die ausdrücklich für EU-OSS bestimmte IBAN;
- optional BIC;
- die zur abgegebenen Erklärung gehörende Zahlungsreferenz;
- Fälligkeit;
- positiver Gesamtsteuerbetrag;
- Quartal und Berechnungsschlüssel.

Die offizielle USP-Information, geprüft am 6. November 2026, verlangt die Zahlung auf das speziell
für EU-OSS vorgesehene Konto und unter Hinweis auf die zugrunde liegende Erklärung. Deshalb dürfen
IBAN und Referenz weder aus einer normalen Finanzamtszahlung übernommen noch geraten werden:

- <https://www.usp.gv.at/themen/steuern-finanzen/umsatzsteuer-ueberblick/weitere-informationen-zur-umsatzsteuer/umsaetze-mit-auslandsbezug/Umsatzsteuer-One-Stop-Shop/EU-OSS/Erklaerung-und-Zahlung-im-EU-OSS.html>

Empfehlung:

- Im XML-Erfolgsdialog steht **Zahlung vorbereiten …**.
- Die Aktion übernimmt Quartal und berechneten Betrag, sendet aber noch keine Mail.
- Nach dem Portalupload wird über **Im Portal abgegeben markieren** ein kleiner Prüfdialog geöffnet.
- Dort werden Zahlungsreferenz und die im Portal/aktuellen BMF-Nachweis bestätigten Kontodaten
  geprüft beziehungsweise ausgewählt.
- Erst **Zahlungsauftrag an XW-Flow senden** verschickt die Transfer-Mail.

Damit bleibt der gewünschte schnelle Einstieg direkt nach dem Export erhalten, ohne einen
unvollständigen oder falschen QR-Code zu erzeugen.

---

## 5. Kompakte Ergebnisdialoge

### 5.1 Gemeinsame Komponente

Neue, kleine Komponente, zum Beispiel:

```text
src/xw_office/ui/components/operation_result_dialog.py
```

Alternativ steuerbereichsspezifisch:

```text
src/xw_office/ui/modules/taxes/result_dialog.py
```

Empfohlene API:

```python
OperationResultDialog(
    parent,
    tone="success" | "neutral" | "warning" | "error",
    title="...",
    summary="...",
    context="...",
    primary_action=None,
    secondary_action=None,
    details="...",
)
```

Verbindliche UX-Regeln:

- keine automatisch verschwindende Toast-Meldung für Einreichungs- oder Exportergebnisse;
- Häkchen-Button mit sichtbarem `✓`, Tooltip und Accessible Name **Schließen**;
- Häkchen ist Default- und Escape-Aktion;
- Erfolg grün, neutral blau/grau, Warnung gelb, Fehler rot;
- keine Roh-Exception im Haupttext;
- technische Details standardmäßig eingeklappt und kopierbar;
- maximal zwei Folgeaktionen zusätzlich zum Häkchen;
- Aktion während eines Workers deaktivieren und mit kleinem Busy-Status versehen;
- Dialog nach einer Folgeaktion nicht kommentarlos schließen, sondern in den Versandstatus wechseln.

### 5.2 Empfohlene Texte

#### U30 produktiv erfolgreich, Zahllast positiv

```text
UVA erfolgreich übermittelt
09/2026 · Zahllast 1.234,56 €

[Bericht + Zahlung weitergeben] [✓]
```

Die Folgeaktion öffnet eine kurze Vorschau mit zwei klar getrennten Zielen und sendet nach
Bestätigung:

- UVA-PDF an sevDesk-Autobox;
- Zahlungsdaten an XW-Flow.

#### U30 produktiv erfolgreich, Nullbetrag oder Gutschrift

```text
UVA erfolgreich übermittelt
09/2026 · Gutschrift 123,45 €

[Bericht an sevDesk senden] [✓]
```

Kein Transferbutton.

#### U30 Testmodus

```text
UVA-Test erfolgreich
09/2026 · Keine produktive Abgabe

[✓]
```

Keine Archiv- oder Zahlungsaktion, damit ein Test nicht wie eine echte Abgabe weiterverarbeitet
wird.

#### U13 produktiv erfolgreich

```text
ZM erfolgreich übermittelt
09/2026 · 4 UID-Zeilen

[U13-Bericht an sevDesk senden] [✓]
```

Die Berichtsaktion ist nur umzusetzen, wenn die sevDesk-Ablage eines U13-Berichts fachlich gewünscht
ist. Kein Transferbutton.

#### U13 ohne meldepflichtige Zeilen

```text
Keine ZM-Abgabe erforderlich
09/2026 · Keine meldepflichtigen Zeilen

[✓]
```

#### EU-OSS-XML gespeichert

```text
EU-OSS-XML gespeichert
Q3/2026 · Steuerbetrag 1.234,56 €

[Zahlung vorbereiten …] [Portal öffnen] [✓]
```

Der Dateipfad steht nicht im Haupttext. Er kann als kurze sekundäre Zeile gekürzt oder über
**Datei im Explorer anzeigen** in den Details angeboten werden.

#### EU-OSS-Portalabgabe bestätigt

```text
EU-OSS-Abgabe bestätigt
Q3/2026 · Zahlungsdaten vollständig

[Zahlungsauftrag senden] [✓]
```

#### Versand beider U30-Nachrichten erfolgreich

```text
Weitergabe abgeschlossen
sevDesk-Bericht ✓ · XW-Flow-Zahlung ✓

[✓]
```

#### Teilfehler

```text
Weitergabe teilweise abgeschlossen
sevDesk-Bericht ✓ · XW-Flow-Zahlung fehlgeschlagen

[Fehlgeschlagene Nachricht erneut senden] [✓]
```

Bereits erfolgreiche Empfänger werden beim Retry nicht nochmals angeschrieben.

---

## 6. Kompakte Fehlermeldungen und nächste Schritte

Jeder Fehler erhält einen stabilen Fehlercode, einen kurzen Benutzersatz und genau passende
Folgeaktionen. Beispiele:

| Kategorie | Haupttext | Empfohlene Aktion |
|---|---|---|
| U30/U13 Datenprüfung | `Meldung konnte nicht gesendet werden` | `Daten prüfen` und danach neu berechnen |
| FinanzOnline-Ablehnung | `FinanzOnline hat die Meldung nicht angenommen` | Referenz/Details prüfen; nicht blind erneut senden |
| Unklarer Timeout nach Sendestart | `Ergebnis der Übermittlung ist unklar` | Abgabestatus/FinanzOnline prüfen; kein automatischer Retry |
| Graph nicht konfiguriert | `Nachricht konnte nicht gesendet werden` | `Mail-Einstellungen öffnen` |
| Falsche Graph-Mailbox | `Absender office@xeisworks.at ist nicht verfügbar` | Konfiguration korrigieren; kein Fallback |
| PDF-Erzeugung | `Steuerbericht konnte nicht erstellt werden` | `Erneut versuchen`; Steuerabgabe bleibt erfolgreich |
| XML-Validierung | `EU-OSS-XML ist nicht gültig` | Daten/OSS-ID prüfen; keine Datei als Erfolg melden |
| Dateizugriff | `XML konnte nicht gespeichert werden` | `Anderen Speicherort wählen` |
| Unvollständige OSS-Zahlung | `Zahlungsdaten sind noch unvollständig` | Portalreferenz/Konto ergänzen |
| Transfer-Vertrag | `Zahlungsauftrag ist nicht QR-fähig` | markierte Felder korrigieren |
| Netzwerk | `Dienst ist vorübergehend nicht erreichbar` | `Erneut versuchen` |

Regeln für Retries:

- Reine Vorschau-, Export-, PDF- und Mailfehler dürfen gezielt erneut versucht werden.
- Nach einem unklaren FinanzOnline-Timeout darf kein automatischer Sende-Retry erfolgen, weil eine
  Doppelabgabe nicht ausgeschlossen ist.
- Bei partiellem Mailversand wird nur der fehlgeschlagene Empfänger erneut bedient.
- Technische Details enthalten Exceptiontyp, stabilen Fehlercode und bereinigte Providerantwort,
  aber keine Tokens, Passwörter, Authorization-Header oder vollständige vertrauliche Payloads.

---

## 7. Steuerberichte als PDF

### 7.1 Eigener Renderer

Neuer reiner Dienst, zum Beispiel:

```text
src/xw_office/services/finanzonline/tax_report_pdf.py
```

PyMuPDF ist bereits eine Projektabhängigkeit und wird in mehreren Diensten für lokale PDFs genutzt.
Der Renderer soll PDF-Bytes deterministisch aus einem unveränderlichen Berichtsdatenmodell erzeugen
und keine UI-Widgets kennen.

### 7.2 UVA-Bericht

Pflichtinhalt:

- Titel `Umsatzsteuervoranmeldung U30`;
- Periode;
- Status `Produktiv übermittelt` oder deutliches Wasserzeichen `TEST`;
- Übermittlungszeitpunkt;
- FinanzOnline-Referenz;
- Zahllast, Nullbetrag oder Gutschrift mit korrektem Vorzeichen;
- gesendete U30-Kennzahlen in verständlicher Tabelle;
- XML-validiert-Status;
- Regelversion;
- Berechnungs- und optional Snapshothash gekürzt;
- Hinweise/Datenqualitätswarnungen;
- Erzeuger `XW-Office`.

Nicht in den sichtbaren Bericht gehören Zugangsdaten, Graph-Konfiguration oder vollständige
Provider-Debugantworten.

Empfohlener Dateiname:

```text
UVA_U30_2026-09_FON-REFERENZ.pdf
```

Unzulässige Dateizeichen müssen entfernt werden. Ohne Referenz wird ein stabiler Hashsuffix
verwendet.

### 7.3 U13-Bericht

Falls freigegeben, eigener Bericht mit:

- Titel `Zusammenfassende Meldung U13`;
- Periode;
- Übermittlungsstatus und Referenz;
- Anzahl UID-Zeilen;
- UID, Art und Betrag je Zeile;
- Warnungen und XML-Status.

Er wird nicht mit dem U30-Bericht vermischt und löst keine Zahlung aus.

### 7.4 Bericht aus dem tatsächlich gesendeten Snapshot

Der PDF-Bericht muss aus `UvaSubmitResult.uva_payload` beziehungsweise
`UvaSubmitResult.zm_payload` und dem konkreten Übermittlungsergebnis entstehen. Eine neue
sevDesk-Berechnung nach der Übermittlung ist unzulässig, weil sich Daten inzwischen geändert haben
könnten.

---

## 8. Mailversand und Absendergarantie

### 8.1 Mailidentität

`MailDeliveryService` soll optional eine ausdrücklich verlangte Sender-Mailbox erhalten, ohne das
Verhalten bestehender Aufrufer zu verändern. Beispiel:

```python
send_mail(
    ...,
    sender_mailbox="office@xeisworks.at",
    require_exact_sender=True,
)
```

Der Steuerdienst verwendet eine unveränderliche Konstante:

```text
TAX_MAIL_SENDER = office@xeisworks.at
```

Verbindliche Prüfungen vor jedem Versand:

- normalisierte Senderadresse ist exakt `office@xeisworks.at`;
- Graph-Zugriff für diese Mailbox ist vorhanden;
- Zieladresse steht in der Allowlist;
- `from`, verwendeter `/users/{mailbox}/sendMail`-Endpunkt und konfigurierte Mailbox stimmen
  überein;
- kein Fallback auf `shop@`, angemeldeten Standardaccount oder Outlook-Defaultkonto.

Allowlist:

```text
autobox@sevdesk.email
transfer@xeisworks.at
```

Die Absendergarantie ist zusätzlich in einem kontrollierten Graph-Integrationstest mit synthetischer
Mail zu prüfen. Ein Unit-Test kann nur Payload und Zielendpunkt, nicht die tatsächlich in Exchange
angewandte Senderidentität beweisen.

### 8.2 Mail an sevDesk-Autobox

Empfohlener Betreff:

```text
UVA U30 09/2026 – erfolgreich übermittelt
```

Kurzer Textkörper:

```text
UVA-Bericht für 09/2026.
FinanzOnline-Übermittlung erfolgreich.
Referenz: <Referenz>
```

Anhang ist ausschließlich der erzeugte PDF-Bericht. Das vollständige U30-XML wird nicht ungefragt
mitgesendet.

### 8.3 Strukturierte Mail an XW-Flow

Empfohlener Betreff:

```text
Zahlung UVA 09/2026
```

Maschinen- und menschenlesbarer Textkörper:

```text
XW-Payment-Version: 1
XW-Payment-Key: tax:uva:2026-09:<calculation_hash>
Art: UVA
Periode: 09/2026
Empfänger: <geprüfter Zahlungsempfänger>
IBAN: <geprüfte IBAN>
BIC: <geprüfter BIC oder leer>
Gesamtbetrag: 1234,56 EUR
Verwendungszweck: <geprüfte Zahlungsreferenz>
Rechnung Nr.: UVA-2026-09
Fällig: 15.11.2026
FinanzOnline-Referenz: <Übermittlungsreferenz>
```

Für EU-OSS entsprechend:

```text
XW-Payment-Key: tax:eu-oss:2026-Q3:<calculation_hash>
Art: EU-OSS
Periode: Q3/2026
...
```

Der Mailtext muss die Labels exakt versioniert beibehalten. Änderungen am Vertrag benötigen
Contract-Tests in beiden Repositories.

---

## 9. Zahlungsdaten und Sicherheitsregeln

### 9.1 U30-Zahlungsprofil

Die offizielle BMF-Information weist darauf hin, dass sich die Bankverbindung abhängig von Amt und
Dienststelle ändern kann und ausschließlich die Bankverbindung aus aktuellen Schriftstücken oder
Buchungsmitteilungen verwendet werden soll:

- <https://www.bmf.gv.at/themen/steuern/fristen-verfahren/steuerzahlungen.html>

Deshalb keine IBAN aus einem Blog, alten Plan oder Quellcode hartcodieren. Benötigt wird ein
explizites, lokal gepflegtes Profil:

```text
payment_recipient
iban
bic
tax_number / Abgabenkontonummer
remittance_template
verified_at
verification_source_label
```

Die Steuernummer ist kein Secret, aber dennoch nicht unnötig in Logs oder Fehlermeldungen
auszugeben. Die UI zeigt bei der Versandvorschau Empfänger, maskierte IBAN, Betrag,
Verwendungszweck, Fälligkeit und Datum der letzten Bestätigung.

### 9.2 EU-OSS-Zahlungsprofil

EU-OSS verwendet ein eigenes Konto. Es darf nicht automatisch das normale Finanzamtsprofil
verwenden. Erforderlich sind:

```text
oss_payment_recipient
oss_iban
oss_bic
portal_declaration_reference
verified_at
verification_source_label
```

Die zur konkreten Erklärung gehörende Referenz wird pro Quartal gespeichert, nicht als globaler
Default. Ohne Referenz kein Versand.

### 9.3 Zahlungsbetrag

- Decimal statt Float;
- Währung fest `EUR`;
- auf zwei Nachkommastellen normalisieren;
- Betrag muss größer null sein;
- bei U30 niemals eine Gutschrift durch `abs()` in eine Zahlung verwandeln;
- EU-OSS-Gesamtbetrag aus genau den Zeilen des exportierten Quartalssnapshots summieren;
- nach Änderung von Quartal, OSS-ID, UID, Quelldaten oder Berechnung muss die vorbereitete Zahlung
  ungültig werden.

### 9.4 Verwendungszweck

Der Verwendungszweck darf nicht frei aus dem FinanzOnline- oder OSS-Text geraten werden. Er kommt
aus einem bestätigten U30-Zahlungsprofil beziehungsweise aus der konkreten EU-OSS-Portalabgabe und
wird vor Versand auf maximal 140 Zeichen geprüft.

### 9.5 Keine automatische Bankausführung

Der neue Button verschickt nur Daten an den bestehenden XW-Flow-Prüfprozess. Kein Banking-Login,
keine Überweisung und keine Markierung **durchgeführt** aus XW-Office heraus.

---

## 10. Persistenz, Idempotenz und Teilfehler

Neuer lokaler Versanddatensatz, zum Beispiel `tax_followup_dispatches`:

| Feld | Zweck |
|---|---|
| `dispatch_key` | eindeutig aus Art, Periode, Berechnungshash und Ziel |
| `filing_kind` | `uva`, `u13`, `eu_oss` |
| `period` | Monat oder Quartal |
| `calculation_hash` | Bindung an den gesendeten/exportierten Snapshot |
| `recipient_kind` | `sevdesk_autobox` oder `xw_flow_transfer` |
| `status` | `pending`, `sent`, `failed` |
| `attempt_count` | Retry-Nachweis |
| `sent_at` | erfolgreicher Versand |
| `message_correlation_id` | lokale Korrelation, keine Tokens |
| `attachment_sha256` | Nachweis des PDF-Inhalts |
| `last_error_code` | wertfreier stabiler Fehlercode |

Unique Constraint:

```text
(filing_kind, period, calculation_hash, recipient_kind)
```

Regeln:

- pro Empfänger eigener Status;
- Versanddatensatz vor dem Graph-Aufruf als `pending` persistieren;
- bei Erfolg `sent`, bei kontrolliertem Fehler `failed`;
- bei unklarem Graph-Timeout Status nicht als sicher ungesendet behandeln;
- Retry sendet nur `failed`; ein unklares `pending` verlangt zuerst Statusprüfung;
- der Button zeigt **Bereits gesendet**, wenn der Schlüssel erfolgreich abgeschlossen ist;
- ein neuer Berechnungshash ist ein neuer fachlicher Stand und braucht bewusste Bestätigung.

XW-Flow ergänzt zusätzlich `XW-Payment-Key` als Ende-zu-Ende-Idempotenzschutz. Damit sind sowohl
Absender-Retry als auch erneuter Mailboxeingang abgedeckt.

---

## 11. Empfohlene Codeaufteilung

### XW-Office

Neue oder zu trennende Bausteine:

```text
src/xw_office/services/finanzonline/tax_report_pdf.py
src/xw_office/services/finanzonline/tax_followup_models.py
src/xw_office/services/finanzonline/tax_followup_service.py
src/xw_office/repositories/tax_followup_dispatch.py
src/xw_office/ui/modules/taxes/result_dialog.py
src/xw_office/ui/modules/taxes/payment_review_dialog.py
```

Zu ändern:

```text
src/xw_office/ui/modules/taxes/view.py
src/xw_office/services/finanzonline/oss_models.py
src/xw_office/services/finanzonline/oss_service.py
src/xw_office/services/mailing/service.py
src/xw_office/services/mailing/graph_client.py
src/xw_office/bootstrap.py
src/xw_office/ui/modules/settings/view.py
```

`TaxesView` soll nur Worker starten und Ergebnisse an Dialog/Follow-up-Service weiterreichen. PDF,
Mailtext, Zahlungskontrolle und Idempotenz gehören nicht in verschachtelte UI-Callbacks.

### XW-Flow

Voraussichtlich zu ändern:

```text
backend/app/services/payments.py
backend/app/services/mail_task_sync.py
backend/app/models/payment_case.py
backend/app/schemas/payment.py
backend/alembic/versions/<neue_revision>.py
backend/tests/test_payments.py
backend/tests/test_mail_task_sync.py
frontend/src/components/payments/PaymentCaseDialog.tsx
```

Vor einer XW-Flow-Umsetzung zuerst `markdowns/README.md` und den aktuellen
`markdowns/ARBEITSPLAN.yaml` lesen und dort ein neues, kleines Cross-Repo-Paket aufnehmen. Alte
Pläne in `markdowns/archiv/` bleiben unverändert.

---

## 12. Umsetzungsreihenfolge für Codex 5.6 Luna

Luna soll nicht alle Pakete in einem Lauf umsetzen. Jedes Paket wird separat getestet, committed
und nach `origin/main` gepusht.

### Paket P0 – Fachliche Konfiguration bestätigen

Ziel:

- aktuelle U30-Zahlungsempfänger-/Kontodaten aus dem letzten offiziellen Schreiben erfassen;
- klären, ob U13-Berichte wirklich an `autobox@sevdesk.email` sollen;
- echten Graph-Zugriff für `office@xeisworks.at` kontrolliert testen;
- festlegen, welche EU-OSS-Kontodaten und Referenz im Portal sichtbar werden.

Abnahme:

- keine Bankdaten aus Vermutung oder Altcode;
- dokumentierter Prüfzeitpunkt und Quelle;
- keine produktive Mail im Unit-Test.

### Paket P1 – Reine Ergebnis- und Zahlungsmodelle

Ziel:

- typisierte Ergebniszustände aus `UvaSubmitResult` und `OssXmlExport` ableiten;
- U30-Zahllast/Gutschrift/Nullbetrag korrekt klassifizieren;
- EU-OSS-Gesamtbetrag und Berechnungshash an den Export binden;
- Mailvertrag als reinen Builder implementieren.

Abnahme:

- keine Qt- oder Graph-Abhängigkeit in den Buildertests;
- Vorzeichen-, Rundungs- und Periodentests grün.

### Paket P2 – Kompakte Dialoge

Ziel:

- gemeinsame Dialogkomponente;
- U30-, U13- und OSS-Zustandsmatrix;
- Häkchen-, Escape-, Fokus- und Screenreaderverhalten;
- technische Details einklappbar.

Abnahme:

- UI-Tests für Texte, Ton, Buttons und Zustände;
- negative OSS-Fälle verwenden ein Error-Symbol, nicht Information;
- kein langer Standard-Erfolgsdialog mehr.

### Paket P3 – PDF-Berichte

Ziel:

- deterministischer U30-PDF-Renderer;
- optional U13-Renderer nach P0-Entscheidung;
- Bericht ausschließlich aus gesendetem Payload.

Abnahme:

- PDF ist parsebar, einseitig oder sauber mehrseitig und enthält Pflichtfelder;
- Testmodus deutlich markiert;
- Golden-Master besser über extrahierten Text/Struktur als über volatile Binärbytes prüfen.

### Paket P4 – XW-Flow-Vertrag zuerst ausrollen

Ziel:

- deterministischer Empfängerparser;
- `XW-Payment-Version` und `XW-Payment-Key`;
- eindeutiger Schlüssel in DB;
- strikte Absenderprüfung für strukturierte Steueraufträge;
- QR-Vertragstest.

Abnahme:

- vollständig strukturierte Testmail erzeugt ohne KI einen QR-fähigen `PaymentCase`;
- ungültige IBAN, Nullbetrag, fehlender Empfänger oder fremder Maschinenabsender werden nicht als
  fertig behandelt;
- zweiter Eingang mit gleichem Payment-Key erzeugt keinen zweiten offenen Fall;
- normale transfer@-Rechnungen bleiben kompatibel;
- XW-Flow-Backendtests, Migration und Frontendtests grün;
- `python scripts/check_markdowns.py` nach Arbeitsplanänderung grün.

### Paket P5 – Absenderfester Graph-Versand in XW-Office

Ziel:

- explizite Sender-Mailbox im Maildienst;
- Steuer-Empfänger-Allowlist;
- keine Defaultmailbox als Fallback;
- synthetischer kontrollierter Integrationstest.

Abnahme:

- Unit-Tests prüfen `/users/office@xeisworks.at/sendMail`, `from` und Empfänger;
- echter Test bestätigt sichtbaren Absender `office@xeisworks.at`;
- fehlende Rechte liefern kompakte, verständliche Fehlermeldung.

### Paket P6 – Versandpersistenz und U30-Folgeaktion

Ziel:

- persistente Empfängerzustände;
- U30-Bericht an Autobox;
- positiver U30-Zahlungsfall an XW-Flow;
- Teilfehler- und Retrylogik.

Abnahme:

- Zahllast sendet genau zwei Nachrichten;
- Nullbetrag/Gutschrift sendet höchstens den Bericht;
- U13 sendet keine Zahlung;
- Doppelklick und Neustart erzeugen keine Dublette;
- bereits erfolgreiche Teilaktion wird beim Retry nicht wiederholt.

### Paket P7 – EU-OSS-Zwei-Schritt-Ablauf

Ziel:

- XML-Erfolg kompakt anzeigen;
- Zahlung vorbereiten;
- Portalbestätigung um Zahlungsdaten ergänzen;
- erst danach Transfer-Mail senden.

Abnahme:

- XML-Export allein erzeugt keinen fertigen Zahlungsfall;
- geändertes Quartal oder neuer Hash invalidiert den Entwurf;
- nur positiver, vollständiger Betrag wird versendet;
- QR in XW-Flow enthält Empfänger, IBAN, Betrag und exakte Portalreferenz.

### Paket P8 – Gesamtregression und Betriebsnachweis

Ziel:

- komplette Zustandsmatrix beider Repositories;
- kontrollierter End-to-End-Test mit synthetischen Daten;
- Dokumentation der manuellen Exchange-/Portalprüfungen.

Abnahme:

- U30 Erfolg, Gutschrift, Testmodus, Ablehnung und Timeout;
- U13 Erfolg, Nullmeldung, UID-Fehler und Ablehnung;
- OSS Exporterfolg, Schreibfehler, Portalbestätigung, fehlende Referenz und Zahlung;
- Graph Vollerfolg, Teilfehler, Retry und unbekannter Timeout;
- XW-Flow erstellt genau einen QR-fähigen Fall;
- keine echten Steuerdaten in Fixtures oder Logs.

---

## 13. Testmatrix

### XW-Office Unit-Tests

- U30 positiver Betrag erzeugt Zahlmodell;
- `0.00` und negative Werte erzeugen kein Zahlmodell;
- ungültige Dezimalwerte blockieren;
- U13 erzeugt nie ein Zahlmodell;
- OSS-Summe wird aus dem konkreten Exportresultat gebildet;
- Report enthält Periode, Referenz, Betrag, Kennzahlen und Hash;
- Mailbuilder hält Labels und Zeichenlimits ein;
- Sender und Empfänger-Allowlist sind fail-closed;
- Dispatch-Unique-Constraint und Teilretry.

### XW-Office UI-Tests

- Erfolg zeigt `✓` und richtige Folgeaktion;
- Testmodus zeigt keine produktive Aktion;
- Gutschrift zeigt keinen Transferbutton;
- U13-Nullfall ist neutral;
- OSS-Export sagt nicht „abgegeben“;
- Fehler zeigt nächsten Schritt und kopierbare Details;
- Worker verhindert Doppelklick;
- Escape und Häkchen schließen.

### XW-Flow Backend-Tests

- strukturierte UVA-Mail wird ohne OpenAI vollständig extrahiert;
- Empfängerlabel wird erkannt;
- IBAN/BIC-Prüfung;
- Betrag und Verwendungszweck stimmen im EPC-QR;
- Fälligkeit wird erkannt;
- `XW-Payment-Key` dedupliziert neue Graph-Message-IDs;
- Maschinenmarker von fremdem Absender wird nicht blind vertraut;
- reguläre PDF-Rechnung bleibt unverändert unterstützt;
- fehlende Pflichtfelder führen zu `needs_review`.

### Manuelle Integrationstests

- echte Graph-Send-As-/Mailboxidentität;
- Zustellung und PDF-Import bei sevDesk-Autobox;
- Eingang in XW-Flows Shared Mailbox;
- QR-Scan mit einer Banking-App gegen synthetische beziehungsweise kontrollierte Testdaten;
- EU-OSS-Portaldaten manuell mit Zahlungsentwurf vergleichen.

---

## 14. Definition of Done

Der Umbau ist erst abgeschlossen, wenn:

1. U30, U13 und EU-OSS kompakte, korrekte Ergebnisdialoge besitzen;
2. jeder Dialog über einen sichtbaren und zugänglichen Häkchen-Button geschlossen werden kann;
3. Fehler nicht als Information erscheinen und einen konkreten nächsten Schritt nennen;
4. ein U30-Bericht aus dem tatsächlich gesendeten Snapshot erzeugt wird;
5. beide erlaubten Zielmails nachweislich von `office@xeisworks.at` kommen;
6. Testübermittlungen keine produktiven Folgeaktionen anbieten;
7. U30-Gutschriften, Nullbeträge und U13 nie als Zahlung an XW-Flow gehen;
8. EU-OSS erst nach vollständiger Portal-/Zahlungsbestätigung an XW-Flow geht;
9. XW-Flow die strukturierte Mail ohne KI vollständig und QR-fähig versteht;
10. ein fachlicher Payment-Key Dubletten über neue Message-IDs hinweg verhindert;
11. Teilfehler gezielt wiederholbar sind;
12. keine Zugangsdaten oder vollständigen vertraulichen Payloads in Logs, Fixtures oder Berichten
    landen;
13. alle betroffenen Tests, Markdownprüfungen und kontrollierten manuellen Gates dokumentiert sind;
14. beide Repositories nach ihrer jeweiligen `AGENTS.md`-Regel auf `main` integriert und nach
    `origin/main` gepusht sind.

---

## 15. Nicht umsetzen

- keine automatische Banküberweisung;
- kein absolut gesetzter negativer UVA-Betrag;
- keine Transfer-Mail bei U13;
- keine produktive Folgeaktion nach Testübermittlung;
- keine Gleichsetzung von EU-OSS-XML-Export und Portalabgabe;
- keine hartcodierte, ungeprüfte Finanzamts- oder EU-OSS-IBAN;
- kein Versand über `shop@xeisworks.at` oder den Outlook-Defaultaccount;
- keine KI als Pflicht für Empfänger, IBAN, Betrag oder Verwendungszweck;
- kein vollständiges XML im normalen Erfolgsdialog;
- keine zweite XW-Flow-Task neben dem `PaymentCase`;
- keine Änderung historischer XW-Flow-Planungsdateien im Archiv.

---

## 16. Offene Betreiberentscheidungen vor P0

Diese Punkte sind nicht aus dem Code ableitbar und müssen vor produktiver Freischaltung bewusst
bestätigt werden:

1. Sollen U13-Berichte tatsächlich ebenfalls an `autobox@sevdesk.email` gehen oder nur U30-Berichte?
2. Welche aktuelle, schriftlich bestätigte Bankverbindung und welche Verrechnungsweisung gelten für
   die normale U30-Zahlung von XeisWorks?
3. Welche Zahlungsdaten zeigt die konkrete EU-OSS-Portalabgabe nach dem Upload an, und welcher Wert
   ist als Zahlungsreferenz zu übernehmen?
4. Besitzt die vorhandene Microsoft-Graph-App die erforderlichen Rechte für den echten Versand als
   `office@xeisworks.at`?
5. Soll der Steuerbericht nach erfolgreicher Autobox-Mail zusätzlich lokal in einem Auditordner
   abgelegt werden, oder genügt die reproduzierbare Erzeugung plus Versandnachweis?

Bis diese Punkte geklärt sind, dürfen Dialog- und Berichtspakete umgesetzt werden; die produktiven
Mailbuttons bleiben jedoch deaktiviert beziehungsweise als **nicht konfiguriert** gekennzeichnet.
