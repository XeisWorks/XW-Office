// Mirrors src/xw_office/web/schemas/products.py exactly (PR07 Read API). Keep these
// two in sync by hand - there is no shared codegen between the Python and TS sides
// for this small, slow-moving read-only surface.

export interface Page<T> {
  items: T[];
  total: number;
  limit: number;
  offset: number;
}

export interface ProductListItem {
  id: string;
  sku: string;
  name: string;
  slug: string;
  status: string;
  active: boolean;
  product_type: string;
  brand_name: string | null;
  category: string | null;
  row_version: number;
  updated_at: string;
}

export interface ProductDetail extends ProductListItem {
  short_description: string | null;
  description: string | null;
  family_id: string | null;
  release_date: string | null;
  created_at: string;
  archived_at: string | null;
}

export interface ProductVariant {
  id: string;
  product_id: string;
  sku: string;
  name: string | null;
  is_default: boolean;
  active: boolean;
  stock_enabled: boolean;
  updated_at: string;
}

/** PRINT_PDF's `uri` is metadata only (network path text) - never render it as a
 * clickable/downloadable link. See docs/product_hub/ architecture decisions. */
export interface ProductAsset {
  id: string;
  product_id: string;
  variant_id: string | null;
  role: "COVER" | "SAMPLE_SCORE" | "PRINT_PDF" | "PREVIEW_PDF" | "AUDIO" | "DOWNLOAD" | "OTHER";
  sort_order: number;
  storage_kind: "OBJECT_STORAGE" | "NETWORK_PATH" | "WIX_MEDIA" | "EXTERNAL_URL";
  uri: string;
  mime_type: string | null;
  size_bytes: number | null;
  source_channel: string | null;
  source_external_id: string | null;
  public_share_allowed: boolean;
  health_status: "unknown" | "ok" | "missing" | "unreadable" | "checksum_mismatch" | "stale";
  last_checked_at: string | null;
}

export interface ProductImprovement {
  id: string;
  product_id: string;
  variant_id: string | null;
  title: string | null;
  description: string;
  source: string;
  severity: "info" | "minor" | "major" | "critical";
  status: "open" | "planned" | "resolved" | "wont_fix";
  created_at: string;
  resolved_at: string | null;
}

export interface ChannelMapping {
  id: string;
  channel: "wix" | "sevdesk" | "amazon" | "vlb";
  entity_type: string;
  external_id: string;
  sync_status: "never" | "pending" | "synced" | "conflict" | "error" | "disabled";
  last_pulled_at: string | null;
  last_pushed_at: string | null;
  last_success_at: string | null;
  last_error: string | null;
}

export interface AuditLogEntry {
  id: string;
  actor_type: string;
  actor_id: string | null;
  source: string;
  action: string;
  changed_fields: string[];
  created_at: string;
}

export interface ProductReadiness {
  wix_ready: boolean;
  wix_missing: string[];
  b2b_ready: boolean;
  b2b_missing: string[];
  print_ready: boolean;
  print_missing: string[];
  sevdesk_ready: boolean;
  sevdesk_missing: string[];
}

export interface ReadinessSummary {
  total_products: number;
  wix_ready: number;
  b2b_ready: number;
  print_ready: number;
  sevdesk_ready: number;
  missing_cover: number;
  open_improvements: number;
}

export interface ProductListFilters {
  search?: string;
  status?: string;
  active?: boolean;
  limit?: number;
  offset?: number;
}
