import { useState } from "react";
import { Link } from "react-router-dom";
import { api, ApiError } from "../api/client";
import type { WixOnlyProduct, WixOnlyVariant } from "../api/types";
import { useApi } from "../hooks/useApi";

export default function WixReconciliationPage({ onUnauthorized }: { onUnauthorized: () => void }) {
  const [reload, setReload] = useState(0);
  const [message, setMessage] = useState("");
  const [busy, setBusy] = useState("");
  const result = useApi(api.getWixOnlyReconciliation, [reload], onUnauthorized);

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
    if (!window.confirm(`Für „${name}“ mit SKU ${sku} einen Hub-Entwurf anlegen und verknüpfen?`)) return;
    setBusy(`${externalId}:${variantExternalId || "product"}`);
    try {
      const created = await api.importWixOnlyReconciliation(externalId, sku, name, variantExternalId);
      setMessage(`Hub-Entwurf „${created.product_name}“ wurde angelegt und verknüpft.`);
      setReload((value) => value + 1);
    } catch (error) { handleError(error); }
    finally { setBusy(""); }
  }

  function actions(entry: WixOnlyProduct | WixOnlyVariant, parentId: string, parentName: string, variant = false) {
    const key = `${parentId}:${variant ? entry.external_id : "product"}`;
    const sku = entry.sku;
    if (!sku) return <span className="hint">Ohne SKU: nur manuelle Prüfung möglich.</span>;
    return <div className="mapping-candidate-actions">
      {entry.suggested_hub_product_id
        ? <button type="button" disabled={busy === key} onClick={() => link(entry.suggested_hub_product_id!, parentId, sku, variant ? entry.external_id : undefined)}>Mit „{entry.suggested_hub_product_name}“ verknüpfen</button>
        : <button className="primary-button" type="button" disabled={busy === key} onClick={() => importDraft(parentId, sku, variant ? `${parentName} – ${entry.name || sku}` : entry.name || sku, variant ? entry.external_id : undefined)}>Als Hub-Entwurf übernehmen</button>}
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
      <div className="reconciliation-list">{result.data.items.map((item) => <article className="mapping-comparison" key={item.external_id}>
        <h2>{item.name || "Ohne Produktname"}</h2>
        <div className="mapping-candidate"><div><strong>Wix-Produkt</strong><span>{item.sku || "ohne eigene SKU"}</span><span className="mapping-id">{item.external_id}</span></div>{!item.parent_mapped && actions(item, item.external_id, item.name)}</div>
        {item.variants.length > 0 && <div className="mapping-candidate-list"><h3>Nicht einzeln verknüpfte Varianten</h3>{item.variants.map((variant) => <div className="mapping-candidate" key={variant.external_id}><div><strong>{variant.name || "Variante"}</strong><span>{variant.sku || "ohne SKU"}</span><span className="mapping-id">{variant.external_id}</span></div>{actions(variant, item.external_id, item.name, true)}</div>)}</div>}
      </article>)}</div>
      {!result.data.items.length && <p className="hint">Alle aktuell erreichbaren Wix-Positionen sind verknüpft.</p>}
    </>}
  </section>;
}
