"""
End-to-end orchestration: fetch filtered permit locations, enrich each one
with its nearest roadway's FWHA/DC functional class, roll up the highest
functional class per permit, and write the final CSV.
"""

from __future__ import annotations

import sys
from pathlib import Path

# Project root on sys.path regardless of how this file is run - see the
# longer comment in dcgis_client.py for why this is needed.
_PROJECT_ROOT = str(Path(__file__).resolve().parent.parent)
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

import csv
import datetime as dt

import config
from pso_enrichment import functional_class as fc
from pso_enrichment import permits as permits_module

CSV_COLUMNS = [
    "PermitNumber",
    "TrackingNumber",
    "PermitType",
    "Utility",
    "Status",
    "StatusDescription",
    "ApplicationDate",
    "IssueDate",
    "EffectiveDate",
    "ExpirationDate",
    "WorkLocationFullAddress",
    "WorkLocationWard",
    "WorkLocationANC",
    "WorkLocationZip",
    "Longitude",
    "Latitude",
    "LocationFunctionalClass",
    "LocationFunctionalClassCode",
    "NearestRouteName",
    "NearestRouteType",
    "NearestRouteDistanceMeters",
    "FunctionalClassMatchMethod",
    "PermitLocationCount",
    "PermitHighestFunctionalClass",
    "PermitHighestFunctionalClassCode",
    "PermitHighestFunctionalClassRouteName",
]


def _enrich_missing_with_qgis(rows: list[dict]) -> None:
    missing = [r for r in rows if not r.get("FunctionalClass")]
    if not missing:
        return
    print(f"  attempting PyQGIS fallback for {len(missing)} unresolved location(s) ...")
    try:
        from pso_enrichment import qgis_fallback
        qgis_fallback.enrich_locations_with_qgis(missing)
    except Exception as exc:  # pragma: no cover - environment dependent
        print(
            f"  PyQGIS fallback unavailable/failed ({exc}). "
            f"{len(missing)} location(s) will appear in the CSV with a "
            "blank functional class."
        )


def _rollup_highest_functional_class(rows: list[dict]) -> None:
    # Grouped by TrackingNumber rather than PermitNumber: PermitNumber is
    # only assigned once a permit is actually issued, so applications still
    # in review (which the data request explicitly wants included) would
    # otherwise collide under a shared null key. TrackingNumber is present
    # and unique per application from the moment it's submitted.
    by_permit: dict[int, list[dict]] = {}
    for row in rows:
        by_permit.setdefault(row["TrackingNumber"], []).append(row)

    for tracking_number, permit_rows in by_permit.items():
        best = min(
            permit_rows,
            key=lambda r: fc.functional_class_rank(r.get("FunctionalClass")),
        )
        highest_class = best.get("FunctionalClass", "")
        highest_code = best.get("FunctionalClassCode", "")
        highest_route = best.get("RouteName", "")
        count = len(permit_rows)
        for row in permit_rows:
            row["PermitHighestFunctionalClass"] = highest_class
            row["PermitHighestFunctionalClassCode"] = highest_code
            row["PermitHighestFunctionalClassRouteName"] = highest_route
            row["PermitLocationCount"] = count


def _to_csv_row(row: dict) -> dict:
    return {
        "PermitNumber": row.get("PermitNumber", ""),
        "TrackingNumber": row.get("TrackingNumber", ""),
        "PermitType": row.get("EventTypeDescription", ""),
        "Utility": row.get("Utility", ""),
        "Status": row.get("Status", ""),
        "StatusDescription": row.get("StatusDescription", ""),
        "ApplicationDate": row.get("ApplicationDateStr", ""),
        "IssueDate": row.get("IssueDateStr", ""),
        "EffectiveDate": row.get("EffectiveDateStr", ""),
        "ExpirationDate": row.get("ExpirationDateStr", ""),
        "WorkLocationFullAddress": row.get("WorkLocationFullAddress", ""),
        "WorkLocationWard": row.get("WorkLocationWard", ""),
        "WorkLocationANC": row.get("WorkLocationANC", ""),
        "WorkLocationZip": row.get("WorkLocationZip", ""),
        "Longitude": row.get("Longitude", ""),
        "Latitude": row.get("Latitude", ""),
        "LocationFunctionalClass": row.get("FunctionalClass", ""),
        "LocationFunctionalClassCode": row.get("FunctionalClassCode", ""),
        "NearestRouteName": row.get("RouteName", ""),
        "NearestRouteType": row.get("RouteType", ""),
        "NearestRouteDistanceMeters": row.get("OffsetMeters", ""),
        "FunctionalClassMatchMethod": row.get("MatchMethod", ""),
        "PermitLocationCount": row.get("PermitLocationCount", ""),
        "PermitHighestFunctionalClass": row.get("PermitHighestFunctionalClass", ""),
        "PermitHighestFunctionalClassCode": row.get("PermitHighestFunctionalClassCode", ""),
        "PermitHighestFunctionalClassRouteName": row.get(
            "PermitHighestFunctionalClassRouteName", ""
        ),
    }


def run() -> None:
    config.OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    print("Fetching and filtering permit records ...")
    rows = permits_module.fetch_filtered_permit_locations()
    print(f"  {len(rows)} permit location(s) match the filters "
          f"(types={config.PERMIT_TYPES}, "
          f"date floor={config.APPLICATION_OR_ISSUE_DATE_FLOOR}, "
          f"utilities={list(config.UTILITY_PATTERNS)})")

    if config.USE_QGIS_FALLBACK:
        print("USE_QGIS_FALLBACK=True: enriching all locations via local PyQGIS join ...")
        for row in rows:
            row.update(dict(fc.EMPTY_RESULT))
        from pso_enrichment import qgis_fallback
        qgis_fallback.enrich_locations_with_qgis(rows)
    else:
        print("Enriching permit locations with FWHA functional class via DDOT LRS API ...")
        fc.enrich_locations(rows)
        _enrich_missing_with_qgis(rows)

    print("Rolling up highest functional class per permit ...")
    _rollup_highest_functional_class(rows)

    print(f"Writing {len(rows)} rows to {config.OUTPUT_CSV_PATH} ...")
    with open(config.OUTPUT_CSV_PATH, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_COLUMNS)
        writer.writeheader()
        for row in rows:
            writer.writerow(_to_csv_row(row))

    unresolved = sum(1 for r in rows if not r.get("FunctionalClass"))
    permit_count = len({r["TrackingNumber"] for r in rows})
    summary_lines = [
        f"Run completed: {dt.datetime.now().isoformat(timespec='seconds')}",
        f"Permit locations written: {len(rows)}",
        f"Distinct permits: {permit_count}",
        f"Locations with no resolved functional class: {unresolved}",
    ]
    config.RUN_LOG_PATH.write_text("\n".join(summary_lines) + "\n")
    print("\n".join(summary_lines))
