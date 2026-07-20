# Repository- und Branch-Regel

- `origin/main` ist der einzige dauerhafte gemeinsame Code-Stand fuer alle PCs.
- Vor Arbeiten immer `main` verwenden und mit `git pull --ff-only origin main` aktualisieren.
- Fertige, getestete Aenderungen muessen in `main` integriert und zu `origin/main` gepusht werden.
- Temporaere Arbeitsbranches wie `agent/*` sind erlaubt, duerfen aber nicht als dauerhafter
  Betriebs- oder Synchronisationsbranch eines PCs verbleiben.
- Einen abweichenden Branch nie durch `git pull origin main` mit `main` vermischen. Stattdessen
  die Arbeit bewusst in `main` integrieren und danach wieder auf `main` wechseln.
- Branchwechsel, Merge und Pull nur mit sauberem Arbeitsbaum durchfuehren. Lokale Aenderungen
  vorher committen oder gezielt stashen.
- Kein Force-Push auf `main`.

# Geschuetztes Architekturarchiv

- `markdowns/XeisWorks_Content_Studio_Originalkonzept_2026-07-19_UNVERAENDERT.md` ist eine
  unveraenderliche historische Quelle. Diese Datei weder bearbeiten noch umbenennen.
- Fuer Content-Studio-Entscheidungen gilt stattdessen
  `markdowns/XeisWorks_Content_Studio_Zielarchitektur_und_Umbauplan_2026-07-20.md`.
- Eine beabsichtigte Aenderung des Archivs erfordert eine ausdrueckliche Benutzeranweisung und
  eine bewusste Aktualisierung der zugehoerigen SHA-256-Pruefung.

