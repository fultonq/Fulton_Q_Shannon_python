"""
Small helper around DC GIS's ArcGIS REST "query" endpoints.

Handles pagination (the permit layer caps responses at 2000 features) and
retries on transient network errors, since both of those turn out to matter
when pulling a multi-thousand-row layer over a public connection.
"""

from __future__ import annotations

import sys
from pathlib import Path

# Make the project root (one level up - where config.py lives) importable
# no matter how this file ends up getting run: `python run.py` from the
# root, `from pso_enrichment import dcgis_client` from elsewhere, or this
# file executed directly as a script (e.g. an IDE's "Run" on this file
# specifically). Only the last case actually needs this - the package's
# __init__.py already does the same thing for normal package imports -
# but it's cheap and idempotent to just always do it here too.
_PROJECT_ROOT = str(Path(__file__).resolve().parent.parent)
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

import json
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Iterable

import config


def _request(url: str, params: dict[str, Any]) -> dict:
    query_string = urllib.parse.urlencode(params)
    full_url = f"{url}?{query_string}"

    last_error: Exception | None = None
    for attempt in range(1, config.REQUEST_RETRIES + 1):
        try:
            with urllib.request.urlopen(
                full_url, timeout=config.REQUEST_TIMEOUT_SECONDS
            ) as response:
                payload = json.loads(response.read())
            if "error" in payload:
                raise RuntimeError(
                    f"ArcGIS REST error calling {url}: {payload['error']}"
                )
            return payload
        except (urllib.error.URLError, OSError, RuntimeError, json.JSONDecodeError) as exc:
            # OSError also covers ConnectionResetError/TimeoutError/other raw
            # socket errors that can surface directly from http.client
            # without being wrapped in a URLError, which showed up in
            # practice partway through a multi-thousand-request run.
            last_error = exc
            if attempt < config.REQUEST_RETRIES:
                time.sleep(config.REQUEST_RETRY_BACKOFF_SECONDS * attempt)
    raise RuntimeError(f"Failed calling {url} after {config.REQUEST_RETRIES} attempts") from last_error


def raw_query(layer_url: str, params: dict) -> dict:
    """Low-level escape hatch for callers that need the full raw ArcGIS
    REST response (e.g. geometry), rather than just the attribute dicts
    that query_all_features() returns."""
    return _request(f"{layer_url}/query", params)


def query_all_features(
    layer_url: str,
    where: str,
    out_fields: Iterable[str],
    order_by: str = "OBJECTID",
    page_size: int = 2000,
) -> list[dict]:
    """
    Pull every feature matching `where`, paging with resultOffset until the
    server returns fewer than a full page.
    """
    features: list[dict] = []
    offset = 0
    while True:
        params = {
            "where": where,
            "outFields": ",".join(out_fields),
            "returnGeometry": "false",
            "f": "json",
            "orderByFields": order_by,
            "resultOffset": offset,
            "resultRecordCount": page_size,
        }
        payload = _request(f"{layer_url}/query", params)
        batch = payload.get("features", [])
        features.extend(f["attributes"] for f in batch)

        if len(batch) < page_size:
            break
        offset += page_size

    return features


def get_point_on_subblock(
    x: float,
    y: float,
    search_radius: int,
    nearest_only: bool,
) -> list[dict]:
    """
    Call the DDOT LRS getPointOnSubBlock extension for a single point.
    Returns the (possibly empty) list of candidate roadway matches, ordered
    nearest-first by the service.
    """
    params = {
        "f": "json",
        "x": x,
        "y": y,
        "inSR": config.LRS_IN_SR,
        "outSR": config.LRS_OUT_SR,
        "searchRadius": search_radius,
        "returnNearestMatchOnly": "true" if nearest_only else "false",
    }
    payload = _request(config.LRS_GET_POINT_ON_SUBBLOCK_URL, params)
    return payload.get("pointOnSubBlocks", [])
