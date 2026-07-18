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

