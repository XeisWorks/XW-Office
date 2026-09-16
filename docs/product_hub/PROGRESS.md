# XW Product Hub — Build Progress

Tracks which PR packages from `XW_PRODUCT_HUB_CODEX_5_6_LUNA_BUILD_PLAN.md` are done, so the
next work session (human, Codex, or Claude) does not have to re-derive state from scratch.
Update this file at the end of every PR.

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
| PR07 | Product Hub Read API | **Done** | See below. |
| PR08–PR16 | — | Not started | |

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
