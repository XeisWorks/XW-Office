import { useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../api/client";
import AsyncState from "../components/AsyncState";
import StatusBadge from "../components/StatusBadge";
import { useApi } from "../hooks/useApi";
import type { ProductListFilters, ProductListItem } from "../api/types";

interface ProductListPageProps {
  onUnauthorized: () => void;
}

// Backend caps at 2000 (see products.py) — comfortably above this catalog's size, so
// every product fits on one page/one request; no offset-based pagination needed.
const FETCH_LIMIT = 2000;
const STATUS_OPTIONS = ["draft", "active", "discontinued", "archived"];

type SortColumn = "sku" | "name" | "category" | "brand_name" | "product_type" | "status" | "active" | "updated_at";
type SortDirection = "asc" | "desc";

const COLUMNS: { key: SortColumn; label: string }[] = [
  { key: "sku", label: "SKU" },
  { key: "name", label: "Name" },
  { key: "category", label: "Kategorie" },
  { key: "brand_name", label: "Marke" },
  { key: "product_type", label: "Typ" },
  { key: "status", label: "Status" },
  { key: "active", label: "Aktiv" },
  { key: "updated_at", label: "Geändert am" },
];

function sortValue(product: ProductListItem, column: SortColumn): string | number {
  switch (column) {
    case "active":
      return product.active ? 1 : 0;
    case "updated_at":
      return product.updated_at;
    default: {
      const value = product[column];
      return (value ?? "").toString().toLocaleLowerCase("de-DE");
    }
  }
}

export default function ProductListPage({ onUnauthorized }: ProductListPageProps) {
  const [search, setSearch] = useState("");
  const [status, setStatus] = useState("");
  const [sortColumn, setSortColumn] = useState<SortColumn>("sku");
  const [sortDirection, setSortDirection] = useState<SortDirection>("asc");

  const filters: ProductListFilters = {
    search: search || undefined,
    status: status || undefined,
    limit: FETCH_LIMIT,
    offset: 0,
  };

  const { data, error, loading } = useApi(
    () => api.listProducts(filters),
    [search, status],
    onUnauthorized,
  );

  function handleSort(column: SortColumn) {
    if (column === sortColumn) {
      setSortDirection((direction) => (direction === "asc" ? "desc" : "asc"));
    } else {
      setSortColumn(column);
      setSortDirection("asc");
    }
  }

  const items = data?.items ?? [];
  const total = data?.total ?? 0;

  const sortedItems = useMemo(() => {
    const sorted = [...(data?.items ?? [])];
    sorted.sort((a, b) => {
      const left = sortValue(a, sortColumn);
      const right = sortValue(b, sortColumn);
      if (left < right) return sortDirection === "asc" ? -1 : 1;
      if (left > right) return sortDirection === "asc" ? 1 : -1;
      return 0;
    });
    return sorted;
  }, [data, sortColumn, sortDirection]);

  return (
    <section>
      <h1>Produkte</h1>
      <div className="filter-bar">
        <input
          type="search"
          placeholder="Suche nach SKU oder Name…"
          value={search}
          onChange={(event) => setSearch(event.target.value)}
        />
        <select value={status} onChange={(event) => setStatus(event.target.value)}>
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
          <p className="hint">{total} Produkte insgesamt</p>
          <table className="data-table">
            <thead>
              <tr>
                {COLUMNS.map((column) => (
                  <th key={column.key} className="sortable-th">
                    <button
                      type="button"
                      className="sortable-header"
                      onClick={() => handleSort(column.key)}
                    >
                      {column.label}
                      {sortColumn === column.key && (
                        <span className="sort-indicator">
                          {sortDirection === "asc" ? " ▲" : " ▼"}
                        </span>
                      )}
                    </button>
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {sortedItems.map((product) => (
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
        </>
      )}
    </section>
  );
}
