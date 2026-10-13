"""
FWHA/DC functional class enrichment for a single lon/lat point, using the
DDOT Linear Referencing System's getPointOnSubBlock extension (Data Source
Approach 1 in the data request).

Strategy, per point:
  1. Ask for just the single nearest roadway feature at a small radius
     (cheap - sub-second).
  2. If that nearest feature is an alley (no functional class), fall back to
     asking for every candidate within an escalating radius and pick the
     closest one that is NOT an alley. This is the slower call, but it is
     only needed for the minority of points whose closest geometry happens
     to be an alley.
  3. If nothing non-alley is found even at the largest configured radius,
     the point is reported with a blank functional class so it's visible
     in the output for manual follow-up (and, if configured, handed to the
     optional PyQGIS fallback - see qgis_fallback.py).
"""

from __future__ import annotations

import sys
from pathlib import Path

# Project root on sys.path regardless of how this file is run - see the
# longer comment in dcgis_client.py for why this is needed.
_PROJECT_ROOT = str(Path(__file__).resolve().parent.parent)
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Optional

import config
from pso_enrichment import dcgis_client

_RANK_INDEX = {name: i for i, name in enumerate(config.FUNCTIONAL_CLASS_RANK)}

EMPTY_RESULT = {
    "FunctionalClass": "",
    "FunctionalClassCode": "",
    "RouteName": "",
    "RouteType": "",
    "OffsetMeters": "",
    "MatchMethod": "none",
}


def functional_class_rank(name: Optional[str]) -> int:
    """Lower is 'more important' (Interstate=0 ... Local=6). Unknown classes
    sort after everything real so they never win a highest-class comparison."""
    if not name:
        return len(config.FUNCTIONAL_CLASS_RANK) + 1
    return _RANK_INDEX.get(name, len(config.FUNCTIONAL_CLASS_RANK))


def _lacks_functional_class(candidate: dict) -> bool:
    """
    True for any candidate that shouldn't be used as "the roadway" for a
    permit location: alleys (per the data request's explicit note), and
    - it turns out in practice - driveways, walkways, and ramps, which the
    LRS also returns with no FWHA/DC functional class assigned. The
    authoritative signal is the functional class *code* being absent
    (routeType labels for these vary - "Alley", "Driveway", "Unknown" - so
    checking the code directly is more robust than matching routeType
    strings).
    """
    other = (
        candidate.get("roadData", {})
        .get("roadwayAttributes", {})
        .get("other", {})
    )
    return not other.get("functionalClassCode")


def _extract(candidate: dict, match_method: str) -> dict:
    other = (
        candidate.get("roadData", {})
        .get("roadwayAttributes", {})
        .get("other", {})
    )
    return {
        "FunctionalClass": other.get("functionalClass") or "",
        "FunctionalClassCode": other.get("functionalClassCode") or "",
        "RouteName": candidate.get("routeName") or "",
        "RouteType": candidate.get("routeType") or "",
        "OffsetMeters": candidate.get("offsetInMeters", ""),
        "MatchMethod": match_method,
    }


def get_functional_class_for_point(longitude: float, latitude: float) -> dict:
    if longitude is None or latitude is None:
        return dict(EMPTY_RESULT)

    # Fast path: single nearest feature at the smallest radius.
    fast_matches = dcgis_client.get_point_on_subblock(
        longitude, latitude,
        search_radius=config.SEARCH_RADIUS_FAST_METERS,
        nearest_only=True,
    )
    if fast_matches and not _lacks_functional_class(fast_matches[0]):
        return _extract(fast_matches[0], "api_nearest")

    # Slow path: the true nearest feature was an alley (or nothing was
    # found at all) - widen the search and pull every candidate so we can
    # pick the closest non-alley roadway.
    for radius in config.SEARCH_RADIUS_ESCALATION:
        candidates = dcgis_client.get_point_on_subblock(
            longitude, latitude,
            search_radius=radius,
            nearest_only=False,
        )
        usable = [c for c in candidates if not _lacks_functional_class(c)]
        if usable:
            best = min(usable, key=lambda c: c.get("offsetInMeters", float("inf")))
            return _extract(best, f"api_escalated_r{radius}")

    return dict(EMPTY_RESULT)


def enrich_locations(rows: list[dict]) -> list[dict]:
    """
    Adds functional-class fields to each permit location row in place
    (mutates and returns the same list), looking up points concurrently.
    """
    def _task(row):
        try:
            result = get_functional_class_for_point(row.get("Longitude"), row.get("Latitude"))
        except Exception as exc:
            # A single point failing (e.g. the LRS service dropping the
            # connection) should not take down a multi-thousand-row run.
            # Leave it blank here; _enrich_missing_with_qgis / the CSV's
            # FunctionalClassMatchMethod column surface it for follow-up.
            result = dict(EMPTY_RESULT)
            result["MatchMethod"] = f"error: {exc}"
        return row, result

    failed = 0
    with ThreadPoolExecutor(max_workers=config.MAX_WORKERS) as pool:
        futures = [pool.submit(_task, row) for row in rows]
        done = 0
        total = len(rows)
        for future in as_completed(futures):
            row, result = future.result()
            row.update(result)
            if result["MatchMethod"].startswith("error"):
                failed += 1
            done += 1
            if done % 100 == 0 or done == total:
                print(f"  enriched {done}/{total} permit locations"
                      f"{f' ({failed} failed so far)' if failed else ''}", flush=True)

    return rows
