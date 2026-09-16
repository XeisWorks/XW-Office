import { useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../api/client";
import AsyncState from "../components/AsyncState";
import StatusBadge from "../components/StatusBadge";
import { useApi } from "../hooks/useApi";
import type { ProductListFilters } from "../api/types";

interface ProductListPageProps {
  onUnauthorized: () => void;
}

const PAGE_SIZE = 50;
const STATUS_OPTIONS = ["draft", "active", "discontinued", "archived"];

export default function ProductListPage({ onUnauthorized }: ProductListPageProps) {
  const [search, setSearch] = useState("");
  const [status, setStatus] = useState("");
  const [offset, setOffset] = useState(0);

  const filters: ProductListFilters = {
    search: search || undefined,
    status: status || undefined,
    limit: PAGE_SIZE,
    offset,
  };

  const { data, error, loading } = useApi(
    () => api.listProducts(filters),
    [search, status, offset],
    onUnauthorized,
  );

  function handleSearchChange(value: string) {
    setSearch(value);
    setOffset(0);
  }

  function handleStatusChange(value: string) {
    setStatus(value);
    setOffset(0);
  }

  const items = data?.items ?? [];
  const total = data?.total ?? 0;
  const hasNext = offset + PAGE_SIZE < total;
  const hasPrev = offset > 0;

  return (
    <section>
      <h1>Produkte</h1>
      <div className="filter-bar">
        <input
          type="search"
          placeholder="Suche nach SKU oder Name…"
          value={search}
          onChange={(event) => handleSearchChange(event.target.value)}
        />
        <select value={status} onChange={(event) => handleStatusChange(event.target.value)}>
          <option value="">Alle Status</option>
          {STATUS_OPTIONS.map((option) => (
            <option key={option} value={option}>
              {option}
            </option>
          ))}
        </select>
      </div>

      <AsyncState loading={loading} error={error} empty={!loading && !error && items.length === 0} />

      {items.length > 0 && (
        <>
          <table className="data-table">
            <thead>
              <tr>
                <th>SKU</th>
                <th>Name</th>
                <th>Kategorie</th>
                <th>Marke</th>
                <th>Typ</th>
                <th>Status</th>
                <th>Aktiv</th>
                <th>Geändert am</th>
              </tr>
            </thead>
            <tbody>
              {items.map((product) => (
                <tr key={product.id}>
                  <td>
                    <Link to={`/products/${product.id}`}>{product.sku}</Link>
                  </td>
                  <td>{product.name}</td>
                  <td>{product.category ?? "—"}</td>
                  <td>{product.brand_name ?? "—"}</td>
                  <td>{product.product_type}</td>
                  <td>{product.status}</td>
                  <td>
                    <StatusBadge
                      label={product.active ? "aktiv" : "inaktiv"}
                      tone={product.active ? "ok" : "neutral"}
                    />
                  </td>
                  <td>{new Date(product.updated_at).toLocaleString("de-DE")}</td>
                </tr>
              ))}
            </tbody>
          </table>
          <div className="pagination">
            <button type="button" disabled={!hasPrev} onClick={() => setOffset(Math.max(0, offset - PAGE_SIZE))}>
              Zurück
            </button>
            <span>
              {offset + 1}–{Math.min(offset + PAGE_SIZE, total)} von {total}
            </span>
            <button type="button" disabled={!hasNext} onClick={() => setOffset(offset + PAGE_SIZE)}>
              Weiter
            </button>
          </div>
        </>
      )}
    </section>
  );
}
