# Project Summary Report

**PSO Permit Functional Class Enrichment — Calendar Year 2026**
Prepared for: Associate Director, Public Space Division
Prepared by: Fulton Q. Shannon
Run date: 2026-10-29 (first delivered 2026-10-13)

---

## 1. Objective

Enrich CY2026 DDOT Public Space Occupancy Permit (PSO) records for
Construction Staging Area and Mobile Crane Work Zone permits filed by DC
Water, PEPCO, and Washington Gas with:

- the FWHA/DC functional class of the roadway **at each individual permit
  location**, and
- the **highest functional class** across all locations tied to a single
  permit application (since permits can span more than one roadway).

Output is a single CSV, one row per permit location, per the data request.

## 2. Data Sources Used

| Source | Role |
|---|---|
| `DCGIS_APPS/DDOT_TOPS/MapServer/24` (DDOT Public Space Occupancy Permits) | Permit records — filtered, one row per location |
| `DDOT/RoadwayBlocks/MapServer/exts/DdotLrsExtensions/getPointOnSubBlock` (DDOT Linear Referencing System) | Primary functional-class enrichment — nearest-roadway lookup per point (Approach 1 in the data request) |
| `DCGIS_DATA/Transportation_WebMercator/MapServer/162` (Roadway SubBlock) | Reference layer for an optional local PyQGIS fallback (Approach 2's underlying layer), used only when the live API can't resolve a point |

No data dictionary exists for any of these feeds; every field used below
was identified by querying the live `?f=json` metadata and sample records
rather than assumed. Both API feeds are public and unauthenticated.

## 3. Methodology / Approach, and Why

### 3.1 Filtering

- **Date floor**: `ApplicationDate >= 2026-01-01 OR IssueDate >= 2026-01-01`,
  pushed down as a server-side WHERE clause. Using OR (not AND) was
  necessary because many permits have an `ApplicationDate` in late 2025
  but an `IssueDate` in 2026 (normal processing lag) — the request asks
  for applications *or* issued permits on/after the floor, and either
  date qualifying is what the data actually reflects.
- **Permit type**: filtered on `EventTypeDescription`, the only field
  whose values ("Construction Staging Area", "Mobile Crane Work Zone",
  etc.) match the request's wording exactly. There is no field literally
  named "permit type."
- **Utility**: filtered on `ApplicantCompany`, chosen after testing three
  candidate fields (`OwnerName`, `PermitteeName`, `ApplicantCompany`).
  `OwnerName`/`PermitteeName` are usually the individual contractor or
  property owner, not the utility, and naive keyword matching against them
  produces false positives (e.g. a contractor named "CONSOLIDATED
  WATERPROOFING" matches `%WATER%`). `ApplicantCompany` was the only field
  that was clean across the entire dataset: exactly six spellings cover
  all three utilities (`DCWater`, `DCWater/CIP`, `DCWater/OPS`,
  `DC WATER - LFDC`, `Pepco`, `Wash Gas & Light Co.`), with zero observed
  false positives. Matching uses case-insensitive regex, not exact string
  equality, so minor future spelling variants (e.g. a different casing)
  would still be caught.
- **Grouping key for the permit-level rollup**: `TrackingNumber`, not
  `PermitNumber`. `PermitNumber` is only assigned once a permit is
  actually issued — in this dataset, 1,850 of 3,689 location rows (1,238
  of 2,544 permits, 49%) are still mid-workflow (Approved/Pending Payment,
  Not Paid, Assigned, Resubmit, etc.) and have no `PermitNumber` yet.
  Since the request explicitly wants applications *or* issued permits
  included, grouping on a field that's frequently null would be wrong.
  `TrackingNumber` is assigned at submission and is never null.

### 3.2 Functional Class Enrichment

Each permit location's coordinates are sent to `getPointOnSubBlock`, which
returns the nearest roadway segment(s) and their FWHA/DC functional class.
Two things required extra handling:

- **Alleys (noted in the data request) and, it turned out in practice,
  driveways/walkways/ramps** are all returned by the API as "the nearest
  roadway" when that's genuinely what's closest, but none of them carry a
  functional class. The request only called out alleys explicitly;
  testing surfaced that several other route types have the identical gap.
  Rather than hard-coding every route-type label to exclude, the logic
  checks whether the functional class *code* is present — if it isn't,
  that candidate is skipped and the search continues to the next-nearest
  real roadway. This is both more correct and more future-proof than
  matching on route-type strings.
- **Performance**: the "return every candidate within radius" call the
  alley-avoidance logic needs is slow (multi-second) and would make a
  ~3,600-row run take hours if used for every point. So each point first
  gets a cheap "nearest feature only" call (well under a second); the
  slow, exhaustive call only runs for the minority of points whose single
  nearest feature is unusable (alley/driveway/etc.), escalating the
  search radius (50m → 100m → 200m, the service's max) only as needed.
  This kept the full run to roughly 5 minutes.

### 3.3 Highest Functional Class Per Permit

For each `TrackingNumber`, the output's `PermitHighestFunctionalClass` is
the location with the best (lowest-numbered) rank in the official
DC/FHWA functional class hierarchy (Interstate > Other Freeway/Expressway
> Principal Arterial > Minor Arterial > Major Collector > Minor Collector
> Local), pulled from the same coded-value domain published on the
Roadway SubBlock layer. This was independently re-verified against the
delivered CSV: recomputing the rollup from scratch and comparing against
every row produced **zero mismatches** across all 2,544 permits, and the
value is identical across every row sharing a permit.

### 3.4 Why the Live API Over the Local/QGIS Approach

The request offered two enrichment approaches. The live LRS API (Approach
1) was used as primary because it returns an authoritative, current
nearest-roadway match in a single call with no extra data engineering. A
PyQGIS-based local fallback (built against Approach 2's reference layer)
is included and wired in automatically for any point the live API can't
resolve, or as a complete substitute via a config switch — useful if the
API is ever unreachable. It was not available to test in this environment
(no local QGIS install) but did engage correctly for the one unresolved
location in this run and reported the outcome rather than failing the run.

## 4. Results

- **3,689 permit location rows**, covering **2,544 distinct permit
  applications**, for Construction Staging Area permits filed by DC Water
  (1,874 rows), Washington Gas (1,717), and PEPCO (98). Application dates
  run from 2026-03-17 to 2026-10-28 — see §7 on why this is not a complete
  CY2026 record.
- **525 permits (21%) have more than one roadway location** attached
  (up to 16 on a single permit; average 1.45 locations/permit) — these
  are exactly the cases the data request flagged, and each location is
  its own CSV row with the shared permit's highest class also shown.
- **Functional class resolved for 3,688 of 3,689 locations (99.97%)**:
  3,596 via the fast nearest-match lookup, 92 via the escalated
  alley/driveway-avoiding fallback.
- Location-level functional class distribution: Local 2,072; Minor
  Arterial 672; Major Collector 581; Principal Arterial 285; Minor
  Collector 71; Interstate 7.
- **Changes since the 2026-10-13 run** (full detail in
  `output/changes_2026-10-13_to_2026-10-29/`): 601 locations added (almost
  all October applications), 558 no longer returned by the feed (mostly
  June/July permits since expired or not paid), and 1,026 updated in place
  — mainly status changes and newly issued permit numbers. 7 intersection
  locations now match the cross street rather than the main road and
  dropped functional class (e.g. Wisconsin Ave & S St NW: Principal
  Arterial → Local).

## 5. Issues Encountered

- **Dropped connections on long runs.** Early full runs against the live
  LRS API occasionally hit a `ConnectionResetError` partway through
  (~1,000 of 3,648 points in), which crashed the whole batch because the
  original retry logic didn't catch that specific exception type. Fixed
  by broadening the retry's exception handling and isolating each point's
  lookup so one failure can't take down the run — it now just gets
  recorded as unresolved and processing continues.
- **Driveways/walkways/ramps silently mimicking alleys.** The first
  complete run produced 13 rows classified as `"Uncassified"` (DC's data
  has a typo for "Unclassified") instead of a real functional class —
  traced to the API returning these route types as the nearest match the
  same way it returns alleys, which the original alley-only filter didn't
  catch. Re-ran after the fix described in §3.2; confirmed zero
  "Uncassified"/alley values remain in the final CSV.
- **A second, independent run of the script was briefly active in
  parallel** (apparently launched from a local IDE) while this run was in
  progress, both targeting the same output file. Flagged to the user
  immediately; they stopped their copy, so there was no file-write
  collision in the delivered CSV.

## 6. Missing / N/A Data

| Field | Blank rate | Explanation |
|---|---|---|
| `PermitNumber`, `IssueDate` | 1,850 / 3,689 rows (50.1%) | Permit hasn't been issued yet — these are in-progress applications (Approved/Pending Payment, Not Paid, Assigned, Resubmit, etc.), which the data request explicitly asked to include. Not a data error. |
| `WorkLocationANC`, `WorkLocationZip` | 3,186 / 3,689 rows (86.4%) (Zip: 3,187) | Confirmed this is a **source-system data quality gap**, not something introduced by this pipeline — the same ~83% blank rate holds across the *entire* permit layer regardless of filters (checked against all 7,385 CY2026 Construction Staging/Mobile Crane records, both utility and non-utility). Worth flagging to DDOT's data team separately. |
| `WorkLocationWard` | 107 / 3,689 rows (2.9%) | Same upstream sparsity, smaller rate. |
| `LocationFunctionalClass` (and the 6 related columns) | 1 / 3,689 rows (0.03%) | One permit location (TrackingNumber 11229770, 1900 Massachusetts Avenue SE) sits inside a cluster of driveways with no classified public street within the 200m search limit — a genuine "no roadway nearby" case, not a lookup failure. Left in the CSV rather than dropped, flagged via `FunctionalClassMatchMethod=none`. |
| Mobile Crane Work Zone permits | 0 of 3,689 rows | **Not missing data** — verified directly: none of the 305 CY2026 Mobile Crane Work Zone permit-locations list DC Water/PEPCO/Washington Gas as `ApplicantCompany`. 158 list a crane operator or permit expediter (e.g. "Metropolitan Permit Services," "Safe Lane Solutions"); the other 147 have `ApplicantCompany` recorded as "N/A". Flagging for the AD: if utility crane work is expected here, it may be filed under a contractor's name in this system rather than the utility's, which an `ApplicantCompany`-based filter can't surface. |

## 7. Limitations

- Functional class reflects DDOT's *current* roadway network/LRS, not
  necessarily the roadway's classification at the time a given historical
  permit was issued.
- The PyQGIS fallback path is implemented but has not been exercised
  against a live QGIS install (none was available in the development
  environment) — review before relying on it for volume.
- `ApplicantCompany` is the best available proxy for "which utility this
  permit is for," but it's whoever filed the application, not a verified
  ownership/utility-assignment field — see the Mobile Crane note above.
- The permit feed appears to keep only recent/active permits: 337 permits
  in the 2026-10-13 run (mostly June/July applications since expired or
  not paid) were no longer returned on 2026-10-29, even though they still
  meet the date filter, and no utility permit applied for before
  2026-03-17 appears in either run. Each run is therefore a snapshot of
  what the feed currently holds, not a complete CY2026 record; ask DDOT
  whether an archive/historical layer exists if the full year is needed.

## 8. Deliverables

- `run.py`, `config.py`, `pso_enrichment/` — full pipeline source
- `output/PSO_Permits_2026_FunctionalClass_Enriched.csv` — the enriched
  dataset described above
- `output/changes_2026-10-13_to_2026-10-29/` — added, removed, and
  changed rows between the 2026-10-13 and 2026-10-29 runs
- `README.md` — setup/run instructions and field reference
- `REPORT.md` — this document
