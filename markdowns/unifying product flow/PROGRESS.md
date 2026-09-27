# Unified Product Flow – Fortschritt

## T08 – OneDrive (2026-09-27)

- Erledigt: serverseitiger Graph-Zugriff mit langlebigen Drive-/Item-IDs,
  Root-Grenzpruefung und privatem Ordner-Browser im fortsetzbaren Produktentwurf.
- Sicherheit: Browser und API liefern ausschliesslich Metadaten; keine Graph-Token,
  Download-URLs oder oeffentlichen PDF-Links. Elemente ausserhalb des konfigurierten
  Root-Unterbaums werden abgewiesen.
- Lokale Tests: 8 gezielte Tests fuer Graph-Client, Asset-Service und die
  geraeteunabhaengige OneDrive-Pfadauflösung; Ruff und Web-Produktionsbuild bestanden.
- Produktionschecks: Graph-Root lesbar, 24 Root-Eintraege gelistet und eine private
  Datei erfolgreich gelesen (64.844 Bytes). Es wurden keine Datei-IDs oder Inhalte geloggt.

## Offener Infrastrukturpunkt fuer T09

- Cloudflare R2 ist erreichbar, aber der hinterlegte Zugriffsschluessel verweigert
  `PutObject` und `DeleteObject`. Der kontrollierte Test hat kein Objekt hinterlassen.
  Fuer die persistente Render-Pipeline braucht der R2-API-Token mindestens Object
  Read & Write fuer den vorgesehenen Bucket.
