import type {
  AuditLogEntry,
  ChannelMapping,
  Page,
  ProductAsset,
  ProductDetail,
  ProductImprovement,
  ProductListFilters,
  ProductListItem,
  ProductReadiness,
  ProductVariant,
  ReadinessSummary,
} from "./types";

const TOKEN_KEY = "xw_product_hub_token";

export function getToken(): string | null {
  try {
    return localStorage.getItem(TOKEN_KEY);
  } catch {
    return null;
  }
}

export function setToken(token: string): void {
  try {
    localStorage.setItem(TOKEN_KEY, token);
  } catch {
    // localStorage can throw in private-browsing/blocked-storage contexts; the
    // token then simply stays in-memory for this page load, which is an
    // acceptable degradation for a read-only internal tool.
  }
}

export function clearToken(): void {
  try {
    localStorage.removeItem(TOKEN_KEY);
  } catch {
    // see setToken
  }
}

export class ApiError extends Error {
  constructor(
    public status: number,
    message: string,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

async function request<T>(path: string): Promise<T> {
  const token = getToken();
  const response = await fetch(path, {
    headers: token ? { Authorization: `Bearer ${token}` } : {},
  });
  if (response.status === 401) {
    clearToken();
    throw new ApiError(401, "Nicht angemeldet oder Token abgelaufen.");
  }
  if (response.status === 503) {
    throw new ApiError(503, "Product Hub API ist nicht konfiguriert oder deaktiviert.");
  }
  if (!response.ok) {
    const text = await response.text().catch(() => "");
    throw new ApiError(response.status, text || `HTTP ${response.status}`);
  }
  return (await response.json()) as T;
}

function buildQuery(filters: ProductListFilters): string {
  const params = new URLSearchParams();
  if (filters.search) params.set("search", filters.search);
  if (filters.status) params.set("status", filters.status);
  if (filters.active !== undefined) params.set("active", String(filters.active));
  params.set("limit", String(filters.limit ?? 50));
  params.set("offset", String(filters.offset ?? 0));
  return params.toString();
}

export const api = {
  listProducts: (filters: ProductListFilters = {}) =>
    request<Page<ProductListItem>>(`/api/v1/products?${buildQuery(filters)}`),
  getProduct: (id: string) => request<ProductDetail>(`/api/v1/products/${id}`),
  getProductBySku: (sku: string) =>
    request<ProductDetail>(`/api/v1/products/by-sku/${encodeURIComponent(sku)}`),
  getVariants: (id: string) => request<ProductVariant[]>(`/api/v1/products/${id}/variants`),
  getAssets: (id: string) => request<ProductAsset[]>(`/api/v1/products/${id}/assets`),
  getImprovements: (id: string) =>
    request<ProductImprovement[]>(`/api/v1/products/${id}/improvements`),
  getChannels: (id: string) => request<ChannelMapping[]>(`/api/v1/products/${id}/channels`),
  getAudit: (id: string) => request<AuditLogEntry[]>(`/api/v1/products/${id}/audit`),
  getReadiness: (id: string) => request<ProductReadiness>(`/api/v1/products/${id}/readiness`),
  getReadinessSummary: () => request<ReadinessSummary>(`/api/v1/catalog/readiness-summary`),
};
