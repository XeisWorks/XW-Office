# XW-Office Multi-PC Betriebsleitfaden

Ziel:
- Jeder Windows-PC kann reproduzierbar installiert, aktualisiert und betrieben werden.
- Betriebsdaten kommen aus PostgreSQL (Railway), Code aus GitHub.

## 1) Voraussetzungen pro PC

- Windows 10/11
- Python 3.11 oder 3.12
- Git
- Drucker lokal installiert (fuer Druck-PCs)

## 2) Erstinstallation

1. Repo klonen:
   - `git clone --recurse-submodules https://github.com/XeisWorks/XW-Office.git`
2. In Projektordner wechseln.
3. Virtuelle Umgebung erstellen:
   - `python -m venv .venv`
4. Umgebung aktivieren:
   - `.venv\\Scripts\\activate`
5. Abhaengigkeiten installieren:
   - `pip install -e ".[dev]"`
6. `.env` aus `.env.example` erstellen und lokale Werte setzen.
7. Migrationen ausfuehren:
   - `alembic upgrade head`
8. Windows-Startmenue-Verknuepfungen erzeugen (einmalig, danach idempotent erneut ausfuehrbar):
   - `powershell -NoProfile -ExecutionPolicy Bypass -File scripts\setup_windows_shortcuts.ps1`
   - Legt im Startmenue den Ordner "XeisWorks Office" mit zwei Eintraegen an: normaler Start und
     Debug-Start. Optional zusaetzlich eine Desktop-Verknuepfung mit `-IncludeDesktopShortcut`.
     Der normale Start prueft beim Start automatisch und lautlos auf Updates (siehe Abschnitt 5),
     eine eigene Update-Verknuepfung gibt es deshalb nicht.
9. Normalen Start testen: Startmenue -> "XeisWorks Office" (kein Konsolenfenster, PySide6-Fenster
   erscheint maximiert).
10. Debug-Start testen: Startmenue -> "XeisWorks Office - Debug" (sichtbare Konsole, gleiches
    Dateilog).
11. "XeisWorks Office" im Startmenue per Rechtsklick -> "An Taskleiste anheften" anheften.

Alternativer Direktstart ohne Verknuepfung (z. B. fuer Codex/Claude Code):
- Normaler Start: `.venv\\Scripts\\pythonw.exe scripts\\xw_office_gui.pyw`
- Diagnose-Start mit sichtbarer Konsole: `run_xw_office_debug.cmd`
- Reines Modul (aequivalent zum Debug-Start, ohne Fehlerdialog-Wrapper): `python -m xw_office`

## 3) Pflichtvariablen (.env oder Secret-Store)

- `DATABASE_URL`
- `FERNET_MASTER_KEY`
- `SEVDESK_API_TOKEN`
- optional je nach Modul:
  - `WIX_API_KEY`, `WIX_SITE_ID`, `WIX_ACCOUNT_ID`
  - `CLICKUP_API_TOKEN`
  - `FON_TEILNEHMER_ID`, `FON_BENUTZER_ID`, `FON_PIN`

Hinweis:
- Tokens bevorzugt ueber Settings in die verschluesselte DB-Verwaltung pflegen.
- Keine Secrets ins Repo committen.

### UVA-Berechnung und Datenfrische

- Die Live-Berechnung zeigt Arbeitsphasen, die Anzahl der sevDesk-Abfragen und die
  bisherige Laufzeit. Der Balken zeigt waehrend der Live-Berechnung Aktivitaet
  ohne vorgetaeuschten Prozentanteil; kein automatisches Hochzaehlen bis 90 %.
- UVA und ZM verwenden identische erfolgreiche sevDesk-Abfragen innerhalb eines
  Berechnungslaufs gemeinsam. Unterschiedliche Filter bleiben getrennt; UVA-IST-
  und ZM-Soll-Auswahl sowie steuerliche Pruefungen bleiben erhalten.
- Detaildaten werden nur fuer diesen Lauf wiederverwendet. Eine Live-Neuberechnung
  leert auch die internen Zahlungs-, Positions-, TaxSet- und Kontakt-Caches.
  "Neu laden" umgeht weiterhin den fertigen Monatscache und den Monats-Snapshot.
- Kontakt-Details werden fuer die ZM erst geladen, nachdem der Beleg nach Datum,
  Status und steuerlichen Fakten als ZM-relevant ausgewaehlt wurde.
- Das Ergebnis nennt Laufzeit und wiederverwendete Abfragen. Phasenlaufzeiten und
  Abfragezaehler stehen im Anwendungslog, ohne Tokens oder Beleginhalte.
  Die Zaehler erfassen logische GET-Abfragen, nicht einzelne HTTP-Retry-Versuche.
- Die vorhandene Begrenzung auf zwei sevDesk-Anfragen pro Sekunde bleibt bestehen.
  Insbesondere aeltere Rechnungen mit Zahlungen im UVA-Monat werden nicht zugunsten
  kuerzerer Laufzeiten ausgeschlossen.
- Die Aktualisierungsabfragen fuer vergangene Monate reichen mindestens bis zum
  heutigen Tag. Spaeter erfasste oder korrigierte Belege werden anschliessend anhand
  ihrer steuerlich massgeblichen Periode ausgewaehlt, nicht anhand des Aktualisierungsdatums.
- Der abschliessende Live-Prueflauf fuer September 2026 dauerte 260,820 Sekunden
  statt der urspruenglich gemeldeten 496,226 Sekunden (rund 47,4 % kuerzer).
  Er benoetigte 492 Quellabfragen und verwendete 12 identische Abfragen wieder.
  Die XML-Datei bestand die offizielle Schema-Pruefung; es wurde nichts eingereicht.
  Laufzeiten bleiben vom API-/Netzwerkzustand und dem Datenumfang abhaengig.

### UVA-Ergebnis und fachliche Grenzen

- Mehrwertsteuer und Vorsteuer erscheinen als kompakte Gruppensummen mit Brutto,
  Netto und Steuer. Auch auslaendische Steuergruppen bleiben sichtbar; ihre Anzeige
  bedeutet nicht, dass diese Betraege als oesterreichische Vorsteuer abgezogen werden.
  Zahllast und Abgabestatus bleiben unmittelbar sichtbar.
- Hinweise sind zusammengefasst; Datenqualitaet, technische Details
  und FinanzOnline-Kennzahlen sind bei Bedarf aufklappbar. Fachliche Abgabesperren
  werden nicht versteckt oder durch das Einklappen aufgehoben.
- Es gibt keinen Golden-Master-/Referenzwert-Abgleich und keine daraus abgeleitete
  Abgabesperre mehr. Monats-Snapshots bleiben ein Datenfrische-/Leistungsmechanismus;
  aeltere Berechnungsversionen werden nicht wiederverwendet. Externe Vergleichsbilder
  werden weder als Referenz gespeichert noch zur Anpassung von Kennzahlen verwendet.
- Zahlungszuordnungen und Banktransaktionen sind unterschiedliche Datensaetze:
  Eine zugeordnete Zahlung wird nicht nochmals ueber ihre Banktransaktion erfasst.
  Mehrere unterschiedliche Zuordnungen derselben Transaktion bleiben erhalten.
  Vollstaendige, datierte Zuordnungen ersparen den zweiten Abruf nur, wenn sie mit
  dem kumulativ bezahlten Belegbetrag uebereinstimmen.
  Die vollstaendige Zuordnungshistorie wird einmal gebuendelt und seitenweise
  gelesen, statt fuer jeden Beleg erneut angefordert. Bei nachweislich vollstaendiger
  Historie bedeutet ein fehlender Beleg, dass keine Zuordnungslogs existieren; ein
  zusaetzlicher Abruf dieser leeren Liste entfaellt. Ist die Historie unvollstaendig
  oder nicht verfuegbar, werden die Zahlungsnachweise einzeln geprueft.
  Ein rohes `paidAmount=0` bei manuell vollstaendig bezahlten Belegen mit Zahlungsdatum
  bedeutet nicht automatisch Nullumsatz. Dagegen schliesst ein aus Zahlungsnachweisen
  abgeleiteter Periodenbetrag von null den Beleg fuer diesen Zahlungsmonat aus.
  Ueberzahlungen werden chronologisch auf den Belegbetrag begrenzt und als Hinweis
  ausgewiesen; dieselbe Rechnung wird dadurch nicht erneut versteuert.
- Teilzahlungen werden mit ungerundetem Verhaeltnis aufgeteilt und erst beim
  Geldbetrag auf Cent gerundet. Rabattbereinigte Accounting-Summen und explizite
  Nullbetraege (z. B. kostenloser Versand) sind verbindlich. Bei einer Steuergruppe
  werden passende Belegsummen statt kumulierter Positions-Rundungsdifferenzen benutzt.
- Fehlende/unlesbare Zahlungsnachweise, unvollstaendige API-Seiten und ungueltige
  Geldbetraege duerfen nicht als erfolgreiche Nullberechnung durchgehen.
  Ungeklaerte Steuerzuordnungen und erhebliche Netto-/Steuerdifferenzen verhindern
  die UVA-Abgabe. Eine reine Bruttodifferenz, z. B. Trinkgeld, wird separat angezeigt.
- Negative Bemessungsgrundlagen werden nicht still aus der XML-Datei weggelassen:
  Sie erfordern eine fachliche Berichtigung. Eine ausdruecklich angegebene
  Umsatzsteuerberichtigung KZ090 wird mit Vorzeichen exportiert. Die Software leitet
  solche Berichtigungen nicht eigenmaechtig aus negativen Nettosummen ab.
- Ausgehende B2B-Auslandsleistungen mit auslaendischer Empfaenger-UID (z. B.
  Werbe-/YouTube-Erloese an einen EU-Unternehmer) sind keine inlaendischen
  Reverse-Charge-Umsaetze der KZ021. Sie bleiben in der Anzeige sichtbar, werden
  aber nicht in KZ000/KZ021 aufgenommen. EU-relevante Erloesbelege werden auch
  dann in der ZM nach Belegdatum erfasst, wenn sie als Einnahmen-Voucher statt
  als Rechnung angelegt wurden. Ein fehlendes Empfaengerland wird nicht geraten.
- Eingehender Reverse Charge richtet sich nach dem Leistungsdatum, nicht nach dem
  Zahlungsmonat; innergemeinschaftliche Erwerbe nach Rechnungsstellung, fruehestens
  Erwerb und spaetestens dem 15. des Folgemonats. Teilzahlungen kuerzen diese
  Bemessungsgrundlagen nicht. Fehlt ein separates Leistungsdatum, gilt das Belegdatum
  entsprechend der bestaetigten Buchungspraxis als Leistungsdatum.
  Monatsuebergreifende RC-Vorauszahlungen mit ungeklaerter Steuerperiode sperren die Abgabe.
  Bei normalen inlaendischen Vorauszahlungen wird Vorsteuer erst bei vorliegender
  Rechnung und Zahlung beruecksichtigt; eine vorherige Zahlung geht nicht verloren.
- Eine lieferantenseitig steuerfreie EU-Warenlieferung hat weiterhin 0 % Lieferantensteuer.
  Fuer den oesterreichischen Erwerb wird der hier bestaetigte inlaendische Satz von
  20 % mit korrespondierendem Vorsteuerabzug angesetzt. Das ist keine nachtraegliche
  Besteuerung der Lieferantenrechnung, sondern die oesterreichische Erwerbsbesteuerung.
- Die vereinfachte Zuordnung fuer innergemeinschaftliche Erwerbe und eingehenden
  Reverse Charge setzt derzeit 20 % und vollen Vorsteuerabzug voraus. Sonderfaelle
  (einschliesslich abweichender Leistungsortregeln) muessen fachlich geprueft werden; ein
  fehlerfreier Testlauf ersetzt keine steuerliche Pruefung der Belegklassifikation.

Fachliche Quellen: [BMF-Umsatzsteuervoranmeldung](https://www.bmf.gv.at/themen/steuern/fuer-unternehmen/umsatzsteuer/informationen/umsatzsteuervoranmeldung.html),
[BMF-Entgeltaenderungen und Berichtigungskennzahlen](https://www.bmf.gv.at/dam/jcr:ca70136e-2995-41e6-8936-ca23e7582b01/Entgeltsaenderungen_in_der_Umsatzsteuervoranmeldung.pdf).
Fuer Leistungsort, Vorsteuer-Zahlungserfordernis und Steuerperiode siehe
[UStG 1994, insbesondere Paragraphen 3a, 12 und 19](https://www.ris.bka.gv.at/GeltendeFassung.wxe?Abfrage=Bundesnormen&Gesetzesnummer=10004873),
[USP/BMF Reverse Charge](https://www.usp.gv.at/themen/steuern-finanzen/umsatzsteuer-ueberblick/weitere-informationen-zur-umsatzsteuer/umsaetze-mit-auslandsbezug/reverse-charge.html)
und [USP/BMF innergemeinschaftlicher Erwerb](https://www.usp.gv.at/themen/steuern-finanzen/umsatzsteuer-ueberblick/weitere-informationen-zur-umsatzsteuer/umsaetze-mit-auslandsbezug/innergemeinschaftlicher-erwerb.html).
Der IST-Vorsteuerabzug verwendet den zahlungsabhaengigen Regelfall des Paragraphen 12;
Ueberrechnungen und die gesetzlichen Ausnahmen (u. a. Vorjahresumsatz ueber
2 Mio. EUR) sind nicht automatisch aus sevDesk ableitbar und beduerfen gesonderter Pruefung.
Die XML-Struktur wird gegen das mitgelieferte offizielle U30-Schema validiert.

### EU-OSS: Quartale, Anzeige und Export

- Im Untermenue Steuern stehen nur UVA und EU-OSS als hervorgehobene obere Tabs.
  Der fruehere Ausgaben-Tab ist entfernt; die eigenstaendige Ausgabenpruefung bleibt erhalten.
- Die Quartalsauswahl zeigt Q1 bis Q4 mit Monatsnamen in einer ausreichend breiten
  Liste. Standard ist das zuletzt abgeschlossene Quartal. Die Ansicht zeigt Steuer,
  Brutto und Netto je Land, Satz und Waren-/Leistungsart. Hinweise, Beleglisten und
  technische Details sind eingeklappt; Exportblocker bleiben unmittelbar sichtbar.
- EU-OSS verwendet das Liefer-/Leistungsquartal, nicht den Zahlungsmonat.
  Wenn ein separates Leistungsdatum fehlt, wird das Rechnungsdatum verwendet.
  Diese Ersatzannahme und die standardmaessige Warenklassifikation muessen fuer
  abweichende Buchungsfaelle geprueft werden. Plattform-Sonderregeln sind nicht automatisch
  umgesetzt. Der sevDesk-Abruf umfasst zusaetzlich 45 Tage vor und 10 Tage nach dem
  Quartal; Rechnungen weit ausserhalb dieses Fensters mit abweichendem Leistungsdatum
  benoetigen eine gesonderte Vollstaendigkeitspruefung.
- Live-Neuberechnungen leeren Positions-Caches. Alte Berechnungs-Snapshots werden
  nach der Versionsaenderung nicht wiederverwendet. Beleg-/Positionslisten werden
  vollstaendig paginiert; Seitenbegrenzung, unlesbare Betraege und fehlgeschlagene
  API-Abrufe duerfen keine scheinbar erfolgreiche Nullberechnung erzeugen.
- Rabattbereinigte Accounting-Betraege und explizite Nullbetraege sind verbindlich.
  Gemischte Steuersaetze werden nach Positionen getrennt, auch wenn der Rechnungskopf
  nur einen Satz nennt. Land-/Steuerkonflikte, unbekannte Auslandsregeln und erhebliche
  Netto-/Steuerdifferenzen sperren den XML-Export statt Umsaetze still wegzulassen.
- Positionsdetails fuer Belege ausserhalb des Lieferquartals, Entwuerfe und eindeutig
  ausgeschlossene Reverse-Charge-/IG-/Export-Belege werden nicht unnoetig geladen.
  Die bestehende API-Ratenbegrenzung bleibt erhalten.
- Der Q3/2026-Live-Prueflauf sank von 357,165 auf 193,403 Sekunden (rund 45,9 %).
  711 Belege wurden geladen und nach Lieferquartal geprueft; der abschliessende Lauf
  benoetigte 386 GET-Abrufe. Die portalbezogene XML-Strukturpruefung und ein Replay
  derselben Quellen bestaetigten die Berechnung. Es wurde keine Meldung abgegeben
  und beim Prueflauf kein Quartals-Snapshot ersetzt.
- Gutschriften werden sichtbar gemacht und sperren den vereinfachten XML-Export
  bis zur fachlichen Pruefung. Berichtigungen bereits gemeldeter Zeitraeume gehoeren
  im Portal in den Bereich "Korrektur frueherer Zeitraeume", nicht ungeprueft als
  negativer aktueller Umsatz in eine gewoehnliche Steuerzeile.
- Das XML ist fuer den manuellen Upload im EU-OSS-Portal bestimmt, nicht fuer einen
  automatischen FinanzOnline-Webservice. Die lokale Strukturpruefung ist kein
  Nachweis einer erfolgreichen Portalannahme. Nullmeldungen und nicht exportierbare
  0%-Zeilen werden ausdruecklich fuer die manuelle Portalbearbeitung ausgewiesen.
  Vergleichsbilder werden nicht als Referenzkonfiguration gespeichert.

Fachliche Quelle:
[USP/BMF: Erklaerung und Zahlung im EU-OSS](https://www.usp.gv.at/themen/steuern-finanzen/umsatzsteuer-ueberblick/weitere-informationen-zur-umsatzsteuer/umsaetze-mit-auslandsbezug/Umsatzsteuer-One-Stop-Shop/EU-OSS/Erklaerung-und-Zahlung-im-EU-OSS.html)
(Quartalsabgrenzung, Vorauszahlungen und Korrekturen frueherer Zeitraeume).

## 4) Betrieb auf mehreren PCs

- Betriebsdaten werden zentral in PostgreSQL synchronisiert.
- `origin/main` ist der einzige verbindliche gemeinsame Code-Stand aller PCs.
- Jeder PC wird dauerhaft auf dem lokalen Branch `main` betrieben; dessen Upstream ist
  `origin/main`.
- Temporaere Arbeitsbranches wie `agent/*` muessen nach Abschluss in `main` integriert werden
  und duerfen nicht als dauerhafter Betriebsstand eines PCs verbleiben.
- Code-Updates laufen ueber einen automatischen, lautlosen Check vor dem normalen Start (siehe
  Abschnitt 5): nur bei sauberem Arbeitsbaum, Branch `main`/Upstream `origin/main` und
  tatsaechlich vorhandenem Update erscheint eine Ja/Nein-Rueckfrage; sonst startet die App
  unveraendert weiter. Der Alltagsstart wird dadurch nie laenger als um ein kurzes
  Netzwerk-Timeout verzoegert und haengt nie zwingend von GitHub ab.

Normaler Betrieb pro PC:
- Alltagsstart ueber die Startmenue-/Taskleisten-Verknuepfung "XeisWorks Office" (fensterlos,
  `pythonw.exe`).
- Diagnose/Live-Debugging durch Entwickler, Codex oder Claude Code ueber
  "XeisWorks Office - Debug" (sichtbare Konsole, gleiches Dateilog).
- Alle Betriebsregeln (Rechnungslogs, Log-Pfade) sind unabhaengig vom gewaehlten Start identisch,
  da beide Wege in dieselbe `logs\xw_office.log` schreiben.

Empfehlung Rollenmodell:
- 1 Druck-PC: stabile Druckerzuordnung, Noten-/Rechnungsdruck.
- 1-2 Office-PCs: Rechnungen, CRM, Steuern, Produktpflege.

## 5) Update-Routine

- Normalfall: beim Start ueber "XeisWorks Office" prueft die App selbst lautlos, ob ein Update
  vorliegt, und fragt per Dialog nach ("Jetzt aktualisieren?" / "Nein"). Kein separater Schritt
  noetig.
- Vor Schichtbeginn zusaetzlich sinnvoll:
  - DB-Status in Einstellungen kurz pruefen.
  - Druckerampel pruefen (Druck-PC).
- Manuell/administrativ jederzeit direkt aufrufbar (z. B. um ohne App-Start zu aktualisieren):
  `powershell -NoProfile -ExecutionPolicy Bypass -File scripts\update_xw_office.ps1`.
- Auf einem PC, der nie automatisch geprueft werden soll (z. B. bewusst pinned Version), vor dem
  Start `XW_OFFICE_SKIP_UPDATE_CHECK=1` setzen.

Der Update-Schritt (`scripts\update_xw_office.ps1`), automatisch wie manuell gleich:
1. Bricht ab, wenn XW-Office noch laeuft, lokale Aenderungen offen sind, der Branch nicht `main`
   ist oder der Upstream nicht `origin/main` ist. In keinem dieser Faelle wird automatisch
   gemergt, gestasht oder verworfen.
2. `git fetch origin main`, danach ausschliesslich `git pull --ff-only origin main`.
3. Installiert Abhaengigkeiten neu, wenn sich `pyproject.toml` geaendert hat.
4. Meldet geaenderte Datenbankmigrationen nur, fuehrt sie aber nicht automatisch aus (siehe unten).
5. Fuehrt einen kurzen Smoke-Preflight (Modul-Import) aus.
6. Protokolliert Alt-/Neu-Commit und Ergebnis in `logs\xw_office_update.log`.

Manuelle Aktualisierung (Fallback, z. B. wenn PowerShell-Skripte gesperrt sind):
1. App schliessen.
2. Sicherstellen, dass keine lokalen Aenderungen offen sind: `git status --short`
3. Auf den gemeinsamen Branch wechseln: `git switch main`
4. Ausschliesslich als Fast-Forward aktualisieren: `git pull --ff-only origin main`
5. `.venv\\Scripts\\python.exe -m pip install -e ".[dev]"`
6. `alembic upgrade head`
7. App neu starten.

Einrichtung bzw. Reparatur des Upstreams pro PC:
- `git branch --set-upstream-to=origin/main main`
- Kontrolle: `git status --short --branch` muss `main...origin/main` anzeigen.

Datenbankmigrationen (`alembic upgrade head`):
- Nicht unkoordiniert auf mehreren PCs gleichzeitig ausfuehren.
- Bevorzugt einmalig und bewusst von einem festgelegten Admin-/Entwicklungs-PC ausfuehren.
- Der Update-Schritt oben meldet neue Migrationsdateien nur, fuehrt sie aber nicht selbst aus.

## 6) Backup und Wiederherstellung

- Primaer-Backup: Railway PostgreSQL Snapshots/Backups.
- Sekundaer: regelmaessiger SQL-Dump.
- Wiederherstellungstest mindestens monatlich.

## 7) Logs und Diagnose (Codex/Claude Code)

Alle Logs liegen unter `<repo>\logs\`, unabhaengig davon, ob normal (fensterlos) oder per
Debug-Start gestartet wurde:

- `xw_office.log` — laufendes Anwendungslog (Rotating, Standard 8 MB x 8 Backups; ueber
  `XW_OFFICE_LOG_MAX_BYTES`/`XW_OFFICE_LOG_BACKUP_COUNT` anpassbar).
- `xw_office_bootstrap.log` — nur bei Fehlern vor dem eigentlichen App-Start (z. B. defektes
  `.venv`, Importfehler), geschrieben vom GUI-Bootstrap.
- `xw_office_crash.log` — harte Python-Abstuerze (`faulthandler`).
- `xw_office_update.log` — Ergebnis jedes Laufs von `scripts\update_xw_office.ps1`.

Log-Level fuer eine Session erhoehen: `XW_OFFICE_LOG_LEVEL=DEBUG` vor dem Start setzen (z. B. in
der Konsole vor `run_xw_office_debug.cmd`). Secrets/Tokens werden vor dem Schreiben ins Log
redigiert.

## 8) Stoerungsbehebung

- Symptom: kein Sync / keine Daten.
  - `DATABASE_URL` pruefen.
  - In Settings Verbindung testen.
- Symptom: Token-bezogene API-Fehler.
  - Secret-Eintraege in Settings pruefen.
- Symptom: Druck nicht verfuegbar.
  - Druckerampel / konfigurierte Druckernamen pruefen.

## 9) Wartungscheckliste (monatlich)

- `pytest tests/`
- `ruff check src/`
- `alembic current` gegen `head` pruefen
- Drucktest mit Rechnungs- und Noten-PDF
- Start-Preflight mit Testdaten verifizieren
