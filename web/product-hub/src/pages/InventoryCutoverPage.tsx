import { useState } from "react";
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
  const [baselineReload, setBaselineReload] = useState(0);
  const [baselineMessage, setBaselineMessage] = useState("");
  const [applying, setApplying] = useState(false);
  const baseline = useApi(api.getLegacyInventoryBaselinePreview, [baselineReload], onUnauthorized);
  const shadowConflicts = useApi(api.getLegacyInventoryShadowConflicts, [baselineReload], onUnauthorized);

  async function applyBaseline() {
    if (!baseline.data) return;
    const ready = baseline.data.items.filter((item) => item.status === "ready");
    if (!ready.length) return;
    if (!window.confirm(
      `${ready.length} geprüfte Legacy-Bestände einmalig als Hub-Ledger-Baseline schreiben?\n\n` +
      "Die Legacy-Daten bleiben unverändert. Bereits initialisierte oder nicht zuordenbare SKUs werden nicht geschrieben.",
    )) return;
    setApplying(true);
    setBaselineMessage("Baseline wird geschrieben ...");
    try {
      const applied = await api.applyLegacyInventoryBaseline(baseline.data.source_hash);
      setBaselineMessage(`Erfolg: ${applied.applied_skus.length} SKU(s) als Ledger-Baseline übernommen. ${applied.blocked_items.length} Position(en) blieben bewusst blockiert.`);
      setBaselineReload((value) => value + 1);
    } catch (error) {
      setBaselineMessage(error instanceof Error ? error.message : String(error));
    } finally { setApplying(false); }
  }

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
      <p className="hint">Der Master-Schalter wird ausschließlich über die Deploy-Konfiguration gesetzt. Nur die unten ausdrücklich bestätigte Baseline schreibt Hub-Ledger-Daten; Wix und sevdesk bleiben unverändert.</p>
      <article className="decision-panel">
        <h2>Legacy-Bestandsbaseline</h2>
        <p>Vorschau aus <code>inventory.stock_levels</code>. Nur exakt zuordenbare, noch nicht initialisierte Hub-Varianten können übernommen werden.</p>
        {baseline.loading && <p className="hint">Legacy-Bestände werden geprüft ...</p>}
        {baseline.error && <p className="hint-error">{baseline.error}</p>}
        {baselineMessage && <p className="hint">{baselineMessage}</p>}
        {baseline.data && <>
          {!baseline.data.shadow_enabled && <p className="hint-error">Shadow Mode ist deaktiviert. Die Vorschau ist sicher; die Übernahme bleibt gesperrt, bis <code>XW_PRODUCT_HUB_INVENTORY_SHADOW_ENABLED=true</code> im Deploy gesetzt ist.</p>}
          {!baseline.data.source_present && <p className="hint-error">Kein Legacy-Bestandsbestand unter <code>inventory.stock_levels</code> gefunden.</p>}
          <table className="data-table"><thead><tr><th>SKU</th><th>Legacy</th><th>Hub-Produkt</th><th>Status</th><th>Prüfung</th></tr></thead><tbody>
            {baseline.data.items.map((item) => <tr key={`${item.sku}:${item.status}`}><td>{item.sku || "—"}</td><td>{item.legacy_on_hand ?? "—"}</td><td>{item.product_name || "—"}</td><td><StatusBadge label={stateLabel(item.status === "ready" ? "ready" : "blocked")} tone={item.status === "ready" ? "ok" : "bad"} /></td><td className="hint">{item.detail}</td></tr>)}
            {!baseline.data.items.length && <tr><td colSpan={5} className="hint">Keine Legacy-Positionen vorhanden.</td></tr>}
          </tbody></table>
          <div className="decision-buttons"><button className="primary-button" type="button" disabled={applying || !baseline.data.shadow_enabled || !baseline.data.items.some((item) => item.status === "ready")} onClick={applyBaseline}>{applying ? "Baseline wird geschrieben ..." : "Geprüfte Baseline übernehmen"}</button><button type="button" disabled={applying} onClick={() => setBaselineReload((value) => value + 1)}>Vorschau aktualisieren</button></div>
        </>}
      </article>
      <article className="decision-panel">
        <h2>Offene Shadow-Abweichungen</h2>
        <p>Diese Queue entsteht, wenn eine abgeschlossene Legacy-Bestandsänderung nicht vollständig im Hub-Ledger gespiegelt werden konnte. Sie wird erst nach einem erfolgreichen absoluten Bestandsabgleich automatisch geschlossen.</p>
        {shadowConflicts.loading && <p className="hint">Shadow-Abweichungen werden geladen ...</p>}
        {shadowConflicts.error && <p className="hint-error">{shadowConflicts.error}</p>}
        {shadowConflicts.data && <table className="data-table"><thead><tr><th>SKU</th><th>Hub-Produkt</th><th>Grund</th><th>Details</th><th>Erkannt</th></tr></thead><tbody>
          {shadowConflicts.data.map((item) => <tr key={item.id}>
            <td>{item.sku || "—"}</td>
            <td>{item.product_id ? <Link to={`/products/${item.product_id}`}>{item.product_name}{item.variant_name ? ` · ${item.variant_name}` : ""}</Link> : item.product_name}</td>
            <td><StatusBadge label={item.status} tone="bad" /></td>
            <td className="hint">{item.detail}</td>
            <td className="hint">{new Date(item.detected_at).toLocaleString("de-AT")}</td>
          </tr>)}
          {!shadowConflicts.data.length && <tr><td colSpan={5} className="hint">Keine offenen Shadow-Abweichungen. Erfolgreiche Spiegelungen werden weiterhin protokolliert.</td></tr>}
        </tbody></table>}
        <p className="hint">Nicht blind schließen: Bei Unterdeckung zuerst den tatsächlichen Legacy- und Hub-Bestand prüfen; bei fehlender Baseline die geprüfte Baseline oben übernehmen.</p>
      </article>
    </>}
  </section>;
}
