# Versandplanung beim START-Lauf

Nach START öffnet sich sofort die Datumsauswahl. Die Vorschau zählt nur physische
Rechnungen, die für diesen Lauf freigegeben sind. Die Klassifizierung verwendet
zuerst das Wix-Lieferland, sonst das sevDesk-Land. Rein digitale Lieferungen zählen
nicht. PLC-Hinweise und bereits erstellte PLC-Labels werden der Österreich-Gruppe
zugeordnet. Wird ein LIVE-PLC-Label später erzeugt, zieht die gespeicherte Planung
automatisch auf das Österreich-Datum desselben Laufs um.

Auslandssendungen aus älteren Läufen bleiben bis zur Erfassung des tatsächlichen
Versanddatums offen. Ab insgesamt drei EU/CH-Sendungen ist „Ausland mit Österreich/PLC
versenden“ voreingestellt; bei weniger als drei wird ein eigenes Auslandsdatum
gewählt. Die fünf Kalendertage beginnen mit dem heutigen Tag in Europe/Vienna.
Ein Klick auf das Datum schließt die Auswahl, bei getrennter Planung ein zweiter
Klick auf das Auslandsdatum. Beim nächsten START wird das geplante Datum wartender
Auslandssendungen auf die neue Auswahl verschoben.

Das geplante Datum ist eine Prognose. Das tatsächliche Datum wird in „KUNDEN
(last run)“ über das Häkchen bei der Sendung auf heute gesetzt; ein Klick auf ein
bereits erfasstes Versanddatum erlaubt eine Korrektur. Im Detail der Rechnung
steht ebenfalls das geplante beziehungsweise tatsächliche Versanddatum. Beide
Datumsarten werden je Rechnungs-ID unter `rechnungen.shipping_dates_v1` in
SettingsKV gespeichert, unabhängig von der auf fünf Läufe begrenzten Ansicht.

Eine Gewichtsgrenze für PLC wird bewusst nicht geschätzt: Die vorhandenen
historischen PLC-Daten sind nach Tag und Land aggregiert und liefern keine
verlässliche Regel, ab welchem Gewicht ein konkretes Label benötigt wird.
