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
  /** Free-form bag (bullet_points, music_attributes, ...) - see products.py's own
   * comment on this field for why it isn't several bespoke fields yet. */
  attributes: Record<string, unknown>;
}

/** One channel's aggregated status for a product/variant row - see catalog_list.py's
 * `_channel_state`. "not_applicable" is a deliberate, non-error state (e.g. a
 * sevdesk-only shipping line item was never meant to have a Wix listing). */
export type ChannelState = "synced" | "error" | "pending" | "not_applicable";

/** One variant row inside a ParentProductListItem's expandable section. Mirrors
 * ProductVariantSummaryOut / catalog_list.VariantSummary. */
export interface ProductVariantSummary {
  id: string;
  sku: string;
  name: string | null;
  format: string | null;
  ensemble: string | null;
  scoring: string | null;
  instrument: string | null;
  is_default: boolean;
  active: boolean;
  price_net: string | null;
  price_gross: string | null;
  vat_percent: string | null;
  currency: string | null;
  stock: number | null;
  wix_state: ChannelState;
  sevdesk_state: ChannelState;
  amazon_state: ChannelState;
}

/** The product list's main row shape ("Product List V2: expandable variants") - one
 * row per fachliches Parent-Produkt; curated grouping already consolidates format/
 * ensemble/scoring variants into a single Product with several ProductVariant rows,
 * this is the read model for that. Mirrors ParentProductListItem /
 * catalog_list.ParentProductSummary. Replaces the old flat ProductListItem shape as
 * the `/products` list endpoint's response. */
export interface ParentProductListItem {
  id: string;
  display_sku: string;
  name: string;
  title_short: string | null;
  category: string | null;
  brand_name: string | null;
  product_type: string;
  status: string;
  active: boolean;
  variant_count: number;
  formats: string[];
  ensembles: string[];
  scorings: string[];
  instruments: string[];
  isbns: string[];
  asins: string[];
  price_net_min: string | null;
  price_net_max: string | null;
  price_gross_min: string | null;
  price_gross_max: string | null;
  currency: string | null;
  stock_total: number | null;
  tags: string[];
  wix_state: ChannelState;
  sevdesk_state: ChannelState;
  amazon_state: ChannelState;
  content_status: string | null;
  review_required: boolean;
  row_version: number;
  updated_at: string;
  variants: ProductVariantSummary[];
}

export interface ProductVariant {
  id: string;
  product_id: string;
  sku: string;
  name: string | null;
  is_default: boolean;
  active: boolean;
  stock_enabled: boolean;
  row_version: number;
  updated_at: string;
}

/** PRINT_PDF's `uri` is metadata only (network path text) - never render it as a
 * clickable/downloadable link. See docs/product_hub/ architecture decisions. */
export interface ProductAsset {
  id: string;
  product_id: string;
  variant_id: string | null;
  role: "COVER" | "GALLERY_IMAGE" | "SAMPLE_SCORE" | "PRINT_PDF" | "PREVIEW_PDF" | "AUDIO" | "DOWNLOAD" | "OTHER";
  sort_order: number;
  storage_kind: "OBJECT_STORAGE" | "NETWORK_PATH" | "WIX_MEDIA" | "EXTERNAL_URL";
  uri: string;
  mime_type: string | null;
  size_bytes: number | null;
  source_channel: string | null;
  source_external_id: string | null;
  source_url: string | null;
  public_share_allowed: boolean;
  health_status: "unknown" | "ok" | "missing" | "unreadable" | "checksum_mismatch" | "stale";
  last_checked_at: string | null;
  row_version: number;
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
  row_version: number;
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

// -- PR09: edit API ------------------------------------------------------------

export interface Tag {
  id: string;
  code: string;
  label: string;
}

export interface Edition {
  id: string;
  product_id: string;
  label: string;
  edition_number: number | null;
  status: string;
  published_at: string | null;
  notes: string | null;
  created_at: string;
}

/** Every edit request carries the row_version the client last saw; the server
 * rejects a stale one with 409 and returns the current server state instead of
 * silently overwriting a concurrent change. */
export interface ProductUpdateRequest {
  expected_row_version: number;
  name?: string;
  short_description?: string;
  description?: string;
  category?: string;
  status?: string;
  active?: boolean;
}

export interface ProductSkuRenameRequest {
  expected_row_version: number;
  sku: string;
}

export interface ImprovementCreateRequest {
  description: string;
  title?: string;
  severity?: "info" | "minor" | "major" | "critical";
}

export interface ImprovementUpdateRequest {
  expected_row_version: number;
  status?: "open" | "planned" | "resolved" | "wont_fix";
}

// -- OpenAI description/bullet-point generator ----------------------------------

/** A draft - never auto-saved. Apply description via the normal PATCH, bullets via
 * setBulletPoints(). Mirrors ContentGenerateResponse in schemas/products.py. */
export interface GeneratedContent {
  description: string;
  bullet_points: string[];
}

export interface BulletPointsUpdateRequest {
  expected_row_version: number;
  bullet_points: string[];
}

// -- Persistent Conflict Wizard ------------------------------------------------

export interface ConflictCase {
  id: string;
  product_id: string;
  variant_id: string | null;
  conflict_type: string;
  severity: "INFO" | "LOW" | "MEDIUM" | "HIGH" | "CRITICAL";
  status: string;
  priority_score: number;
  title: string;
  summary: string | null;
  detected_at: string;
  last_seen_at: string;
  snoozed_until: string | null;
  resolution_type: string | null;
  resolution_note: string | null;
  row_version: number;
}

export interface ConflictObservation {
  id: string;
  source: "hub" | "wix" | "sevdesk" | "amazon";
  raw_value: unknown;
  normalized_value: unknown;
  source_revision: string | null;
  observed_at: string;
}

export interface ConflictField {
  id: string;
  field_path: string;
  selected_value: unknown;
  selected_source: string | null;
  resolution_type: string | null;
  status: string;
  observations: ConflictObservation[];
}

export interface ConflictAction {
  id: string;
  channel: string;
  action_type: string;
  field_path: string | null;
  before_value: unknown;
  after_value: unknown;
  selected: boolean;
  status: string;
  outbox_event_id: string | null;
  error: string | null;
  verified_at: string | null;
}

export interface ConflictCaseDetail extends ConflictCase {
  product_sku: string;
  product_name: string;
  fields: ConflictField[];
  actions: ConflictAction[];
}

export interface ConflictCreateWixProductResult extends ConflictCase {
  external_id: string;
  catalog_version: "v1" | "v3";
  operation: "created_and_mapped" | "reused_existing";
}

export interface ConflictAdvice {
  title: string;
  explanation: string;
  likely_causes: string[];
  recommendation: string;
  next_steps: string[];
  confidence: "low" | "medium" | "high";
  warnings: string[];
  evidence: string[];
  mapping_search_status: "not_mapping" | "found" | "none" | "unavailable";
  mapping_search_terms: string[];
  mapping_candidates: ConflictMappingCandidate[];
  mapping_comparison: ConflictMappingComparison | null;
}

export interface ConflictMappingCandidate {
  external_id: string;
  name: string;
  sku: string;
  variant_external_id: string;
  variant_name: string;
  score: number;
  match_reasons: string[];
  description: string;
  product_type: string;
}

export interface ConflictMappingComparison {
  hub_name: string;
  hub_sku: string;
  hub_description: string;
  hub_product_type: string;
  hub_category: string;
  hub_status: string;
  hub_active: boolean;
  old_external_id: string;
  old_status: string;
  candidate: ConflictMappingCandidate | null;
}

export interface ConflictSummary {
  open: number;
  critical: number;
  waiting: number;
  partially_resolved: number;
  resolved: number;
}

/** Thrown by the API client when the server responds 409 (stale row_version) - the
 * conflict body is the current server state, per the build plan's "Konflikt -> HTTP
 * 409 mit aktuellem Serverstand". */
export interface ConflictError<T> {
  kind: "conflict";
  current: T;
}
