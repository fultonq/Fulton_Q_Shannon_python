# File Dictionary

A reference for every file in this project: what it is, what it's for, and
what it depends on. (The data itself has no data dictionary from the
source system - this is the companion dictionary for the *codebase* that
enriches it.)

## Entry point

| File | Lines | Purpose |
|---|---|---|
| `run.py` | 16 | The only file you run directly: `python run.py`. Imports `pso_enrichment.pipeline.run()` and calls it. Contains no logic of its own - exists purely so there's one obvious, documented command to execute. |

## Configuration

| File | Lines | Purpose |
|---|---|---|
| `config.py` | 156 | Every user-editable setting in the project, as plain variables with inline comments: output paths (`OUTPUT_DIR`, `OUTPUT_CSV_PATH`), the data filters (`APPLICATION_OR_ISSUE_DATE_FLOOR`, `PERMIT_TYPES`, `UTILITY_PATTERNS`), the two data source URLs (`PERMIT_LAYER_URL`, `LRS_GET_POINT_ON_SUBBLOCK_URL`) and the fields pulled from each, the functional-class rank order (`FUNCTIONAL_CLASS_RANK`), search-radius/escalation and concurrency settings, and the optional QGIS fallback switches (`USE_QGIS_FALLBACK`, `QGIS_INSTALL_PREFIX`, etc.). No functions - only constants. Everything else in the project reads its settings from here and nowhere else. |
| `requirements.txt` | 12 | Documents that the core pipeline has zero pip dependencies (stdlib only - `urllib`, `json`, `csv`, `concurrent.futures`). Notes that PyQGIS (`qgis.core`), needed only for the optional fallback, is **not** pip-installable and must come from an actual QGIS Desktop/Server install. |

## Package: `pso_enrichment/`

| File | Lines | Purpose | Key functions |
|---|---|---|---|
| `__init__.py` | 18 | Package marker. Also inserts the project root (one level up - where `config.py` lives) onto `sys.path` the moment the package is imported, so `import config` resolves regardless of how/where the package gets imported from. | — |
| `dcgis_client.py` | 124 | Thin, generic client around DC GIS's ArcGIS REST "query" endpoints. Handles pagination (feature layers cap at 2,000 rows/request) and retries on transient network errors (including the `ConnectionResetError` seen on long runs). | `query_all_features()` - paged fetch of permit records; `get_point_on_subblock()` - wraps the DDOT LRS `getPointOnSubBlock` extension call; `raw_query()` - low-level escape hatch used by the QGIS fallback to pull geometry. |
| `permits.py` | 91 | Fetches and filters the PSO permit layer per the data request: date floor, the two permit types, and utility identification via regex against `ApplicantCompany`. Adds derived fields (normalized `Utility`, human-readable date strings). | `fetch_filtered_permit_locations()` |
| `functional_class.py` | 154 | The core enrichment logic against the live LRS API. Two-tier lookup (cheap nearest-only call first, falls back to an escalating-radius full candidate search only when the nearest hit is unusable), with alleys/driveways/ramps/walkways excluded by checking for a real functional-class code rather than matching route-type labels. Runs lookups concurrently via a thread pool, isolating per-point failures so one bad point can't crash the whole batch. | `get_functional_class_for_point()`, `functional_class_rank()` (hierarchy comparison), `enrich_locations()` (threaded batch driver) |
| `qgis_fallback.py` | 261 | Optional local enrichment path using PyQGIS, used automatically for any location the live API can't resolve (or for every point, if `config.USE_QGIS_FALLBACK = True`). Downloads and caches the Roadway SubBlock reference layer as GeoJSON (atomic write), then runs a `native:joinbynearest` spatial join in a standalone PyQGIS session. Requires an actual QGIS install - gracefully fails (caught by `pipeline.py`) when `qgis.core` isn't present, which is the normal case in this dev environment. | `ensure_roadway_cache()`, `enrich_locations_with_qgis()` |
| `pipeline.py` | 170 | Orchestrates the whole run: fetch → enrich (API, with QGIS fallback for any gaps) → roll up each permit's highest functional class → write the CSV → write `run_log.txt`. Defines the final CSV's column order and per-row mapping. | `run()` (the only function `run.py` calls) |

## Documentation

| File | Lines | Purpose |
|---|---|---|
| `README.md` | 244 | The primary how-to-run reference: quick start, the config variables worth knowing about, a full column-by-column reference for the output CSV, the methodology/data-exploration notes (why `ApplicantCompany` not `PermitteeName`, why `TrackingNumber` not `PermitNumber`, the alley/driveway/ramp functional-class gap, etc.), QGIS fallback setup, project layout, and known limitations. |
| `REPORT.md` | 185 | A narrative summary written for the Associate Director: objective, data sources, methodology and the reasoning behind each choice, results with real numbers from the delivered CSV, issues encountered during development (and how they were fixed), a full missing/N-A data census with explanations, and limitations. |
| `FILE_DICTIONARY.md` | — | This file. |

## Generated output (produced by running `run.py`, not hand-edited)

| File | Rows | Purpose |
|---|---|---|
| `output/PSO_Permits_2026_FunctionalClass_Enriched.csv` | 3,690 (header + 3,689 permit locations) | The deliverable: one row per permit application location, each location's own FWHA/DC functional class, and the highest functional class across all locations sharing that permit. Column reference is in `README.md`. |
| `output/run_log.txt` | 4 | Plain-text summary from the most recent run: timestamp, rows written, distinct permits, and how many locations had no resolved functional class. |

## Run comparison: `output/changes_2026-10-13_to_2026-10-29/`

Compares the 2026-10-13 run with the 2026-10-29 run. Rows are matched on
`TrackingNumber` + `WorkLocationFullAddress` + `Longitude` + `Latitude`.
Generated by a one-off comparison script, not by `run.py`.

| File | Rows | Purpose |
|---|---|---|
| `added_rows.csv` | 602 (header + 601) | Permit locations in the 2026-10-29 run but not the 2026-10-13 run - almost all October 2026 applications. Same columns as the main output CSV. |
| `removed_rows.csv` | 559 (header + 558) | Permit locations in the 2026-10-13 run that the feed no longer returns - mostly June/July permits since expired or not paid. Same columns as the main output CSV. The 2026-10-13 CSV's one exact duplicate row is counted once. |
| `changed_fields.csv` | 2,958 (header + 2,957) | One row per changed value across the 1,026 locations present in both runs: location identifiers, then `Field`, `OldValue_2026-10-13`, `NewValue_2026-10-29`. |

## Not present (intentionally)

- `data/` exists but is empty in the delivered project - it's where `qgis_fallback.py` caches the downloaded roadway reference layer (`roadway_subblock_cache.geojson`) the first time the QGIS fallback actually runs. It's a regenerable cache, not source, so it isn't shipped.
- No `__pycache__` directories or `.pyc` files are included.
