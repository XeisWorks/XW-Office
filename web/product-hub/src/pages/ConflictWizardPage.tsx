import { useEffect, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { api, ApiError } from "../api/client";
import type { ConflictAction, ConflictCaseDetail } from "../api/types";
import StatusBadge from "../components/StatusBadge";

function display(value: unknown): string {
  if (value === null || value === undefined || value === "") return "—";
  return typeof value === "string" ? value : JSON.stringify(value);
}

export default function ConflictWizardPage({ onUnauthorized }: { onUnauthorized: () => void }) {
  const { id } = useParams();
  const navigate = useNavigate();
  const [item, setItem] = useState<ConflictCaseDetail | null>(null);
  const [actions, setActions] = useState<ConflictAction[]>([]);
  const [custom, setCustom] = useState("");
  const [message, setMessage] = useState("");

  async function load() {
    if (!id) {
      const queue = await api.listConflicts();
      if (queue.items[0]) navigate(`/conflicts/${queue.items[0].id}`, { replace: true });
      else setMessage("Die Konflikt-Queue ist leer.");
      return;
    }
    const detail = await api.getConflict(id);
    setItem(detail); setActions(detail.actions); setMessage("");
  }

  useEffect(() => { load().catch(handleError); }, [id]); // eslint-disable-line react-hooks/exhaustive-deps

  function handleError(error: unknown) {
    if (error instanceof ApiError && error.status === 401) onUnauthorized();
    setMessage(error instanceof Error ? error.message : String(error));
  }

  async function decide(resolutionType: string, source?: string) {
    if (!item || !id) return;
    try {
      const updated = await api.decideConflict(id, {
        expected_row_version: item.row_version,
        resolution_type: resolutionType,
        selected_source: source,
        ...(resolutionType === "CUSTOM_VALUE" ? { custom_value: custom } : {}),
      });
      if (["INTENTIONAL_DIFFERENCE", "IGNORE"].includes(resolutionType)) {
        setMessage("Fall abgeschlossen."); await load(); return;
      }
      const preview = await api.previewConflict(id);
      setActions(preview); setItem({ ...item, ...updated }); setMessage("Entscheidung gespeichert. Bitte Vorschau prüfen.");
    } catch (error) { handleError(error); }
  }

  async function apply() {
    if (!item || !id) return;
    try {
      const updated = await api.applyConflict(id, item.row_version);
      setItem({ ...item, ...updated }); setMessage(updated.status === "RESOLVED" ? "Fall verifiziert und abgeschlossen." : "Channel-Aktion wurde sicher in die Outbox gestellt.");
    } catch (error) { handleError(error); }
  }

  async function later() {
    if (!item || !id) return;
    const until = new Date(Date.now() + 7 * 86400000).toISOString();
    try { await api.snoozeConflict(id, item.row_version, until); navigate("/conflicts"); }
    catch (error) { handleError(error); }
  }

  if (!item) return <section><h1>Conflict Wizard</h1><p className="hint">{message || "Fall wird geladen …"}</p></section>;
  const sources = Array.from(new Set(item.fields.flatMap((field) => field.observations.map((obs) => obs.source))));
  return (
    <section>
      <Link to="/conflicts">← Zur Queue</Link>
      <div className="conflict-heading"><div><h1>{item.product_sku} · {item.product_name}</h1><p>{item.conflict_type}</p></div><StatusBadge label={item.severity} tone={item.severity === "CRITICAL" || item.severity === "HIGH" ? "bad" : item.severity === "MEDIUM" ? "warn" : "neutral"} /></div>
      {item.severity === "CRITICAL" && <div className="critical-warning">Kritischer Identitäts-/Mapping-Konflikt: keine automatische Auflösung.</div>}
      <div className="comparison-grid">
        <div className="comparison-head">Feld</div>{sources.map((source) => <div className="comparison-head" key={source}>{source === "hub" ? "Product Hub" : source}</div>)}
        {item.fields.map((field) => <div className="comparison-row" key={field.id} style={{ gridTemplateColumns: `repeat(${sources.length + 1}, minmax(0, 1fr))` }}>
          <strong>{field.field_path}</strong>{sources.map((source) => <div key={source}>{display([...field.observations].reverse().find((obs) => obs.source === source)?.raw_value)}</div>)}
        </div>)}
      </div>
      <div className="decision-panel">
        <h2>Welcher Wert ist richtig?</h2>
        <div className="decision-buttons">
          {sources.map((source) => <button type="button" key={source} onClick={() => decide(`USE_${source.toUpperCase()}`, source)}>{source === "hub" ? "Product Hub" : source} übernehmen</button>)}
        </div>
        <div className="custom-decision"><input value={custom} onChange={(event) => setCustom(event.target.value)} placeholder="Eigener Wert" /><button type="button" onClick={() => decide("CUSTOM_VALUE")}>Eigenen Wert verwenden</button></div>
        <div className="secondary-actions"><button type="button" onClick={() => decide("INTENTIONAL_DIFFERENCE")}>Unterschied ist beabsichtigt</button><button type="button" onClick={later}>Eine Woche später</button><button type="button" onClick={() => decide("IGNORE")}>Ignorieren</button></div>
      </div>
      {actions.length > 0 && <div className="impact-panel"><h2>Impact Preview</h2>{actions.map((action) => <div className="impact-row" key={action.id}><span>{action.channel}</span><span>{display(action.before_value)} → {display(action.after_value)}</span><StatusBadge label={action.status} tone={action.status === "VERIFIED" ? "ok" : action.status === "SKIPPED" || action.status === "FAILED" ? "bad" : "warn"} />{action.error && <span className="hint-error">{action.error}</span>}</div>)}<button className="primary-button" type="button" onClick={apply} disabled={!actions.some((action) => action.selected && action.status === "PLANNED")}>Ausgewählte Änderungen ausführen</button></div>}
      {message && <p className="hint">{message}</p>}
    </section>
  );
}
