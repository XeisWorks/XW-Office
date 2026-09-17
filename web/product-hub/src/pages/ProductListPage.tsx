import { useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { useNavigate } from "react-router-dom";
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

const ALL_COLUMN_KEYS = COLUMNS.map((column) => column.key);
const VISIBLE_COLUMNS_STORAGE_KEY = "xw_product_hub_visible_columns";

const CELL_RENDERERS: Record<SortColumn, (product: ProductListItem) => ReactNode> = {
  sku: (product) => product.sku,
  name: (product) => product.name,
  category: (product) => product.category ?? "—",
  brand_name: (product) => product.brand_name ?? "—",
  product_type: (product) => product.product_type,
  status: (product) => product.status,
  active: (product) => (
    <StatusBadge label={product.active ? "aktiv" : "inaktiv"} tone={product.active ? "ok" : "neutral"} />
  ),
  updated_at: (product) => new Date(product.updated_at).toLocaleString("de-DE"),
};

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

// Per-viewer convenience only (never shared, never read back by us) - a blocked or
// cleared storage just falls back to "show everything", which is always a safe default.
function loadVisibleColumns(): SortColumn[] {
  try {
    const raw = localStorage.getItem(VISIBLE_COLUMNS_STORAGE_KEY);
    if (!raw) return ALL_COLUMN_KEYS;
    const parsed: unknown = JSON.parse(raw);
    if (Array.isArray(parsed)) {
      const valid = parsed.filter((key): key is SortColumn => ALL_COLUMN_KEYS.includes(key as SortColumn));
      if (valid.length > 0) return valid;
    }
  } catch {
    // ignore — fall back to showing everything
  }
  return ALL_COLUMN_KEYS;
}

export default function ProductListPage({ onUnauthorized }: ProductListPageProps) {
  const navigate = useNavigate();
  const [search, setSearch] = useState("");
  const [status, setStatus] = useState("");
  const [sortColumn, setSortColumn] = useState<SortColumn>("sku");
  const [sortDirection, setSortDirection] = useState<SortDirection>("asc");
  const [visibleColumns, setVisibleColumns] = useState<SortColumn[]>(loadVisibleColumns);
  const [columnPickerOpen, setColumnPickerOpen] = useState(false);
  const columnPickerRef = useRef<HTMLDivElement | null>(null);

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

  useEffect(() => {
    if (!columnPickerOpen) return;
    function handleClickOutside(event: MouseEvent) {
      if (columnPickerRef.current && !columnPickerRef.current.contains(event.target as Node)) {
        setColumnPickerOpen(false);
      }
    }
    document.addEventListener("mousedown", handleClickOutside);
    return () => document.removeEventListener("mousedown", handleClickOutside);
  }, [columnPickerOpen]);

  function handleSort(column: SortColumn) {
    if (column === sortColumn) {
      setSortDirection((direction) => (direction === "asc" ? "desc" : "asc"));
    } else {
      setSortColumn(column);
      setSortDirection("asc");
    }
  }

  function toggleColumn(key: SortColumn) {
    setVisibleColumns((current) => {
      const isVisible = current.includes(key);
      if (isVisible && current.length === 1) return current; // always keep at least one column
      const next = isVisible ? current.filter((k) => k !== key) : [...current, key];
      try {
        localStorage.setItem(VISIBLE_COLUMNS_STORAGE_KEY, JSON.stringify(next));
      } catch {
        // see loadVisibleColumns — a blocked store just means the choice won't persist
      }
      return next;
    });
  }

  const items = data?.items ?? [];
  const total = data?.total ?? 0;
  const shownColumns = COLUMNS.filter((column) => visibleColumns.includes(column.key));

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
      <div className="list-toolbar">
        <h1>Produkte</h1>
        <div className="column-picker" ref={columnPickerRef}>
          <button
            type="button"
            className="icon-button"
            aria-label="Sichtbare Spalten auswählen"
            title="Sichtbare Spalten auswählen"
            onClick={() => setColumnPickerOpen((open) => !open)}
          >
            👁
          </button>
          {columnPickerOpen && (
            <div className="column-picker-menu">
              {COLUMNS.map((column) => (
                <label key={column.key}>
                  <input
                    type="checkbox"
                    checked={visibleColumns.includes(column.key)}
                    onChange={() => toggleColumn(column.key)}
                  />
                  {column.label}
                </label>
              ))}
            </div>
          )}
        </div>
      </div>

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
                {shownColumns.map((column) => (
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
                <tr
                  key={product.id}
                  className="row-clickable"
                  tabIndex={0}
                  onClick={() => navigate(`/products/${product.id}`)}
                  onKeyDown={(event) => {
                    if (event.key === "Enter") navigate(`/products/${product.id}`);
                  }}
                >
                  {shownColumns.map((column) => (
                    <td key={column.key}>{CELL_RENDERERS[column.key](product)}</td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </>
      )}
    </section>
  );
}
