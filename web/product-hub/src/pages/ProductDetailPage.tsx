import { useState } from "react";
import { Link, useParams } from "react-router-dom";
import { api } from "../api/client";
import AsyncState from "../components/AsyncState";
import StatusBadge from "../components/StatusBadge";
import { healthTone, readinessTone, syncTone } from "../components/tone";
import { useApi } from "../hooks/useApi";

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

function formatDate(value: string | null): string {
  return value ? new Date(value).toLocaleString("de-DE") : "—";
}

export default function ProductDetailPage({ onUnauthorized }: ProductDetailPageProps) {
  const { id = "" } = useParams<{ id: string }>();
  const [tab, setTab] = useState<TabKey>("variants");

  const product = useApi(() => api.getProduct(id), [id], onUnauthorized);
  const readiness = useApi(() => api.getReadiness(id), [id], onUnauthorized);
  const variants = useApi(() => api.getVariants(id), [id], onUnauthorized);
  const assets = useApi(() => api.getAssets(id), [id], onUnauthorized);
  const channels = useApi(() => api.getChannels(id), [id], onUnauthorized);
  const improvements = useApi(() => api.getImprovements(id), [id], onUnauthorized);
  const audit = useApi(() => api.getAudit(id), [id], onUnauthorized);

  return (
    <section>
      <p>
        <Link to="/products">&larr; zurück zur Liste</Link>
      </p>

      <AsyncState loading={product.loading} error={product.error} />

      {product.data && (
        <>
          <header className="detail-header">
            <h1>{product.data.name}</h1>
            <p className="detail-sub">
              {product.data.sku} · {product.data.product_type}
              {product.data.category ? ` · ${product.data.category}` : ""}
              {product.data.brand_name ? ` · ${product.data.brand_name}` : ""}
            </p>
            {product.data.short_description && <p>{product.data.short_description}</p>}
          </header>

          {readiness.data && (
            <div className="readiness-row">
              <StatusBadge label="Wix" tone={readinessTone(readiness.data.wix_ready)} />
              <StatusBadge label="B2B" tone={readinessTone(readiness.data.b2b_ready)} />
              <StatusBadge label="Print" tone={readinessTone(readiness.data.print_ready)} />
              <StatusBadge label="sevdesk" tone={readinessTone(readiness.data.sevdesk_ready)} />
            </div>
          )}

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
