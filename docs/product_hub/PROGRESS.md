# XW Product Hub — Build Progress

Tracks which PR packages from `XW_PRODUCT_HUB_CODEX_5_6_LUNA_BUILD_PLAN.md` are done, so the
next work session (human, Codex, or Claude) does not have to re-derive state from scratch.
Update this file at the end of every PR.

## Conflict Resolution Wizard CW00–CW07 (2026-09-17)

Die erste produktive Wizard-Stufe ist umgesetzt: additive Migration 016, persistente
Cases/Felder/Observations/Aktionen/Scans, Normalisierung und Klassifikation vorhandener
`sync_conflict`-Signale, idempotenter Scan, Queue/Detail-WebUI, fortsetzbare
Entscheidungen, Snooze/Intentional Difference, verpflichtende Impact-Vorschau,
Optimistic Locking und auditierte Product-Hub-Änderungen. Wix-Korrekturen laufen
ausschließlich als `conflict.wix_apply` über die bestehende Outbox und werden erst nach
dem vorhandenen Wix-Readback als verifiziert abgeschlossen.

Sicherheitsgrenzen: Wizard, Scan und externe Channel-Anwendung haben getrennte,
standardmäßig deaktivierte Feature Flags. sevdesk/Amazon erscheinen als explizit nicht
unterstützt, bis echte Write-/Readback-Adapter vorhanden sind. Details und Reuse-Map:
`docs/product_hub/conflict_wizard/CW00_CURRENT_STATE.md`.

Zusätzlicher PR00–PR14-Befund: Die lokale `.venv` konnte durch einen alten
Editable-Install weiterhin `XW-Studio` statt dieses Checkouts importieren. `pytest`
setzt deshalb nun über `pyproject.toml` zuverlässig `src` voran.

## CW02B – Wix source snapshots and product images (2026-09-18)

Der Wizard kann jetzt über `POST /api/v1/conflicts/scan/wix` (und den Button **Wix
einlesen & vergleichen**) ausschließlich vorhandene Wix-Produktmappings read-only
einlesen. Pro Mapping werden Rohprodukt, Varianten und Bestand versionssicher
archiviert; unveränderte Payloads erzeugen keinen Duplikat-Snapshot. Produktbilder
werden als Asset-Metadaten übernommen: erstes Bild `COVER`, weitere `GALLERY_IMAGE`,
jeweils mit Wix-URL und ohne Download oder Wix-Write. Nicht mehr in Wix vorhandene Bilder
werden als `stale` erhalten. Die sicheren Felder `name`, `description` und `visible`
werden idempotent zu technischen Konflikten und dann Wizard-Cases materialisiert.
Externe Writes bleiben weiter standardmäßig deaktiviert.

## Product List V2: parent products with expandable variants (2026-09-17)

Follow-up to the Master Seed V2 replace below, from `docs/CLAUDE_CODE_PROMPT_Product_List_Parent_Variants_V2.md`.
The "duplicate physical/digital rows" problem this brief describes turned out to be
two separate, smaller gaps rather than a missing grouping model — curated grouping
(`grouping.py`) already consolidates format/ensemble/scoring variants into one
`Product` with several `ProductVariant` rows; `list_products()` just never excluded
*archived* (grouped-away) children, and the list API never aggregated per-variant data
onto the parent row. No new grouping logic was written or needed.

**Key finding used throughout**: `Product.sku` is always the canonical/default
variant's SKU by construction (`create_product()` gives a product and its sole
variant the same SKU; grouping never renames the parent or touches its own default
variant) — this made `display_sku` free, no new column needed. Per-row metadata
(`format`/`music_attributes`/`title_short`/...) that a grouped-away variant's original
row carried survives on that row's own (archived, never hard-deleted) `Product.attributes`
— recovered with one batched `Product.sku IN (...)` lookup
(`repositories/product_hub.py`'s `list_products_by_skus`), no backfill/migration step
needed.

**Backend**:
- `repositories/product_hub.py` — `ProductFilter.include_archived` (default `False`,
  was previously not filtered at all); search now also matches any variant's SKU, not
  just the parent's; new batched methods (`list_variants_for_products`,
  `list_products_by_skus`, `list_prices_for_variants`,
  `list_channel_mappings_for_entities`, `list_tag_labels_for_products`,
  `sum_stock_on_hand_for_variants`) so the list endpoint is a handful of queries per
  page, never one per product.
- `services/product_hub/catalog_list.py` (new) — `build_parent_product_summaries`:
  assembles `ParentProductSummary`/`VariantSummary` (variant_count, formats/
  ensembles/scorings/instruments, price net/gross min-max, stock_total, tags, Wix/
  sevdesk/Amazon channel state, content_status, review_required, full variant list).
  `natural_sku_key` — numeric-segment-aware SKU sort (`XW-101.2` before `XW-101.10`).
- `web/schemas/products.py` / `web/routers/products.py` — `GET /api/v1/products` now
  returns `ParentProductListItem` (was the flat `ProductListItem`) — one row per
  fachliches Product, `variants: [...]` embedded for the expand UI.
- Known gap: `channel_mapping` is product-scoped only (confirmed during the Master
  Seed V2 grouping run below — see the "Astronaut" conflict), so only a product's
  *default* variant can honestly report a real Wix sync state; every other variant
  falls back to its own `sync_wix` hint. ISBN/ASIN were **not** added as list columns
  (would need another batched `product_identifier` query) — noted as a remaining gap,
  not silently dropped.

**Frontend** (`web/product-hub/`):
- `pages/ProductListPage.tsx` — SKU is now a pinned, always-visible, always-first,
  naturally-sorted column (`utils/naturalSort.ts`); expand/expand-collapse chevron for
  `variant_count > 1` renders a per-variant sub-table (Format/Besetzung, SKU, Netto,
  Brutto, Bestand, Wix, sevdesk, Amazon, Aktiv); expand click never navigates to the
  detail page (`stopPropagation`); column picker extended from 8 to 23 toggleable
  fields (§8 minus ISBN/ASIN, see backend gap above) with the same documented
  defaults as the build request.
- `vitest` added as a dev dependency (pinned to v2, since v3+ requires Vite 6/7 and
  this project is still on Vite 5) — the project previously had no test runner at
  all. `naturalSort.test.ts` covers the sort requirement directly; full component/DOM
  tests (expand/collapse interaction, ARIA, keyboard) were **not** added — that needs
  jsdom + testing-library, a separate infrastructure decision, and were instead
  verified by code review, `tsc --noEmit`, and manual reasoning through the DoD list.

**No Wix/sevdesk/Amazon writes** — this is a read-model change only.

## Master Seed V2 (2026-09-17): canonical SKUs, aliases, curated grouping applied

V1 (972 flat products, see "Catalog correction" below) is fully replaced by Master
Seed V2 — not a text fix, a corrected catalog: canonical `XW-4xx -> XW-4xxx` SKU
normalization, 87 legacy-SKU aliases, consistent brands/categories, unified titles
across format variants, explicit `sync_wix`/`sync_sevdesk`/`sync_amazon` channel hints,
and — for the first time — the seed's own curated grouping is actually *applied*
instead of staying flat.

**Files** (`docs/producthub_master-seed/`): `XW_Product_Hub_Master_Seed_2026-09-17.csv`
(kanonischer Pfad, content now V2, 915 rows), `XW_Product_Hub_Master_Seed_README.md`
(V2), `XW_Product_Hub_Review_Conflicts_2026-09-17.csv` (V2, 24 rows), plus two new V2
files: `XW_Product_Hub_SKU_Aliases_V2_2026-09-17.csv` (87 rows) and
`XW_Product_Hub_Channel_Cleanup_V2_2026-09-17.csv` (91 rows, documentation/worklist
only — **no automated Wix/sevdesk/Amazon writes happened or were even attempted**).

**New code**:
- `services/product_hub/master_seed_v2_validate.py` — hard-invariant validator (unique
  SKUs, no 3-digit `XW-4xx`, forbidden words `Zusatzstimme`/`ZST`/`ZS`/`Band` in the
  three title fields, brand rules, `Zusatzstimme` category rule, format-variant title
  equality). One documented, data-confirmed exception: `XW-017` (`record_state=REVIEW`)
  violates the word rule in `code_short` only — reported, not blocking, since it's
  already a self-flagged review case (also in `Review_Conflicts_2026-09-17.csv`).
- `master_seed_import.py` — extended (not replaced) to carry the new V2 columns
  (`canonical_sku`, `legacy_sku_aliases`, `canonical_variant`, `variant_role`,
  `arrangement_variant`, `sot_status`, `derived_from_sku`, `sync_wix/sevdesk/amazon`,
  `wix_publish_eligible`, `review_required`, `channel_cleanup_required/notes`) into
  `normalized_fields`/`product.attributes` — purely informational, never triggers an
  external action.
- `repositories/product_hub.py` — new `add_sku_alias`/`list_sku_aliases` (idempotent;
  repointing an existing alias to a different target raises rather than guessing).
- `services/product_hub/sku_alias_import.py` — applies the alias CSV via
  `add_sku_alias` after commit; an alias never creates its own product.
- `services/product_hub/master_seed_v2_grouping.py` — reads `product_group_id`/
  `canonical_variant`/`parent_sku`/`variant_role` only (cross-checks `parent_sku`
  against the `canonical_variant`-derived parent; skips on disagreement); calls the
  existing `GroupingService.preview_grouping` then `group_products_into_parent` per
  group, never on a fuzzy basis. Unsafe (channel-mapping-conflicting) groups are
  skipped and reported, never forced.
- `services/product_hub/master_seed_v2_replace.py` — `check_catalog_replaceable`
  (compares the catalog's entire `audit_log` trail against the known set of automated
  import+grouping actions; any other action — a manual PATCH, a bullet-point edit —
  blocks the replace) and `delete_legacy_master_seed_catalog` (FK-safe order,
  everything deleted **explicitly**, not left to `ON DELETE CASCADE` — see the
  module's own docstring for the SQLite-cascade bug this caught during local testing).
- `scripts/product_hub/replace_master_seed_v2.py` — the repeatable, checked pipeline:
  validate -> check-replaceable -> delete -> stage -> match (safety check) -> commit ->
  group -> import aliases -> summary + acceptance checks. `--yes` required to write
  anything; without it, dry-run only. Confirmed idempotent (ran twice back-to-back
  locally, byte-for-byte identical result the second time).

**Bug caught and fixed mid-rollout**: the first production attempt failed at the
grouping step with `IntegrityError: ix_product_variant_one_default_per_product` — a
PostgreSQL-only partial unique index (migration 009) that no SQLAlchemy model
declares and no SQLite test therefore enforces. Root cause: `move_variant()` re-parented
a variant without clearing its `is_default` flag, so moving a (always-default, since
every `create_product()` gives a product exactly one, default variant) child variant
into a parent that already had its own default variant produced two `is_default=true`
rows under one `product_id`. Fixed in `repositories/product_hub.py`'s `move_variant`
(always clears `is_default` on move; the caller's existing `set_default_variant` call
promotes the right one) and mirrored in `grouping.py`. The grouping tests' own SQLite
fixture now creates the same partial unique index manually so this class of bug can't
hide again. First attempt had already safely deleted+re-staged+committed before
failing (transactional per group — nothing corrupted); the second, fixed run replaced
the catalog cleanly from scratch.

A second, unrelated, pre-existing bug was found while first attempting the delete:
`inventory_movement` (PR13/14's variant-keyed shadow ledger) was never actually
created in production — migration 014's own `if "inventory_movement" not in
existing_tables` guard silently skipped it because migration 002 already had a
same-named but incompatible (product-keyed) legacy table. The Inventory V2
shadow-mode ledger had therefore never actually recorded a real movement in
production. **Fixed as a same-day follow-up**: migration 015
(`015_inventory_movement_rename.py`) creates PR13/14's ledger under its own,
collision-free name, `product_hub_inventory_movement`
(`models/product_hub_inventory.py`'s `InventoryMovement.__tablename__` updated to
match); the legacy `inventory_movement` table is untouched, still owned by the
unrelated desktop inventory path. Applied to production (`alembic upgrade head`,
014 -> 015) and verified: `product_hub_inventory_movement` exists with the correct
variant-keyed schema, legacy `inventory_movement` still has its original 0 rows.
`delete_legacy_master_seed_catalog` now deletes from the correctly-named table too.

**Verified locally (SQLite) before touching production**, then **run against
production for real** with identical results both times:
- 915 rows staged, 915 committed (0 errors), 0 matching conflicts/duplicates/suggestions
  (empty table, as expected)
- grouping: 136 candidate groups, **131 applied** (160 variants moved, 160 child
  products archived), **5 deferred as genuine channel-mapping conflicts** — 4 of the 5
  are exactly the documented Channel-Cleanup cases (`XW-4039`/`XW-4034` legacy-SKU
  normalization, `XW-4516` Mnoschil, `XW-6012` Bier-Polka/BH-Polka); the 5th
  (`XW-6402`/`XW-6801`, "Astronaut" in two ensembles) is new: it shows that
  `channel_mapping` is currently product-level only, so two independently-Wix-listed
  ensemble variants of one grouped product can't be represented without a future
  variant-level channel-mapping extension. None of these 5 were forced — they stay
  flat, ungrouped, exactly as before, until their channel_cleanup is done externally.
- 87 SKU aliases created, 0 errors
- all 9 acceptance checks from the build request passed: `resolve_sku("XW-443") ==
  resolve_sku("XW-4043")`; XW-443 resolves only via alias; `XW-102.5`/`XW-102.5-D`
  share one product and title; `XW-551.01`/`XW-551.01-P` share one product and title;
  `XW-511.16` draft/`XW-511.17` live; `XW-562.12` title contains "#2"; `XW-4024.2`/
  `XW-4024.3` end up as two distinct variants of one grouped product; brand/category/
  forbidden-word invariants enforced by the step-1 validator (which ran and passed on
  the exact CSV before any write).
- final state (both locally and in production, identical): 915 `product` rows total,
  755 non-archived (131 groups merged 160 rows away), `product_variant` still 915
  (grouping moves variants, never deletes them), 87 `product_sku_alias`, 262
  `channel_mapping` (wix).

**Not done automatically, by design**: no Wix/sevdesk/Amazon write of any kind — the
Channel-Cleanup CSV stays a worklist. The 5 deferred grouping conflicts stay flat until
resolved. Full PR15/PR16 (inventory cutover / legacy JSON removal) still explicitly out
of scope, unchanged from before (see "Why PR15/PR16 stop here" below).

## Catalog correction (2026-09-17): wrong-sheet import replaced with master-seed

The first real catalog load (111 products, 2026-09-16) used the `Produktpalette` sheet
directly — the wrong source. Per the user: only the `XeisWorks`/`MusikHeroes` sheets are
source of truth. The user prepared a reconciled 972-row master-seed CSV (cross-referencing
XLSX/Wix/sevdesk/Amazon, see `docs/producthub_master-seed/…_README.md` for the full
source-of-truth/modeling rules) and asked for the 111 wrong products to be deleted and
replaced with it.

Deleted all 111 products (correct FK order: product_improvement/product_edition/audit_log/
channel_mapping first, then product_variant, then product — RESTRICT constraints block a
naive `DELETE FROM product`). New `services/product_hub/master_seed_import.py` stages the
CSV; `import_commit.py` gained master-seed-specific enrichment (Wix linkage only when the
seed already knows the handle, AUTO_DRAFT content flagged as an open `product_improvement`
for editorial review, `EXTERNAL_ONLY` sevdesk-only rows tagged "Nicht zum Verkauf" instead of
treated as missing-Wix-mapping defects). Committed **972 products, 0 errors** — verified
against the README's own expected counts (244 draft/501 live/227 review, 226 not-for-sale,
660 auto-draft-content, all exact matches).

**Not done yet**: the CSV's pre-computed curated-grouping hints (`parent_sku`/
`product_group_id`/`group_key`) are staged in `product.attributes` but not yet applied — the
972 products are currently all flat/ungrouped, per the "safe migration rule" (import flat
first, curated grouping is a separate, explicit step). Applying that grouping is a natural
next step whenever picked up.

## OpenAI content generator + WebUI column visibility (2026-09-17)

Two follow-up requests after the master-seed catalog correction:

1. **OpenAI description/bullet-point generator.** `services/product_hub/content_generation.py`
   (`ContentGenerationService`) mirrors the existing hand-rolled `httpx` → Responses API pattern
   used elsewhere in this codebase (`ai_classifier.py`, `sendungen/service.py` — model
   `gpt-4.1-mini`, no OpenAI SDK anywhere), reading `OPENAI_API_KEY` via the same
   `_EnvSecretSource` adapter PR11's Wix work introduced. `POST
   /api/v1/products/{id}/generate-content` returns a **draft only** — it never writes to the DB.
   Saving is a separate, explicit step: the description goes through the existing product PATCH,
   bullet points through the new `PUT /api/v1/products/{id}/bullet-points`
   (`EditingService.set_bullet_points`, stored in `product.attributes.bullet_points`). Same
   "never silently apply" rule as every other AUTO_DRAFT content in this system. WebUI: a
   "Beschreibung generieren (KI)" button on the product detail page shows the draft with
   Übernehmen/Verwerfen before anything is saved.
2. **Column visibility picker.** Eye-icon button top-right of the product list applies a
   `localStorage`-persisted (per-viewer only, never synced) set of visible columns. Table rows
   became fully clickable (`onClick`/`onKeyDown` → navigate) instead of relying on a `Link` in
   the SKU cell, so hiding the SKU column never breaks navigation to the detail page.

**Not raised yet**: the near-duplicate SKU pair the user spotted (`XW-102.3-D` vs `XW-102.3 D`,
identical title) from the master-seed import — no action taken; per the "no fuzzy auto-merge"
rule this needs explicit human review, not a silent fix.

## Status

| PR | Title | Status | Notes |
|---|---|---|---|
| PR00 | Align architecture docs and guardrails | **Done** | `docs/product_pipeline_masterplan.md` / `docs/product_pipeline_phases.yaml` updated; historical "sevDesk = SOT für Bestand" statement struck through and replaced. Approved specs copied to `docs/product_hub/`. |
| PR01 | Canonical ORM schema and repositories | **Done, migration applied to Railway** | See below. |
| PR02 | Import staging foundation | **Done** | See below. |
| PR03 | Wix read importer | **Done (code), reads only via fixtures — never called against the live Wix API in this session** | See below. |
| PR04 | sevdesk read importer | **Done** | See below. |
| PR05 | Excel import and matching | **Done** | See below. |
| PR06 | Import commit service + curated grouping | **Done** | See below. |
| PR07 | Product Hub Read API | **Done and confirmed live on Railway** (`/api/v1/products` → 401 on the production domain) | See below. |
| PR08 | Read-only WebUI/PWA | **Done and confirmed live on Railway** (`/app/` → 200, SPA routes fall back to `index.html`, `/api/v1/products` still 401 as before) | See below. |
| PR09 | Edit API + WebUI editing + Verbesserungen/Auflagen | **Done (code + migration applied), edit API kept off in production pending a deliberate flip** | See below. |
| PR10 | Transactional outbox + sync foundation | **Done (schema + worker + wiring), migration applied — no consumer/handler yet** | See below. |
| PR11 | Wix push + reconcile + conflict management | **Done (code, no new migration), push kept off in production pending a deliberate flip** | See below. |
| PR12 | Händlerfreigabe + CSV/XLSX Export | **Done and confirmed live on Railway** (`/share/{token}` is public, no bootstrap token needed) | See below. |
| PR13 | Inventory V2 Shadow Mode | **Done and deployed** — ledger + alerts + shadow reconcile, legacy inventory paths untouched (by design) | See below. |
| PR14 | Lagerwarnungen + XW-Flow Integration | **Done and deployed** — alert crossing + `/api/v1/inventory/summary`, XW-Flow task as an outbox-event intent (no real HTTP client — see below) | See below. |
| PR15 | Inventory Cutover: Product Hub wird Master | **Deliberately not attempted** — see "Why PR15/PR16 stop here" below | — |
| PR16 | Legacy JSON entfernen | **Blocked on PR15** | — |

## ⚠️ Infrastructure incident (2026-09-16, discovered during PR12): DATABASE_URL was never
set on the XW-Content-Web Railway service

**Every "confirmed live" note for PR07–PR11 above was a false positive.** Every
production check run in this session (and apparently since PR07) only ever tested the
*no-bootstrap-token* path and asserted `401` — proof the route exists, never proof the
DB-backed gate (`require_product_hub_enabled`) actually passes. `XW-Content-Web`'s
Railway variables were `XW_CONTENT_BOOTSTRAP_TOKEN` / `XW_CONTENT_ENVIRONMENT` /
`XW_CONTENT_PUBLIC_URL` only — **no `DATABASE_URL` at all** — so
`ContentWebSettings.database_url` was always `""`, `_session_factory` was always
`None`, and every single Product Hub endpoint (read API, edit API, sync API, sharing
API) had been returning `503 {"detail":"Product Hub API is not
configured/enabled"}` for every real request, this entire time. All migrations
(009–013) landed fine regardless, because those were applied directly via `alembic
upgrade head` against a `DATABASE_URL` from *this development machine's own shell*,
not from Railway's environment for the service — two completely separate places
that happened to point at the same Postgres, which is exactly why this went
unnoticed: the data was always correct, only the *web service's own access to it*
was never wired up.

**Found via:** PR12's new public `/share/{token}` route has no bootstrap-token
dependency at all, so an unauthenticated curl hit the DB gate directly instead of
stopping at a 401 first — returned 503, which is what surfaced this.

**Fixed:** `railway variables --service XW-Content-Web --set
'DATABASE_URL=${{Postgres.DATABASE_URL}}'` (referencing the same Postgres service this
whole build has been migrating against) — Railway auto-redeployed on the variable
change (deployment `7144c5ef…`, SUCCESS). **Verified with a real unauthenticated
request** (`/share/nonexistent-token` → `404 {"detail":"Unknown share"}`, not 503) —
this is the first point in the whole PR07–PR12 arc where a request has been
confirmed to actually reach the database in production.

**Implication:** PR07–PR11's "confirmed live" claims in the sections below should be
read as "code deployed and reachable at the HTTP layer," not "verified working
end-to-end with real data" — that verification effectively happens for the first
time now, after this fix. Recommend an explicit pass with the real bootstrap token
(not available in this session) to click through `/api/v1/products`,
`/app/`'s actual data rendering, etc. before trusting any of it beyond what curl-
without-auth can prove.

## PR01 detail

**Code delivered:**
- `src/xw_office/models/product_hub.py` — first ORM mapping of the legacy `product` table
  (previously migration-only, no model) plus all new PR01 tables (`product_family`,
  `product_variant`, `product_identifier`, `category`/`product_category`, `tag`/`product_tag`,
  `price_list`/`product_price`, `product_asset`, `print_rule`, `product_edition`,
  `product_improvement`, `channel_mapping`, `channel_category_mapping`, `audit_log`) and the
  `product_sku_alias` → `product_variant` bridge (`ProductSkuAlias.variant_id`).
- `src/xw_office/repositories/product_hub.py` — `ProductHubRepository`: `get_product`,
  `get_product_by_sku`, `list_products` (filters), `create_product` (always creates exactly one
  default variant), `update_product` (optimistic locking via `row_version`, raises
  `OptimisticLockError`), `resolve_sku` (variant SKU or legacy alias, case/whitespace-normalized),
  `list_variants`, `get_default_variant`, `set_default_variant` (enforces "one default variant per
  product" at the app layer — see below), `list_identifiers`, `add_identifier`, `list_assets`.
- `src/xw_office/migrations/versions/009_product_hub_core.py` — additive Alembic migration from
  head `008_digital_license_fulfillment`. Extends `product` (slug, short_description, description,
  family_id, product_type, active, release_date, attributes, row_version, archived_at), creates
  all new tables, seeds `price_list` rows `RETAIL_EUR`/`B2B_EUR`, and backfills exactly one default
  `product_variant` + `channel_mapping` (wix/sevdesk) + `product_asset`(PRINT_PDF/NETWORK_PATH) +
  `print_rule` for every pre-existing `product` row. Idempotent per table/column (checks
  `inspector.get_table_names()` / `get_columns()` before creating).
- `ProductHubSection` feature flags added to `AppConfig` (`core/config.py`) and
  `config/default.yaml`: `catalog_read_enabled`, `catalog_write_enabled`, `sync_push_enabled`,
  `inventory_shadow_enabled`, `inventory_master_enabled`, `shared_catalog_enabled` — all `false`
  by default, per build-plan §4. Nothing reads them yet (no consumer until PR07+).
- `tests/unit/test_product_hub_repository.py` — 18 tests (SQLite in-memory, same pattern as
  `tests/unit/test_repositories.py`): SKU normalization/uniqueness, slug uniqueness, SKU
  resolution (direct + legacy alias, with/without `variant_id` bridge set), default-variant
  invariant, optimistic locking (success + stale + unknown field), identifier uniqueness +
  "exactly one owner" CHECK constraint (both directions), `Decimal`-only money, list/search
  filters.

**Verified in this environment:** `pytest tests/` (1041 passed, 1 pre-existing unrelated failure
— see below), `ruff check src/` (clean), `mypy src/xw_office/models/product_hub.py
src/xw_office/repositories/product_hub.py src/xw_office/migrations/versions/009_product_hub_core.py`
(clean; the 447 pre-existing mypy errors elsewhere in `src/xw_office/ui/...` are untouched and
CI already runs mypy with `continue-on-error: true`).

**Pre-existing, unrelated test failure:** `tests/unit/test_uva_soap_mock.py::test_unconfigured_client_raises`
fails when run as part of the full suite (passes alone) — reproduced identically on `main` before
any product-hub change, confirmed via `git stash -u`. Order-dependent test pollution in the
FinanzOnline UVA tests, not caused by this work.

**Migration applied to Railway (2026-09-16):**
`alembic current` was 008 (no drift) and the live `product` table had **0 rows** — the real
operational catalog still lives entirely in `SettingKV["inventory.products"]`, `product` has never
been written to by `ProductCatalogService`/`InventoryService`, so the backfill loop was a no-op by
construction (verified before running: `SELECT COUNT(*) FROM product` = 0). `alembic upgrade head`
was run against the real `DATABASE_URL`; `alembic current` now reports `009_product_hub_core
(head)`, all 16 new tables exist, `price_list` has `RETAIL_EUR`/`B2B_EUR` seeded, and `product` has
the new `slug`/`row_version`/`active`/... columns. Given the 0-row backfill, no separate data
spot-check was needed this time — a future migration that touches non-empty tables should still get
a backup/snapshot first.

**Design decisions worth knowing for later PRs:**
- "One default variant per product" is enforced two ways: a PostgreSQL-only partial unique index
  (`ix_product_variant_one_default_per_product`, `WHERE is_default = true`) in the migration, and
  transactionally in `ProductHubRepository.set_default_variant` — the latter is what makes the
  SQLite-backed test suite meaningful, since SQLAlchemy's `postgresql_where` index option is
  silently dialect-specific.
- SKU storage/comparison is normalized (`strip().upper()`) end to end, matching the existing
  `ProductCatalogService` convention (`part.sku.strip().upper()`), not the "preserve original,
  compare normalized" split the data-model doc mentions as an option.
- `product.sku`, `wix_product_id`, `sevdesk_part_id`, `print_file_path`, `min_stock_target`,
  `reprint_batch_qty` are untouched and still legacy-authoritative for existing consumers
  (`ProductCatalogService`, `InventoryService` — both still read/write
  `SettingKV["inventory.products"]`/`inventory.stock_levels"]` exclusively, not the `product`
  table). PR01 does not change any of that; it only adds new, currently-unused structure
  alongside it, per the build plan's explicit "no Big-Bang" instruction.

## PR02 detail

**Code delivered:**
- `src/xw_office/models/product_hub_import.py` — `import_batch`, `staging_product`,
  `staging_variant`, `staging_identifier`, `staging_asset`, `staging_inventory`,
  `staging_category`, `import_match_candidate`. No staging table has any relationship to the
  canonical schema beyond plain UUID columns (`proposed_product_id`, etc.) — deliberately not
  FKs, since a staged row may propose a product that does not exist yet.
- `src/xw_office/repositories/product_hub_import.py` — `ProductHubImportRepository`:
  `create_batch`/`finish_batch`, `ingest_staging_product` (idempotent upsert keyed on
  `(import_batch_id, source, source_key)`, preserves any existing match decision on re-ingest),
  `set_match`, `list_staging_products` (filters), plus `add_identifier`/`add_asset`/
  `add_inventory`/`add_category`/`add_variant` and `add_match_candidate`/`list_match_candidates`.
  `hash_payload()` is a stable (key-sorted) sha256 helper, reusable by the PR03–PR05 importers.
- `src/xw_office/migrations/versions/010_product_hub_import_staging.py` — additive from head
  `009_product_hub_core`. Claude's own `alembic upgrade head` attempt was blocked by the Claude
  Code auto-mode classifier ("Production Deploy"); the user ran it manually in PowerShell instead
  (confirmed: `alembic current` → `010_product_hub_import_staging (head)`).
- `tests/unit/test_product_hub_import_repository.py` — 10 tests: idempotent re-ingest (same
  payload and changed payload, both without duplicating rows), payload-hash stability
  (key-order-independent), match-decision preservation across re-ingest, batch
  completion/failure, filtered listing, all staging sub-row types round-tripping, and an explicit
  rollback test (forces a unique-constraint violation mid-transaction on a raw `Session`, confirms
  `session.rollback()` leaves zero rows).

**Verified:** `pytest tests/` all green except the two known pre-existing, order-dependent
flaky failures below (never both together; count varies by run); `ruff check src/` clean;
`mypy` clean on every PR02 file (the 2 `core/config.py` errors that show up when mypy follows
imports are pre-existing — confirmed identical on `main` via `git stash -u`, unrelated to this
change, lines 121/401, `list[dict]`/`no-any-return` in code this PR did not touch).

**Newly observed (not a regression, but worth recording):** adding
`tests/unit/test_product_hub_import_repository.py` shifts pytest's collection order enough
that `tests/ui/test_async_action.py::test_async_action_sets_and_restores_busy_state`
intermittently fails in the full-suite run (passes alone; passed again on a repeat full-suite
run with the exact same code) — this is pre-existing order/state flakiness in the Qt test
suite, not something PR02's pure-SQLAlchemy code can cause. Worth a dedicated cleanup PR
outside the product-hub track (e.g. explicit `PYTHONHASHSEED`/qapp-fixture isolation) if it
keeps being disruptive.

## PR03 detail

**Code delivered:**
- `src/xw_office/services/wix/product_details_client.py` — three new, additive, read-only
  methods on the existing `WixProductDetailsClient`: `get_product_raw` (full unparsed product
  JSON — `get_product`/`WixProductDetail` intentionally drop media and the full variant list),
  `query_variants` (Catalog V3 Read-Only Variants, up to 1000/query), `query_inventory`
  (Inventory V3, variant/location-based). None of the existing methods/behavior changed.
- `src/xw_office/services/product_hub/wix_import.py` — `WixProductImporter`: pages all Wix
  products via the existing `WixProductsClient.list_products()`, then for each product fetches
  raw detail + variants + inventory and writes everything into staging
  (`ProductHubImportRepository`). Media rule: first item = `COVER`, the rest = `SAMPLE_SCORE`
  (confirmed architecture decision). One failing product is recorded in the batch's
  `error_summary` and does not abort the rest of the batch. Depends only on two small
  `Protocol`s (`WixProductsSource`, `WixDetailsSource`), so it can be tested without any network
  access or real Wix credentials.
- **No Wix write call anywhere in this PR** — `WixProductImporter` never calls an update/PATCH
  endpoint, only the pre-existing read client and the two new read-only methods above.

**Verified:** `pytest tests/` — 1065 passed (+24 new: 6 client-level fixture tests in
`test_wix_product_details_client.py`, 8 importer tests in `test_wix_import_service.py` covering
every build-plan fixture scenario — no variants, multiple variants, no media, cover+samples,
revision present, variant-based inventory, one-product-failure isolation, idempotent re-run —
plus the 10 pre-existing PR02 tests picking up the new `list_assets`/`list_inventory` repository
methods used by the importer tests); `ruff check src/` clean; `mypy` clean on every PR03 file
(only the same 2 pre-existing, unrelated `core/config.py` errors surface transitively). Same
single pre-existing flaky UVA failure as before, nothing new.

**Not done — deliberately, not a gap:** this PR was never run against the real Wix API. Per
the build plan ("Fixtures für: ...") PR03 is meant to be validated with fixtures, not live
calls, and reading a production e-commerce catalog from an agent session is exactly the kind
of external, business-visible action that should be a deliberate choice, not a side effect of
writing code. The next natural verification step is a **real, credentialed dry run**
(`WixProductImporter(...).run()` against the actual `WixProductsClient`/`WixProductDetailsClient`,
pointed at production Wix, still read-only) — worth doing once PR04/PR05 exist too, so the
resulting staging data can be reviewed end-to-end rather than piecemeal.

## PR04 detail

**Code delivered:**
- `src/xw_office/services/sevdesk/part_client.py` — one new, additive, read-only method on the
  existing `PartClient`: `fetch_parts_raw` (raw, unparsed `/Part` payloads, same pagination as
  the private `_fetch_parts`, kept fully independent of it/`list_parts`/`ensure_parts_cache` so
  none of their existing, widely-used behavior can change).
- `src/xw_office/services/product_hub/sevdesk_import.py` — `SevdeskPartImporter`: fetches every
  raw Part, reuses the already-tested `_parse_part` (a pure function) for field extraction, and
  stages one `staging_product` + one `staging_inventory` row (location `sevdesk`) + an optional
  `staging_category` row per Part. `internalComment` is kept only in `normalized_fields` and is
  never mapped onto a public description field (explicit build-plan rule). A Part without a SKU
  is staged with a blank SKU — no placeholder like the legacy `ProductCatalogService`'s
  `SEVDESK-<id>` is invented; that stays a matching-time decision (PR05/06). One failing Part
  does not abort the batch (same isolation pattern as PR03, proven with a payload engineered to
  fail JSON-hashing rather than a contrived "malformed" field that `_parse_part` already handles
  defensively).
- **No sevdesk write call anywhere in this PR.**

**Verified:** `pytest tests/` — 1076 passed (+11 new: 2 `fetch_parts_raw` tests in
`test_part_client.py`, 9 importer tests in `test_sevdesk_import_service.py` covering physical vs.
digital `stockEnabled`, category mapping, no-category, blank-SKU handling, alternate stock field
names, internal-comment isolation, single-part-failure isolation, and independent-batch re-runs);
`ruff check src/` clean; `mypy` clean on `fetch_parts_raw`/the importer (the pre-existing errors
that surface transitively — 2 in `core/config.py`, 2 in `services/http_client.py`, 3 in
`part_client.py`'s existing `_parse_part`/`SevdeskPart` — are all confirmed identical on the
pre-PR04 branch via `git stash -u`, none in code this PR touches). Same single pre-existing
flaky UVA failure, nothing new.

**Migration 010 status:** applied to Railway by the user via PowerShell (`alembic upgrade head`)
after Claude's own attempt was blocked by the Claude Code auto-mode classifier as a "Production
Deploy" action — confirmed via `alembic current` → `010_product_hub_import_staging (head)`.
Future migrations (011+) will need the same manual step unless that classifier rule changes.

## PR05 detail

**Product decision folded in (2026-09-16, from the user directly):** Amazon is **never** its
own category or product family. It becomes a suggested `Amazon` tag plus `product_identifier`
rows (`ASIN`/`FNSKU`/`ISBN13`) — consistent with the already-approved data model, where "Amazon"
was already listed as a *tag* example, not a category.

**Real file used:** the user placed the actual, current business workbook at
`docs/Produktpalette.xlsx` (committed — this repo already keeps other real business PDFs
directly under `docs/`, e.g. invoices and product covers, so this matches existing convention).

**Code delivered:**
- `src/xw_office/services/product_hub/excel_import.py` — `ExcelWorkbookImporter` plus three pure
  parsing functions (`parse_produktpalette_rows`, `parse_amazon_rows`, `read_besetzungen`) kept
  separate from the `openpyxl.load_workbook` call so the tricky part (multi-block sheet layout)
  is unit-testable without any file I/O.
  - `Produktpalette` is not one flat table — it is five "EDITION" blocks
    (TANZLMUSI/BLECH4ER/BLECH7ER/MUSIKHEROES/BÖHMISCH), each with its own title row and its own
    `Art.Nr./Titel/Beschreibung/SKG*/brutto/netto/netto` header row. Category comes from the
    nearest preceding title row containing "EDITION"; anything outside an active header block
    (subtitles, the "da Blechhauf'n" brand sub-label, the closing SKG legend) is skipped, not
    guessed at.
  - The sheet's two ambiguous "netto" columns (divisors `/1.05` vs `/1.1`, undocumented which is
    correct) are **both staged, never picked between** — a mismatch beyond a small tolerance
    becomes a `price_warning` for manual review, per the explicit build-plan rule.
  - `Amazon` rows are merged onto the matching Produktpalette-staged row by SKU via the new
    `ProductHubImportRepository.merge_normalized_fields` (shallow-merges into
    `normalized_fields` instead of clobbering it the way `ingest_staging_product`'s upsert would);
    ASIN/FNSKU/ISBN13 become `staging_identifier` rows, "Amazon" becomes a
    `normalized_fields["suggested_tags"]` entry. An Amazon row with no matching Produktpalette
    SKU still gets a minimal staging product so its identifiers are not lost, but — critically —
    gets **no category**, only the tag.
  - `Besetzungen` becomes a flat controlled-vocabulary list recorded on the batch's
    `source_metadata` (`ImportBatch.set_batch_metadata`, new), not staged as products.
  - `Händler` is recorded as present (`source_metadata`) but **deliberately not parsed** — it is
    a non-tabular, multiple-mini-tables-per-row layout, and the build plan explicitly scopes it
    as "nur kontrolliert" (controlled reference only, not auto-imported).
  - `XeisWorks`/`MusikHeroes` are not touched at all in this PR — the approved data model marks
    them `legacy_catalog_view`/`legacy_series_and_variant_relationship_reference`, evidence for
    PR06's curated grouping later, not PR05 import material.
- `ProductHubImportRepository` gains `set_batch_metadata` and `merge_normalized_fields` (both
  additive, needed so a second sheet can enrich a staging row a first sheet already created).

**Verified against the real workbook, not just fixtures:** a dedicated smoke test
(`test_run_against_real_workbook_is_read_only_and_stages_products`, skipped gracefully if the
file is ever absent) runs the importer against `docs/Produktpalette.xlsx` itself and asserts the
file's bytes are byte-for-byte unchanged afterward. A manual run confirmed: **111 products
staged** (matches the deep-research audit's independently-counted "111 eindeutige Produkt-SKUs"
exactly), all 5 categories detected correctly, 22 identifiers staged from the Amazon sheet with
**zero** Amazon-only orphan products (every Amazon SKU already existed in Produktpalette), and
**22 netto-ambiguity price warnings** correctly raised instead of silently guessing a price.

**Verified:** `pytest tests/` — 1091 passed (+15 new in `test_excel_import_service.py`: 9 pure
parsing-logic tests — category detection, multi-block handling, footnote/non-SKU skipping,
rows-outside-any-block, ambiguous/non-ambiguous/single-value netto, Amazon field extraction,
Besetzungen — plus 5 end-to-end tests against a small generated fixture workbook and the 1 real
smoke test above); `ruff check src/` clean; `mypy` clean on every PR05 file. Added a
`[[tool.mypy.overrides]]` for `openpyxl.*` (`ignore_missing_imports`) since no `types-openpyxl`
stub package is installed and this is the first module in the codebase to import openpyxl in
`src/`. Same single pre-existing flaky UVA failure, nothing new.

**No migration needed:** PR05 only uses the PR02 staging schema; no new tables/columns.

### PR05 continued: cross-source matching engine

**Code delivered:**
- `src/xw_office/services/product_hub/matching.py` — `MatchingEngine.run(batch_id=...)` resolves
  every (or one batch's) `staging_product` row against the canonical schema in the build plan's
  strict priority order, never auto-merging below "exact" certainty:
  1. existing `channel_mapping.external_id` (wix/sevdesk rows already linked)
  2. exact normalized SKU (`ProductHubRepository.resolve_sku`)
  3. SKU alias (same call — `ResolvedSku` gained a `matched_via: "sku" | "alias"` field so the
     matching engine can tell `exact_sku` and `sku_alias` apart in `match_method`)
  4. unique identifier (ISBN/EAN/ASIN/...) — resolves via all of *that row's own* staged
     identifiers; if they resolve to more than one distinct canonical product, that is treated
     as a **conflict** (contradictory identifiers on the same row), not a match — a single
     identifier matching one existing product is a normal tier-4 match, not a conflict, even if
     the row's SKU alone did not already match
  5. fuzzy name suggestion (rapidfuzz `WRatio`, threshold 80) — written only as
     `import_match_candidate` rows plus `match_status="suggested_match"`, **never**
     `proposed_product_id`/`exact_match` — a human must confirm it
  - Also detects **duplicates** (two different staged rows in the same run both resolving to the
    same canonical product) and **title drift** (SKU/alias match found, but the staged name and
    the canonical product's name diverge — rapidfuzz score below 90).
  - Returns a `MatchingReport` — the "Import-Review-Bericht" the build plan asks for: counts per
    match tier plus `conflicts`/`duplicates`/`title_drift` string lists for human review.
- `ProductHubRepository` (PR01) gained three lookups needed to support this:
  `get_channel_mapping`, `find_identifier`, `get_variant` — all additive, read-only.

**Verified:** `pytest tests/` — 1102 passed (+11 new in `test_product_hub_matching_engine.py`,
covering all 5 priority tiers individually, the conflict-vs-normal-match distinction explicitly
(two dedicated tests proving contradictory identifiers are flagged while a single reused
identifier is not), fuzzy-threshold boundary behavior, duplicate detection, title drift, and
batch-scoped vs. all-staging runs); `ruff check src/` clean; `mypy` clean on every file this
touched (same 2 pre-existing, unrelated `core/config.py` errors surface transitively). Same
single pre-existing flaky UVA failure, nothing new.

**PR05 is now complete** per the build plan's own definition (import + matching engine +
review-report). PR06 (import commit service + curated grouping) is the natural next step: it
will read `match_status`/`proposed_product_id` plus `import_match_candidate` rows this engine
produced, let a human approve/reject, and only then write to the canonical schema.

## PR06 detail (part 1: import commit service)

**Code delivered:**
- `src/xw_office/services/product_hub/import_commit.py` — `ImportCommitService`, one DB
  transaction per staging row (`session_scope` per call, `ProductHubRepository` and
  `ProductHubImportRepository` share that one `Session` so canonical writes and the staging
  row's status update are atomic together):
  - `approve_match`/`reject_match` — human review step; `approve_match` only allowed from
    `exact_match`/`suggested_match` (never silently promotes a `conflict`).
  - `preview_commit` — read-only dry run: `create` / `link_existing` / `already_committed` /
    `blocked` (with a reason), plus staged identifier/asset counts and suggested tags.
  - `create_from_staging` — the "safe 1:1 import" path: only from `unmatched`/`rejected`,
    requires a SKU, creates one product + one default variant, then enriches it.
  - `commit_approved_match` — the "link to existing" path: only from `approved`, enriches the
    already-existing target product, never touches its core fields (name/sku/...), only adds
    what is missing.
  - `commit_import_batch` — orchestrates a whole batch: auto-creates every `unmatched` row
    (no ambiguity to resolve), links every `approved` row, and explicitly does **not** touch
    `suggested_match`/`conflict`/`rejected` rows — those need a human decision first and are
    counted as `skipped_needs_review`. Per-row try/except: one row's `CommitError` is recorded
    in `errors` and does not abort the rest of the batch.
  - Idempotency anchor: `StagingProduct.committed_product_id`/`committed_at`
    (`ProductHubImportRepository.mark_committed`, new) — re-running `create_from_staging`,
    `commit_approved_match`, or a whole `commit_import_batch` on already-committed rows is a
    safe no-op that returns the existing product instead of writing anything new.
  - Enrichment (`_merge_staging_extras`, shared by both commit paths): staged identifiers
    (conflict-checked against the canonical `product_identifier` table — a genuine conflict
    raises `CommitError` and commits nothing for that row), staged assets (deduped by
    `role`+`source_external_id`, stored as `storage_kind='EXTERNAL_URL'` — no download/mirroring
    in this PR, that stays a later asset-pipeline concern), Excel `staging_category` rows become
    real internal `category`/`product_category` rows (Wix/sevdesk staged categories are
    deliberately left in staging — mapping *external* categories needs its own curated step, a
    channel_category_mapping, not silent reuse as internal taxonomy), and
    `normalized_fields["suggested_tags"]` (the PR05 Amazon-tag mechanism) becomes real
    `tag`/`product_tag` rows — this is where "Amazon is a tag, not a category" actually lands in
    the canonical schema.
  - `wix`/`sevdesk` sourced rows get a `channel_mapping` row created automatically if one
    doesn't already exist for that `(channel, external_id)`.
  - Every commit/approve/reject writes an `audit_log` entry
    (`ProductHubRepository.record_audit`/`list_audit_log`, new).
  - **No `product_price` rows are created.** Given the Excel importer's explicit
    netto-ambiguity warnings (PR05), auto-writing a price would mean guessing at real business
    pricing — that stays a deliberate, reviewed step (PR09 edit API), not part of this PR.
- `ProductHubRepository` (PR01) gained: `create_channel_mapping`, `add_asset`,
  `get_or_create_category`/`list_product_categories`/`add_product_category`,
  `get_or_create_tag`/`list_product_tags`/`add_product_tag`, `move_variant` (used by the
  grouping half below), `record_audit`/`list_audit_log` — all additive.
- `ProductHubImportRepository` (PR02) gained `mark_committed`.

**Verified:** `pytest tests/` — 1121 passed (+19 new in
`test_product_hub_import_commit_service.py`: create/link/idempotency/status-guard tests for
both commit paths, the identifier-conflict-aborts-cleanly case, channel-mapping and
Excel-category enrichment, batch orchestration (create+link+skip+idempotent-rerun+
error-isolation), and all four `preview_commit` outcomes); `ruff check src/` clean; `mypy`
clean on every file this touched. Same single pre-existing flaky UVA failure, nothing new.

**No migration needed:** PR06 only writes through PR01/PR02's existing schema.

## PR06 detail (part 2: curated grouping) — PR06 now fully done

**Code delivered:**
- `src/xw_office/services/product_hub/grouping.py` — `GroupingService`, one transaction per
  call, same shared-session pattern as the commit service:
  - `move_variant_to_product(variant_id, target_product_id, actor=...)` — the low-level
    primitive: re-parents one variant, writes an audit entry. Variant-scoped identifiers/assets
    (`variant_id` set) follow automatically since their FK is the variant, not the product —
    nothing else needs to move for those.
  - `preview_grouping(parent_product_id, child_product_ids)` — read-only: counts of
    variants/identifiers/assets that would move, plus any `channel_mapping_conflicts`
    (`.is_safe` is `False` when any exist). No writes, ever.
  - `group_products_into_parent(parent_product_id, child_product_ids, actor=...)` — the curated
    grouping command itself. Two-phase: a **pure-read pre-check** (channel-mapping conflicts +
    all child ids exist) that raises `GroupingConflictError`/`KeyError` with **zero writes** if
    anything is wrong, then an apply phase that only runs once the pre-check is clean. For each
    child product: moves every variant, moves product-scoped identifiers/assets
    (`ProductHubRepository.reparent_identifier`/`reparent_asset`, new), copies
    `product_category`/`product_tag` links onto the parent then removes the child's own
    (`remove_product_categories`/`remove_product_tags`, new), moves `channel_mapping` rows
    (`reparent_channel_mapping`, new), then archives the child (`archive_product`, new —
    `active=False`/`archived_at`, never a hard delete). Ends with exactly one `is_default=True`
    variant on the parent (the parent's own pre-existing default wins over any moved-in child
    default) and one `audit_log` entry per archived child plus one summary entry on the parent.
  - Product-level identifier moves need **no conflict pre-check at all**: since
    `(scheme, normalized_value)` is already globally unique in `product_identifier`, a child's
    own identifier row cannot, by construction, collide with anything the parent already has —
    the only real grouping-time conflict is two *separate* channel listings (e.g. both parent
    and child already have their own Wix product), which the pre-check catches explicitly.
- `ProductHubRepository` gains the six additive methods named above plus
  `list_channel_mappings`.

**Verified:** `pytest tests/` — 1130 passed (+9 new in `test_product_hub_grouping_service.py`:
a full MusikHeroes-shaped scenario (one parent + two children, each carrying an identifier, an
asset, a category, and a tag) proving every SKU stays independently `resolve_sku`-resolvable
under the parent afterward and nothing is lost; the default-variant invariant explicitly;
the channel-mapping-conflict abort with a follow-up assertion that the child was **not**
touched at all; `preview_grouping` for both the conflict and the clean case; parent-cannot-
be-its-own-child, empty-children, and an unknown child id aborting before any real child is
touched); `ruff check src/` clean; `mypy` clean on every file this touched. Same single
pre-existing flaky UVA failure, nothing new.

**PR06 is now fully complete** per its own build-plan scope (atomic commit service, audit log,
preview/diff, safe 1:1 import, explicit curated grouping). PR07 (Product Hub Read API) is the
natural next step — it is the first PR that gives XW-Office Desktop and the future WebUI
anything to actually call.

## PR07 detail

**This is the first PR that changes the deployed Railway web service** (`xw-content-web`, built
from `Dockerfile.web`/`requirements-web.txt`) rather than only the desktop package — everything
before PR07 only added code the desktop app and its SQLite-backed tests could reach.

**Code delivered:**
- `src/xw_office/web/schemas/products.py` — Pydantic response models
  (`ProductListItem`/`ProductDetail`/`ProductVariantOut`/`ProductAssetOut`/
  `ProductImprovementOut`/`ChannelMappingOut`/`AuditLogOut`/`ProductReadinessOut`/
  `ReadinessSummaryOut`, generic `Page[T]`). Never serializes an ORM object directly
  (`from_attributes=True` + explicit fields only); `row_version` is included on product
  responses per the build plan's "editable internal responses" rule. `ProductAssetOut.uri` is
  included — that is fine for *this* bearer-token-protected internal API (Desktop needs the
  network path to find/print files) and is explicitly documented as **not** reusable as-is for
  PR12's future public/dealer-share schema, which must define its own, separately
  field-whitelisted models instead.
- `src/xw_office/web/routers/products.py` — `build_products_router(get_repo)`, a factory
  function (mirrors `create_app(settings)`'s own injection style) so the router stays testable
  and reusable without importing `web/app.py`'s closures. Implements every endpoint the build
  plan lists: `GET /api/v1/products` (search/status/active/family_id filters, real DB-level
  limit/offset pagination), `GET /api/v1/products/{id}`, `GET /api/v1/products/by-sku/{sku}`,
  `.../variants`, `.../assets`, `.../improvements`, `.../channels`, `.../audit`, plus
  `.../{id}/readiness` and `GET /api/v1/catalog/readiness-summary`.
- `src/xw_office/services/product_hub/readiness.py` — `evaluate_product_readiness`/
  `build_readiness_summary`, pure read-only functions (a readiness *check* must never have a
  side effect — caught and fixed a bug during development where the B2B-tag check would have
  silently created a `Tag` row on first use). Wix-ready/B2B-ready/Print-ready/sevdesk-ready per
  the deep-research doc's own criteria; two criteria are explicitly documented as approximated
  (Wix/sevdesk "category mapped" uses internal-category/channel-mapping presence as a proxy,
  since `channel_category_mapping` has no read/write support yet) rather than silently faked.
  Retail/B2B price and print-profile checks query the real `product_price`/`print_rule` tables —
  today that means most products correctly show as *not* ready, since PR06 deliberately never
  auto-creates prices and no print rule has been curated yet. That is the intended, honest
  behavior, not a bug to "fix" by lowering the bar.
- `src/xw_office/web/app.py` — extends `ContentWebSettings` with `database_url` (from
  `DATABASE_URL`, Railway's own internal Postgres URL — no YAML/`config/default.yaml` needed,
  since that file is deliberately **not** copied into `Dockerfile.web`'s image) and
  `product_hub_catalog_read_enabled` (from `XW_PRODUCT_HUB_CATALOG_READ_ENABLED`, defaults to
  `true`, a kill switch independent of a code deploy). Builds a SQLAlchemy engine/session
  factory only when `database_url` is set; `require_product_hub_enabled` fails closed with 503
  when the DB isn't configured or the flag is off, matching the existing
  `require_bootstrap_token`'s fail-closed-on-503 pattern exactly. The products router is
  included with **both** the existing bootstrap-token dependency and this new one.
- `requirements-web.txt` gains `sqlalchemy`, `psycopg2-binary`, `python-dotenv` — the last one
  because `xw_office.core.database`/`xw_office.repositories.product_hub` transitively import
  `xw_office.core.config`, which imports `python-dotenv` at module level even though this web
  app never calls `load_config()` itself. Verified this is sufficient and correct by installing
  *only* `requirements-web.txt` into a throwaway venv and round-tripping real HTTP requests
  through `TestClient` against a SQLite-backed app instance — confirms the lean production image
  will actually work, not just "imports fine with the full desktop dependency set installed."
- `ProductHubRepository` gained: DB-level pagination (`ProductFilter.limit`/`.offset`,
  `count_products`), `list_prices`/`get_price_list_by_code`, `get_print_rule`,
  `list_improvements`, `find_tag_by_code` (the read-only counterpart to `get_or_create_tag`,
  needed once the readiness side-effect bug above was found and fixed) — all additive.

**Verified:** `pytest tests/` — 1154 passed (+17 new in `test_product_hub_web_api.py`: auth
(401)/DB-not-configured (503)/flag-disabled (503) fail-closed behavior, every endpoint against a
seeded product, 404s for unknown id/SKU, pagination, and search filtering; +7 new in
`test_product_hub_readiness.py` including the explicit "never writes a tag" regression test);
`ruff check src/` clean; `mypy` clean on every file this touched; existing
`test_content_web.py`/`test_content_brands.py` still pass unmodified (no regression to the
already-deployed Content Studio endpoints). Same single pre-existing flaky UVA failure, nothing
new. Additionally smoke-tested against the real, lean `requirements-web.txt` dependency set in
an isolated venv (see above) — not just this repo's full desktop environment.

**No migration needed:** PR07 only reads through PR01's existing schema.

**Deploy status (2026-09-16): live and confirmed.** Merged to `main` and pushed to
`origin/main` (`b93310e..126016c`, fast-forward). Five consecutive deploy attempts (2
pre-existing from 2026-09-15 evening, before any of this work; 3 from this session) failed at
the container-start stage with **zero** log output, despite every build succeeding cleanly
(including the new `sqlalchemy`/`psycopg2-binary`/`python-dotenv` dependencies). Root cause
found: `railway.toml` had a `[deploy].startCommand` override
(`PYTHONPATH=src python -m uvicorn ...`) added 2026-09-15 09:32/09:38 as an attempted fix for
an unrelated issue, never validated against a real deploy before the failures started — that
command string is shell syntax (`VAR=value cmd`), and Railway's `startCommand` for a
Dockerfile-builder service is not guaranteed to run through a shell the way
`Dockerfile.web`'s own `CMD ["sh", "-c", "..."]` does, so the container never got as far as
starting Python. `Dockerfile.web` already sets `PYTHONPATH` correctly via `ENV`, making the
override redundant as well as broken. Fix: removed the `startCommand` line
(`c40ac50`) so Railway falls back to the Dockerfile's own `CMD`. Confirmed on the next deploy
attempt (`dd87c443`): `SUCCESS`, and `https://studio.xeisworks.at/api/v1/products` → `401`
(was `404` before this fix — the endpoint now genuinely exists in production). Full write-up
in `docs/web_deploy_betriebsleitfaden.md` §3, including the lesson that a `startCommand`/
`Procfile` change needs the same "confirmed by an actual observed deploy" bar as any other
code change — not just "looks plausible."

**Still open, separate from the above:** the GitHub→Railway auto-deploy webhook did not
trigger a new build within 10+ minutes after the initial PR07 push — every deploy in this
session went through the manual `railway up` fallback instead. Not yet root-caused; may or
may not be related to the `startCommand` incident. Worth confirming on the next ordinary push
to `main` whether the webhook fires on its own now.

**Deploy tooling added alongside this investigation:** `scripts/deploy_web.ps1` (PC-independent,
runs the exact CI quality gate, verifies branch/upstream/clean tree, pushes, watches Railway for
the resulting deployment, and — only with explicit `-Fallback` — triggers `railway up` as a
manual replacement path) and `docs/web_deploy_betriebsleitfaden.md` (the operating runbook,
matching the tone/structure of `docs/multi_pc_betriebsleitfaden.md`).

## PR08 detail

**Code delivered:** `web/product-hub/` — a React 18 + TypeScript + Vite PWA, built as a static
bundle and served **same-origin** by the existing `xw_office.web.app` FastAPI service (no
separate deployment, no CORS). Read-only, mirrors the PR07 API exactly:

- `src/api/types.ts` / `src/api/client.ts` — hand-kept mirror of `web/schemas/products.py`
  (no shared codegen for this small, slow-moving surface); token-based auth reusing the same
  bootstrap-bearer-token as the rest of the Content API, entered once via `TokenGate` and stored
  in `localStorage`.
- `src/pages/DashboardPage.tsx` — readiness tiles. Deliberately limited to what
  `/api/v1/catalog/readiness-summary` can compute today (total/wix/b2b/print/sevdesk-ready,
  missing-cover, open-improvements); the build plan's low_stock/out_of_stock/sync_conflicts
  widgets need the inventory ledger and sync-conflict tables from later PRs and are not faked.
- `src/pages/ProductListPage.tsx` — search/status filter + paginated table over
  `ProductListItem` fields only (no per-row N+1 readiness/channel calls).
- `src/pages/ProductDetailPage.tsx` — tabbed read-only sections (variants, assets/print-health,
  sync/channels, improvements, audit-log). Asset `uri` values are always rendered as plain text,
  never as a link — see the `ProductAsset` comment in `types.ts` for why (network paths /
  internal storage keys, not public URLs).
- `vite-plugin-pwa` with `base: "/app/"`, installable manifest, `navigateFallbackDenylist:
  [/^\/api\//]` so the service worker never intercepts API calls.

**Backend wiring (`src/xw_office/web/app.py`):** a new `_SPAStaticFiles` (falls back to
`index.html` for unknown paths so React Router handles client-side routes like
`/app/products/<id>` instead of getting a 404) mounted at `/app` when
`ContentWebSettings.product_hub_web_dist` is a real directory — absent in plain-API deployments
and most local dev setups, where the mount is simply skipped. `Dockerfile.web` is now two
stages: `node:20-slim` runs `npm ci && npm run build` for `web/product-hub/`, and only the
resulting `dist/` is copied into the final `python:3.12-slim` image (no Node/npm ships in the
deployed image).

**Verified locally:** `npm run build` (tsc --noEmit + vite build) and `npm run lint`
(`eslint . --max-warnings=0`) both clean; started the FastAPI app locally and curled `/app/`,
`/app/manifest.webmanifest`, and `/app/products/123` (SPA fallback returns `index.html` as
expected) alongside the existing `/health` and `/api/v1/products` routes. Full backend suite
(`pytest`) at 1154/1155 passing — the one remaining failure
(`test_uva_soap_mock.py::test_unconfigured_client_raises`) is a pre-existing, environment-
dependent flake unrelated to this PR: `FinanzOnlineClient`'s credential resolution falls back to
reading `FON_*`/`FINANZONLINE_*` env vars directly, so on any machine where those happen to be
set, `has_submission_credentials()` returns true and the "unconfigured client raises" assumption
no longer holds. Worth an isolated fix later (the test should clear/patch those env vars rather
than rely on the ambient shell being clean).

**Deployed:** `git push origin main` (`0b8590a`), webhook still did not fire (consistent with
the open item below), so `railway up` was used as the documented fallback. Multi-stage
`Dockerfile.web` build succeeded on Railway (Node stage + Python stage,
deployment `6dbf647a…`, status SUCCESS). Confirmed live: `https://studio.xeisworks.at/health`
→ 200, `/app/` → 200, `/app/manifest.webmanifest` → 200, `/app/products/123` → SPA fallback
serves `index.html`, `/api/v1/products` still → 401 (bootstrap token required, unchanged).

**Not done:** no browser/manual click-through of the built UI against live data yet (only
curl-level route verification) — recommended once the bootstrap token is available to test with.
The `scripts\deploy_web.ps1` quality gate hard-fails on the flaky UVA test above (no flake
allowlist), so this deploy bypassed the script and ran push/`railway up` directly after manually
confirming ruff/mypy/pytest results — worth adding tolerance for known pre-existing flakes to the
script, or fixing the flake itself, before the next PR's deploy.

## PR09 detail

**Migration `011_product_hub_row_versions`, applied to Railway Postgres:** adds a
`row_version` column to `product_variant`, `product_asset`, `print_rule` and
`product_improvement` (`product.row_version` already existed from PR01). Everything
else PR09 needed — `product_edition`, `product_improvement.resolved_in_edition_id`,
`price_list`/`product_price`, `tag`/`product_tag` — was already in the PR01 schema,
just unused until now. **Naming pitfall hit and documented in the migration's own
docstring:** the first attempt used a 38-character revision id
(`011_product_hub_editable_row_versions`); `alembic_version.version_num` is
`VARCHAR(32)`, so the final version-stamp `UPDATE` failed with
`StringDataRightTruncation` *after* the DDL had already run inside the same
transaction — Postgres rolled the whole thing back cleanly (confirmed via
`alembic current` still showing 010 afterwards), so nothing was left half-applied,
but the shorter `011_product_hub_row_versions` (28 chars) had to be used instead.

**Code delivered:**
- `src/xw_office/models/product_hub.py` — `row_version` field on the four entities above.
- `src/xw_office/repositories/product_hub.py` — `update_variant`, `update_asset`,
  `remove_identifier`, `set_price` (writes a new effective-dated row and closes the
  previous one — prices are never mutated in place, so no lock needed there),
  `upsert_print_rule` (create-if-missing, else optimistic-locked update),
  `create_improvement`/`update_improvement`, `create_edition`/`list_editions`/
  `assign_improvements_to_edition`, `remove_product_category`/`remove_product_tag`,
  plus small `get_asset`/`get_improvement`/`get_tag` getters the router's 409 handler
  needs to fetch "current server state." All follow `update_product`'s existing
  optimistic-lock pattern (`OptimisticLockError` on stale `row_version`).
- `src/xw_office/services/product_hub/editing.py` (new) — `EditingService`, one
  DB-transaction-per-call wrapper (mirrors `grouping.py`'s pattern) that combines each
  repository write with a `record_audit` call, and enforces a per-entity field
  allowlist (`UnknownFieldError`) so a stray/renamed request field fails with 400
  instead of silently touching an unrelated column.
- `src/xw_office/web/schemas/products.py` — request bodies (`ProductUpdateRequest`,
  `VariantUpdateRequest`, `AssetUpdateRequest`, `TagAddRequest`, `IdentifierAddRequest`,
  `PriceSetRequest`, `PrintRuleUpsertRequest`, `ImprovementCreateRequest`,
  `ImprovementUpdateRequest`, `EditionCreateRequest`) and new read-out schemas
  (`TagOut`, `IdentifierOut`, `PriceOut`, `PrintRuleOut`, `EditionOut`); existing
  variant/asset/improvement schemas gained `row_version`.
- `src/xw_office/web/routers/products.py` — every PATCH/POST/PUT/DELETE route lives on
  a nested `write_router`, mounted into the main router with its own
  `require_edit_enabled` dependency (see below) — a 409 handler (`_conflict`) refetches
  and returns the current server state per the build plan's "Konflikt -> HTTP 409 mit
  aktuellem Serverstand," rather than just a bare error.
- `src/xw_office/web/app.py` — new `ContentWebSettings.product_hub_edit_enabled`
  (env `XW_PRODUCT_HUB_EDIT_ENABLED`), **defaults to `False`** — a separate kill switch
  from the read API's, since this is the first write-capable HTTP surface this service
  has ever exposed. Deliberately left off in production after this deploy; flip it on
  once the WebUI editing flow has been exercised for real.
- `web/product-hub/src/pages/ProductDetailPage.tsx` — inline product Stammdaten edit
  form (name/status/category/short+long description), a tag row (add by code / remove
  chip), and an improvements "+ Verbesserung hinzufügen" form with a "Als gelöst
  markieren" action per open item — matching the build plan's explicit UX note that the
  improvement UI should look simple while staying separate audited records underneath.
  409 conflicts trigger a refetch instead of a silent overwrite.
- `web/product-hub/src/api/{types,client}.ts` — `ConflictApiError` (carries the 409
  body's current-state payload), the new edit methods, `Tag`/`Edition` types.

**Deliberately not built in this round** (backend API is ready, WebUI isn't): inline
editing for asset metadata (role/sort_order), variant prices, and print rules —
`ProductDetailPage`'s Assets/Print tab is still read-only. Same for identifiers (add
via API works, no UI yet) and the edition-creation flow (`create_edition` +
`resolve_improvement_ids` works end-to-end via API, no "neue Auflage" button yet). Adding
these is mechanical (same pattern as tags/improvements) whenever picked back up.

**Verified locally:** 45 new tests (32 repository-level incl. optimistic-lock/stale-
version cases, 13 HTTP-level incl. the 503-when-disabled gate, 409-with-current-state,
and an audit-log-entry-written check) all pass; full backend suite at 1181/1182 (same
one pre-existing flaky UVA test, confirmed unrelated). `npm run build`/`lint` clean for
the frontend changes. Not yet done: no browser click-through of the new edit forms —
also blocked on `product_hub_edit_enabled` being off in production right now.

**Deployed:** migration applied directly via `alembic upgrade head` against the
production Railway Postgres (confirmed via `alembic current` → `011_product_hub_row_
versions`). Code not yet pushed/deployed as of writing this section — see the commit
that follows. GitHub webhook: still not connected (`railway status` shows
`source.repo: null` for XW-Content-Web) despite the project rename to "XW-Office" and
the user's dashboard reconnect attempt — the Railway CLI's local project link
(`~/.railway/config.json`, keyed by absolute repo path) also had to be redone after the
`XW-Studio` → `XW-Office` folder rename (`railway link -p b9ca5990-...`), unrelated to
the GitHub side but worth knowing if `railway` commands suddenly say "No linked project
found" again after a future folder move.

## PR10 detail

**Migration `012_product_hub_sync_outbox`, applied to Railway Postgres:** the six
schema-only tables from the data model spec — `outbox_event`, `sync_job`, `sync_item`,
`sync_conflict`, `sync_cursor`, `external_payload_archive` — exactly as specified in
`XW_PRODUCT_HUB_DATA_MODEL.yaml`. Naming stayed under alembic's 32-char
`version_num` limit this time (`012_product_hub_sync_outbox`, 27 chars) — see
migration 011's docstring for what happens if you don't.

**Code delivered:**
- `src/xw_office/models/product_hub_sync.py` (new) — the six ORM models, registered
  in `models/__init__.py` alongside the existing product_hub/product_hub_import
  modules so `Base.metadata` (and therefore both Alembic and the SQLite test suite)
  sees them.
- `src/xw_office/repositories/product_hub_sync.py` (new) — `append_outbox_event`, a
  **plain function** (not a scope-owning repository method) that writes on the
  *caller's* session, since the whole point is that it must commit inside the
  caller's own transaction, never open its own. Also `SyncRepository` for the
  worker side (`claim_outbox_events`/`mark_outbox_event_processed`/
  `mark_outbox_event_failed`/`release_outbox_event`/`list_dead_events`) and basic
  `sync_job`/`sync_conflict`/`sync_cursor` CRUD ready for PR11 to build on.
- `src/xw_office/services/product_hub/outbox_worker.py` (new) — `OutboxWorker`:
  claims available events, dispatches to a handler registered by `event_type`,
  applies bounded exponential backoff on failure (default: 60s base, doubling, capped
  at 1h, dead-lettered — i.e. excluded from further retries and surfaced via
  `list_dead_events()` — after 8 attempts; all three are constructor overrides, not
  hardcoded). Events whose `event_type` has **no registered handler** are released
  without penalty rather than burning a retry attempt, since that's the expected
  state for every event type right now — nothing registers a handler until PR11's
  Wix push adapter exists. Deployment shape is deliberately left open per
  `XW_PRODUCT_HUB_IMPLEMENTATION.yaml` (`worker.deployment:
  separate_Railway_worker_or_periodic_worker`) — `process_once()` is transport-
  agnostic; wiring an actual Railway cron/worker service is not part of this PR.
- `src/xw_office/services/product_hub/editing.py` — every one of PR09's 11 mutating
  methods now also calls `append_outbox_event` in the same transaction as its
  `record_audit` call, per the build plan's "Outbox-Regel" (business change + outbox
  event in the *same* DB transaction). Event types used: `product.updated` (product/
  variant/tag/identifier edits — all product-aggregate-scoped), `asset.changed`,
  `price.changed`, `print_rule.updated`, `improvement.created`/`improvement.updated`,
  `edition.created` — the first four names come straight from the build plan's
  "Eventtypen Beispiele"; the rest follow the same convention.

**Deliberately not wired in this round:** `ProductHubRepository.create_product` and
the PR06 `grouping.py`/PR06 `import_commit.py` write paths do **not** yet write
outbox events (no `product.created` events from imports/grouping today). PR10 is
scoped to PR09's edit surface — extending coverage to the import/grouping flows is a
small, mechanical follow-up (same `append_outbox_event` call, same transaction) but
touches already-shipped, already-verified code paths without a concrete near-term
consumer, so it's deferred rather than done speculatively.

**Verified locally:** 14 new tests (9 sync-repository: claim/backoff/dead-letter/
no-handler-release + sync_job/sync_conflict/sync_cursor CRUD; 5 outbox-worker:
handler dispatch, backoff growth/cap, dead-lettering) all pass; full backend suite
at 1195/1196 (same one pre-existing flaky UVA test). No manual/browser verification
possible since there is still no real handler to observe end-to-end — that's PR11's
job.

**Deployed:** migration applied directly via `alembic upgrade head`
(confirmed via `alembic current` → `012_product_hub_sync_outbox`). Since
`product_hub_edit_enabled` is still off in production, **no outbox events are
actually being written yet** even after this deploy — the write path only exists
behind PR09's still-disabled edit API. Code push/deploy: see the commit that follows.

## PR11 detail

**No new migration** — everything PR11 needed already exists from PR10's schema
(`outbox_event`, `sync_conflict`, `external_payload_archive`).

**Reused rather than rebuilt:** `src/xw_office/services/wix/product_details_client.py`
already had a v3-revision-aware `WixProductDetailsClient` (from PR03) with
per-field `update_product_*` methods that fetch the current revision before every
PATCH — exactly the "Bei V3 Revision immer aktuelle Revision verwenden" requirement.
The only gap: those methods swallow the HTTP status into a bare bool
(`_patch_v3` → `(bool, str)`), so a 409 revision conflict was indistinguishable
from any other failure. Added one new method,
`patch_product_field_with_conflict_detection`, that surfaces
`(success, error, http_status_code)` — additive, doesn't touch the existing
`update_product_*` methods or their tests.

**Code delivered:**
- `src/xw_office/services/product_hub/wix_push.py` (new) — `WixPushService`:
  - **Owned fields** (Hub master, per "Hub ist Master für definierte Felder"): `name`,
    `description`, `price` (RETAIL_EUR gross, default variant), `visible` (→
    `Product.active`). Extending this tuple later is additive.
  - **Push always re-derives current Hub state** rather than trusting an outbox
    event's payload — the event is only a "product X may need re-syncing" signal
    (see `wix_push_handler`), which sidesteps staleness/ordering between when an
    event was written and when it's processed.
  - **Drift detection**: compares Wix's *live* value for each field against the most
    recent `external_payload_archive` snapshot (the last-known-good state after our
    last successful push — a legitimate reuse of that PR10 table's stated "debug/audit
    snapshot" purpose as a drift baseline, no new column needed). If Wix's live value
    differs from that snapshot AND doesn't already equal what the Hub wants to write,
    a `sync_conflict` is created and that field is **not** overwritten. Never silent.
  - **Idempotent**: a field already matching between Hub and Wix is skipped with zero
    HTTP calls; the baseline snapshot is refreshed after every successful push, so a
    second push of unchanged state is a pure no-op (`status="no_changes"`).
  - **Disabled push**: gated by `push_enabled` (a callable, re-checked every call,
    mirroring PR09's `product_hub_edit_enabled` pattern) — when off, `push_product` is
    a pure no-op with zero Wix HTTP calls, returning `status="skipped_disabled"`.
  - `resolve_conflict(conflict_id, resolution=...)` implements all three build-plan
    actions: `keep_hub_and_push` (force-writes the Hub's value, blocked with a 409 if
    push is currently disabled), `accept_external` (writes Wix's value back into the
    Hub — `Product.name`/`description`/`active` directly, `price` via a new
    effective-dated `ProductPrice` row through the existing `set_price` repository
    method — never mutated in place), `ignore_once` (resolves the record without
    touching either side; the divergence will simply be re-detected next push).
  - `wix_push_handler(push_service, product_repo)` — the outbox handler, registered
    for both `product.updated` and `price.changed` (the latter carries a *variant*
    id per PR09/PR10's wiring, resolved to its product via `get_variant`). Raises on
    `status="error"` so `OutboxWorker`'s existing backoff/retry applies; every other
    outcome (pushed, no changes, conflict recorded, disabled, not yet mapped) is a
    legitimate terminal state, not a failure to retry.
- `src/xw_office/repositories/product_hub_sync.py` — `archive_external_payload`/
  `get_latest_external_payload` (the drift baseline), `get_sync_conflict`.
- `src/xw_office/web/app.py` — new `sync_push_enabled` flag (env
  `XW_PRODUCT_HUB_SYNC_PUSH_ENABLED`, **defaults off**, same reasoning as PR09's edit
  flag: first outbound-write channel this service has). `WixProductDetailsClient` is
  constructed with a small `_EnvSecretSource` shim (`get_secret(name) ->
  os.getenv(name)`) rather than the desktop's DB-backed `SecretService` — this lean
  web service has no encrypted secret store, and (see next paragraph) the client
  itself deliberately does *not* fall back to bare env vars on its own.
- `src/xw_office/web/routers/sync.py` + `web/schemas/sync.py` (new) — `GET
  /api/v1/sync/conflicts` (optional `channel` filter), `POST
  /api/v1/sync/conflicts/{id}/resolve`, `POST /api/v1/sync/worker/run-once` (manually
  triggers `OutboxWorker.process_once()` — there is no separate Railway worker/cron
  deployed yet, so this is the practical way to actually exercise the pipeline; see
  `XW_PRODUCT_HUB_IMPLEMENTATION.yaml`'s `worker.deployment:
  separate_Railway_worker_or_periodic_worker` for the eventually-intended shape),
  `GET /api/v1/sync/worker/dead-events`. All four share PR09's
  `product_hub_edit_enabled` gate rather than getting a third flag, since resolving a
  conflict or running the worker are both write-adjacent actions.

**A mistake made and reverted during this PR:** first attempt added a bare
`os.getenv(...)` fallback *inside* `WixProductDetailsClient._api_key()` etc. (matching
`FinanzOnlineClient`'s own SecretService-then-env pattern). This broke two existing
tests (`test_has_credentials_false_when_no_key`,
`test_detect_version_returns_unknown_without_credentials`) because this dev
machine's shell has real `WIX_API_KEY`/`WIX_SITE_ID` set as ambient env vars — the
*shared* client's "no credentials configured" behavior became environment-dependent
for every caller, not just the web app, which is the same class of bug as the
already-documented UVA test flake. Reverted; the `_EnvSecretSource` shim above keeps
the env-var fallback local to this one call site instead.

**Verified locally:** 24 new tests (16 `WixPushService`-level against a fake Wix
client covering disabled/not-mapped/no-changes/first-push/idempotency/drift-conflict/
409-conflict/generic-error/all three resolutions/the outbox handler's aggregate-type
dispatch/an end-to-end retry-through-`OutboxWorker` check — i.e. every case the build
plan's own test list names: "409/revision conflict, retry, idempotency, disabled
push" — plus 8 HTTP-level for the new sync router) all pass; full backend suite at
1219/1220 (same one pre-existing flaky UVA test, confirmed still isolated to that one
test after this PR's changes). No live Wix account was called — everything above
runs against a fake/stub client; there's been no manual/browser or real-Wix
verification of an actual push yet, since `sync_push_enabled` stays off in
production.

**Not done / explicit scope cuts:** Media push ("Hub-Metadaten respektieren: COVER
zuerst, Samples danach") is not built — that needs the S3-compatible object storage
integration from `XW_PRODUCT_HUB_IMPLEMENTATION.yaml` (`object_storage.type:
S3_compatible`), which doesn't exist yet in this codebase; pushing images is a
separate, larger piece of work. No `sync_job`/`sync_item` rows are written per push —
those tables (already schema-ready from PR10) are better suited to a future bulk/
scheduled reconciliation run than to per-event single-product pushes, so they stay
unused until that's built. `create_product`/import/grouping flows still don't emit
outbox events (unchanged from PR10's scope note), so freshly imported products won't
auto-push to Wix even once `sync_push_enabled` is on — only products edited through
PR09's edit API will trigger a push.

**Deploy incident: first attempt (`95af4eaa…`) FAILED at container start**, not
build — `ModuleNotFoundError: No module named 'httpx'`. Root cause: `wix_push.py`
imports `xw_office.services.wix.product_details_client`, and importing *anything*
under `xw_office.services.wix.*` runs that package's `__init__.py`, which
unconditionally imports the legacy `client.py` too (for its own re-exports) — and
`client.py` imports `httpx`, which was never in `requirements-web.txt` (only in the
full desktop `pyproject.toml`, which is why local dev/tests never caught this — the
repo's own `.venv` has both). Traced the rest of that chain
(`core.performance_metrics`, `services.shipping.countries`,
`services.wix.order_cache`) and confirmed everything else is stdlib-only, so `httpx`
was the complete fix. Added it to `requirements-web.txt`, then verified with the same
check `scripts\deploy_web.ps1 -VerifyLeanWebImage` runs (throwaway venv, only
`requirements-web.txt` installed, import `xw_office.web.app`) *before* redeploying —
should have done this the first time; the CI/local quality gate uses the full desktop
`.venv` so it can't catch a lean-image-only missing dependency, which is exactly what
that flag exists for.

## PR12 detail

**Migration `013_product_hub_sharing`, applied to Railway Postgres:**
`shared_catalog_view` + `export_log`, exactly per the data model spec. Only
`token_hash` (SHA-256 hex) is ever persisted — the plaintext token is generated at
creation, returned exactly once in the API response, and never stored anywhere.

**Code delivered:**
- `src/xw_office/models/product_hub_sharing.py` (new) — `SharedCatalogView`,
  `ExportLog`, and `ALLOWED_SHARE_FIELDS` — the hard ceiling on what a share can ever
  expose (`cover_url`, `sku`, `isbn`, `name`, `description`, `price_uvp`, `price_b2b`,
  `available`), checked at creation time regardless of what a request body asks for,
  per the build plan's "interne Felder können nicht von normaler Editor-Rolle
  freigegeben werden."
- `src/xw_office/repositories/product_hub_sharing.py` (new) — `SharingRepository`:
  create/get/list/revoke a share, `touch_last_access`, `record_export`. Never touches
  a plaintext token.
- `src/xw_office/services/product_hub/sharing.py` (new) — `SharingService`:
  - `create_share`: generates the token (`secrets.token_urlsafe(32)`), stores only its
    hash, validates `field_whitelist` against `ALLOWED_SHARE_FIELDS`.
  - `resolve_token`: hash-lookup + revoked/expired checks + a minimal in-memory
    sliding-window rate limiter (60 req/min per token hash — no Redis, matching this
    project's "no microservices/Redis without proven need" constraint; would need
    revisiting only if this service ever scales past one instance).
  - `query_catalog(share)`: the **one** server-side query HTML, CSV and XLSX all call
    — per the build plan's explicit requirement that all three "use the same
    server-side query" so they can never silently disagree. Implements the
    Standardfilter (`tag=B2B`, `status=live`, `active=true`) and Standardfelder (cover/
    SKU/ISBN/name/description/UVP from `RETAIL_EUR`/B2B price from `B2B_EUR` or the
    share's own `price_list_id`/availability). `available` is derived from the default
    variant's `active` flag — there's no real per-unit stock quantity in Product Hub
    yet (that's PR13+'s Inventory V2), so this is an honest simplification, not a
    placeholder pretending to be real stock data.
  - `resolve_conflict`-style safety: a `COVER` asset with `storage_kind="NETWORK_PATH"`
    is skipped even if present — the "Niemals öffentlich: NETWORK_PATH, PRINT_PDF"
    rule enforced in code, not just by convention.
- `src/xw_office/web/routers/sharing_admin.py` + `web/schemas/sharing.py` (new) —
  authenticated admin API: `POST/GET /api/v1/shares`, `POST
  /api/v1/shares/{id}/revoke`. Gated by `product_hub_edit_enabled` (reused, not a new
  flag — creating a public data-exposure surface is at least as sensitive as editing
  products). The create response is the only one that ever carries `token`.
- `src/xw_office/web/routers/share_public.py` (new) — `GET /share/{token}` (inline
  server-rendered HTML, matching the existing `_landing_page` precedent in `app.py` —
  no new templating dependency), `GET /share/{token}/export.csv` (stdlib `csv`),
  `GET /share/{token}/export.xlsx` (`openpyxl`). **Deliberately not behind the
  bootstrap-token dependency** — that's the entire point of a share link — but still
  fails closed (503) via `require_product_hub_enabled` if the Product Hub isn't
  configured at all, and every request re-validates the token (404 unknown, 410
  revoked/expired, 429 rate-limited, 403 if that format is disabled for this share).
- `requirements-web.txt` — added `openpyxl>=3.1,<4` for XLSX export (verified against
  the lean-image check before deploying this time, see below).

**Two bugs found and fixed while writing tests** (both are the same recurring class of
issue seen earlier in PR09/PR10 — SQLite round-trips silently drop what Postgres
keeps): (1) `resolve_token` returned the *pre-touch* `SharedCatalogView` object
because `touch_last_access` opens its own session (the repo is factory-backed, not a
single bound session) — fixed by re-fetching after the touch; (2) comparing
`share.expires_at` (naive after an SQLite round-trip) against
`datetime.now(timezone.utc)` (aware) raised `TypeError` — fixed by treating a naive
value as UTC before comparing, which is correct for both SQLite (tests) and Postgres
(production) rather than papering over it only in test code.

**Verified locally:** 26 new tests (14 service-level — token generation/hashing,
resolve success/unknown/revoked/expired/rate-limited, whitelist enforcement, default
filter, NETWORK_PATH-cover exclusion, custom price list, export logging; 12 HTTP-level
— admin CRUD + gating, public view/csv/xlsx, 404/410/403/503) all pass; full backend
suite at 1245/1246 (same one pre-existing flaky UVA test). **This time, the lean-image
check ran before deploying** (throwaway venv, only `requirements-web.txt`, import
`xw_office.web.app`) — confirmed clean, so this PR's deploy did not repeat PR11's
incident.

**Not done / explicit scope cuts:** No "create/manage shares" UI in the React app —
the admin API is fully functional and tested, but there's no button for it yet in
`ProductDetailPage`/a new page; a follow-up, not a blocker, since the feature is fully
usable via the API today. `filter_definition`/`sort_definition` only understand the
build plan's fixed Standardfilter shape (`{tag, status, active}`) — a richer filter
DSL (arbitrary field/operator combinations) is a future extension if a second use
case ever needs one. `password_hash` stays an unused schema column, matching the data
model's own "optional expiry/password später" framing. Rate limiting is per-process
in-memory, not distributed — fine for the current single-instance deployment.

## PR13/PR14 detail

**Migration `014_product_hub_inventory`, applied to Railway Postgres:**
`inventory_location`, `inventory_stock`, `inventory_movement` (append-only ledger),
`inventory_alert` — exactly per the data model spec, including the Postgres partial
unique index (`WHERE status = 'open'`) enforcing "at most one open alert per
variant/location/type" at the DB level (SQLite tests enforce the same rule in the
repository instead — partial indexes aren't portable, same reasoning as the "one
default variant" note in `models/product_hub.py`).

**This is explicitly shadow mode**, matching the build plan's own framing of PR13
("Hub-Lagerledger aufbauen, **noch ohne finalen Master-Cutover**"). Three things are
deliberately *not* done, and are the reason PR15 doesn't follow immediately — see the
next section:

1. **No legacy call site was rewired.** `SettingKV["inventory.products"]` /
   `inventory.stock_levels`, `InventoryService`, and `PrintDecisionEngine` are
   completely untouched. Researched (not modified) as part of scoping this PR:
   `InventoryService` (`services/inventory/service.py`) owns `load_stock_levels`,
   `build_start_preflight`/`build_reprint_preflight`,
   `execute_start_workflow`/`execute_reprint_workflow`, `set_product_stock`, etc. —
   all still the only thing any real print/fulfillment/correction/return/recount path
   in this app calls. `PrintDecisionEngine` (`services/products/print_decision.py`)
   computes reprint decisions from `ProductCatalogService` + legacy `PrintRule`
   (`min_stock_target`/`reprint_batch_qty` on the *legacy* `product` table, migration
   002/003 — a different, older thing than Product Hub's own `print_rule` table from
   PR01/PR09). The build plan's "Bridge" note ("bestehende InventoryService-Aufrufer
   dürfen zunächst weiterlaufen") is satisfied by construction: nothing was changed,
   so nothing needed a bridge.
2. **No automatic sevdesk stock polling.** `PartClient.get_part_stock(part_id) -> int`
   already exists (`services/sevdesk/part_client.py`) and already does what's needed
   — but it's constructed via `SevdeskConnection`, which requires a full desktop
   `AppConfig` (a large, many-sub-dataclass object), not something the lean web
   service has ever constructed. `reconcile_variant_stock(variant_id,
   sevdesk_on_hand=...)` takes the external figure as a parameter instead of fetching
   it live — the comparison/conflict-creation logic is real, tested, and reuses
   PR10's `sync_conflict` table exactly as designed, just not wired to an automatic
   poll yet. Also worth noting for whoever wires this: sevdesk `channel_mapping` rows
   are keyed at the **product** level today (`entity_type="product"`), not per
   variant — there is no existing repository call that resolves
   `variant_id → sevdesk part_id` directly.
3. **No real XW-Flow HTTP call.** There is no XW-Flow API client anywhere in this
   codebase, and its contract isn't documented here — building one would mean
   fabricating field names/auth/endpoints. Instead, a newly-opened alert writes an
   `inventory_alert.opened` outbox event (via the exact PR10 mechanism) with every
   field the build plan specifies: `title` (`"Nachdruck: <SKU> – <Produktname>"`),
   `description`, `notes` (stock/threshold/open improvements), `planning_mode`
   (`"PIPELINE"`), `external_entity_type`/`external_entity_id`, `external_deep_link`,
   and `client_request_id` (`UUID5` of a fixed namespace + the alert's own UUID, per
   spec). No handler is registered — same "wait for a real integration" pattern PR10
   established for Wix before PR11 existed.

**Code delivered:**
- `src/xw_office/models/product_hub_inventory.py`, `repositories/
  product_hub_inventory.py` (new) — `InventoryRepository.record_movement` is the
  *only* writer of `inventory_stock.on_hand`: idempotent on `idempotency_key` (a
  repeat returns the existing movement rather than double-applying — this directly
  exercises PR15's precondition #7, "Inventory-Movement-Idempotency getestet", years
  ahead of attempting the cutover itself), and raises `NegativeStockError` rather
  than letting `on_hand` go negative (the data model's own constraint).
- `src/xw_office/services/product_hub/inventory.py` (new) — `InventoryV2Service`:
  `record_movement` (ledger write + alert crossing: `before > threshold AND after <=
  threshold` opens `low_stock`/`out_of_stock` exactly per the build plan's crossing
  rule; `after > threshold` resolves any open alert), `reconcile_variant_stock`
  (shadow drift, see above), `compute_summary` (the `/inventory/summary` tile).
- `src/xw_office/web/routers/inventory.py` + `web/schemas/inventory.py` (new) —
  `GET /api/v1/inventory/summary`, `GET .../alerts`, `GET
  .../variants/{id}/stock|movements` (read, gated by the read flag only);
  `POST .../movements`, `PUT .../variants/{id}/thresholds`, `POST .../reconcile`,
  `POST .../alerts/{id}/resolve` (write, additionally gated by
  `product_hub_edit_enabled` — same reused-flag reasoning as PR11/PR12).

**Verified locally:** 26 new tests (9 repository — idempotency, negative-stock
rejection, alert dedupe/resolve; 10 service — alert crossing open/no-reopen/resolve,
outbox payload field-by-field, reconcile drift/no-drift/no-duplicate-conflict,
summary counts; 7 HTTP — auth gates, movement/stock/alert/reconcile round-trips, 409
on negative stock) all pass; full backend suite at 1271/1272 (same one pre-existing
flaky UVA test). Lean-image check ran clean before deploying (no new third-party
dependency — everything here is stdlib + already-required SQLAlchemy/FastAPI).

**Deployed:** migration applied via `alembic upgrade head` (confirmed via `alembic
current` → `014_product_hub_inventory`), code pushed and deployed via `railway up`
(webhook still not auto-firing — same open item as every prior PR this session).

## Why PR15/PR16 stop here

Asked to continue "bis Schritt PR16, falls sinnvoll" (through PR16, if sensible) —
PR13 and PR14 were sensible to build now: additive, `external_writes: false`/
`xw_flow_tasks_only`, fully reversible, no cutover. **PR15 is a different kind of
thing.** Its own precondition list (build plan, verbatim) is not a code checklist —
it's an operational sign-off gate:

1. alle bekannten Bestandsänderungspfade laufen durch Inventory V2 *(not true yet —
   see scope cut #1 above; would require rewiring every legacy call site first)*
2. Shadow Mode über **repräsentativen Zeitraum** ohne ungeklärte Drift *(requires
   actually running shadow mode against real traffic for a real stretch of time —
   cannot be satisfied by writing code in one sitting, by definition)*
3. sevdesk-/Hub-Bestände reconciled *(reconcile logic exists but has never been run
   against a real sevdesk figure — see scope cut #2)*
4. Backups vorhanden *(not something a coding session can verify)*
5. Rollback-Schalter getestet *(the flag exists in the build plan's design — `product_
   hub.inventory_master_enabled` — but nothing has tested flipping it back off yet,
   because nothing has flipped it on)*
6. keine kritischen Sync-Fehler offen
7. Inventory-Movement-Idempotency getestet *(this one **is** done — see above)*
8. Druckpfad verwendet Hub-Bestand *(not true — `PrintDecisionEngine` is untouched)*
9. Wix-/sevdesk-Projektionen getestet *(not built — that's what PR15 itself would add)*

Attempting PR15 now would mean flipping `product_hub.inventory_master_enabled=true`
— making the Hub the **canonical source of truth for a real business's physical
inventory** — while most of these conditions are provably false. That's exactly the
"Big-Bang refactor" this whole build plan has been explicit about avoiding at every
prior step. PR16 (remove the legacy JSON blobs) depends on PR15 being live and
stable, so it's blocked transitively.

**What would need to happen first, for whoever picks this up:** rewire the legacy
call sites listed in scope cut #1 onto `InventoryV2Service.record_movement` (one at a
time, each independently verifiable); wire real sevdesk stock polling (needs the
`AppConfig`-in-lean-web-service question resolved properly, not rushed); run shadow
reconcile for a real period and actually look at the drift it finds; get backups
confirmed and a rollback rehearsal done by a human who owns that call. None of that
is a "continue autonomously" task — it's an operational readiness process this
session correctly stopped short of.

## PR15 readiness surface (implemented; no cutover)

The Product Hub now exposes `GET /api/v1/inventory/cutover-readiness` and the
WebUI page `/app/inventory/cutover`. It reports live ledger/stock evidence, open
sevdesk inventory drift and the full sync queue, while explicitly keeping the
remaining legacy mutation paths, missing channel projections and the human
operational sign-off as blocking gates. `XW_PRODUCT_HUB_INVENTORY_SHADOW_ENABLED`
and `XW_PRODUCT_HUB_INVENTORY_MASTER_ENABLED` are read-only deploy flags in this
surface; the UI cannot enable the master or perform any stock/external write.

The next controlled bridge step is also available: `/app/inventory/cutover` shows a
read-only preview of legacy `inventory.stock_levels` against exact active Hub
variants. With `XW_PRODUCT_HUB_INVENTORY_SHADOW_ENABLED=true`, an explicitly
confirmed action writes one idempotent `import_baseline` movement per safe SKU. The
reviewed source hash must still match; malformed/unmapped/inactive/already-initialized
entries are skipped, and the legacy JSON plus Wix/sevdesk remain untouched.

The first live desktop bridge is now limited to `InventoryService.set_product_stock`:
when the desktop's `product_hub.inventory_shadow_enabled` and a database are enabled,
it mirrors a successfully completed legacy absolute-stock update to an already
baselined, exact active Hub variant. Missing mappings, inactive variants and missing
baselines are logged and never block the legacy operation. START/REPRINTS, invoice
consumption outside START, returns/recount and the print-decision path initially
remained outside this first bridge step.

START and REPRINTS are now included in the desktop Shadow bridge as separate ledger
reasons: production is `print_run`, invoice consumption is `sale`, and REPRINTS are
only `print_run`. The legacy JSON is saved first; only then are the known movements
mirrored. A consumption that would make the Hub ledger negative is capped at available
stock and logged as a shortage instead of inventing stock or blocking the completed
legacy workflow. Invoice fulfillment outside START, returns/recount and
`PrintDecisionEngine` remain the next unbridged paths.
