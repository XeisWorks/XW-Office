import { useEffect, useRef, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { api, ApiError } from "../api/client";
import type { ConflictAction, ConflictAdvice, ConflictCaseDetail, ConflictMappingCandidate, ConflictMappingOwner } from "../api/types";
import StatusBadge from "../components/StatusBadge";
import {
  conflictFieldLabel,
  conflictTypeLabel,
  deterministicGuidance,
  displayConflictValue,
  technicalValue,
} from "../utils/conflictPresentation";

type DuplicateWixSkuEntry = {
  external_id: string;
  name: string;
  sku: string;
  variant_external_id: string;
  variant_name: string;
};

function duplicateWixSkuEntries(item: ConflictCaseDetail): DuplicateWixSkuEntry[] {
  const raw = item.fields.flatMap((field) => field.observations)
    .find((observation) => observation.source === "wix")?.raw_value;
  if (!raw || typeof raw !== "object" || Array.isArray(raw)) return [];
  const matches = (raw as { matches?: unknown }).matches;
  if (!Array.isArray(matches)) return [];
  return matches.flatMap((match): DuplicateWixSkuEntry[] => {
    if (!match || typeof match !== "object" || Array.isArray(match)) return [];
    const row = match as Record<string, unknown>;
    const externalId = String(row.external_id ?? "").trim();
    const sku = String(row.sku ?? "").trim();
    if (!externalId || !sku) return [];
    return [{
      external_id: externalId,
      name: String(row.name ?? "").trim(),
      sku,
      variant_external_id: String(row.variant_external_id ?? "").trim(),
      variant_name: String(row.variant_name ?? "").trim(),
    }];
  });
}

export default function ConflictWizardPage({ onUnauthorized }: { onUnauthorized: () => void }) {
  const { id } = useParams();
  const navigate = useNavigate();
  const [item, setItem] = useState<ConflictCaseDetail | null>(null);
  const [actions, setActions] = useState<ConflictAction[]>([]);
  const [advice, setAdvice] = useState<ConflictAdvice | null>(null);
  const [adviceLoading, setAdviceLoading] = useState(false);
  const [remappingId, setRemappingId] = useState<string | null>(null);
  const [mappingCollision, setMappingCollision] = useState<{ candidate: ConflictMappingCandidate; owner: ConflictMappingOwner } | null>(null);
  const [transferringMapping, setTransferringMapping] = useState(false);
  const [skuEditCandidate, setSkuEditCandidate] = useState<ConflictMappingCandidate | null>(null);
  const [newWixSku, setNewWixSku] = useState("");
  const [updatingWixSku, setUpdatingWixSku] = useState(false);
  const [destructiveAction, setDestructiveAction] = useState<"create-wix" | "archive-hub" | null>(null);
  const [custom, setCustom] = useState("");
  const [message, setMessage] = useState("");
  const [messageTone, setMessageTone] = useState<"neutral" | "success" | "error">("neutral");
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
    setMessageTone("neutral");
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
    setMessageTone("error");
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
      // The apply response contains the case, but not the updated action rows.
      // Reload them so the confirmation state cannot leave a stale executable button.
      await load();
      setMessage(updated.status === "RESOLVED" ? "Änderung erfolgreich verifiziert und abgeschlossen." : "Änderung erfolgreich angestoßen und sicher in die Wix-Outbox gestellt.");
      setMessageTone("success");
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
    setMessageTone("neutral");
    try {
      await api.scanWixConflicts();
      adviceRequestFor.current = null;
      await load();
      setMessage("Wix-Prüfung abgeschlossen.");
      setMessageTone("success");
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

  async function remapMapping(externalId: string, productName: string, variantExternalId?: string, variantName?: string) {
    if (!item || !id) return;
    const candidate: ConflictMappingCandidate = {
      external_id: externalId, name: productName, sku: item.product_sku,
      variant_external_id: variantExternalId || "", variant_name: variantName || "",
      score: 0, match_reasons: [], description: "", product_type: "",
    };
    try {
      setMessage("Bestehende Hub-Zuordnungen werden geprüft …");
      setMessageTone("neutral");
      const owner = await api.getConflictMappingOwner(id, externalId, variantExternalId);
      if (owner.found) {
        setMappingCollision({ candidate, owner });
        setMessage("");
        return;
      }
    } catch (error) { handleError(error); return; }
    const confirmed = window.confirm(
      `Wix-Mapping auf „${productName}“${variantName ? ` – ${variantName}` : ""} (${externalId}) umstellen?\n\n` +
      "Es werden keine Wix-Daten geändert. Nur die Verknüpfung im Product Hub wird ersetzt.",
    );
    if (!confirmed) return;
    setRemappingId(externalId); setMessage("Wix-Kandidat wird nochmals verifiziert …");
    try {
      await api.remapConflict(id, item.row_version, externalId, variantExternalId);
      await load();
      setMessage("Mapping geändert und Fall abgeschlossen. Bitte anschließend den Wix-Abgleich starten.");
    } catch (error) { handleError(error); }
    finally { setRemappingId(null); }
  }

  async function transferMapping() {
    if (!item || !id || !mappingCollision) return;
    const { candidate, owner } = mappingCollision;
    const target = candidate.variant_name ? `${candidate.name} – ${candidate.variant_name}` : candidate.name;
    const confirmed = window.confirm(
      `Die Wix-Zuordnung von „${owner.product_name}“ (${owner.product_sku}) auf „${item.product_name}“ (${item.product_sku}) übertragen?\n\n` +
      `Die bisherige Hub-Zuordnung wird entfernt. In Wix selbst wird nichts geändert.`,
    );
    if (!confirmed) return;
    setTransferringMapping(true);
    setMessage("Wix-Zuordnung wird kontrolliert übertragen …");
    setMessageTone("neutral");
    try {
      await api.transferWixMappingForConflict(id, item.row_version, candidate.external_id, candidate.variant_external_id || undefined);
      setMappingCollision(null);
      await load();
      setMessage(`Wix-Zuordnung „${target}“ wurde von ${owner.product_name} auf dieses Hub-Produkt übertragen. Der bisherige Datensatz wird beim nächsten Abgleich als nicht verknüpft erkannt.`);
      setMessageTone("success");
    } catch (error) { handleError(error); }
    finally { setTransferringMapping(false); }
  }

  function startWixSkuEdit(candidate: ConflictMappingCandidate) {
    if (!candidate.variant_external_id) {
      setMessage("Diese Wix-Position ist keine eindeutig erkennbare Variante; die SKU kann hier nicht sicher geändert werden.");
      setMessageTone("error");
      return;
    }
    setSkuEditCandidate(candidate);
    setNewWixSku(candidate.sku);
    setMessage("");
  }

  async function updateWixSku() {
    if (!item || !id || !skuEditCandidate || !skuEditCandidate.variant_external_id) return;
    const cleanSku = newWixSku.trim();
    if (!cleanSku) {
      setMessage("Bitte eine neue SKU eingeben.");
      setMessageTone("error");
      return;
    }
    const confirmed = window.confirm(
      `Wix-SKU der Variante „${skuEditCandidate.variant_name || skuEditCandidate.name}“ wirklich von ${skuEditCandidate.sku} auf ${cleanSku} ändern?\n\n` +
      "Der Product Hub wird dabei nicht verändert. Vor dem Speichern prüft der Hub, ob die neue SKU in Wix bereits vergeben ist.",
    );
    if (!confirmed) return;
    setUpdatingWixSku(true);
    setMessage("Wix-SKU wird auf Eindeutigkeit geprüft und geändert …");
    setMessageTone("neutral");
    try {
      const result = await api.updateWixVariantSkuForConflict(
        id,
        item.row_version,
        skuEditCandidate.external_id,
        skuEditCandidate.variant_external_id,
        skuEditCandidate.sku,
        cleanSku,
      );
      setSkuEditCandidate(null);
      setNewWixSku("");
      adviceRequestFor.current = null;
      if (item.conflict_type === "DUPLICATE_SKU") await api.scanWixConflicts();
      await load();
      setMessage(`Wix-Variante erfolgreich geändert: ${result.previous_sku} → ${result.sku} (Catalog ${result.catalog_version.toUpperCase()}).${item.conflict_type === "DUPLICATE_SKU" ? " Der Wix-Abgleich wurde erneut ausgeführt." : ""}`);
      setMessageTone("success");
    } catch (error) { handleError(error); }
    finally { setUpdatingWixSku(false); }
  }

  async function createWixProduct() {
    if (!item || !id) return;
    const confirmed = window.confirm(
      `Wix-Entwurf für „${item.product_name}“ mit SKU ${item.product_sku} anlegen?\n\n` +
      "Der Entwurf bleibt in Wix unsichtbar und wird danach mit diesem Hub-Produkt verknüpft.",
    );
    if (!confirmed) return;
    setDestructiveAction("create-wix"); setMessage("Wix-Entwurf wird angelegt …"); setMessageTone("neutral");
    try {
      const result = await api.createWixProductForConflict(id, item.row_version);
      await load();
      const operationMessage = result.operation === "reused_existing"
        ? "Bestehendes Wix-Produkt gefunden und mit dem Hub verknüpft"
        : "Wix-Produkt erstellt und mit dem Hub verknüpft";
      setMessage(`${operationMessage} (Catalog ${result.catalog_version.toUpperCase()}, ID ${result.external_id}). Bitte Inhalte und Sichtbarkeit in Wix prüfen.`);
      setMessageTone("success");
    } catch (error) { handleError(error); }
    finally { setDestructiveAction(null); }
  }

  async function archiveHubProduct() {
    if (!item || !id) return;
    const confirmed = window.confirm(
      `„${item.product_name}“ im Product Hub archivieren?\n\n` +
      "Das Produkt und alle aktiven Varianten werden deaktiviert, aber nicht gelöscht. Bestehende Wix-Verknüpfungen bleiben als Historie erhalten; Wix selbst wird nicht geändert.",
    );
    if (!confirmed) return;
    setDestructiveAction("archive-hub"); setMessage("Produkt wird im Hub archiviert …"); setMessageTone("neutral");
    try {
      const resolved = await api.archiveHubProductForConflict(id, item.row_version);
      setMessage(`Erfolg: ${resolved.resolution_note || "Produkt wurde im Hub archiviert; Wix blieb unverändert."}`);
      setMessageTone("success");
      window.setTimeout(() => navigate("/conflicts"), 1800);
    } catch (error) { handleError(error); }
    finally { setDestructiveAction(null); }
  }

  if (!item) return <section><h1>Konflikt-Assistent</h1><p className="hint">{message || "Fall wird geladen …"}</p></section>;

  const guidance = deterministicGuidance(item);
  const isMappingConflict = item.conflict_type === "WRONG_PRODUCT_MAPPING";
  const isDuplicateSkuConflict = item.conflict_type === "DUPLICATE_SKU";
  const duplicateEntries = isDuplicateSkuConflict ? duplicateWixSkuEntries(item) : [];
  const sources = Array.from(new Set(item.fields.flatMap((field) => field.observations.map((obs) => obs.source))));
  const comparison = advice?.mapping_comparison;
  const preferredCandidate = advice?.mapping_search_status === "ambiguous"
    ? null
    : comparison?.candidate ?? advice?.mapping_candidates[0] ?? null;
  const ambiguousCandidates = advice?.mapping_search_status === "ambiguous"
    ? advice.mapping_candidates.filter((candidate) => candidate.match_reasons.includes("Exakte SKU"))
    : [];
  const otherCandidates = preferredCandidate
    ? advice?.mapping_candidates.filter((candidate) => candidate.external_id !== preferredCandidate.external_id) ?? []
    : [];
  const oldMappingStatus = comparison?.old_status === "not_found"
    ? "Bei Wix nicht gefunden"
    : comparison?.old_status === "unmapped"
      ? "Noch nicht mit Wix verknüpft"
      : "Nicht abrufbar";
  const selectedActions = actions.filter((action) => action.selected);
  const hasPlannedActions = selectedActions.some((action) => action.status === "PLANNED");
  const executionFailed = selectedActions.some((action) => action.status === "FAILED");
  const executionPending = selectedActions.some((action) => action.status === "QUEUED");
  const executionComplete = selectedActions.length > 0 && selectedActions.every((action) => ["VERIFIED", "SKIPPED"].includes(action.status));
  const executionButtonLabel = executionPending
    ? "Ausführung angestoßen – wartet auf Wix"
    : executionFailed
      ? "Fehlgeschlagene Änderungen erneut ausführen"
      : "Ausgewählte Änderungen ausführen";
  const actionRows = actions.map((action) => (
    <div className="impact-row" key={action.id}>
      <span>{action.channel}</span>
      <span>{displayConflictValue(action.field_path ?? "", action.before_value)} → {displayConflictValue(action.field_path ?? "", action.after_value)}</span>
      <StatusBadge label={action.status} tone={action.status === "VERIFIED" ? "ok" : action.status === "SKIPPED" || action.status === "FAILED" ? "bad" : "warn"} />
      {action.error && <span className="hint-error">{action.error}</span>}
    </div>
  ));

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
                <span className="mapping-meta">{comparison.hub_product_type === "digital" ? "Digital" : "Physisch"} · {comparison.hub_active ? "aktiv" : "inaktiv"}{comparison.hub_category ? ` · ${comparison.hub_category}` : ""}</span>
                <small>{comparison.hub_description || "Keine Produktbeschreibung im Product Hub."}</small>
              </div>
              <div className="mapping-side mapping-side-new">
                <span className="comparison-label">{ambiguousCandidates.length > 0 ? "Mögliche Produkte" : "Vorschlag"}{preferredCandidate ? ` · ${preferredCandidate.score}%` : ""}</span>
                {preferredCandidate ? <>
                  <strong>{preferredCandidate.name || "Ohne Produktname"}</strong>
                  {preferredCandidate.variant_name && <span className="mapping-variant-name">{preferredCandidate.variant_name}</span>}
                  <span>{preferredCandidate.sku || "ohne SKU"}</span>
                  <span className="mapping-id">{preferredCandidate.external_id}</span>
                  <p>{preferredCandidate.match_reasons.join(" · ")}</p>
                  {preferredCandidate.product_type && <span className="mapping-meta">{preferredCandidate.product_type === "digital" ? "Digital" : "Physisch"}</span>}
                  {preferredCandidate.description
                    ? <div className="mapping-description" dangerouslySetInnerHTML={{ __html: preferredCandidate.description }} />
                    : <small>Beschreibung in Wix nicht verfügbar.</small>}
                  <button className="primary-button preferred-mapping-button" type="button" disabled={remappingId !== null || destructiveAction !== null} onClick={() => remapMapping(preferredCandidate.external_id, preferredCandidate.name, preferredCandidate.variant_external_id, preferredCandidate.variant_name)}>
                    {remappingId === preferredCandidate.external_id ? "Wird verifiziert …" : "Vorschlag übernehmen"}
                  </button>
                  {preferredCandidate.variant_external_id && <button type="button" disabled={updatingWixSku || destructiveAction !== null} onClick={() => startWixSkuEdit(preferredCandidate)}>SKU in Wix ändern</button>}
                </> : ambiguousCandidates.length > 0 ? <>
                  <p>Mehrere Wix-Produkte verwenden diese SKU. Bitte das fachlich passende Produkt auswählen.</p>
                  <div className="mapping-candidate-list">{ambiguousCandidates.map((candidate) => <div className="mapping-candidate" key={candidate.external_id}>
                    <div><strong>{candidate.name || "Ohne Produktname"}</strong>{candidate.variant_name && <span className="mapping-variant-name">{candidate.variant_name}</span>}<span className="hint">{candidate.sku || "ohne SKU"} · {candidate.score}%</span><span className="mapping-id">{candidate.external_id}</span></div>
                    <div className="mapping-candidate-actions"><button type="button" disabled={remappingId !== null || destructiveAction !== null} onClick={() => remapMapping(candidate.external_id, candidate.name, candidate.variant_external_id, candidate.variant_name)}>Dieses Produkt verknüpfen</button>{candidate.variant_external_id && <button type="button" disabled={updatingWixSku || destructiveAction !== null} onClick={() => startWixSkuEdit(candidate)}>SKU in Wix ändern</button>}</div>
                  </div>)}</div>
                </> : <><p>{advice?.mapping_search_status === "unavailable" ? "Wix-Suche nicht verfügbar." : "Kein eindeutiger Wix-Kandidat gefunden."}</p><Link className="primary-button preferred-mapping-button" to={`/products/${item.product_id}`}>SKU im Hub ändern</Link></>}
              </div>
            </div>}
          </article>

          {mappingCollision && <div className="mapping-collision" role="alert">
            <h2>Wix-Zuordnung ist bereits belegt</h2>
            <p>Die ausgewählte {mappingCollision.candidate.variant_name ? "Wix-Variante" : "Wix-ID"} gehört derzeit zu:</p>
            <p><strong>{mappingCollision.owner.product_name}</strong> · {mappingCollision.owner.product_sku}{mappingCollision.owner.variant_sku ? ` · Variante ${mappingCollision.owner.variant_sku}` : ""}</p>
            <div className="decision-buttons">
              <Link to={`/products/${mappingCollision.owner.product_id}`}>Bestehendes Hub-Produkt anzeigen</Link>
              <button className="danger-button" type="button" disabled={transferringMapping} onClick={transferMapping}>{transferringMapping ? "Wird übertragen …" : mappingCollision.owner.is_current_case_owner ? "Bestehende Zuordnung verwenden" : "Zuordnung hierher übertragen"}</button>
              <button type="button" disabled={transferringMapping} onClick={() => setMappingCollision(null)}>Abbrechen</button>
            </div>
            <small>Die Übertragung ändert keine Wix-Daten. Der bisherige Hub-Datensatz verliert nur diese Wix-Verknüpfung und wird beim nächsten Abgleich erneut geprüft.</small>
          </div>}

          {skuEditCandidate && <div className="custom-decision wix-sku-edit">
            <label htmlFor="wix-variant-sku">Neue Wix-SKU für <strong>{skuEditCandidate.name}</strong>{skuEditCandidate.variant_name ? ` – ${skuEditCandidate.variant_name}` : ""}</label>
            <input id="wix-variant-sku" value={newWixSku} onChange={(event) => setNewWixSku(event.target.value)} maxLength={120} autoFocus />
            <button className="primary-button" type="button" disabled={updatingWixSku} onClick={updateWixSku}>{updatingWixSku ? "Wird in Wix gespeichert …" : "SKU in Wix speichern"}</button>
            <button type="button" disabled={updatingWixSku} onClick={() => { setSkuEditCandidate(null); setNewWixSku(""); }}>Abbrechen</button>
          </div>}

          {otherCandidates.length > 0 && <details className="alternative-candidates">
            <summary>Weitere mögliche Produkte ({otherCandidates.length})</summary>
            <div className="mapping-candidate-list">{otherCandidates.map((candidate) => <div className="mapping-candidate" key={candidate.external_id}>
              <div><strong>{candidate.name || "Ohne Produktname"}</strong>{candidate.variant_name && <span className="mapping-variant-name">{candidate.variant_name}</span>}<span className="hint">{candidate.sku || "ohne SKU"} · {candidate.score}%</span><span className="mapping-id">{candidate.external_id}</span></div>
              <button type="button" disabled={remappingId !== null} onClick={() => remapMapping(candidate.external_id, candidate.name, candidate.variant_external_id, candidate.variant_name)}>Diesen Vorschlag wählen</button>
            </div>)}</div>
          </details>}

          <div className="decision-panel mapping-action-panel">
            <div>
              <h2>Andere Auflösung wählen</h2>
              <p className="hint">Die KI-Empfehlung bleibt hervorgehoben. Wähle hier, wenn das Produkt oder die Verknüpfung anders behandelt werden soll.</p>
            </div>
            <div className="decision-buttons"><button type="button" disabled={destructiveAction !== null} onClick={retryWix}>Wix erneut prüfen</button><Link to={`/products/${item.product_id}`}>Produkt im Hub bearbeiten</Link><button type="button" disabled={destructiveAction !== null} onClick={createWixProduct}>{destructiveAction === "create-wix" ? "Wix-Entwurf wird angelegt …" : "In Wix als Entwurf anlegen"}</button></div>
            <details><summary>Weitere Aktionen</summary><div className="secondary-actions"><button type="button" onClick={() => decide("INTENTIONAL_DIFFERENCE")}>Als Ausnahme markieren</button><button type="button" onClick={later}>In einer Woche erinnern</button><button type="button" onClick={() => decide("IGNORE")}>Ignorieren</button><button className="danger-button" type="button" disabled={destructiveAction !== null} onClick={archiveHubProduct}>{destructiveAction === "archive-hub" ? "Wird archiviert …" : "Produkt im Hub archivieren"}</button></div></details>
          </div>
        </>
      ) : isDuplicateSkuConflict ? (
        <>
          <article className="conflict-explanation" aria-labelledby="duplicate-sku-title">
            <h2 id="duplicate-sku-title">{guidance.title}</h2>
            <p>{guidance.explanation}</p>
            <h3>Betroffene Wix-Positionen</h3>
            {duplicateEntries.length > 0 ? <div className="mapping-candidate-list">{duplicateEntries.map((entry) => (
              <div className="mapping-candidate" key={`${entry.external_id}:${entry.variant_external_id || "product"}`}>
                <div><strong>{entry.name || "Ohne Produktname"}</strong>{entry.variant_name && <span className="mapping-variant-name">{entry.variant_name}</span>}<span className="hint">{entry.sku}</span><span className="mapping-id">{entry.external_id}</span></div>
                <div className="mapping-candidate-actions">{entry.variant_external_id
                  ? <button type="button" disabled={updatingWixSku} onClick={() => startWixSkuEdit({ ...entry, score: 0, match_reasons: [], description: "", product_type: "" })}>SKU in Wix ändern</button>
                  : <span className="hint">Keine eindeutig bearbeitbare Variante</span>}</div>
              </div>
            ))}</div> : <p className="hint">Die Detaildaten werden beim nächsten Wix-Abgleich erneut geladen.</p>}
            <p className="hint">Eine Änderung betrifft nur die ausgewählte Wix-Variante. Der Hub bleibt unverändert.</p>
            <div className="decision-buttons"><button type="button" onClick={retryWix}>Wix erneut prüfen</button><Link to={`/products/${item.product_id}`}>Produkt im Hub bearbeiten</Link></div>
            <details><summary>Weitere Aktionen</summary><div className="secondary-actions"><button type="button" onClick={() => decide("INTENTIONAL_DIFFERENCE")}>Als Ausnahme markieren</button><button type="button" onClick={later}>In einer Woche erinnern</button><button type="button" onClick={() => decide("IGNORE")}>Ignorieren</button><button className="danger-button" type="button" disabled={destructiveAction !== null} onClick={archiveHubProduct}>{destructiveAction === "archive-hub" ? "Wird archiviert …" : "Produkt im Hub archivieren"}</button></div></details>
          </article>

          {skuEditCandidate && <div className="custom-decision wix-sku-edit">
            <label htmlFor="wix-variant-sku">Neue Wix-SKU für <strong>{skuEditCandidate.name}</strong>{skuEditCandidate.variant_name ? ` – ${skuEditCandidate.variant_name}` : ""}</label>
            <input id="wix-variant-sku" value={newWixSku} onChange={(event) => setNewWixSku(event.target.value)} maxLength={120} autoFocus />
            <button className="primary-button" type="button" disabled={updatingWixSku} onClick={updateWixSku}>{updatingWixSku ? "Wird in Wix gespeichert …" : "SKU in Wix speichern"}</button>
            <button type="button" disabled={updatingWixSku} onClick={() => { setSkuEditCandidate(null); setNewWixSku(""); }}>Abbrechen</button>
          </div>}
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

      {actions.length > 0 && <div className="impact-panel"><h2>Vorschau der Änderungen</h2>{actionRows}
        {executionComplete && <div className="execution-confirmation" role="status"><span className="execution-check" aria-hidden="true">✓</span>Ausgewählte Änderungen erfolgreich ausgeführt</div>}
        {!executionComplete && <button className={`primary-button ${executionPending ? "execution-pending" : ""}`} type="button" onClick={apply} disabled={!hasPlannedActions || executionPending}>{executionButtonLabel}</button>}
      </div>}

      <details className="technical-details"><summary>Technische Details anzeigen</summary>
        {item.fields.map((field) => <div key={field.id}><h3>{field.field_path}</h3>{field.observations.map((observation) => <div key={observation.id}><strong>{observation.source}</strong><pre>{technicalValue(observation.raw_value)}</pre></div>)}</div>)}
      </details>
      {message && <p className={messageTone === "success" ? "success-message" : messageTone === "error" ? "error-message" : "hint"} role={messageTone === "error" ? "alert" : "status"}>{message}</p>}
    </section>
  );
}
