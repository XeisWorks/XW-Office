# PLC-Paketnachweis

## Ablauf in RECHNUNGEN

1. Beim Erstellen eines PLC-Labels erfasst XW-Office die zum Zeitpunkt des Aufrufs zugeordneten physischen Artikel je Paket. Digitale Artikel werden ausgeschlossen. Die Daten werden vor dem Webservice-Aufruf dauerhaft gespeichert und erst nach erfolgreicher PLC-Antwort als erstellte Sendung angezeigt.
2. Zu jeder Sendung werden das Label-PDF, die PLC-Codes und das erzeugte Packlisten-PDF archiviert. Im Menü **Ansehen → Paketinhalt & Tracking** stehen Paketinhalt, Label-Erstellzeit und Trackingcode. Für Bestellungen mit mehreren archivierten Sendungen bleibt zusätzlich der Button **Sendungen & Packlisten** sichtbar.
3. Bei genau einem Paket und genau einem PLC-Code ist die Zuordnung eindeutig. Bei mehreren Paketen bleibt sie offen, bis der Code vom tatsächlichen Paketlabel im Nachweisdialog gescannt oder eingegeben und bestätigt wurde. Die Reihenfolge der PLC-Antwort ist kein Zuordnungsbeleg.
4. Liegt eine originale TrackingData-v2-XML-Datei der Österreichischen Post vor, kann sie im Nachweisdialog importiert werden. Der Import speichert nur Ereignisse zu PLC-Codes der ausgewählten Rechnung, ist anhand von Ereignis-ID und Code wiederholbar und hält den SHA-256-Fingerabdruck der Quelldatei fest.

Die lokale Label-Erstellung oder ein Druckauftrag beweisen keine Übergabe an die Post. Annahme und Zustellung werden anhand importierter Post-Ereignisse und der offiziellen Sendungsverfolgung geprüft. `AVI` bedeutet nur elektronische Ankündigung; `ZUS` bezeichnet ein Zustellereignis. Die Ereigniszeit wird im Format der Post-Datei angezeigt. Ohne importierte Post-Daten verweist der Dialog auf die offizielle Sendungsverfolgung.

## Neue und spätere Lieferungen

Eine spätere Teillieferung erhält eine neue PLC-Sendung mit eigenem Label, Packliste und Trackingcode. Ein zusätzliches Packstück innerhalb einer bereits erzeugten Sendung ist kein verlässlicher Weg, um eine zeitlich spätere Übergabe mit eigener Packliste und Annahme nachzuweisen. Der lokale Dialog erstellt dafür wie bisher eine weitere Sendung mit Referenzsuffix.

Artikel in `ColloArticleList` werden im aktuellen Webservice nur dort übertragen, wo die Zollabwicklung sie benötigt. Das Feld ist laut PLC-API beschrieben, sein Verhalten für inländische Sendungen ist jedoch im Post-Testsystem noch nicht bestätigt. Die strukturierte lokale Zuordnung und die Packlisten funktionieren ohne diese Annahme.

## Inbetriebnahme

Vor dem Einsatz auf einer vorhandenen Datenbank `alembic upgrade head` ausführen. Die Migration `037_plc_parcel_evidence` legt die Paket- und Trackingtabellen an und erweitert `plc_shipment`. Frühere Labels haben keinen rückwirkend erzeugbaren strukturierten Paketinhalt; ihre archivierten PDFs bleiben einsehbar. Für automatische Trackingdaten ist ein Trackingdaten-Vertrag bzw. Zugang der Post erforderlich. Der Dateiimport funktioniert ohne direkte Schnittstellenfreischaltung, sobald eine originale XML-Datei vorliegt.

Quellen: [PLC How-tos](https://www.post.at/-/media/dokumente/de/geschaeftlich/versenden/paket/howtos_plc_de.pdf), [Trackingdaten v2](https://assets.post.at/-/media/Dokumente/De/Geschaeftlich/Versenden/Paket/Trackingdaten_Kundeninfo_V2.pdf), [Sendungsstatus](https://www.post.at/p/c/hilfe-sendungsstatus), [Post-API](https://customerservices.post.at/).
