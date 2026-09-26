# Start für Codex 5.6 Luna

Dieses Paket enthält einen Implementierungsauftrag in 8 Bauphasen / 19 Arbeitspaketen. „Codex 5.6 Luna“ ist die vom Nutzer gewünschte ausführende Umgebung; die Dateien setzen keine bestimmte Modell-ID oder automatisch verfügbare Laufzeit voraus.

## Verwendung
Paket entpacken. BUILD_PLAN.md, TASK_QUEUE.yaml und COVER_SPEC.yaml im XW-Office-Repo unter docs/product_workflow/ ablegen. reference/ als visuelle Entwicklungsreferenz mitnehmen. Schriftdateien und private OneDrive-/Providerdaten gehören nicht ins öffentliche Repository.

Folgenden Auftrag an Codex geben:

> Lies AGENTS.md und docs/product_workflow/BUILD_PLAN.md, TASK_QUEUE.yaml sowie COVER_SPEC.yaml vollständig. Prüfe den aktuellen main-Stand, bevor du Änderungen machst. Setze das erste noch nicht abgeschlossene, von seinen Abhängigkeiten freigegebene Arbeitspaket um. Starte bei T01. Verwende die vorhandenen Product-Hub-, Outbox-, Konflikt-, Graph- und OpenAI-Bausteine. Erfinde keine zweite Produktdatenbank. Erhalte Druck-, Rechnungs- und Bestandsabläufe. Führe die fachlich relevanten Tests dieses Pakets aus. Dokumentiere in docs/product_workflow/PROGRESS.md Istbefund, Änderungen, Tests mit Ergebnis, offene externe Einrichtung, Commit und nächsten Task. Aktualisiere den Taskstatus nur nach erfüllten Abnahmekriterien. Bei fehlenden Zugangsdaten mit Fakes und sauberem Einrichtungsstatus weiterarbeiten; Livefunktion nicht als getestet behaupten. Keine produktiven Produkte oder Social Posts als Test erzeugen. Befolge die Repo-Regeln für Integration und Push. Liefere am Ende den nutzbaren Zwischenstand und den nächsten Task.

Fortsetzung:

> Lies PROGRESS.md und TASK_QUEUE.yaml. Prüfe aktuelle Änderungen und bearbeite das nächste freigegebene Arbeitspaket mit denselben Regeln. Bereits erledigte Tasks nur bei konkreter Regression erneut bearbeiten.

## Reihenfolge und sichtbarer Nutzen
| Phase | Ergebnis |
|---|---|
| P00 | Belegte Bestandsaufnahme und Migrationsvorschau |
| P01 | Desktop und Web lesen denselben Hub |
| P02 | Speicherbarer Wizard mit Kopieren und Wix-Optionen |
| P03 | OneDrive-PDF-Auswahl und Beispielseiten unterwegs |
| P04 | Cover mit exakten Fonts und konfigurierbaren Vorlagen |
| P05 | Vollständige, wiederaufnehmbare Wix-/sevDesk-Anlage |
| P06 | Externe Korrekturen und geprüfter Gesamtbetrieb |
| P07 | Bestehende und neue Amazon-DE-Artikel |

## Einmalig bereitzustellen, wenn die jeweilige Phase beginnt
- P03: Microsoft-Serveranmeldung und gewählte OneDrive-Ordner; vorhandene Integration zuerst untersuchen.
- P04: tatsächliche Book-Antiqua- und Deneane-Fontdateien als private Ressourcen; Hintergrundordner.
- P05: reale Wix-/sevDesk-Verbindung und ein bestehendes Produkt zum read-only Prüfen von Optionen und Editorlinks.
- P07: Amazon-SP-API-Zugang und tatsächliche Artikelidentifikatoren bzw. freigegebene Ausnahmen.

## Dateien
BUILD_PLAN.md: Entscheidungen, Architektur, Daten-/Syncvertrag, Migration und Quellen.
TASK_QUEUE.yaml: kleine aufeinander aufbauende Implementierungspakete mit Abnahme.
COVER_SPEC.yaml: konkrete Typografie und kalibrierbare Layoutwerte.
reference/: originale Hintergrundvorlage sowie vorhandenes Cover und SKU-/Besetzungsbeispiel. Das sind Referenzen, kein neu gerendertes Cover.

Die Codeimplementierung und visuelle Kalibrierung sind noch auszuführen. YAML-Dateien wurden syntaktisch geprüft; dieses Paket enthält keinen bereits getesteten Anwendungscode.
