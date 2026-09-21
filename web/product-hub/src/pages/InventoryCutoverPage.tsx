import { Link } from "react-router-dom";
import { api } from "../api/client";
import StatusBadge from "../components/StatusBadge";
import { useApi } from "../hooks/useApi";

function stateLabel(state: string) {
  if (state === "ready") return "Erfüllt";
  if (state === "manual") return "Manuell bestätigen";
  return "Blockiert";
}

export default function InventoryCutoverPage({ onUnauthorized }: { onUnauthorized: () => void }) {
  const result = useApi(api.getInventoryCutoverReadiness, [], onUnauthorized);

  return <section>
    <Link to="/">&larr; Zum Dashboard</Link>
    <div className="conflict-heading"><div><h1>Inventory-Cutover</h1><p>PR15-Readiness: Product Hub wird erst nach allen Nachweisen zum Bestands-Master.</p></div></div>
    {result.loading && <p className="hint">Readiness wird geprüft ...</p>}
    {result.error && <p className="hint-error">{result.error}</p>}
    {result.data && <>
      <article className={result.data.eligible ? "cutover-status cutover-status-ready" : "cutover-status cutover-status-blocked"}>
        <h2>{result.data.eligible ? "Cutover kann freigegeben werden" : "Cutover bleibt gesperrt"}</h2>
        <p>{result.data.master_enabled
          ? "Der Master-Schalter ist gesetzt. Prüfe die Nachweise sofort; die Anwendung aktiviert ihn nicht selbst."
          : "Der Product Hub ist weiterhin nicht als Inventory Master aktiviert."}</p>
        <p className="hint">Stand: {new Date(result.data.assessed_at).toLocaleString("de-AT")}</p>
      </article>
      <table className="data-table">
        <thead><tr><th>Kriterium</th><th>Status</th><th>Nachweis</th></tr></thead>
        <tbody>{result.data.checks.map((check) => <tr key={check.code}>
          <td>{check.label}</td>
          <td><StatusBadge label={stateLabel(check.state)} tone={check.state === "ready" ? "ok" : check.state === "manual" ? "warn" : "bad"} /></td>
          <td className="hint">{check.detail}</td>
        </tr>)}</tbody>
      </table>
      <p className="hint">Der Master-Schalter wird ausschließlich über die Deploy-Konfiguration gesetzt; diese Seite führt keine Lagerbewegung und keine externe Änderung aus.</p>
    </>}
  </section>;
}
