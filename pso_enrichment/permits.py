"""
Fetch and filter DDOT Public Space Occupancy Permit records per the data
request:

  - Permit applications or issued permits >= config.APPLICATION_OR_ISSUE_DATE_FLOOR
  - EventTypeDescription in config.PERMIT_TYPES
  - ApplicantCompany identifies one of config.UTILITY_PATTERNS

The permit layer stores one row per permit *location*. A single permit
(TrackingNumber/PermitNumber) can have more than one location row - this is
expected and is exactly what the data request means by "some permits will
have multiple roadways associated with them".
"""

from __future__ import annotations

import sys
from pathlib import Path

# Project root on sys.path regardless of how this file is run - see the
# longer comment in dcgis_client.py for why this is needed.
_PROJECT_ROOT = str(Path(__file__).resolve().parent.parent)
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

import datetime as dt
import re

import config
from pso_enrichment import dcgis_client


def _epoch_ms_to_date_str(value) -> str:
    if value is None:
        return ""
    return dt.datetime.fromtimestamp(value / 1000, tz=dt.timezone.utc).strftime("%Y-%m-%d")


def _build_where_clause() -> str:
    event_types = ",".join(f"'{t}'" for t in config.PERMIT_TYPES)
    floor_date = config.APPLICATION_OR_ISSUE_DATE_FLOOR
    return (
        f"EventTypeDescription IN ({event_types}) "
        f"AND (ApplicationDate >= TIMESTAMP '{floor_date} 00:00:00' "
        f"OR IssueDate >= TIMESTAMP '{floor_date} 00:00:00')"
    )


def _match_utility(applicant_company: str | None) -> str | None:
    if not applicant_company:
        return None
    for utility_name, pattern in config.UTILITY_PATTERNS.items():
        if re.search(pattern, applicant_company, re.IGNORECASE):
            return utility_name
    return None


def fetch_filtered_permit_locations() -> list[dict]:
    """
    Returns one dict per permit *location* row, already filtered to the
    target permit types / date floor / utilities, with a few derived
    fields added (Utility, ApplicationDateStr, IssueDateStr).
    """
    where = _build_where_clause()
    raw_rows = dcgis_client.query_all_features(
        config.PERMIT_LAYER_URL,
        where=where,
        out_fields=config.PERMIT_OUT_FIELDS,
    )

    rows = []
    for row in raw_rows:
        utility = _match_utility(row.get("ApplicantCompany"))
        if utility is None:
            continue

        row = dict(row)
        row["Utility"] = utility
        row["ApplicationDateStr"] = _epoch_ms_to_date_str(row.get("ApplicationDate"))
        row["IssueDateStr"] = _epoch_ms_to_date_str(row.get("IssueDate"))
        row["EffectiveDateStr"] = _epoch_ms_to_date_str(row.get("EffectiveDate"))
        row["ExpirationDateStr"] = _epoch_ms_to_date_str(row.get("ExpirationDate"))

        if row.get("Longitude") is None or row.get("Latitude") is None:
            # Can't enrich a location with no coordinates; keep the row but
            # it will come through the pipeline with a blank functional class.
            pass

        rows.append(row)

    return rows
