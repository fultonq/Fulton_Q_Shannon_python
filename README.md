# PSO Permit Functional Class Enrichment

Enriches calendar-year-2026 DDOT Public Space Occupancy Permit records with
the FWHA/DC functional class of the roadway at each permit location, plus
the single highest functional class associated with each permit
application (a permit can have more than one location/roadway attached to
it).

Built for the Associate Director of Public Space Division's request:
Construction Staging Area / Mobile Crane Work Zone permits for DC Water,
PEPCO, and Washington Gas, from calendar year 2026 forward.

## What it does

1. **Fetch & filter** permit records from the DDOT Public Space Occupancy
   Permits REST feed
   (`DCGIS_APPS/DDOT_TOPS/MapServer/24`), keeping rows where:
   - `EventTypeDescription` is "Construction Staging Area" or "Mobile Crane
     Work Zone"
   - `ApplicationDate` OR `IssueDate` is on/after 2026-01-01
   - `ApplicantCompany` identifies DC Water, PEPCO, or Washington Gas
2. **Enrich** each permit location with the FWHA/DC functional class of the
   nearest roadway, using DDOT's Linear Referencing System
   (`getPointOnSubBlock`), excluding alleys (which carry no functional
   class).
3. **Roll up** the highest functional class across all locations that
   share a permit application.
4. **Write** one CSV row per permit location with both the location's own
   functional class and the permit's overall highest functional class.

## Quick start (Windows 11 or any OS with Python 3.10+)

```
cd Fulton_Q_Shannon_python          (the folder this README is in)
python -m venv venv
venv\Scripts\activate          (Windows)   /  source venv/bin/activate  (Linux/Mac)
pip install -r requirements.txt
python run.py
```

No API keys are required - every data source used is DC's public,
unauthenticated ArcGIS REST feed. The core pipeline only needs the Python
standard library (`requirements.txt` has no hard dependencies); it needs
an internet connection to reach `dcgis.dc.gov`.

Output lands in `output/PSO_Permits_2026_FunctionalClass_Enriched.csv`,
plus a short `output/run_log.txt` with row/permit counts. A full run
(~3,600+ permit locations) takes on the order of several minutes, mostly
spent waiting on the LRS API.

### Results from the included CSV

The CSV in `output/` is a real run against the live data on 2026-10-13, not
a sample/mock. For reference:

- 3,648 permit locations, across 2,482 distinct permit applications
  (`TrackingNumber`), for DC Water / PEPCO / Washington Gas Construction
  Staging Area permits from CY2026 to date (see the Mobile Crane Work Zone
  note above for why that type has zero rows).
- 3,647 of 3,648 locations (99.97%) resolved to a roadway functional class;
  3,538 on the fast nearest-only lookup, 109 needed the escalated/alley-
  avoiding fallback. The 1 unresolved location is a real edge case
  (1900 Massachusetts Avenue SE) sitting inside a cluster of driveways with
  no classified public street within the 200m search limit - it's in the
  CSV with a blank functional class and `FunctionalClassMatchMethod=none`
  rather than silently dropped.
- Location-level functional class distribution: Local 2,015; Minor
  Arterial 679; Major Collector 571; Principal Arterial 286; Minor
  Collector 89; Interstate 7.

## Configuring a run

Everything you'd want to change for a different year, different permit
types, different utilities, etc. lives in **`config.py`** - open it and
edit the plain variables at the top of each section (each one has a
comment explaining what it does). You do not need to touch any other file
for a normal re-run. Notable variables:

| Variable | Purpose |
|---|---|
| `APPLICATION_OR_ISSUE_DATE_FLOOR` | The "on/after this date" filter (currently `2026-01-01`) |
| `PERMIT_TYPES` | Which `EventTypeDescription` values to keep |
| `UTILITY_PATTERNS` | Regex patterns matched against `ApplicantCompany`, and the normalized utility name each maps to |
| `SEARCH_RADIUS_FAST_METERS` / `SEARCH_RADIUS_ESCALATION` | How far to search for the nearest non-alley roadway |
| `MAX_WORKERS` | How many LRS lookups run in parallel |
| `USE_QGIS_FALLBACK` | Switches enrichment from the live API to a local PyQGIS spatial join (see below) |
| `OUTPUT_CSV_PATH` | Where the final CSV is written |

## Output CSV columns

| Column | Meaning |
|---|---|
| `PermitNumber` | Issued permit number (e.g. `PA11175511`). **Blank for applications that have not yet been issued a permit** - see note below. |
| `TrackingNumber` | Stable ID assigned the moment an application is submitted; always present. This is what location rows are grouped by to compute the permit-level rollup. |
| `PermitType` | `EventTypeDescription` - "Construction Staging Area" or "Mobile Crane Work Zone" |
| `Utility` | Normalized utility name: "DC Water", "PEPCO", or "Washington Gas" |
| `Status` / `StatusDescription` | Permit's current workflow status (Issued, Approved (Pending Payment), Permit Expired, Withdrawn, etc.) |
| `ApplicationDate`, `IssueDate`, `EffectiveDate`, `ExpirationDate` | Key dates (YYYY-MM-DD) |
| `WorkLocationFullAddress`, `WorkLocationWard`, `WorkLocationANC`, `WorkLocationZip` | Location context |
| `Longitude`, `Latitude` | The permit location point |
| `LocationFunctionalClass`, `LocationFunctionalClassCode` | FWHA/DC functional class of the nearest (non-alley) roadway **to this specific location** |
| `NearestRouteName`, `NearestRouteType`, `NearestRouteDistanceMeters` | Which roadway the functional class came from, and how far away it was |
| `FunctionalClassMatchMethod` | `api_nearest` / `api_escalated_rNN` / `qgis_fallback` / `none` - how the match was found (see Methodology) |
| `PermitLocationCount` | How many location rows exist for this permit application |
| `PermitHighestFunctionalClass`, `PermitHighestFunctionalClassCode`, `PermitHighestFunctionalClassRouteName` | The highest-ranked functional class (and the roadway it came from) across **all** of this permit's locations |

Functional class rank, highest to lowest: Interstate, Other Freeway and
Expressway, Principal Arterial, Minor Arterial, Major Collector, Minor
Collector, Local (the DC/FHWA "DCFunctionalClasses" coded-value domain).

## Methodology / data exploration notes

There's no data dictionary for this feed, so these are the things that had
to be worked out by probing the live services directly (via the REST
`?f=json` metadata and sample queries) rather than assumed:

- **Permit type** lives in `EventTypeDescription`, not a field literally
  named "type". Values match the request text exactly
  ("Construction Staging Area", "Mobile Crane Work Zone").
- **Which field identifies the utility** took some digging. Several
  candidate fields exist (`OwnerName`, `PermitteeName`, `ApplicantCompany`).
  `PermitteeName`/`OwnerName` are frequently the individual contractor or
  property owner rather than the utility, and naive substring matching on
  them also pulls in false positives (e.g. a contractor literally named
  "CONSOLIDATED WATERPROOFING" matches `%WATER%`). `ApplicantCompany` turned
  out to be clean and consistent across the whole dataset, with exactly six
  spellings covering the three utilities (`DCWater`, `DCWater/CIP`,
  `DCWater/OPS`, `DC WATER - LFDC`, `Pepco`, `Wash Gas & Light Co.`) and no
  observed false positives, so that's what `UTILITY_PATTERNS` matches
  against.
- **Permit identifier**: `PermitNumber` is only assigned once an
  application is actually issued a permit - about half of in-scope rows
  are still mid-workflow (Approved/Pending Payment, Assigned, Resubmit,
  etc.) and have a null `PermitNumber`. Since the data request explicitly
  wants "permit applications **or** issued permits," `TrackingNumber`
  (always present, assigned at submission) is the real per-application key
  used for grouping and the "highest functional class per permit" rollup.
- **One row per permit location**: the permit layer already stores one
  row per location (same `TrackingNumber`/`PermitNumber`, different
  `WorkLocationFullAddress`/coordinates) for multi-location permits, so no
  extra join was needed to discover that structure - just grouping by
  `TrackingNumber`.
- **Alleys**: the LRS (`getPointOnSubBlock`) returns a `routeType` of
  `"Alley"` with a null functional class for alley geometry, confirming the
  data request's note. The enrichment logic explicitly skips any candidate
  with `routeType == "Alley"` (or a missing functional class) and keeps
  searching outward for the nearest real street - see below.
- **No Mobile Crane Work Zone rows in the output**: this isn't a bug. Of
  the 256 "Mobile Crane Work Zone" permits in CY2026, every single
  `ApplicantCompany` is a crane operator or permit expediter (e.g.
  "Metropolitan Permit Services", "Safe Lane Solutions", "Permit Me LLC")
  working on someone else's behalf - none list DC Water, PEPCO, or
  Washington Gas as the applicant. So the filtered output is
  Construction-Staging-Area-only for CY2026 to date. Worth flagging to the
  AD in case utilities' crane work is being filed under a different
  applicant name internally that this field doesn't surface.

### Nearest-roadway lookup strategy

`getPointOnSubBlock` with `returnNearestMatchOnly=true` is fast
(well under a second) but can return an alley if that's genuinely the
closest piece of linework to the point. Asking for every candidate within
radius (`returnNearestMatchOnly=false`) is reliable but much slower
(multiple seconds, worse at larger radii) - calling it for every one of
~3,600 locations would make a run take hours.

So each point is looked up in two stages:

1. Ask for just the nearest feature at a small radius
   (`SEARCH_RADIUS_FAST_METERS`, default 50m). If it isn't an alley, done.
2. Only if that nearest feature *is* an alley (or nothing was found), fall
   back to the full candidate list at an escalating radius
   (`SEARCH_RADIUS_ESCALATION`, default 50/100/200m - 200m is the service's
   max), and take the closest non-alley candidate from that list.

This keeps the large majority of lookups on the cheap path and only pays
the expensive one for the minority of points that land in or next to an
alley.

## QGIS fallback (optional)

The live LRS API above is the primary, recommended method (and is what
the delivered CSV was built from) - it's Approach 1 from the data request.
This project also includes an optional PyQGIS-based local fallback
(`pso_enrichment/qgis_fallback.py`), built against Approach 2's underlying
reference layer (Roadway SubBlock, `DCGIS_DATA/Transportation_WebMercator/MapServer/162`).
It's used automatically for any location the live API can't resolve (rare,
e.g. a point with no roadway at all within 200m), and can be switched to
as the primary method by setting `config.USE_QGIS_FALLBACK = True`.

It works by:
1. Downloading the Roadway SubBlock layer once (excluding alleys),
   reprojected to WGS84, caching it as GeoJSON under `data/`.
2. Starting a standalone PyQGIS session (`QgsApplication`) and running the
   `native:joinbynearest` processing algorithm between the permit points
   and the roadway centerlines.

**Requires a local QGIS install with Python bindings** - this is not
pip-installable. On Windows 11, the simplest path is installing QGIS
Desktop (which bundles its own Python + PyQGIS), then running this project
with *that* Python, e.g.
`"C:\Program Files\QGIS 3.34.0\bin\python-qgis.bat" run.py`, or by setting
`config.QGIS_INSTALL_PREFIX` to your QGIS install folder (e.g.
`r"C:\Program Files\QGIS 3.34.0"`) and running with a Python environment
that has `qgis`/`PyQt5` on its path (the OSGeo4W shell that ships with
QGIS sets this up for you). This repo was developed/tested in an
environment without QGIS installed, so the live-API path is the one that's
been fully exercised end-to-end; the QGIS module follows standard PyQGIS
standalone-script patterns but treat it as the documented-but-lighter-
tested path.

## Project layout

```
config.py                                 All user-editable settings
run.py                                     Entry point: python run.py
pso_enrichment/
    dcgis_client.py                        ArcGIS REST query helper (pagination, retries)
    permits.py                              Fetch + filter permit locations
    functional_class.py                     Live-API enrichment + rank comparison
    qgis_fallback.py                        Optional local PyQGIS enrichment
    pipeline.py                             Orchestration + CSV writer
output/
    PSO_Permits_2026_FunctionalClass_Enriched.csv   Deliverable
    run_log.txt                             Row/permit counts from the last run
data/
    roadway_subblock_cache.geojson          Cached by the QGIS fallback (only created if used)
```

## Known limitations

- Functional class reflects the *current* state of DDOT's roadway network
  and LRS, not necessarily the state at the time a given historical permit
  was issued.
- A small number of permit locations may have no coordinates in the source
  data (rare); these pass through with a blank functional class rather
  than being dropped, so the AD can still see them in the CSV.
- The QGIS fallback path has not been run against a live QGIS install in
  this environment (none was available); review it before relying on it
  for a production run.
