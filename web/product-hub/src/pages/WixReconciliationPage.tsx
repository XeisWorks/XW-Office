import { useState } from "react";
import { Link } from "react-router-dom";
import { api, ApiError } from "../api/client";
import type { WixOnlyProduct, WixOnlyVariant } from "../api/types";
import { useApi } from "../hooks/useApi";

export default function WixReconciliationPage({ onUnauthorized }: { onUnauthorized: () => void }) {
  const [reload, setReload] = useState(0);
  const [showDeferred, setShowDeferred] = useState(false);
  const [message, setMessage] = useState("");
  const [busy, setBusy] = useState("");
  const result = useApi(() => api.getWixOnlyReconciliation(showDeferred), [reload, showDeferred], onUnauthorized);

  function handleError(error: unknown) {
    if (error instanceof ApiError && error.status === 401) onUnauthorized();
    setMessage(error instanceof Error ? error.message : String(error));
  }

  async function link(productId: string, externalId: string, sku: string, variantExternalId?: string) {
    if (!window.confirm(`Wix-SKU ${sku} mit dem vorgeschlagenen Hub-Produkt verknüpfen? Wix selbst wird nicht geändert.`)) return;
    setBusy(`${externalId}:${variantExternalId || "product"}`);
    try {
      await api.linkWixOnlyReconciliation(productId, externalId, sku, variantExternalId);
      setMessage(`Wix-SKU ${sku} wurde mit dem Hub verknüpft.`);
      setReload((value) => value + 1);
    } catch (error) { handleError(error); }
    finally { setBusy(""); }
  }

  async function importDraft(externalId: string, sku: string, name: string, variantExternalId?: string) {
    if (!window.confirm(
      `Für „${name}“ mit SKU ${sku} einen Hub-Entwurf anlegen und verknüpfen?\n\n` +
      "Es werden nur Name, SKU und die Wix-Verknüpfung angelegt. Preise, Bilder, Texte und Sichtbarkeit werden nicht kopiert; Wix bleibt unverändert.",
    )) return;
    setBusy(`${externalId}:${variantExternalId || "product"}`);
    try {
      const created = await api.importWixOnlyReconciliation(externalId, sku, name, variantExternalId);
      setMessage(`Erfolg: Hub-Entwurf „${created.product_name}“ wurde angelegt und verknüpft. Bitte Inhalte und Freigabe im Hub ergänzen.`);
      setReload((value) => value + 1);
    } catch (error) { handleError(error); }
    finally { setBusy(""); }
  }

  async function setDisposition(
    externalId: string,
    disposition: "active" | "deferred" | "ignored",
    variantExternalId?: string,
  ) {
    const key = `${externalId}:${variantExternalId || "product"}`;
    const label = disposition === "ignored" ? "dauerhaft ausblenden" : disposition === "deferred" ? "30 Tage zurückstellen" : "wieder in die Arbeitsliste aufnehmen";
    if (!window.confirm(`${label}? Wix wird dabei nicht geändert.`)) return;
    setBusy(key);
    try {
      const deferredUntil = disposition === "deferred"
        ? new Date(Date.now() + 30 * 24 * 60 * 60 * 1000).toISOString()
        : undefined;
      await api.setWixOnlyReconciliationDisposition(externalId, disposition, variantExternalId, deferredUntil);
      setMessage(disposition === "ignored"
        ? "Position dauerhaft ausgeblendet. Sie bleibt über ‚Ausgeblendete anzeigen‘ wieder aktivierbar."
        : disposition === "deferred"
          ? "Position wurde für 30 Tage zurückgestellt. Wix blieb unverändert."
          : "Position ist wieder in der regulären Arbeitsliste.");
      setReload((value) => value + 1);
    } catch (error) { handleError(error); }
    finally { setBusy(""); }
  }

  function actions(entry: WixOnlyProduct | WixOnlyVariant, parentId: string, parentName: string, variant = false) {
    const key = `${parentId}:${variant ? entry.external_id : "product"}`;
    const sku = entry.sku;
    const variantId = variant ? entry.external_id : undefined;
    if (entry.disposition !== "active") return <div className="mapping-candidate-actions">
      <span className="hint">{entry.disposition === "ignored" ? "Dauerhaft ausgeblendet" : `Zurückgestellt bis ${new Date(entry.deferred_until!).toLocaleDateString("de-AT")}`}</span>
      <button type="button" disabled={busy === key} onClick={() => setDisposition(parentId, "active", variantId)}>Wieder aufnehmen</button>
    </div>;
    return <div className="mapping-candidate-actions">
      {!sku ? <span className="hint">Ohne SKU: keine automatische Verknüpfung oder Anlage.</span>
        : entry.suggested_hub_product_id
        ? <button type="button" disabled={busy === key} onClick={() => link(entry.suggested_hub_product_id!, parentId, sku, variantId)}>Mit „{entry.suggested_hub_product_name}“ verknüpfen</button>
        : <button className="primary-button" type="button" disabled={busy === key} onClick={() => importDraft(parentId, sku, variant ? `${parentName} – ${entry.name || sku}` : entry.name || sku, variantId)}>Als Hub-Entwurf übernehmen</button>}
      <button type="button" disabled={busy === key} onClick={() => setDisposition(parentId, "deferred", variantId)}>In 30 Tagen prüfen</button>
      <button type="button" disabled={busy === key} onClick={() => setDisposition(parentId, "ignored", variantId)}>Dauerhaft ausblenden</button>
    </div>;
  }

  return <section>
    <Link to="/conflicts">← Zur Konfliktliste</Link>
    <div className="conflict-heading"><div><h1>Wix-only-Abgleich</h1><p>Wix-Produkte und Varianten ohne Hub-Verknüpfung</p></div><button type="button" onClick={() => setReload((value) => value + 1)}>Liste aktualisieren</button></div>
    {message && <p className="hint">{message}</p>}
    {result.loading && <p className="hint">Wix-Katalog wird geladen …</p>}
    {result.error && <p className="hint-error">{result.error}</p>}
    {result.data && <>
      <p className="hint">{result.data.total_products} Wix-Produkte mit offenen Zuordnungen · {result.data.total_variants} Wix-Varianten ohne eigene Hub-Verknüpfung</p>
      <label className="reconciliation-toggle"><input type="checkbox" checked={showDeferred} onChange={(event) => setShowDeferred(event.target.checked)} /> Ausgeblendete anzeigen ({result.data.deferred_items} zurückgestellt, {result.data.ignored_items} ignoriert)</label>
      <div className="reconciliation-list">{result.data.items.map((item) => <article className="mapping-comparison" key={item.external_id}>
        <h2>{item.name || "Ohne Produktname"}</h2>
        <div className="mapping-candidate"><div><strong>Wix-Produkt</strong><span>{item.sku || "ohne eigene SKU"}</span><span className="mapping-id">{item.external_id}</span></div>{!item.parent_mapped && actions(item, item.external_id, item.name)}</div>
        {item.variants.length > 0 && <div className="mapping-candidate-list"><h3>Nicht einzeln verknüpfte Varianten</h3>{item.variants.map((variant) => <div className="mapping-candidate" key={variant.external_id}><div><strong>{variant.name || "Variante"}</strong><span>{variant.sku || "ohne SKU"}</span><span className="mapping-id">{variant.external_id}</span></div>{actions(variant, item.external_id, item.name, true)}</div>)}</div>}
      </article>)}</div>
      {!result.data.items.length && <p className="hint">Alle aktuell erreichbaren Wix-Positionen sind verknüpft.</p>}
    </>}
  </section>;
}
