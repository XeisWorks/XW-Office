# Figma, VS Code und LLMs

## Zweck

XW-Office hat mit `web/product-hub` eine React-Oberfläche. Die Figma-Remote-MCP-Verbindung
liefert einem MCP-fähigen Agenten den Kontext eines konkreten Figma-Frames (Layout, Variablen,
Komponenten und Assets), damit er Änderungen im vorhandenen UI statt mit geratenen Styles
implementiert. Code Connect ergänzt dies später um Verweise auf die echten React-Komponenten.

## Einmal je VS-Code-Installation verbinden

Die portable Workspace-Konfiguration ist `.vscode/mcp.json` und nutzt ausschließlich den von
Figma empfohlenen Remote-Endpunkt `https://mcp.figma.com/mcp`. In VS Code:

1. GitHub Copilot aktivieren und die Arbeitsmappe öffnen.
2. `MCP: Open Workspace Folder Configuration` öffnen und prüfen, dass der Server `figma` läuft.
3. Bei der ersten Verbindung **Allow access** wählen und sich mit dem Figma-Konto anmelden.

Den Desktop-Server (`http://127.0.0.1:3845/mcp`) nicht zusätzlich eintragen: Der Remote-Server
hat den größeren Funktionsumfang und verhindert doppelte bzw. widersprüchliche Werkzeuge.

## Arbeitsregel für Agenten

Wenn eine Aufgabe auf einem Figma-Entwurf beruht, muss der Auftrag einen Figma-Link enthalten,
idealerweise **Copy link to selection** mit `node-id`. Der Agent soll zuerst den Designkontext
und vorhandene Komponenten/Variablen lesen, dann die vorhandene React-Struktur weiterverwenden
und die Änderung wie üblich testen. Kein Figma-Link bedeutet: keine Designabsichten erraten.

## Code Connect

`web/product-hub/figma.config.json` ist für parserlose `*.figma.ts`-Vorlagen vorbereitet; das
CLI ist als Entwicklungsabhängigkeit des Webprojekts installiert. Eine Vorlage wird erst erstellt,
wenn es dafür eine veröffentlichte Figma-Komponente und ihren Auswahl-Link gibt. Sie wird neben
der passenden React-Komponente abgelegt und beschreibt ausschließlich deren echte Props.

Vor einem bewussten Publish lokal einen Figma-PAT mit den nötigen Scopes sicher hinterlegen und
anschließend aus `web/product-hub` ausführen:

```powershell
npm exec -- figma connect publish
```

`FIGMA_ACCESS_TOKEN`, PATs, OAuth-Antworten und Browserdaten dürfen nie committed oder geloggt
werden. Ohne veröffentlichte Komponenten oder ohne berechtigten Seat bleibt MCP für
Designkontext nutzbar; Code Connect wird dann einfach nicht veröffentlicht.
