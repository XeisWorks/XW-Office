import { Fragment, useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { useNavigate } from "react-router-dom";
import { api } from "../api/client";
import AsyncState from "../components/AsyncState";
import StatusBadge from "../components/StatusBadge";
import { channelStateSymbol, channelStateTone } from "../components/tone";
import { useApi } from "../hooks/useApi";
import { compareNatural } from "../utils/naturalSort";
import type { ChannelState, ParentProductListItem, ProductListFilters, ProductVariantSummary } from "../api/types";

interface ProductListPageProps {
  onUnauthorized: () => void;
}

// Backend caps at 2000 (see products.py) — comfortably above this catalog's size, so
// every product fits on one page/one request; no offset-based pagination needed.
const FETCH_LIMIT = 2000;
const STATUS_OPTIONS = ["draft", "active", "discontinued", "archived"];

type ColumnKey =
  | "name"
  | "title_short"
  | "category"
  | "brand_name"
  | "product_type"
  | "variant_count"
  | "formats"
  | "ensembles"
  | "scorings"
  | "instruments"
  | "isbns"
  | "asins"
  | "price_gross"
  | "price_net"
  | "stock_total"
  | "tags"
  | "wix_state"
  | "sevdesk_state"
  | "amazon_state"
  | "content_status"
  | "review_required"
  | "status"
  | "active"
  | "updated_at";

type SortKey = "sku" | ColumnKey;
type SortDirection = "asc" | "desc";

function formatPriceRange(min: string | null, max: string | null): string {
  const minNum = min !== null ? Number(min) : null;
  const maxNum = max !== null ? Number(max) : null;
  const fmt = (n: number) => n.toLocaleString("de-DE", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  if (minNum !== null && maxNum !== null) {
    return minNum === maxNum ? `${fmt(minNum)} €` : `${fmt(minNum)}–${fmt(maxNum)} €`;
  }
  if (minNum !== null) return `${fmt(minNum)} €`;
  if (maxNum !== null) return `${fmt(maxNum)} €`;
  return "—";
}

function formatSinglePrice(value: string | null): string {
  if (value === null) return "—";
  return `${Number(value).toLocaleString("de-DE", { minimumFractionDigits: 2, maximumFractionDigits: 2 })} €`;
}

function ChannelBadge({ state, label }: { state: ChannelState; label: string }) {
  return (
    <StatusBadge label={`${label} ${channelStateSymbol(state)}`} tone={channelStateTone(state)} />
  );
}

const COLUMNS: { key: ColumnKey; label: string; defaultVisible: boolean }[] = [
  { key: "name", label: "Name", defaultVisible: true },
  { key: "title_short", label: "Kurzname", defaultVisible: false },
  { key: "category", label: "Kategorie", defaultVisible: true },
  { key: "brand_name", label: "Marke", defaultVisible: true },
  { key: "product_type", label: "Typ", defaultVisible: false },
  { key: "variant_count", label: "Varianten", defaultVisible: true },
  { key: "formats", label: "Formate", defaultVisible: false },
  { key: "ensembles", label: "Besetzung", defaultVisible: false },
  { key: "scorings", label: "Scoring", defaultVisible: false },
  { key: "instruments", label: "Instrument", defaultVisible: false },
  { key: "isbns", label: "ISBN", defaultVisible: false },
  { key: "asins", label: "ASIN", defaultVisible: false },
  { key: "price_gross", label: "Preis brutto", defaultVisible: true },
  { key: "price_net", label: "Preis netto", defaultVisible: false },
  { key: "stock_total", label: "Bestand", defaultVisible: false },
  { key: "tags", label: "Tags", defaultVisible: false },
  { key: "wix_state", label: "Wix", defaultVisible: false },
  { key: "sevdesk_state", label: "sevdesk", defaultVisible: false },
  { key: "amazon_state", label: "Amazon", defaultVisible: false },
  { key: "content_status", label: "Content-Status", defaultVisible: false },
  { key: "review_required", label: "Review", defaultVisible: false },
  { key: "status", label: "Status", defaultVisible: true },
  { key: "active", label: "Aktiv", defaultVisible: true },
  { key: "updated_at", label: "Geändert am", defaultVisible: false },
];

const ALL_COLUMN_KEYS = COLUMNS.map((column) => column.key);
const DEFAULT_VISIBLE_COLUMNS = COLUMNS.filter((c) => c.defaultVisible).map((c) => c.key);
const VISIBLE_COLUMNS_STORAGE_KEY = "xw_product_hub_visible_columns_v2";

const CELL_RENDERERS: Record<ColumnKey, (item: ParentProductListItem) => ReactNode> = {
  name: (item) => item.name,
  title_short: (item) => item.title_short ?? "—",
  category: (item) => item.category ?? "—",
  brand_name: (item) => item.brand_name ?? "—",
  product_type: (item) => item.product_type,
  variant_count: (item) => item.variant_count,
  formats: (item) => (item.formats.length > 0 ? item.formats.join(", ") : "—"),
  ensembles: (item) => (item.ensembles.length > 0 ? item.ensembles.join(", ") : "—"),
  scorings: (item) => (item.scorings.length > 0 ? item.scorings.join(", ") : "—"),
  instruments: (item) => (item.instruments.length > 0 ? item.instruments.join(", ") : "—"),
  isbns: (item) => (item.isbns.length > 0 ? item.isbns.join(", ") : "—"),
  asins: (item) => (item.asins.length > 0 ? item.asins.join(", ") : "—"),
  price_gross: (item) => formatPriceRange(item.price_gross_min, item.price_gross_max),
  price_net: (item) => formatPriceRange(item.price_net_min, item.price_net_max),
  stock_total: (item) => (item.stock_total !== null ? item.stock_total : "—"),
  tags: (item) => (item.tags.length > 0 ? item.tags.join(", ") : "—"),
  wix_state: (item) => <ChannelBadge state={item.wix_state} label="Wix" />,
  sevdesk_state: (item) => <ChannelBadge state={item.sevdesk_state} label="sevdesk" />,
  amazon_state: (item) => <ChannelBadge state={item.amazon_state} label="Amazon" />,
  content_status: (item) => item.content_status ?? "—",
  review_required: (item) =>
    item.review_required ? <StatusBadge label="Review" tone="warn" /> : "—",
  status: (item) => item.status,
  active: (item) => (
    <StatusBadge label={item.active ? "aktiv" : "inaktiv"} tone={item.active ? "ok" : "neutral"} />
  ),
  updated_at: (item) => new Date(item.updated_at).toLocaleString("de-DE"),
};

function sortValue(item: ParentProductListItem, key: SortKey): string | number {
  switch (key) {
    case "active":
    case "review_required":
      return item[key] ? 1 : 0;
    case "variant_count":
    case "stock_total":
      return item[key] ?? -1;
    case "price_gross":
      return item.price_gross_min !== null ? Number(item.price_gross_min) : -1;
    case "price_net":
      return item.price_net_min !== null ? Number(item.price_net_min) : -1;
    case "formats":
    case "ensembles":
    case "scorings":
    case "instruments":
    case "isbns":
    case "asins":
    case "tags":
      return (item[key] as string[]).join(", ").toLocaleLowerCase("de-DE");
    case "wix_state":
    case "sevdesk_state":
    case "amazon_state":
    case "updated_at":
    case "name":
    case "title_short":
    case "category":
    case "brand_name":
    case "product_type":
    case "content_status":
    case "status":
      return (item[key] ?? "").toString().toLocaleLowerCase("de-DE");
    case "sku":
      return item.display_sku;
    default:
      return "";
  }
}

// Per-viewer convenience only (never shared, never read back by us) - a blocked or
// cleared storage just falls back to the documented defaults, which is always safe.
function loadVisibleColumns(): ColumnKey[] {
  try {
    const raw = localStorage.getItem(VISIBLE_COLUMNS_STORAGE_KEY);
    if (!raw) return DEFAULT_VISIBLE_COLUMNS;
    const parsed: unknown = JSON.parse(raw);
    if (Array.isArray(parsed)) {
      const valid = parsed.filter((key): key is ColumnKey => ALL_COLUMN_KEYS.includes(key as ColumnKey));
      if (valid.length > 0) return valid;
    }
  } catch {
    // ignore — fall back to the defaults
  }
  return DEFAULT_VISIBLE_COLUMNS;
}

function VariantRow({ variant }: { variant: ProductVariantSummary }) {
  const dimension = [variant.format, variant.ensemble].filter(Boolean).join(" · ") || "—";
  return (
    <tr className="variant-row">
      <td className="mono-cell">{dimension}</td>
      <td className="mono-cell">{variant.sku}</td>
      <td>{formatSinglePrice(variant.price_net)}</td>
      <td>{formatSinglePrice(variant.price_gross)}</td>
      <td>{variant.stock ?? "—"}</td>
      <td>
        <ChannelBadge state={variant.wix_state} label="Wix" />
      </td>
      <td>
        <ChannelBadge state={variant.sevdesk_state} label="sevdesk" />
      </td>
      <td>
        <ChannelBadge state={variant.amazon_state} label="Amazon" />
      </td>
      <td>
        <StatusBadge label={variant.active ? "aktiv" : "inaktiv"} tone={variant.active ? "ok" : "neutral"} />
      </td>
    </tr>
  );
}

export default function ProductListPage({ onUnauthorized }: ProductListPageProps) {
  const navigate = useNavigate();
  const [search, setSearch] = useState("");
  const [status, setStatus] = useState("");
  const [sortKey, setSortKey] = useState<SortKey>("sku");
  const [sortDirection, setSortDirection] = useState<SortDirection>("asc");
  const [visibleColumns, setVisibleColumns] = useState<ColumnKey[]>(loadVisibleColumns);
  const [columnPickerOpen, setColumnPickerOpen] = useState(false);
  const [expandedIds, setExpandedIds] = useState<Set<string>>(() => new Set());
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

  function handleSort(key: SortKey) {
    if (key === sortKey) {
      setSortDirection((direction) => (direction === "asc" ? "desc" : "asc"));
    } else {
      setSortKey(key);
      setSortDirection("asc");
    }
  }

  function toggleColumn(key: ColumnKey) {
    setVisibleColumns((current) => {
      const isVisible = current.includes(key);
      const next = isVisible ? current.filter((k) => k !== key) : [...current, key];
      try {
        localStorage.setItem(VISIBLE_COLUMNS_STORAGE_KEY, JSON.stringify(next));
      } catch {
        // see loadVisibleColumns — a blocked store just means the choice won't persist
      }
      return next;
    });
  }

  function toggleExpanded(productId: string) {
    setExpandedIds((current) => {
      const next = new Set(current);
      if (next.has(productId)) next.delete(productId);
      else next.add(productId);
      return next;
    });
  }

  const items = data?.items ?? [];
  const total = data?.total ?? 0;
  const shownColumns = COLUMNS.filter((column) => visibleColumns.includes(column.key));
  const columnCount = shownColumns.length + 2; // + expand toggle + pinned SKU

  const sortedItems = useMemo(() => {
    const sorted = [...(data?.items ?? [])];
    sorted.sort((a, b) => {
      if (sortKey === "sku") {
        const cmp = compareNatural(a.display_sku, b.display_sku);
        return sortDirection === "asc" ? cmp : -cmp;
      }
      const left = sortValue(a, sortKey);
      const right = sortValue(b, sortKey);
      if (left < right) return sortDirection === "asc" ? -1 : 1;
      if (left > right) return sortDirection === "asc" ? 1 : -1;
      return 0;
    });
    return sorted;
  }, [data, sortKey, sortDirection]);

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
              <label>
                <input type="checkbox" checked disabled />
                SKU
              </label>
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
          placeholder="Suche nach SKU (auch Variante), Name…"
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
                <th className="expand-th" aria-hidden="true" />
                <th className="sortable-th">
                  <button type="button" className="sortable-header" onClick={() => handleSort("sku")}>
                    SKU
                    {sortKey === "sku" && (
                      <span className="sort-indicator">{sortDirection === "asc" ? " ▲" : " ▼"}</span>
                    )}
                  </button>
                </th>
                {shownColumns.map((column) => (
                  <th key={column.key} className="sortable-th">
                    <button
                      type="button"
                      className="sortable-header"
                      onClick={() => handleSort(column.key)}
                    >
                      {column.label}
                      {sortKey === column.key && (
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
              {sortedItems.map((item) => {
                const expandable = item.variant_count > 1;
                const expanded = expandable && expandedIds.has(item.id);
                return (
                  <Fragment key={item.id}>
                    <tr
                      className="row-clickable"
                      tabIndex={0}
                      onClick={() => navigate(`/products/${item.id}`)}
                      onKeyDown={(event) => {
                        if (event.key === "Enter") navigate(`/products/${item.id}`);
                      }}
                    >
                      <td className="expand-cell">
                        {expandable && (
                          <button
                            type="button"
                            className="expand-toggle"
                            aria-label={expanded ? "Varianten einklappen" : "Varianten ausklappen"}
                            aria-expanded={expanded}
                            onClick={(event) => {
                              event.stopPropagation();
                              toggleExpanded(item.id);
                            }}
                            onKeyDown={(event) => event.stopPropagation()}
                          >
                            {expanded ? "▾" : "▸"}
                          </button>
                        )}
                      </td>
                      <td className="mono-cell">
                        {item.display_sku}
                        {expandable && <span className="hint"> · {item.variant_count} Varianten</span>}
                      </td>
                      {shownColumns.map((column) => (
                        <td key={column.key}>{CELL_RENDERERS[column.key](item)}</td>
                      ))}
                    </tr>
                    {expanded && (
                      <tr className="variant-subtable-row">
                        <td />
                        <td colSpan={columnCount - 1}>
                          <table className="variant-subtable">
                            <thead>
                              <tr>
                                <th>Format / Besetzung</th>
                                <th>SKU</th>
                                <th>Netto</th>
                                <th>Brutto</th>
                                <th>Bestand</th>
                                <th>Wix</th>
                                <th>sevdesk</th>
                                <th>Amazon</th>
                                <th>Aktiv</th>
                              </tr>
                            </thead>
                            <tbody>
                              {[...item.variants]
                                .sort((a, b) => compareNatural(a.sku, b.sku))
                                .map((variant) => (
                                  <VariantRow key={variant.id} variant={variant} />
                                ))}
                            </tbody>
                          </table>
                        </td>
                      </tr>
                    )}
                  </Fragment>
                );
              })}
            </tbody>
          </table>
        </>
      )}
    </section>
  );
}
