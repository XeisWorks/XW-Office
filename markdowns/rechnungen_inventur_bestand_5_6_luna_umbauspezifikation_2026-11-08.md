# Inventur, Rechnungsabgang und Lagerwarnung – Umbauspezifikation für Codex 5.6 Luna

- **Stand:** 8. November 2026
- **Repository:** `XeisWorks/XW-Office`
- **Codebasis bei der Analyse:** `main` / `2684773`
- **Status:** fachliche Umsetzung weitgehend integriert und vollständig getestet; Produktionsdaten-/Deployment-Gates noch offen
- **Arbeitsplan:** [rechnungen_inventur_bestand_5_6_luna_task_queue_2026-11-08.yaml](rechnungen_inventur_bestand_5_6_luna_task_queue_2026-11-08.yaml)

## Implementierungsfortschritt

- Aktueller Zwischenstand: Der Freigabe-Buchungskern verarbeitet physische Rechnungspositionen idempotent; eindeutig referenzierte Gutschriften werden als begrenzte Gegenbewegungen ebenfalls idempotent gebucht. Die SevDesk-Gegenbeleg-Feedverdrahtung läuft über `xw-inventory-worker`; unklare Fälle bleiben als `needs_review` sichtbar.
- Eine geführte Product-Hub-Inventur ist als `InventoryCountService` mit persistierter Zählliste, Differenzvorschau, Stichtags-Snapshot und idempotenter `recount`-Buchung umgesetzt. Die geschützte API unterstützt Start, Zeilenerfassung und Abschluss; bestätigte Inventuren sind unveränderlich.
- Die bestehende `PieceBlock`-Druckentscheidung berücksichtigt nun den Artikeltyp: POD nutzt Lagerstücke und druckt Fehlmengen in Chargen von drei; Druckerei-Noten werden bei Unterdeckung als Nachbestellung markiert und nicht lokal gedruckt. Sammelaggregation und bestätigte `print_run`-Buchungen laufen über denselben lagerbereinigten Plan.
- Das offene RECHNUNGEN-Printfeld verwendet diese Policy nun auch beim Einzel- und Sammeldruck: Lagerbestand wird zuerst berücksichtigt, POD-Fehlmengen werden chargenweise ermittelt, und Druckerei-Unterdeckung deaktiviert den lokalen Druckknopf zugunsten eines Nachbestellhinweises.
- Bestätigte Sammeldruckläufe werden jetzt als `print_run` mit stabilem Idempotenzschlüssel in die Shadow-Spiegelung gegeben; die bisherige absolute Bestandskorrektur wird für diesen Pfad nicht mehr verwendet.
- Das offene Printfeld bevorzugt für die Druckentscheidung den zentralen Hub-Istbestand und fällt nur bei nicht verfügbarem Hub auf den sevDesk-Cache zurück.
- Der offene Rechnungsdruck zeigt jetzt pro aggregierter SKU bestellt, aus Lager, neu drucken und die Disposition; POD-Bedarfe werden sequenziell geplant, sodass Restbestand nicht doppelt zugeteilt wird.
- Für nicht angereicherte Legacy-Print-Aggregate bleibt der Einzel-/Sammeldruck rückwärtskompatibel; sobald der Bestandsplan einen Istbestand liefert, gilt ausschließlich die neue Lager-/POD-Policy.
- Das Alarm-Popup zeigt zusätzlich Forecast-Modus und automatischen Vorschlag; manuelle Schwellen werden als `fixed` gespeichert, und „Automatik verwenden“ setzt den Forecast wieder aktiv.
- Ein `InventoryForecastRefreshService` aggregiert finale sevDesk-Rechnungen und Gutschriften für alle aktiven physischen Varianten und persistiert den Drei-Monats-Wert. Der read-only Monatsadapter, `POST /api/v1/inventory/forecast/refresh` und das Railway-Cron-CLI `xw-inventory-forecast-refresh` sind verdrahtet; die eigentliche Cron-Zeitplanung bleibt deploymentseitig.
- Für P07 gibt es jetzt einen persistierten `InventoryAlertTaskService` mit Duplikatschutz und Graph-Mail-Inhalt sowie ein RECHNUNGEN-LAGERALARME-Popup. Dort lassen sich Ist-/Alarmbestand und Forecastdaten prüfen, die Schwelle speichern und per „Task erzeugen“ an `todo@xeisworks.at` senden.
- Die Task-Erzeugung sperrt den Alarm und die bestehende Task-Zeile transaktional, sodass parallele Klicks unter PostgreSQL nicht zu doppelten Mails führen.
- Ein read-only `sevdesk_history_audit` prüft finale sevDesk-Rechnungen und Gutschriften über 60 vollständige Monate, ignoriert Entwürfe und meldet fehlende SKU sowie unvollständige Abdeckung. `xw-inventory-worker` führt Forecast-Refresh und externen sevDesk-Abgleich regelmäßig und idempotent aus; nur die Railway-Service-Aktivierung ist noch extern.
- Der Rechnungs-Freigabepfad prüft physische Product-Hub-SKUs jetzt vor dem sevDesk-Freigabeschritt; erst nach erfolgreicher Freigabe wird die idempotente Bestandsbewegung angewandt. Damit werden unauflösbare Positionen nicht mehr erst nach einer externen Freigabe sichtbar.
- Ein `SevdeskInvoiceInventoryPoller` nutzt für externe finale sevDesk-Rechnungen denselben idempotenten Dokument-/Positionsschlüssel; Entwürfe werden ignoriert und unklare Positionen landen in einer sichtbaren Prüfliste.
- START verbraucht den Legacy-Bestand weiterhin für den Übergang, überspringt bei aktivem Freigabe-Buchungskern aber die Legacy→Hub-Verbrauchsspiegelung. Damit erzeugen Freigabe und nachgelagerter START-Lauf keinen doppelten Hub-Abgang.
- Für Gegenbelege steht ein konservativer `SevdeskCreditNoteInventoryService` bereit: automatische Rückbuchung erfolgt nur bei expliziter Ursprungsrechnung und Ursprungsposition; unklare Geld-/Positionsbelege werden als `needs_review` gemeldet.
- Der bestehende Monatsfeed ist jetzt über `SevdeskHistoryProviderAdapter` als Produktionsquelle für Forecast und externen Abgleich nutzbar; `xw-inventory-sync` bucht finale externe Rechnungen/Gutschriften idempotent und beendet sich bei Klärfällen bewusst mit Fehlerstatus.
- `InventoryV2Service.refresh_reorder_point` kann den Drei-Monats-Forecast bzw. den SKU-Fixwert persistieren und die Warnung sofort neu bewerten; der regelmäßige Historien-Worker ist als `xw-inventory-worker` vorhanden und die Alarmanzeige zeigt Forecast-Mittelwert/Fenster.
- Der Lagerbestand speichert neben dem aktiven Alarmbestand jetzt auch den automatischen Forecast und den Modus `auto`/`fixed`, damit ein Fixwert den Vorschlag nicht verdeckt.
- Die Forecast-Provenienz (Nettoabsatz, volle Verkaufsmonate, Datenfenster, Datenqualität und letzter Refresh) wird in `inventory_stock` persistiert und im Alarm-Popup sowie in der Task-Mail verwendet.
- Die Hub-Ledgerbuchung sperrt Lagerort und Bestandszeile transaktional, revalidiert den Idempotenzschlüssel nach dem Lock und rollt bei einem konkurrierenden Unique-Key-Sieg die Zwischenänderung zurück.
- Die Cutover-Readiness nimmt nun den read-only Bestandsquellen-Audit und direkte Legacy-/Hub-Mengenabweichungen als eigene Gates auf; der Master bleibt bis zu den manuellen Betriebsnachweisen absichtlich deaktiviert.
- Gesamtprüfung am 8. November 2026: `python -m pytest -q` → **1.964 bestanden**; `python -m alembic heads/current` → `035_inventory_forecast_metadata` (Head). `main` ist sauber zu `origin/main` gepusht.

- **P00 – Live-Datenvertrag und Bestandsquellen:** begonnen und erster lesender Audit-Baustein umgesetzt in `services/product_hub/inventory_audit.py`; keine Bestands- oder sevDesk-Schreibzugriffe.
- Der Audit meldet doppelte SKU, fehlende physische sevDesk-Part-Mappings, negative oder fehlende Quellbestände, Legacy-/Hub-Drift und fehlendes Verkaufsstartdatum. Der Live-DB-Snapshot ist jetzt als read-only `InventoryV2Service.audit_inventory_sources()` und `GET /api/v1/inventory/audit` verfügbar; vier Audit-Tests laufen grün.
- Als gemeinsame Grundlage für P05 ist `services/product_hub/inventory_forecast.py` ergänzt: vollständige Kalendermonate, 60-Monats-Fenster, Nettoverkauf minus Gutschriften, Startwert 50 bis sechs volle Verkaufsmonate und manueller Fixwert sind deterministisch testbar.
- Als gemeinsame Grundlage für P01/P06 ist `services/product_hub/inventory_policy.py` ergänzt: digitale Artikel bewegen keinen Bestand, Druckerei-Noten melden Fehlmengen als Nachbestellung und POD druckt fehlende Mengen in Dreierchargen nach Lagerverbrauch.
- Der Legacy-/Hub-Katalog kann die Artikelart `external_print`, `pod` oder `digital` nun explizit mitführen; unbekannte Werte fallen kontrolliert auf `external_print` zurück. Die bestehende Drucklogik ist damit rückwärtskompatibel vorbereitet, aber noch nicht vollständig auf den neuen Plan verdrahtet.
- Der Hub-Schwellenpfad bewertet den aktuellen Bestand jetzt sofort nach einer Schwellenänderung und öffnet bzw. löst Warnungen ohne erfundene Bewegungsbuchung auf. API- und Servicetests decken die Erhöhung und Senkung der Schwelle ab.
- Für P03 ist `inventory_document_booking` ergänzt: je Dokument, exakter Position und Bewegungsart wird die bereits angewandte kumulative Menge persistiert. Wiederholte Freigabe-/Polling-Aufrufe buchen damit 0 Differenz; Mengenänderungen und Rückbuchungen wenden nur die Differenz an. Migration und 2 Integrationsfälle sind enthalten.
- Der Freigabeweg kann den Buchungskern nun optional aus dem Bootstrap verwenden: Nach erfolgreicher physischer sevDesk-Freigabe werden normalisierte Produktpositionen gegen exakte Hub-Varianten aufgelöst und über die Buchungsmarke gebucht. Digitale Positionen bleiben ohne Bewegung; fehlende physische Varianten werden als Fehler sichtbar.
- **Verbleibende Betriebs-Gates:** Railway-Cron-Zeitplan und sevDesk-/Graph-Produktionszugänge müssen in der Zielumgebung aktiviert werden; die echte Inventur, ein repräsentativer Shadow-Lauf, Projektionstests, Backup und Rollback-Probe sind bewusst nicht automatisierbar und blockieren den Product-Hub-Master-Cutover.

## 1. Verbindliche Fachentscheidungen

1. Der gezählte Bestand gedruckter Noten wird bei einer bevorstehenden Inventur je eindeutiger SKU/Variante festgelegt. Der Product Hub (PostgreSQL) bleibt der geplante, endgültige Bestands-Master. Während der Übergangsphase bleibt `inventory.stock_levels` operative Quelle und wird in den Hub gespiegelt; sevDesk dient dem Abgleich. Nach dem Cutover gibt es keine zweite unabhängige Bestandswahrheit.
2. Der Verkauf einer physischen Note reduziert den Bestand **genau einmal bei endgültiger Freigabe der sevDesk-Rechnung**. Ein Entwurf (Status 100), das bloße Öffnen einer Rechnung, E-Mail-Versand, Zahlung und späteres Wix-Fulfillment buchen keinen zweiten Abgang. Das gilt für Wix-basierte, manuell angelegte und außerhalb von XW-Office freigegebene sevDesk-Rechnungen.
3. Bei Storno oder Gutschrift wird die eindeutig betroffene Stückzahl **automatisch** zurückgebucht; bei Teilgutschrift nur deren eindeutig zugeordnete Menge. Diese Regel gilt ausdrücklich auch ohne gesonderte Bestätigung einer physischen Rückkehr ins Lager. Unklare, rein wertmäßige Gegenbelege dürfen keine erfundene Stückzahl erzeugen und gehen in eine sichtbare Klärliste. Beschädigung/fehlende Rücksendung wird danach als eigene, begründete Korrektur gebucht.
4. Für in der Druckerei hergestellte Noten ist der Alarmbestand standardmäßig dynamisch: erwarteter Nettoabsatz der nächsten drei Monate, berechnet aus bis zu fünf Jahren endgültiger sevDesk-Rechnungspositionen. Ein manueller **Fixwert je SKU/Variante** kann den automatischen Wert ersetzen; der berechnete Vorschlag bleibt sichtbar.
5. Neue Druckerei-Noten behalten **50 Stück Alarmbestand**, bis sechs **volle Verkaufsmonate** vorliegen. Danach übernimmt der berechnete Drei-Monats-Wert. Ein vollständig verkaufsfähiger Monat ohne Absatz zählt als Nullmonat. Beginn der Verkaufbarkeit muss aus einem verlässlichen Produktdatum oder einer bestätigten manuellen Angabe stammen; fehlt beides, bleibt der Startwert aktiv und die Datenlücke sichtbar.
6. Print-on-Demand (POD) bedeutet unbegrenzte *Herstellbarkeit*, nicht unbegrenzten *Ist-Bestand*. Bei fehlendem verfügbarem Stück wird standardmäßig **drei Exemplare** gedruckt. Beispiel: 0 Stück, 1 Verkauf → bestätigter Druck `+3`, Rechnungsabgang `-1`, danach 2 Stück; die nächsten zwei Einzelverkäufe verwenden das Lager. Bei größerem gleichzeitigem Bedarf wird in Dreierchargen aufgerundet. Der Standard ist künftig je Variante konfigurierbar.
7. In `RECHNUNGEN` erscheint ein Alarm-Button mit Anzahl betroffener Produkte. Sein Popup zeigt Produkt, SKU, Ist- und Alarmbestand sowie Berechnungsgrundlage; dort lässt sich der Alarmbestand ändern und per **„Task erzeugen“** eine Microsoft-Graph-Mail an `todo@xeisworks.at` senden. Der Versand erfolgt erst nach Klick und mit Duplikatschutz.

**Schwellenrichtung:** Ein höherer Alarmbestand macht einen Alarm wahrscheinlicher. Ein bestehender Alarm verschwindet automatisch, wenn der Ist-Bestand wieder **größer** als die aktive Schwelle ist oder die Schwelle unter den Ist-Bestand gesenkt wird. Das Popup darf eine Erhöhung der Schwelle nicht als Löschung darstellen. Gleichstand `Ist <= Schwelle` löst einen Alarm aus.

## 2. Nachgewiesener Code-Stand und Lücken

| Bereich | Vorhanden | Fehlt bzw. ist riskant |
| --- | --- | --- |
| Product Hub | `inventory_stock`, append-only `product_hub_inventory_movement`, `inventory_alert`, APIs für Bestand/Bewegungen/Schwellen und Cutover-Prüfung | Der Hub ist noch nicht operativer Master; Projektionsadapter und Cutover-Gates fehlen. |
| Legacy-Inventur | `InventoryService.apply_stock_correction()` und Desktop-Aktion „Retoure / Inventur“ für eine SKU | Kein geführter Inventurlauf mit Zählliste, vollständigem SKU-Abgleich und Abschluss. |
| Rechnung | `build_inventory_requirements()` berücksichtigt Wix- und manuelle sevDesk-Positionen; START spiegelt einige Bewegungen in den Hub | Kein zentraler, pro Rechnung idempotenter Freigabe-Handler. START bucht Verbrauch gesammelt **nach** dem Rechnungsbatch; bei Teilfehlern unterbleibt er auch für erfolgreiche Rechnungen. Rechnungen außerhalb von START werden nicht vollständig erfasst. |
| Warnung | `reorder_point`, Alarmzeilen und Warnungs-Outbox | Nur Schwellenübertritt nach Bewegung; Änderung der Schwelle und bereits niedriger Inventur-Startbestand werden nicht zuverlässig neu bewertet. Kein RECHNUNGEN-Popup, keine Absatzprognose, keine versendete Task-Mail. |
| Produktdruck | Druckpläne, sevDesk-Part-Bestand, lokaler Shadow-Abgleich | `PRINT PRODUKTE OFFEN` verwendet bestellte Stückzahlen direkt als Druckmenge. Die Liste enthält keinen lagerbereinigten Druckplan. `stockEnabled=false` kann im Legacy-Katalog „digital/∞“ bedeuten und POD fälschlich vom Druck ausschließen. |

Relevante Einstiegspunkte: `src/xw_office/services/inventory/service.py`, `services/product_hub/inventory.py`, `repositories/product_hub_inventory.py`, `services/invoice_processing/service.py`, `services/products/print_decision.py`, `ui/modules/rechnungen/open_invoice_overview.py`, `ui/modules/rechnungen/view.py`, `ui/modules/rechnungen/tagesgeschaeft_view.py`, `ui/modules/products/view.py`, `services/mailing/service.py`. Aktueller Cutover-Stand: `docs/product_hub/PROGRESS.md`. Die Spezifikation für manuelle sevDesk-Entwürfe vom 6. November 2026 bleibt für deren Rechnungs-/Druckkontext maßgeblich.

Die Analyse prüfte Code und Dokumentation, **keine** tatsächlichen Lagerzahlen, Live-Flags, sevDesk-Bestände oder die Vollständigkeit einzelner historischer Belege. Der Benutzer bestätigt die fachliche Vollständigkeit der fünfjährigen sevDesk-Verkaufshistorie; der Import muss sie technisch vor dem Produktivstart prüfen.

## 3. Identität, Mengen und Buchungszeitpunkt

### 3.1 Produkt- und Lageridentität

- Jede physische Rechnungsposition muss eindeutig auf eine aktive Product-Hub-Variante, Lagerort `MAIN` und SKU zeigen. Variantenspezifische sevDesk-Part-Mappings haben Vorrang; der bestehende Produkt-Fallback ist nur bei genau einer aktiven Bestandsvariante zulässig. Keine fuzzy Zuordnung für Bestandsbuchungen.
- Drei getrennte Artikelarten: `external_print` (Druckerei-Note), `pod` (physisches Eigen-/Bedarfsdruckprodukt), `digital` (keine Lagerbewegung). Das `∞` darf bei POD höchstens die Druckkapazität kennzeichnen; daneben steht der numerische vorgedruckte Bestand.
- Stückzahlen sind nichtnegative ganze Zahlen. Rabatt-, Versand-, reine Dienstleistungs- und digitale Positionen erzeugen keine physische Bewegung. Bundles/Mehrfach-Titel benötigen eine explizite, geprüfte Komponentenauflösung.
- `on_hand` ist der physisch gezählte Bestand. „Verfügbar“ berücksichtigt nur tatsächlich vorhandene Reservierungen; der hier beschlossene Rechnungsabgang erfolgt bei Freigabe. Die Alarmregel verwendet `on_hand` und zeigt eine etwaige Differenz zu `available` zusätzlich.

### 3.2 Verkauf und Gegenbelege

Ein einziger Buchungsdienst verarbeitet sowohl den unmittelbaren XW-Office-Freigabeerfolg als auch einen nachlaufenden, paginierten sevDesk-Abgleich mit dauerhaftem Wasserstand und Überlappung. Beide Wege benutzen dieselbe Transaktion und denselben eindeutigen Beleg-/Positionsschlüssel. Keine Bestandsänderung allein durch das Laden der RECHNUNGEN-Ansicht.

Während des Shadow-Betriebs bleibt der bisherige Bestand die operative Lesequelle: Ein erfasstes Geschäftsereignis aktualisiert ihn einmal und spiegelt dieselbe Bewegung in das Hub-Ledger. Eine fehlgeschlagene Spiegelung wird als Drift/Retry sichtbar, niemals als erfolgreicher Gleichstand dargestellt. Erst nach dem geprüften Cutover wird das Hub-Ledger zur schreibenden Quelle und der Bestand zu sevDesk/Wix projiziert. Beide Betriebsarten verwenden denselben Belegschlüssel, damit ein Umschalten keine zweite Buchung auslöst.

1. Vor Freigabe im Desktop: Positionen und eindeutige Variante prüfen; bei POD den notwendigen Druck planen. Unauflösbare Positionen stoppen die betroffene Freigabe und erscheinen in einer Klärliste.
2. Nach bestätigter Freigabe: finalen Belegstatus und endgültige Positionen erneut lesen; je Position die Differenz zur bereits gebuchten Menge atomar und idempotent als `sale` erfassen. Jeder Beleg hat einen verfolgbaren Zustand (`pending`, `booked`, `needs_review`) und einen Fehlergrund.
3. Besteht bei einer **extern** freigegebenen Rechnung zu wenig gezählter Bestand, darf der Abgleich weder auf 0 kappen noch eine negative Menge im `on_hand` vortäuschen. Er hält die ungebuchte Fehlmenge als offenen, sichtbaren Bestandskonflikt fest und verarbeitet sie nach bestätigtem Zugang/Druck. Freigaben im Desktop müssen einen solchen Mangel vorab anzeigen und bis zur Lösung stoppen.
4. Storno/Gutschrift: nur final bestätigte Gegenbelege mit eindeutigem Bezug zur Ursprungsposition verarbeiten. Vollstorno kehrt deren noch nicht rückgebuchte Menge um; Teilgutschrift nur zugeordnete Stücke. Summe der Rückbuchungen je Position darf die gebuchte Verkaufsmenge nicht überschreiten. Mehrfachabruf, mehrere Teilgutschriften und nachträgliche Belegänderungen müssen deterministisch bleiben. Wertgutschriften ohne Stückzahl landen in `needs_review`.
5. Gegenbelege nach dem Inventur-Stichtag können auch eine vor dem Stichtag verkaufte Rechnung betreffen. Der gezählte Anfangsbestand enthält deren damaligen Verkauf bereits; eine spätere eindeutige Rückbuchung erhöht deshalb den aktuellen Bestand, ohne eine historische `sale`-Bewegung nachzubuchen.

Die Buchung von Ursprungs- und Gegenbeleg, Bewegungszeile, materialisiertem Bestand und Alarm-Neubewertung braucht eine gemeinsame Datenbanktransaktion bzw. einen sicher wiederholbaren Zustandsübergang. Der bestehende Repository-Pfad muss für parallele Desktop-/Worker-Aufrufe gegen verlorene Updates abgesichert werden. Fehler eines Belegs dürfen die Bestandsbuchung erfolgreich freigegebener anderer Rechnungen nicht verschlucken.

### 3.3 Inventur und Cutover

- Lesende Zählliste aller aktiven `external_print`- und `pod`-Varianten mit SKU, Titel, Lagerort, bisherigem Wert, Eingabefeld, Zählzeitpunkt und Referenz exportierbar machen. Nicht gemappte, doppelte oder inaktive SKUs gesondert anzeigen.
- Mehrere Zählstände erfassen, Änderungen vor Abschluss vergleichen und nur bestätigte Differenzen als `recount` buchen. Der erste bestätigte Stichtag ist die Grundlage für den Hub-Cutover; vorhandene Shadow-Baselines werden abgeglichen, nicht blind ein zweites Mal importiert. POD-Vordrucke werden tatsächlich gezählt, nicht mit `∞` oder pauschal 0 angesetzt.
- Vor dem Umschalten: Backups, vollständige Zuordnung, Shadow-Drift, noch offene Bestandskonflikte, sevDesk-/Wix-Projektionen und Rollback praktisch prüfen. Die vorhandene `/app/inventory/cutover`-Bereitschaftsanzeige bleibt Gate; kein bloßes Aktivieren von `inventory_master_enabled`.
- Historische Rechnungen vor dem Stichtag dienen der Prognose und werden **nicht** rückwirkend als Verkäufe gegen den neu gezählten Bestand gebucht. Noch offene Entwürfe werden bei späterer Freigabe normal erfasst. Stichtag und Import-Wasserstand müssen dauerhaft gespeichert werden.

## 4. Prognose und Alarm-Lebenszyklus

### 4.1 Absatzberechnung

Pro Variante und `MAIN` täglich sowie nach relevanten Rechnungs-/Gegenbelegänderungen rechnen:

```text
N = Anzahl voller, verkaufsfähiger Kalendermonate im Fenster der letzten 60 vollen Monate
Nettoabsatz = Summe endgültig verkaufter physischer Stücke minus eindeutig gutgeschriebener/stornierter Stücke
Monatsmittel = Nettoabsatz / N
Automatischer Alarmbestand = ceil(Monatsmittel × 3)
```

`N` enthält Nullmonate und ist maximal 60. Bei weniger als sechs vollen Monaten gilt 50. Ab sechs Monaten wird der berechnete Wert verwendet, auch wenn noch keine fünf Jahre vorliegen. Negative Nettowerte werden für die Schwelle auf 0 begrenzt; Datenanomalien bleiben sichtbar. Nicht eindeutige Positionen werden im Qualitätsbericht ausgewiesen und nicht stillschweigend als Nullabsatz behandelt. Die UI zeigt Fenster, `N`, Nettoabsatz, Monatsmittel, Prognosezeitpunkt und Datenqualität. Ein Fixwert setzt nur die aktive Schwelle außer Kraft; die Prognose läuft weiter. Wechsel von `fixed` zurück zu `auto` ist möglich.

Für POD ist diese Druckerei-Nachbestellprognose nicht der Auslöser des Drei-Stück-Drucks. POD verwendet den tatsächlichen vorgedruckten Bestand, offenen Bedarf und die konfigurierte Druckcharge.

### 4.2 Alarmzustand

- Genau ein aktiver Lagerwarnfall je Variante und Lagerort; Schwere `low_stock` oder `out_of_stock`. `out_of_stock` ersetzt `low_stock`, ohne einen zweiten offenen Fall oder eine zweite Task zu erzeugen.
- Bei jeder Bestandsbewegung, Inventur, Schwellenänderung, Prognoseneuberechnung und beim Start des Warnungs-Workers den **aktuellen Zustand** prüfen: `on_hand <= active_reorder_point` öffnet/aktualisiert, `on_hand > active_reorder_point` löst auf. So werden bereits bei der Erstinventur niedrige Bestände erkannt.
- Ein manuell quittierter Alarm bleibt fachlich offen, solange die Bedingung gilt; die Quittierung blendet ihn nicht dauerhaft aus. Speicherung von Schwellenmodus, Fixwert, Berechnungszeitpunkt, altem/neuem Wert und Bearbeiter ist auditierbar.
- Der bestehende automatische XW-Flow-Task-Intent `inventory_alert.opened` darf zusammen mit der gewünschten Graph-Mail nicht unbemerkt zwei Aufgaben erzeugen. Vor dem Rollout einen eindeutigen Aufgabenkanal und dessen Duplikatschlüssel festlegen; für diesen Wunsch ist die **manuell ausgelöste Graph-Mail** maßgeblich.

## 5. RECHNUNGEN: Popup, Mail und Druckliste

### 5.1 Lagerwarnung

Der Alarm-Button zeigt die Zahl aktuell betroffener Varianten, auch ohne offene Rechnungsentwürfe. Im Popup: SKU, Produkttitel/Variante, Lagerort, Ist-Bestand, aktiver Alarmbestand, `auto`/`fixed`, Monatsmittel, Dreimonatsprognose, Datenfenster, letzter Abgleich, vorgeschlagene Nachbestell-/Nachdruckmenge und Link zum Product Hub. Bei mehreren Produkten sortiert die Liste zuerst Fehlbestand, dann Abstand zur Schwelle. Bearbeitung des Fixwerts mit Vorschau der Alarmfolge; Speichern aktualisiert Warnung und Button sofort. Die Option „Automatik verwenden“ entfernt den Fixwert.

„Task erzeugen“ sendet über den vorhandenen `MailDeliveryService`/MS Graph an `todo@xeisworks.at`. Betreff enthält SKU und Titel; Inhalt enthält Alarm-ID, SKU, Titel/Variante, Lagerort, Ist-Bestand, Alarmbestand und Modus, 60-Monats-/verfügbares Datenfenster, Monatsmittel, Dreimonatsbedarf, Ziel-/Bestellmenge, Zeitstempel und Produktlink. Keine Kundendaten. Versandstatus `bereit`, `sendet`, `gesendet`, `unklar`, `fehlgeschlagen` je Alarm persistieren. Ein erneuter Klick nach Erfolg bietet nur eine ausdrücklich bestätigte neue Mail; bei Timeout nach Graph-Aufruf wird nicht blind wiederholt, sondern der unklare Zustand sichtbar gemacht.

### 5.2 PRINT PRODUKTE OFFEN

Die Anzeige trennt **bestellt**, **im Lager**, **bereits für andere offene Vorgänge eingeplant**, **aus Lager entnehmen** und **neu drucken**. Druckmenge wird über alle offenen Rechnungen für dieselbe exakte Variante geplant; derselbe Bestand darf nicht zwei Rechnungen vollständig decken. Für Druckerei-Noten mit ausreichendem Bestand: `0 drucken`, Hinweis „aus Lager“. Bei Fehlbestand: kein automatischer Druckereidruck, sondern Warnung/Nachbestellfall. Für POD: bei Fehlmenge `3 × ceil(Fehlmenge / 3)` drucken; Beispiel 2 vorrätig und 3 offen → 3 drucken, 2 nach Freigabe der drei Rechnungen übrig. Nur bestätigte Druckerfolge buchen `print_run`; Wiederholungen und manueller Mehrdruck brauchen einen eigenen eindeutigen Produktionsschlüssel. Einzel- und Sammeldruck benutzen denselben Plan. Historische Drucklauf-Ansichten dürfen keinen neuen Bestand oder Druckauftrag vortäuschen.

## 6. Umsetzungsreihenfolge und Abnahme

Die zugehörige YAML zerlegt die Arbeit in kleine, einzeln prüfbare Pakete. Reihenfolge: Dateninventur und Read-only-Prognose → Inventur und Lageridentität → idempotente Rechnungs-/Gegenbelegbuchung im Shadow-Modus → Alarmregeln → POD-Druckplan → RECHNUNGEN-Popup/Graph-Mail → verifizierter Hub-Cutover. Der alte Bestand wird erst nach bestandenem Cutover als unabhängiger Schreiber entfernt.

Pflichtfälle der Abnahme:

1. Inventur: 17 statt 20 erzeugt genau eine `recount`-Bewegung `-3`; erneutes Speichern dupliziert sie nicht.
2. Wix- und manuelle sevDesk-Rechnung mit je zwei physischen Stücken: nach Freigabe jeweils einmal `-2`; wiederholter START, Polling oder Mailversand ändern nichts.
3. Batch mit zwei erfolgreichen und einer fehlgeschlagenen Rechnung: die zwei Erfolge werden trotzdem korrekt gebucht.
4. Extern freigegebene sevDesk-Rechnung wird nach Abgleich genau einmal gebucht; fehlende SKU oder Unterdeckung erscheinen in der Klärliste.
5. Vollstorno `+ursprüngliche Stückzahl`; zwei Teilgutschriften ergeben maximal die ursprünglich gebuchte Menge; reine Wertgutschrift erzeugt keine geschätzte Stückbewegung.
6. Druckerei-Titel mit 5 vollen Monaten hat Alarmbestand 50; nach dem 6. vollen Monat wird der berechnete Wert aktiv. Ein Fixwert bleibt trotz neuer Verkäufe aktiv; Rückkehr zur Automatik übernimmt den aktuellen Vorschlag.
7. Schwelle 5 und Bestand 4 öffnet Alarm; Änderung auf 3 löst ihn auf, Änderung auf 6 öffnet ihn wieder. Bestand 0 zeigt `out_of_stock`, nicht zwei Alarme.
8. POD: 0 vorrätig, 1 verkauft → 3 gedruckt, 2 verbleiben; weitere zwei Verkäufe drucken nichts. Zwei vorrätig, drei gleichzeitig verkauft → eine Dreiercharge; gleiche Planung im Einzel- und Sammeldruck.
9. Graph-Mail wird nur nach Klick gesendet, enthält alle Pflichtfelder und erzeugt bei Doppelklick/Retry nicht unbemerkt eine zweite Task.
10. Historische Verkäufe vor dem Inventur-Stichtag verändern den gezählten Anfangsbestand nicht; ein späterer eindeutiger Gegenbeleg dazu wird korrekt zurückgebucht.

## 7. Arbeitsanweisung an Codex 5.6 Luna

Vor jedem Paket `AGENTS.md`, diesen Text, die YAML, `docs/product_hub/PROGRESS.md` und die betroffenen aktuellen Codepfade lesen. Mit sauberem `main` beginnen und `git pull --ff-only origin main` ausführen. Migrationen nur additiv gegen den **aktuellen** Alembic-Head erstellen; keine historischen Migrationen oder das geschützte Architekturarchiv verändern. Pro Paket nur den angegebenen Scope umsetzen, gezielte Tests und einen realistischen manuellen Abnahmeschritt durchführen, Fortschritt und verbleibende Risiken dokumentieren. Erst fertig getestete Änderungen nach `main` integrieren und ohne Force-Push zu `origin/main` pushen. Kein Bestands-Master-Cutover allein aufgrund grüner Unit-Tests: Datenabgleich, Projektionen, Shadow-Lauf und Rollback-Nachweis gehören zur Abnahme.
