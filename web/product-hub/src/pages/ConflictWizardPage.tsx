import { useEffect, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { api, ApiError } from "../api/client";
import type { ConflictAction, ConflictAdvice, ConflictCaseDetail } from "../api/types";
import StatusBadge from "../components/StatusBadge";
import {
  conflictFieldLabel,
  conflictTypeLabel,
  deterministicGuidance,
  displayConflictValue,
  technicalValue,
} from "../utils/conflictPresentation";

const CONFIDENCE_LABELS = { low: "niedrig", medium: "mittel", high: "hoch" };

export default function ConflictWizardPage({ onUnauthorized }: { onUnauthorized: () => void }) {
  const { id } = useParams();
  const navigate = useNavigate();
  const [item, setItem] = useState<ConflictCaseDetail | null>(null);
  const [actions, setActions] = useState<ConflictAction[]>([]);
  const [advice, setAdvice] = useState<ConflictAdvice | null>(null);
  const [adviceLoading, setAdviceLoading] = useState(false);
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
    setItem(detail);
    setActions(detail.actions);
    setAdvice(null);
    setMessage("");
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

  async function retryWix() {
    setMessage("Wix-Verknüpfungen werden erneut geprüft …");
    try {
      await api.scanWixConflicts();
      await load();
      setMessage("Wix-Prüfung abgeschlossen.");
    } catch (error) { handleError(error); }
  }

  async function askAi() {
    if (!id) return;
    setAdviceLoading(true); setMessage("");
    try { setAdvice(await api.getConflictAdvice(id)); }
    catch (error) { handleError(error); }
    finally { setAdviceLoading(false); }
  }

  if (!item) return <section><h1>Konflikt-Assistent</h1><p className="hint">{message || "Fall wird geladen …"}</p></section>;

  const guidance = deterministicGuidance(item);
  const isMappingConflict = item.conflict_type === "WRONG_PRODUCT_MAPPING";
  const sources = Array.from(new Set(item.fields.flatMap((field) => field.observations.map((obs) => obs.source))));
  return (
    <section>
      <Link to="/conflicts">← Zur Konfliktliste</Link>
      <div className="conflict-heading">
        <div><h1>{item.product_sku} · {item.product_name}</h1><p>{conflictTypeLabel(item.conflict_type)}</p></div>
        <StatusBadge label={item.severity} tone={item.severity === "CRITICAL" || item.severity === "HIGH" ? "bad" : item.severity === "MEDIUM" ? "warn" : "neutral"} />
      </div>
      {item.severity === "CRITICAL" && <div className="critical-warning">Kritischer Identitäts- oder Verknüpfungskonflikt: Bitte manuell prüfen. Es wird nichts automatisch geändert.</div>}

      <article className="conflict-explanation" aria-labelledby="conflict-explanation-title">
        <h2 id="conflict-explanation-title">{guidance.title}</h2>
        <p>{guidance.explanation}</p>
        <h3>Meine Empfehlung</h3>
        <p>{guidance.recommendation}</p>
        <details><summary>Mögliche Ursachen</summary><ul>{guidance.possibleCauses.map((cause) => <li key={cause}>{cause}</li>)}</ul></details>
      </article>

      <div className="comparison-scroll">
        <table className="comparison-table">
          <thead><tr><th scope="col">Verglichenes Feld</th>{sources.map((source) => <th scope="col" key={source}>{source === "hub" ? "Product Hub" : source}</th>)}</tr></thead>
          <tbody>{item.fields.map((field) => <tr key={field.id}>
            <th scope="row">{conflictFieldLabel(field.field_path)}</th>
            {sources.map((source) => <td key={source}>{displayConflictValue(field.field_path, [...field.observations].reverse().find((obs) => obs.source === source)?.raw_value)}</td>)}
          </tr>)}</tbody>
        </table>
      </div>

      {isMappingConflict ? (
        <div className="decision-panel">
          <h2>Sichere nächste Schritte</h2>
          <p>Bei einer fehlerhaften Produkt-Verknüpfung kann kein Wert automatisch übernommen werden.</p>
          <div className="decision-buttons">
            <button className="primary-button" type="button" onClick={retryWix}>Wix erneut prüfen</button>
            <button type="button" onClick={later}>Eine Woche später erinnern</button>
          </div>
        </div>
      ) : (
        <div className="decision-panel">
          <h2>Welcher Wert ist fachlich richtig?</h2>
          <div className="decision-buttons">
            {sources.map((source) => <button type="button" key={source} onClick={() => decide(`USE_${source.toUpperCase()}`, source)}>{source === "hub" ? "Product Hub" : source} übernehmen</button>)}
          </div>
          <div className="custom-decision"><input value={custom} onChange={(event) => setCustom(event.target.value)} placeholder="Eigener Wert" /><button type="button" onClick={() => decide("CUSTOM_VALUE")}>Eigenen Wert verwenden</button></div>
          <div className="secondary-actions"><button type="button" onClick={() => decide("INTENTIONAL_DIFFERENCE")}>Unterschied ist beabsichtigt</button><button type="button" onClick={later}>Eine Woche später</button><button type="button" onClick={() => decide("IGNORE")}>Ignorieren</button></div>
        </div>
      )}

      <div className="ai-advice-panel">
        <div><h2>Optionaler KI-Ratgeber</h2><p className="hint">Erklärt nur und macht einen Vorschlag. Die KI kann nichts speichern oder ausführen.</p></div>
        <button type="button" onClick={askAi} disabled={adviceLoading}>{adviceLoading ? "KI prüft …" : "Mit KI erklären"}</button>
        {advice && <div className="ai-advice-result">
          <p className="ai-label">KI-Vorschlag – nicht automatisch übernommen</p>
          <h3>{advice.title}</h3><p>{advice.explanation}</p>
          <h4>Empfehlung</h4><p>{advice.recommendation}</p>
          {advice.next_steps.length > 0 && <ol>{advice.next_steps.map((step) => <li key={step}>{step}</li>)}</ol>}
          {advice.warnings.map((warning) => <p className="hint-error" key={warning}>{warning}</p>)}
          <details><summary>Belege und Einschätzung</summary><p>Vertrauen: {CONFIDENCE_LABELS[advice.confidence]}</p><ul>{advice.evidence.map((evidence) => <li key={evidence}>{evidence}</li>)}</ul></details>
        </div>}
      </div>

      {actions.length > 0 && <div className="impact-panel"><h2>Vorschau der Änderungen</h2>{actions.map((action) => <div className="impact-row" key={action.id}><span>{action.channel}</span><span>{displayConflictValue(action.field_path ?? "", action.before_value)} → {displayConflictValue(action.field_path ?? "", action.after_value)}</span><StatusBadge label={action.status} tone={action.status === "VERIFIED" ? "ok" : action.status === "SKIPPED" || action.status === "FAILED" ? "bad" : "warn"} />{action.error && <span className="hint-error">{action.error}</span>}</div>)}<button className="primary-button" type="button" onClick={apply} disabled={!actions.some((action) => action.selected && action.status === "PLANNED")}>Ausgewählte Änderungen ausführen</button></div>}

      <details className="technical-details"><summary>Technische Details anzeigen</summary>
        {item.fields.map((field) => <div key={field.id}><h3>{field.field_path}</h3>{field.observations.map((observation) => <div key={observation.id}><strong>{observation.source}</strong><pre>{technicalValue(observation.raw_value)}</pre></div>)}</div>)}
      </details>
      {message && <p className="hint">{message}</p>}
    </section>
  );
}
