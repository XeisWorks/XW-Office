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
| PR03–PR16 | — | Not started | |

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
  `009_product_hub_core`, applied to Railway (`alembic current` → `010_product_hub_import_staging
  (head)`).
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
