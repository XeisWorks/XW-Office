import type {
  AuditLogEntry,
  BulletPointsUpdateRequest,
  ConflictAction,
  ConflictAdvice,
  ConflictCase,
  ConflictCaseDetail,
  ConflictSummary,
  ChannelMapping,
  Edition,
  GeneratedContent,
  ImprovementCreateRequest,
  ImprovementUpdateRequest,
  Page,
  ParentProductListItem,
  ProductAsset,
  ProductDetail,
  ProductImprovement,
  ProductListFilters,
  ProductReadiness,
  ProductSkuRenameRequest,
  ProductUpdateRequest,
  ProductVariant,
  ReadinessSummary,
  Tag,
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

/** Thrown on 409 — `current` is the server's current state (see build plan's
 * "Konflikt -> HTTP 409 mit aktuellem Serverstand"), so callers can show it or
 * refetch instead of guessing what changed. */
export class ConflictApiError<T = unknown> extends ApiError {
  constructor(public current: T) {
    super(409, "Der Datensatz wurde zwischenzeitlich geändert.");
    this.name = "ConflictApiError";
  }
}

interface RequestOptions {
  method?: "GET" | "POST" | "PATCH" | "PUT" | "DELETE";
  body?: unknown;
}

async function request<T>(path: string, options: RequestOptions = {}): Promise<T> {
  const token = getToken();
  const headers: Record<string, string> = token ? { Authorization: `Bearer ${token}` } : {};
  if (options.body !== undefined) headers["Content-Type"] = "application/json";
  const response = await fetch(path, {
    method: options.method ?? "GET",
    headers,
    body: options.body !== undefined ? JSON.stringify(options.body) : undefined,
  });
  if (response.status === 401) {
    clearToken();
    throw new ApiError(401, "Nicht angemeldet oder Token abgelaufen.");
  }
  if (response.status === 503) {
    throw new ApiError(503, "Product Hub API ist nicht konfiguriert oder deaktiviert.");
  }
  if (response.status === 409) {
    const body = await response.json().catch(() => null);
    throw new ConflictApiError(body);
  }
  if (response.status === 204) {
    return undefined as T;
  }
  if (!response.ok) {
    const text = await response.text().catch(() => "");
    let message = text;
    try {
      const parsed = JSON.parse(text) as { detail?: unknown };
      if (typeof parsed.detail === "string") message = parsed.detail;
    } catch {
      // Non-JSON errors are already useful as plain text.
    }
    throw new ApiError(response.status, message || `HTTP ${response.status}`);
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
    request<Page<ParentProductListItem>>(`/api/v1/products?${buildQuery(filters)}`),
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

  // -- PR09: edit API -----------------------------------------------------------
  updateProduct: (id: string, body: ProductUpdateRequest) =>
    request<ProductDetail>(`/api/v1/products/${id}`, { method: "PATCH", body }),
  renameProductSku: (id: string, body: ProductSkuRenameRequest) =>
    request<ProductDetail>(`/api/v1/products/${id}/rename-sku`, { method: "POST", body }),
  getTags: (productId: string) => request<Tag[]>(`/api/v1/products/${productId}/tags`),
  addTag: (productId: string, tagCode: string) =>
    request<Tag>(`/api/v1/products/${productId}/tags`, {
      method: "POST",
      body: { tag_code: tagCode },
    }),
  removeTag: (productId: string, tagId: string) =>
    request<void>(`/api/v1/products/${productId}/tags/${tagId}`, { method: "DELETE" }),
  createImprovement: (productId: string, body: ImprovementCreateRequest) =>
    request<ProductImprovement>(`/api/v1/products/${productId}/improvements`, {
      method: "POST",
      body,
    }),
  updateImprovement: (productId: string, improvementId: string, body: ImprovementUpdateRequest) =>
    request<ProductImprovement>(`/api/v1/products/${productId}/improvements/${improvementId}`, {
      method: "PATCH",
      body,
    }),
  getEditions: (productId: string) => request<Edition[]>(`/api/v1/products/${productId}/editions`),
  createEdition: (productId: string, label: string, resolveImprovementIds: string[] = []) =>
    request<Edition>(`/api/v1/products/${productId}/editions`, {
      method: "POST",
      body: { label, resolve_improvement_ids: resolveImprovementIds },
    }),

  // -- OpenAI description/bullet-point generator ---------------------------------
  generateContent: (productId: string) =>
    request<GeneratedContent>(`/api/v1/products/${productId}/generate-content`, {
      method: "POST",
    }),
  setBulletPoints: (productId: string, body: BulletPointsUpdateRequest) =>
    request<ProductDetail>(`/api/v1/products/${productId}/bullet-points`, {
      method: "PUT",
      body,
    }),

  // -- Conflict Wizard ----------------------------------------------------------
  getConflictSummary: () => request<ConflictSummary>("/api/v1/conflicts/summary"),
  listConflicts: (filters: Record<string, string> = {}) => {
    const params = new URLSearchParams(filters);
    return request<Page<ConflictCase>>(`/api/v1/conflicts?${params.toString()}`);
  },
  getConflict: (id: string) => request<ConflictCaseDetail>(`/api/v1/conflicts/${id}`),
  getConflictAdvice: (id: string) =>
    request<ConflictAdvice>(`/api/v1/conflicts/${id}/advice`, { method: "POST" }),
  remapConflict: (id: string, expectedRowVersion: number, externalId: string, note?: string) =>
    request<ConflictCase>(`/api/v1/conflicts/${id}/mapping`, {
      method: "POST",
      body: {
        expected_row_version: expectedRowVersion,
        external_id: externalId,
        ...(note ? { note } : {}),
      },
    }),
  createWixProductForConflict: (id: string, expectedRowVersion: number) =>
    request<ConflictCase>(`/api/v1/conflicts/${id}/create-wix-product`, {
      method: "POST",
      body: { expected_row_version: expectedRowVersion },
    }),
  archiveHubProductForConflict: (id: string, expectedRowVersion: number) =>
    request<ConflictCase>(`/api/v1/conflicts/${id}/archive-hub-product`, {
      method: "POST",
      body: { expected_row_version: expectedRowVersion },
    }),
  scanConflicts: (productId?: string) =>
    request<{ differences_found: number; cases_created: number; cases_updated: number }>(
      `/api/v1/conflicts/scan${productId ? `?product_id=${encodeURIComponent(productId)}` : ""}`,
      { method: "POST" },
    ),
  scanWixConflicts: (force = false) =>
    request<{
      differences_found: number;
      cases_created: number;
      cases_updated: number;
      source: {
        catalog_products_indexed: number;
        products_fetched: number;
        products_cached: number;
        products_missing_from_index: number;
        full_refresh: boolean;
        images_created: number;
        images_updated: number;
        errors: string[];
      };
    }>(`/api/v1/conflicts/scan/wix${force ? "?force=true" : ""}`, { method: "POST" }),
  startConflict: (id: string, expectedRowVersion: number) =>
    request<ConflictCase>(`/api/v1/conflicts/${id}/start`, {
      method: "POST",
      body: { expected_row_version: expectedRowVersion },
    }),
  decideConflict: (
    id: string,
    body: {
      expected_row_version: number;
      resolution_type: string;
      selected_source?: string;
      custom_value?: unknown;
      note?: string;
    },
  ) => request<ConflictCase>(`/api/v1/conflicts/${id}/decision`, { method: "POST", body }),
  previewConflict: (id: string, channels?: string[]) =>
    request<ConflictAction[]>(`/api/v1/conflicts/${id}/preview`, {
      method: "POST",
      body: { channels },
    }),
  applyConflict: (id: string, expectedRowVersion: number) =>
    request<ConflictCase>(`/api/v1/conflicts/${id}/apply`, {
      method: "POST",
      body: { expected_row_version: expectedRowVersion },
    }),
  snoozeConflict: (id: string, expectedRowVersion: number, until: string) =>
    request<ConflictCase>(`/api/v1/conflicts/${id}/snooze`, {
      method: "POST",
      body: { expected_row_version: expectedRowVersion, until },
    }),
  ignoreConflict: (id: string, expectedRowVersion: number) =>
    request<ConflictCase>(`/api/v1/conflicts/${id}/ignore`, {
      method: "POST",
      body: { expected_row_version: expectedRowVersion },
    }),
};
