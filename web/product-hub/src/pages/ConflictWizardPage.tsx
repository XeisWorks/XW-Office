import { useEffect, useRef, useState } from "react";
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

export default function ConflictWizardPage({ onUnauthorized }: { onUnauthorized: () => void }) {
  const { id } = useParams();
  const navigate = useNavigate();
  const [item, setItem] = useState<ConflictCaseDetail | null>(null);
  const [actions, setActions] = useState<ConflictAction[]>([]);
  const [advice, setAdvice] = useState<ConflictAdvice | null>(null);
  const [adviceLoading, setAdviceLoading] = useState(false);
  const [remappingId, setRemappingId] = useState<string | null>(null);
  const [custom, setCustom] = useState("");
  const [message, setMessage] = useState("");
  const adviceRequestFor = useRef<string | null>(null);

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
    if (adviceRequestFor.current !== id) {
      adviceRequestFor.current = id;
      void loadAdvice(id);
    }
  }

  useEffect(() => {
    adviceRequestFor.current = null;
    load().catch(handleError);
  }, [id]); // eslint-disable-line react-hooks/exhaustive-deps

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
      adviceRequestFor.current = null;
      await load();
      setMessage("Wix-Prüfung abgeschlossen.");
    } catch (error) { handleError(error); }
  }

  async function loadAdvice(caseId: string) {
    setAdviceLoading(true); setMessage("");
    try {
      const result = await api.getConflictAdvice(caseId);
      if (adviceRequestFor.current === caseId) setAdvice(result);
    }
    catch (error) { handleError(error); }
    finally { if (adviceRequestFor.current === caseId) setAdviceLoading(false); }
  }

  async function remapMapping(externalId: string, productName: string) {
    if (!item || !id) return;
    const confirmed = window.confirm(
      `Wix-Mapping auf „${productName}“ (${externalId}) umstellen?\n\n` +
      "Es werden keine Wix-Daten geändert. Nur die Verknüpfung im Product Hub wird ersetzt.",
    );
    if (!confirmed) return;
    setRemappingId(externalId); setMessage("Wix-Kandidat wird nochmals verifiziert …");
    try {
      await api.remapConflict(id, item.row_version, externalId);
      await load();
      setMessage("Mapping geändert und Fall abgeschlossen. Bitte anschließend den Wix-Abgleich starten.");
    } catch (error) { handleError(error); }
    finally { setRemappingId(null); }
  }

  if (!item) return <section><h1>Konflikt-Assistent</h1><p className="hint">{message || "Fall wird geladen …"}</p></section>;

  const guidance = deterministicGuidance(item);
  const isMappingConflict = item.conflict_type === "WRONG_PRODUCT_MAPPING";
  const sources = Array.from(new Set(item.fields.flatMap((field) => field.observations.map((obs) => obs.source))));
  const comparison = advice?.mapping_comparison;
  const preferredCandidate = comparison?.candidate ?? advice?.mapping_candidates[0] ?? null;
  const otherCandidates = advice?.mapping_candidates.filter((candidate) => candidate.external_id !== preferredCandidate?.external_id) ?? [];
  const oldMappingStatus = comparison?.old_status === "not_found" ? "Bei Wix nicht gefunden" : "Nicht abrufbar";

  return (
    <section>
      <Link to="/conflicts">← Zur Konfliktliste</Link>
      <div className="conflict-heading">
        <div><h1>{item.product_sku} · {item.product_name}</h1><p>{conflictTypeLabel(item.conflict_type)}</p></div>
        <StatusBadge label={item.severity} tone={item.severity === "CRITICAL" || item.severity === "HIGH" ? "bad" : item.severity === "MEDIUM" ? "warn" : "neutral"} />
      </div>

      {isMappingConflict ? (
        <>
          <article className="mapping-comparison" aria-label="Vergleich der Wix-Verknüpfung">
            <h2>Vergleich</h2>
            {adviceLoading && <p className="hint">KI prüft die Wix-Verknüpfung und sucht passende Produkte …</p>}
            {comparison && <div className="mapping-comparison-grid">
              <div className="mapping-side mapping-side-old">
                <span className="comparison-label">Bisher</span>
                <strong>{comparison.hub_name || item.product_name}</strong>
                <span>{comparison.hub_sku || item.product_sku}</span>
                <span className="mapping-id">{comparison.old_external_id || "Keine Wix-ID gespeichert"}</span>
                <p>{oldMappingStatus}</p>
                <small>{comparison.hub_description || "Keine Produktbeschreibung im Product Hub."}</small>
              </div>
              <div className="mapping-side mapping-side-new">
                <span className="comparison-label">Vorschlag{preferredCandidate ? ` · ${preferredCandidate.score}%` : ""}</span>
                {preferredCandidate ? <>
                  <strong>{preferredCandidate.name || "Ohne Produktname"}</strong>
                  <span>{preferredCandidate.sku || "ohne SKU"}</span>
                  <span className="mapping-id">{preferredCandidate.external_id}</span>
                  <p>{preferredCandidate.match_reasons.join(" · ")}</p>
                  <small>{preferredCandidate.description || "Beschreibung in Wix nicht verfügbar."}</small>
                  <button className="primary-button preferred-mapping-button" type="button" disabled={remappingId !== null} onClick={() => remapMapping(preferredCandidate.external_id, preferredCandidate.name)}>
                    {remappingId === preferredCandidate.external_id ? "Wird verifiziert …" : "Vorschlag übernehmen"}
                  </button>
                </> : <p>{advice?.mapping_search_status === "unavailable" ? "Wix-Suche nicht verfügbar." : "Kein eindeutiger Wix-Kandidat gefunden."}</p>}
              </div>
            </div>}
          </article>

          {otherCandidates.length > 0 && <details className="alternative-candidates">
            <summary>Weitere mögliche Produkte ({otherCandidates.length})</summary>
            <div className="mapping-candidate-list">{otherCandidates.map((candidate) => <div className="mapping-candidate" key={candidate.external_id}>
              <div><strong>{candidate.name || "Ohne Produktname"}</strong><span className="hint">{candidate.sku || "ohne SKU"} · {candidate.score}%</span><span className="mapping-id">{candidate.external_id}</span></div>
              <button type="button" disabled={remappingId !== null} onClick={() => remapMapping(candidate.external_id, candidate.name)}>Diesen Vorschlag wählen</button>
            </div>)}</div>
          </details>}

          <div className="decision-panel compact-decision-panel">
            <div className="decision-buttons"><button type="button" onClick={retryWix}>Wix erneut prüfen</button></div>
            <details><summary>Weitere Aktionen</summary><div className="secondary-actions"><button type="button" onClick={() => decide("INTENTIONAL_DIFFERENCE")}>Als Ausnahme markieren</button><button type="button" onClick={later}>In einer Woche erinnern</button><button type="button" onClick={() => decide("IGNORE")}>Ignorieren</button></div></details>
          </div>
        </>
      ) : (
        <>
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
          <div className="decision-panel">
            <h2>Welcher Wert ist fachlich richtig?</h2>
            <div className="decision-buttons">
              {sources.map((source) => <button type="button" key={source} onClick={() => decide(`USE_${source.toUpperCase()}`, source)}>{source === "hub" ? "Product Hub" : source} übernehmen</button>)}
            </div>
            <div className="custom-decision"><input value={custom} onChange={(event) => setCustom(event.target.value)} placeholder="Eigener Wert" /><button type="button" onClick={() => decide("CUSTOM_VALUE")}>Eigenen Wert verwenden</button></div>
            <div className="secondary-actions"><button type="button" onClick={() => decide("INTENTIONAL_DIFFERENCE")}>Unterschied ist beabsichtigt</button><button type="button" onClick={later}>Eine Woche später</button><button type="button" onClick={() => decide("IGNORE")}>Ignorieren</button></div>
          </div>
        </>
      )}

      <div className="ai-advice-panel compact-ai-advice">
        <h2>KI-Empfehlung</h2>
        {adviceLoading && <p className="hint">Wird automatisch erstellt …</p>}
        {advice && <p>{advice.recommendation || advice.explanation}</p>}
      </div>

      {actions.length > 0 && <div className="impact-panel"><h2>Vorschau der Änderungen</h2>{actions.map((action) => <div className="impact-row" key={action.id}><span>{action.channel}</span><span>{displayConflictValue(action.field_path ?? "", action.before_value)} → {displayConflictValue(action.field_path ?? "", action.after_value)}</span><StatusBadge label={action.status} tone={action.status === "VERIFIED" ? "ok" : action.status === "SKIPPED" || action.status === "FAILED" ? "bad" : "warn"} />{action.error && <span className="hint-error">{action.error}</span>}</div>)}<button className="primary-button" type="button" onClick={apply} disabled={!actions.some((action) => action.selected && action.status === "PLANNED")}>Ausgewählte Änderungen ausführen</button></div>}

      <details className="technical-details"><summary>Technische Details anzeigen</summary>
        {item.fields.map((field) => <div key={field.id}><h3>{field.field_path}</h3>{field.observations.map((observation) => <div key={observation.id}><strong>{observation.source}</strong><pre>{technicalValue(observation.raw_value)}</pre></div>)}</div>)}
      </details>
      {message && <p className="hint">{message}</p>}
    </section>
  );
}
