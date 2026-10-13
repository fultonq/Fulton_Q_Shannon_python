"""
Optional PyQGIS-based fallback enrichment.

The live DDOT LRS API (pso_enrichment.functional_class, "Approach 1" in the
data request) is the primary enrichment method and is what the delivered
CSV is built from. This module exists for two situations where it can be
useful instead:

  1. config.USE_QGIS_FALLBACK = True: every point is enriched locally
     instead of calling the live API at all (useful if the LRS endpoint is
     down, rate-limiting you, or you're working offline from a cached
     extract).
  2. Even with USE_QGIS_FALLBACK = False, pipeline.py calls into this
     module for any individual locations the live API could not resolve
     (e.g. truly isolated points with no roadway within 200m), as a second
     opinion before giving up.

It works by downloading DDOT's "Roadway SubBlock" layer (the same
reference layer Approach 2 in the data request points to -
DCGIS_DATA/Transportation_WebMercator/MapServer/162), caching it locally as
GeoJSON, loading it into a standalone PyQGIS session, and running the
`native:joinbynearest` processing algorithm between the permit points and
the roadway centerlines - excluding alleys (ROADTYPE = Alley), same as the
API path.

Requires a local QGIS install with Python bindings (see README.md). This
module is only imported when it's actually needed, so the rest of the
project runs fine without QGIS installed.
"""

from __future__ import annotations

import sys
from pathlib import Path

# Project root on sys.path regardless of how this file is run - see the
# longer comment in dcgis_client.py for why this is needed.
_PROJECT_ROOT = str(Path(__file__).resolve().parent.parent)
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

import json

import config
from pso_enrichment import dcgis_client

# DCGIS_DATA/Transportation_WebMercator/MapServer/162 "DCFunctionalClasses"
# coded-value domain - the raw query only returns the numeric code, so we
# translate it here to the same vocabulary the LRS API returns
# (config.FUNCTIONAL_CLASS_RANK).
_DC_FUNCTIONAL_CLASS_NAMES = {
    11: "Interstate",
    12: "Other Freeway and Expressway",
    14: "Principal Arterial",
    16: "Minor Arterial",
    17: "Major Collector",
    18: "Minor Collector",
    19: "Local",
}


def _download_roadway_subblocks_as_geojson() -> dict:
    """
    Pulls every non-alley Roadway SubBlock feature (geometry reprojected to
    WGS84 so it lines up with the permit points) and returns a GeoJSON
    FeatureCollection dict.
    """
    out_fields = ["ROUTEID", "ROUTENAME", "ROADTYPE", "DCFUNCTIONALCLASS"]
    features = []
    offset = 0
    page_size = 2000
    while True:
        # Excluding on DCFUNCTIONALCLASS being populated (rather than just
        # ROADTYPE <> Alley) matches pso_enrichment.functional_class's logic
        # and also drops driveways/walkways/ramps, which carry no functional
        # class in this layer just like alleys do.
        params = {
            "where": "DCFUNCTIONALCLASS IS NOT NULL",
            "outFields": ",".join(out_fields),
            "returnGeometry": "true",
            "outSR": 4326,
            "f": "json",
            "resultOffset": offset,
            "resultRecordCount": page_size,
        }
        payload = dcgis_client.raw_query(config.ROADWAY_SUBBLOCK_LAYER_URL, params)
        batch = payload.get("features", [])
        for feature in batch:
            attrs = feature["attributes"]
            paths = feature.get("geometry", {}).get("paths")
            if not paths:
                continue
            fc_code = attrs.get("DCFUNCTIONALCLASS")
            features.append({
                "type": "Feature",
                "geometry": {"type": "MultiLineString", "coordinates": paths},
                "properties": {
                    "ROUTEID": attrs.get("ROUTEID"),
                    "ROUTENAME": attrs.get("ROUTENAME"),
                    "FunctionalClass": _DC_FUNCTIONAL_CLASS_NAMES.get(fc_code, ""),
                    # Stored as a string to match the type the live LRS API
                    # path uses for the same field (functional_class.py's
                    # _extract() gets "functionalClassCode" as a string from
                    # that service) - keeps the two enrichment paths
                    # type-consistent for anything downstream.
                    "FunctionalClassCode": str(fc_code) if fc_code is not None else "",
                },
            })
        if len(batch) < page_size:
            break
        offset += page_size

    return {"type": "FeatureCollection", "features": features}


def ensure_roadway_cache() -> str:
    """Downloads the roadway reference layer once and caches it to disk.
    Returns the cache file path as a string."""
    config.DATA_DIR.mkdir(parents=True, exist_ok=True)
    cache_path = config.ROADWAY_SUBBLOCK_CACHE_PATH
    if not cache_path.exists():
        print(f"Downloading roadway reference layer to {cache_path} ...")
        geojson = _download_roadway_subblocks_as_geojson()
        # Write to a temp file and rename into place atomically, so an
        # interrupted download (network drop, killed process) can never
        # leave behind a truncated file that cache_path.exists() would
        # treat as "already downloaded" on every future run.
        tmp_path = cache_path.with_suffix(cache_path.suffix + ".part")
        tmp_path.write_text(json.dumps(geojson), encoding="utf-8")
        tmp_path.replace(cache_path)
        print(f"  cached {len(geojson['features'])} non-alley roadway segments")
    return str(cache_path)


def _init_qgis():
    from qgis.core import QgsApplication

    if config.QGIS_INSTALL_PREFIX:
        QgsApplication.setPrefixPath(config.QGIS_INSTALL_PREFIX, True)
    qgs = QgsApplication([], False)
    qgs.initQgis()

    # The `processing` package (and the native:* algorithms it registers,
    # including native:joinbynearest below) lives under the QGIS install's
    # own python/plugins folder, which is not on sys.path just from
    # initQgis() - this is the standard standalone-PyQGIS-script pattern
    # from QGIS's own documentation. Without it, `import processing` below
    # raises ModuleNotFoundError on a stock install.
    plugins_path = str(Path(QgsApplication.pkgDataPath()) / "python" / "plugins")
    if plugins_path not in sys.path:
        sys.path.append(plugins_path)

    import processing  # noqa: F401 (registers algorithms as a side effect)
    from processing.core.Processing import Processing
    Processing.initialize()

    return qgs


def enrich_locations_with_qgis(rows: list[dict]) -> list[dict]:
    """
    Enrich (in place) the given permit location rows using a local PyQGIS
    nearest-neighbor join against the cached roadway reference layer.
    Only touches rows that have Longitude/Latitude; rows without
    coordinates are left untouched.
    """
    if not rows:
        return rows

    roadway_path = ensure_roadway_cache()

    qgs = _init_qgis()
    try:
        from qgis.core import (
            QgsFeature,
            QgsFields,
            QgsField,
            QgsGeometry,
            QgsPointXY,
            QgsVectorLayer,
        )
        from PyQt5.QtCore import QVariant
        import processing

        roadway_layer = QgsVectorLayer(roadway_path, "roadway_subblocks", "ogr")
        if not roadway_layer.isValid():
            raise RuntimeError(f"Could not load roadway layer from {roadway_path}")

        fields = QgsFields()
        fields.append(QgsField("row_index", QVariant.Int))
        point_layer = QgsVectorLayer("Point?crs=EPSG:4326", "permit_points", "memory")
        # addAttributes() wants a list of QgsField, not the QgsFields
        # container itself.
        point_layer.dataProvider().addAttributes(fields.toList())
        point_layer.updateFields()

        indexable_rows = [
            (i, row) for i, row in enumerate(rows)
            if row.get("Longitude") is not None and row.get("Latitude") is not None
        ]

        point_features = []
        for i, row in indexable_rows:
            feature = QgsFeature(fields)
            feature.setGeometry(
                QgsGeometry.fromPointXY(QgsPointXY(row["Longitude"], row["Latitude"]))
            )
            feature.setAttribute("row_index", i)
            point_features.append(feature)
        point_layer.dataProvider().addFeatures(point_features)
        point_layer.updateExtents()

        result = processing.run(
            "native:joinbynearest",
            {
                "INPUT": point_layer,
                "INPUT_2": roadway_layer,
                "FIELDS_TO_COPY": ["ROUTENAME", "FunctionalClass", "FunctionalClassCode"],
                "DISCARD_NONMATCHING": False,
                "PREFIX": "",
                "NEIGHBORS": 1,
                # Left unset (not passed at all) rather than set to None -
                # some QGIS versions raise QgsProcessingException on an
                # explicit None for this optional distance parameter. The
                # max-distance cutoff is enforced manually below instead
                # (config.QGIS_FALLBACK_MAX_DISTANCE_METERS).
                "OUTPUT": "memory:",
            },
        )
        joined_layer = result["OUTPUT"]

        for feature in joined_layer.getFeatures():
            row_index = feature["row_index"]
            row = rows[row_index]
            distance_m = feature["distance"]
            route_name = feature["ROUTENAME"]
            functional_class = feature["FunctionalClass"]
            functional_class_code = feature["FunctionalClassCode"]

            if functional_class and (
                distance_m is None
                or distance_m <= config.QGIS_FALLBACK_MAX_DISTANCE_METERS
            ):
                row["FunctionalClass"] = functional_class
                row["FunctionalClassCode"] = functional_class_code
                row["RouteName"] = route_name or ""
                row["RouteType"] = "Street"
                row["OffsetMeters"] = distance_m
                row["MatchMethod"] = "qgis_fallback"

        return rows
    finally:
        # Imported here, not at the top of the try block: qgis.core is
        # already loaded and cached by this point (via _init_qgis()
        # succeeding above), so this import is effectively free and can't
        # itself fail in a way that would skip the qgs.exitQgis() cleanup
        # below - unlike importing it earlier alongside the other names,
        # which would leave qgs un-cleaned-up if that import raised.
        from qgis.core import QgsProject
        QgsProject.instance().clear()
        qgs.exitQgis()
