import { useState } from "react";
import { Link } from "react-router-dom";
import { api, ApiError } from "../api/client";
import StatusBadge from "../components/StatusBadge";
import { useApi } from "../hooks/useApi";

export default function ConflictListPage({ onUnauthorized }: { onUnauthorized: () => void }) {
  const [severity, setSeverity] = useState("");
  const [channel, setChannel] = useState("");
  const [reload, setReload] = useState(0);
  const [message, setMessage] = useState("");
  const summary = useApi(api.getConflictSummary, [reload], onUnauthorized);
  const queue = useApi(
    () => api.listConflicts({ ...(severity ? { severity } : {}), ...(channel ? { channel } : {}) }),
    [severity, channel, reload],
    onUnauthorized,
  );

  async function scan() {
    setMessage("Scan läuft …");
    try {
      const result = await api.scanConflicts();
      setMessage(`${result.differences_found} Unterschiede, ${result.cases_created} neue Fälle.`);
      setReload((value) => value + 1);
    } catch (error) {
      if (error instanceof ApiError && error.status === 401) onUnauthorized();
      setMessage(error instanceof Error ? error.message : String(error));
    }
  }

  return (
    <section>
      <div className="list-toolbar">
        <div><h1>Konflikte</h1><p className="hint">Dauerhafte, auditierbare Bereinigungs-Queue</p></div>
        <button className="primary-button" type="button" onClick={scan}>Jetzt vergleichen</button>
      </div>
      {message && <p className="hint">{message}</p>}
      {summary.data && (
        <div className="tile-grid conflict-summary">
          <div className="tile"><span className="tile-value">{summary.data.open}</span><span className="tile-label">Offen</span></div>
          <div className="tile tile-warn"><span className="tile-value">{summary.data.critical}</span><span className="tile-label">Kritisch</span></div>
          <div className="tile"><span className="tile-value">{summary.data.waiting}</span><span className="tile-label">Wiedervorlage</span></div>
          <div className="tile"><span className="tile-value">{summary.data.partially_resolved}</span><span className="tile-label">Teilweise gelöst</span></div>
        </div>
      )}
      <div className="filter-bar">
        <select value={severity} onChange={(event) => setSeverity(event.target.value)} aria-label="Schweregrad">
          <option value="">Alle Schweregrade</option><option>CRITICAL</option><option>HIGH</option><option>MEDIUM</option><option>LOW</option><option>INFO</option>
        </select>
        <select value={channel} onChange={(event) => setChannel(event.target.value)} aria-label="Channel">
          <option value="">Alle Channels</option><option value="wix">Wix</option><option value="sevdesk">sevdesk</option><option value="amazon">Amazon</option>
        </select>
      </div>
      {queue.loading && <p className="hint">Queue wird geladen …</p>}
      {queue.error && <p className="hint-error">{queue.error}</p>}
      {queue.data && (
        <table className="data-table">
          <thead><tr><th>Priorität</th><th>Fall</th><th>Typ</th><th>Status</th><th>Zuletzt gesehen</th></tr></thead>
          <tbody>
            {queue.data.items.map((item) => (
              <tr key={item.id}>
                <td><StatusBadge label={item.severity} tone={item.severity === "CRITICAL" || item.severity === "HIGH" ? "bad" : item.severity === "MEDIUM" ? "warn" : "neutral"} /></td>
                <td><Link to={`/conflicts/${item.id}`}>{item.title}</Link><div className="hint">{item.summary}</div></td>
                <td>{item.conflict_type}</td><td>{item.status}</td><td>{new Date(item.last_seen_at).toLocaleString("de-AT")}</td>
              </tr>
            ))}
            {!queue.data.items.length && <tr><td colSpan={5} className="hint">Keine passenden offenen Fälle.</td></tr>}
          </tbody>
        </table>
      )}
    </section>
  );
}
