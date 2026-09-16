import { useState, type FormEvent } from "react";
import { Link, useParams } from "react-router-dom";
import { api, ConflictApiError } from "../api/client";
import AsyncState from "../components/AsyncState";
import StatusBadge from "../components/StatusBadge";
import { healthTone, readinessTone, syncTone } from "../components/tone";
import { useApi } from "../hooks/useApi";
import type { ProductDetail } from "../api/types";

interface ProductDetailPageProps {
  onUnauthorized: () => void;
}

type TabKey = "variants" | "assets" | "channels" | "improvements" | "audit";

const TABS: { key: TabKey; label: string }[] = [
  { key: "variants", label: "Varianten" },
  { key: "assets", label: "Assets / Print" },
  { key: "channels", label: "Sync / Kanäle" },
  { key: "improvements", label: "Verbesserungen" },
  { key: "audit", label: "Audit-Log" },
];

const SEVERITIES = ["info", "minor", "major", "critical"] as const;

function formatDate(value: string | null): string {
  return value ? new Date(value).toLocaleString("de-DE") : "—";
}

export default function ProductDetailPage({ onUnauthorized }: ProductDetailPageProps) {
  const { id = "" } = useParams<{ id: string }>();
  const [tab, setTab] = useState<TabKey>("variants");
  const [refreshKey, setRefreshKey] = useState(0);
  const refresh = () => setRefreshKey((key) => key + 1);

  const product = useApi(() => api.getProduct(id), [id, refreshKey], onUnauthorized);
  const readiness = useApi(() => api.getReadiness(id), [id, refreshKey], onUnauthorized);
  const variants = useApi(() => api.getVariants(id), [id, refreshKey], onUnauthorized);
  const assets = useApi(() => api.getAssets(id), [id, refreshKey], onUnauthorized);
  const channels = useApi(() => api.getChannels(id), [id, refreshKey], onUnauthorized);
  const tags = useApi(() => api.getTags(id), [id, refreshKey], onUnauthorized);
  const improvements = useApi(() => api.getImprovements(id), [id, refreshKey], onUnauthorized);
  const audit = useApi(() => api.getAudit(id), [id, refreshKey], onUnauthorized);

  // -- product Stammdaten edit form -----------------------------------------------
  const [editingProduct, setEditingProduct] = useState(false);
  const [productForm, setProductForm] = useState<{
    name: string;
    status: string;
    category: string;
    short_description: string;
    description: string;
  } | null>(null);
  const [productSaving, setProductSaving] = useState(false);
  const [productError, setProductError] = useState<string | null>(null);

  function startEditingProduct(current: ProductDetail) {
    setProductForm({
      name: current.name,
      status: current.status,
      category: current.category ?? "",
      short_description: current.short_description ?? "",
      description: current.description ?? "",
    });
    setProductError(null);
    setEditingProduct(true);
  }

  async function handleProductSubmit(event: FormEvent, current: ProductDetail) {
    event.preventDefault();
    if (!productForm) return;
    setProductSaving(true);
    setProductError(null);
    try {
      await api.updateProduct(id, {
        expected_row_version: current.row_version,
        name: productForm.name,
        status: productForm.status,
        category: productForm.category,
        short_description: productForm.short_description,
        description: productForm.description,
      });
      setEditingProduct(false);
      refresh();
    } catch (err) {
      if (err instanceof ConflictApiError) {
        setProductError(
          "Wurde zwischenzeitlich geändert - bitte aktuellen Stand laden und erneut versuchen.",
        );
        refresh();
      } else {
        setProductError(err instanceof Error ? err.message : String(err));
      }
    } finally {
      setProductSaving(false);
    }
  }

  // -- tags ----------------------------------------------------------------------
  const [tagCode, setTagCode] = useState("");
  const [tagError, setTagError] = useState<string | null>(null);

  async function handleAddTag(event: FormEvent) {
    event.preventDefault();
    const code = tagCode.trim().toUpperCase();
    if (!code) return;
    setTagError(null);
    try {
      await api.addTag(id, code);
      setTagCode("");
      refresh();
    } catch (err) {
      setTagError(err instanceof Error ? err.message : String(err));
    }
  }

  async function handleRemoveTag(tagId: string) {
    try {
      await api.removeTag(id, tagId);
      refresh();
    } catch (err) {
      setTagError(err instanceof Error ? err.message : String(err));
    }
  }

  // -- improvements: add + resolve -------------------------------------------------
  const [newImprovement, setNewImprovement] = useState("");
  const [newSeverity, setNewSeverity] = useState<(typeof SEVERITIES)[number]>("minor");
  const [improvementError, setImprovementError] = useState<string | null>(null);

  async function handleAddImprovement(event: FormEvent) {
    event.preventDefault();
    const description = newImprovement.trim();
    if (!description) return;
    setImprovementError(null);
    try {
      await api.createImprovement(id, { description, severity: newSeverity });
      setNewImprovement("");
      refresh();
    } catch (err) {
      setImprovementError(err instanceof Error ? err.message : String(err));
    }
  }

  async function handleResolveImprovement(improvementId: string, rowVersion: number) {
    setImprovementError(null);
    try {
      await api.updateImprovement(id, improvementId, {
        expected_row_version: rowVersion,
        status: "resolved",
      });
      refresh();
    } catch (err) {
      if (err instanceof ConflictApiError) {
        refresh();
      } else {
        setImprovementError(err instanceof Error ? err.message : String(err));
      }
    }
  }

  return (
    <section>
      <p>
        <Link to="/products">&larr; zurück zur Liste</Link>
      </p>

      <AsyncState loading={product.loading} error={product.error} />

      {product.data && (
        <>
          <header className="detail-header">
            {!editingProduct ? (
              <>
                <div className="detail-header-row">
                  <h1>{product.data.name}</h1>
                  <button type="button" onClick={() => startEditingProduct(product.data!)}>
                    Bearbeiten
                  </button>
                </div>
                <p className="detail-sub">
                  {product.data.sku} · {product.data.product_type}
                  {product.data.category ? ` · ${product.data.category}` : ""}
                  {product.data.brand_name ? ` · ${product.data.brand_name}` : ""}
                </p>
                {product.data.short_description && <p>{product.data.short_description}</p>}
              </>
            ) : (
              productForm && (
                <form
                  className="edit-form"
                  onSubmit={(event) => handleProductSubmit(event, product.data!)}
                >
                  <label>
                    Name
                    <input
                      value={productForm.name}
                      onChange={(e) => setProductForm({ ...productForm, name: e.target.value })}
                    />
                  </label>
                  <label>
                    Status
                    <input
                      value={productForm.status}
                      onChange={(e) => setProductForm({ ...productForm, status: e.target.value })}
                    />
                  </label>
                  <label>
                    Kategorie
                    <input
                      value={productForm.category}
                      onChange={(e) => setProductForm({ ...productForm, category: e.target.value })}
                    />
                  </label>
                  <label>
                    Kurzbeschreibung
                    <input
                      value={productForm.short_description}
                      onChange={(e) =>
                        setProductForm({ ...productForm, short_description: e.target.value })
                      }
                    />
                  </label>
                  <label>
                    Beschreibung
                    <textarea
                      value={productForm.description}
                      onChange={(e) =>
                        setProductForm({ ...productForm, description: e.target.value })
                      }
                    />
                  </label>
                  {productError && <p className="hint hint-error">{productError}</p>}
                  <div className="edit-form-actions">
                    <button type="submit" disabled={productSaving}>
                      Speichern
                    </button>
                    <button
                      type="button"
                      className="link-button"
                      onClick={() => setEditingProduct(false)}
                      disabled={productSaving}
                    >
                      Abbrechen
                    </button>
                  </div>
                </form>
              )
            )}
          </header>

          {readiness.data && (
            <div className="readiness-row">
              <StatusBadge label="Wix" tone={readinessTone(readiness.data.wix_ready)} />
              <StatusBadge label="B2B" tone={readinessTone(readiness.data.b2b_ready)} />
              <StatusBadge label="Print" tone={readinessTone(readiness.data.print_ready)} />
              <StatusBadge label="sevdesk" tone={readinessTone(readiness.data.sevdesk_ready)} />
            </div>
          )}

          <div className="tag-row">
            {(tags.data ?? []).map((tag) => (
              <span key={tag.id} className="tag-chip">
                {tag.label}
                <button type="button" onClick={() => handleRemoveTag(tag.id)} aria-label={`${tag.label} entfernen`}>
                  ×
                </button>
              </span>
            ))}
            <form className="tag-add-form" onSubmit={handleAddTag}>
              <input
                placeholder="Tag-Code, z. B. AMAZON"
                value={tagCode}
                onChange={(e) => setTagCode(e.target.value)}
              />
              <button type="submit">+ Tag</button>
            </form>
          </div>
          {tagError && <p className="hint hint-error">{tagError}</p>}

          <nav className="tab-bar">
            {TABS.map((entry) => (
              <button
                key={entry.key}
                type="button"
                className={tab === entry.key ? "tab-active" : ""}
                onClick={() => setTab(entry.key)}
              >
                {entry.label}
              </button>
            ))}
          </nav>

          {tab === "variants" && (
            <>
              <AsyncState
                loading={variants.loading}
                error={variants.error}
                empty={!variants.loading && !variants.error && (variants.data?.length ?? 0) === 0}
              />
              {variants.data && variants.data.length > 0 && (
                <table className="data-table">
                  <thead>
                    <tr>
                      <th>SKU</th>
                      <th>Name</th>
                      <th>Standard</th>
                      <th>Aktiv</th>
                      <th>Bestandsführung</th>
                      <th>Geändert am</th>
                    </tr>
                  </thead>
                  <tbody>
                    {variants.data.map((variant) => (
                      <tr key={variant.id}>
                        <td>{variant.sku}</td>
                        <td>{variant.name ?? "—"}</td>
                        <td>{variant.is_default ? "ja" : "nein"}</td>
                        <td>{variant.active ? "ja" : "nein"}</td>
                        <td>{variant.stock_enabled ? "ja" : "nein"}</td>
                        <td>{formatDate(variant.updated_at)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              )}
            </>
          )}

          {tab === "assets" && (
            <>
              <AsyncState
                loading={assets.loading}
                error={assets.error}
                empty={!assets.loading && !assets.error && (assets.data?.length ?? 0) === 0}
              />
              {assets.data && assets.data.length > 0 && (
                <table className="data-table">
                  <thead>
                    <tr>
                      <th>Rolle</th>
                      <th>Speicherart</th>
                      <th>Pfad / URI</th>
                      <th>Zustand</th>
                      <th>Zuletzt geprüft</th>
                    </tr>
                  </thead>
                  <tbody>
                    {assets.data.map((asset) => (
                      <tr key={asset.id}>
                        <td>{asset.role}</td>
                        <td>{asset.storage_kind}</td>
                        {/* Plain text only, never a link - uri may be a network path or
                            internal storage key, not a public URL. */}
                        <td className="mono-cell">{asset.uri}</td>
                        <td>
                          <StatusBadge label={asset.health_status} tone={healthTone(asset.health_status)} />
                        </td>
                        <td>{formatDate(asset.last_checked_at)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              )}
            </>
          )}

          {tab === "channels" && (
            <>
              <AsyncState
                loading={channels.loading}
                error={channels.error}
                empty={!channels.loading && !channels.error && (channels.data?.length ?? 0) === 0}
              />
              {channels.data && channels.data.length > 0 && (
                <table className="data-table">
                  <thead>
                    <tr>
                      <th>Kanal</th>
                      <th>Objekt</th>
                      <th>Externe ID</th>
                      <th>Sync-Status</th>
                      <th>Zuletzt erfolgreich</th>
                      <th>Letzter Fehler</th>
                    </tr>
                  </thead>
                  <tbody>
                    {channels.data.map((channel) => (
                      <tr key={channel.id}>
                        <td>{channel.channel}</td>
                        <td>{channel.entity_type}</td>
                        <td>{channel.external_id}</td>
                        <td>
                          <StatusBadge label={channel.sync_status} tone={syncTone(channel.sync_status)} />
                        </td>
                        <td>{formatDate(channel.last_success_at)}</td>
                        <td>{channel.last_error ?? "—"}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              )}
            </>
          )}

          {tab === "improvements" && (
            <>
              <form className="improvement-add-form" onSubmit={handleAddImprovement}>
                <input
                  placeholder="+ Verbesserung hinzufügen"
                  value={newImprovement}
                  onChange={(e) => setNewImprovement(e.target.value)}
                />
                <select
                  value={newSeverity}
                  onChange={(e) => setNewSeverity(e.target.value as (typeof SEVERITIES)[number])}
                >
                  {SEVERITIES.map((severity) => (
                    <option key={severity} value={severity}>
                      {severity}
                    </option>
                  ))}
                </select>
                <button type="submit">Hinzufügen</button>
              </form>
              {improvementError && <p className="hint hint-error">{improvementError}</p>}

              <AsyncState
                loading={improvements.loading}
                error={improvements.error}
                empty={
                  !improvements.loading && !improvements.error && (improvements.data?.length ?? 0) === 0
                }
              />
              {improvements.data && improvements.data.length > 0 && (
                <ul className="improvement-list">
                  {improvements.data.map((item) => (
                    <li key={item.id}>
                      <StatusBadge
                        label={item.severity}
                        tone={item.severity === "critical" || item.severity === "major" ? "bad" : "warn"}
                      />
                      <strong>{item.title ?? item.description}</strong>
                      <span className="hint"> · {item.status} · {item.source}</span>
                      {item.title && <p>{item.description}</p>}
                      {item.status === "open" && (
                        <button
                          type="button"
                          className="link-button"
                          onClick={() => handleResolveImprovement(item.id, item.row_version)}
                        >
                          Als gelöst markieren
                        </button>
                      )}
                    </li>
                  ))}
                </ul>
              )}
            </>
          )}

          {tab === "audit" && (
            <>
              <AsyncState
                loading={audit.loading}
                error={audit.error}
                empty={!audit.loading && !audit.error && (audit.data?.length ?? 0) === 0}
              />
              {audit.data && audit.data.length > 0 && (
                <table className="data-table">
                  <thead>
                    <tr>
                      <th>Zeitpunkt</th>
                      <th>Aktion</th>
                      <th>Quelle</th>
                      <th>Akteur</th>
                      <th>Geänderte Felder</th>
                    </tr>
                  </thead>
                  <tbody>
                    {audit.data.map((entry) => (
                      <tr key={entry.id}>
                        <td>{formatDate(entry.created_at)}</td>
                        <td>{entry.action}</td>
                        <td>{entry.source}</td>
                        <td>
                          {entry.actor_type}
                          {entry.actor_id ? ` (${entry.actor_id})` : ""}
                        </td>
                        <td>{entry.changed_fields.join(", ") || "—"}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              )}
            </>
          )}
        </>
      )}
    </section>
  );
}
