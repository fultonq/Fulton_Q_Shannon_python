"""
Configuration for the PSO Permit Functional Class Enrichment tool.

Edit the values below to change what gets pulled and how the script behaves.
Everything else in the project reads its settings from this file only -
you should not need to touch any other file to run a normal job.
"""

from pathlib import Path

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
# BASE_DIR is the folder this config.py lives in, so the script works no
# matter where the project folder is copied to on disk (Windows or Linux).
BASE_DIR = Path(__file__).resolve().parent
OUTPUT_DIR = BASE_DIR / "output"
DATA_DIR = BASE_DIR / "data"
OUTPUT_CSV_PATH = OUTPUT_DIR / "PSO_Permits_2026_FunctionalClass_Enriched.csv"
RUN_LOG_PATH = OUTPUT_DIR / "run_log.txt"

# ---------------------------------------------------------------------------
# Data Requirements (from the data request)
# ---------------------------------------------------------------------------
# Permit applications or issued permits should be equal to or after this date.
APPLICATION_OR_ISSUE_DATE_FLOOR = "2026-01-01"

# The two permit types (EventTypeDescription field) the AD wants to see.
PERMIT_TYPES = [
    "Construction Staging Area",
    "Mobile Crane Work Zone",
]

# The three public utilities to keep. Matching is done against the
# ApplicantCompany field with the case-insensitive regex patterns below
# (ApplicantCompany was verified against the live data to be the clean,
# utility-specific field - see README "Data Exploration Notes").
# Keys are the normalized utility name that will show up in the output CSV.
UTILITY_PATTERNS = {
    "DC Water": r"DC\s*WATER",
    "PEPCO": r"PEPCO",
    "Washington Gas": r"WASH\w*\s*GAS",
}

# ---------------------------------------------------------------------------
# Data source: DDOT Public Space Occupancy Permits (REST feed)
# ---------------------------------------------------------------------------
PERMIT_LAYER_URL = (
    "https://maps2.dcgis.dc.gov/dcgis/rest/services/DCGIS_APPS/"
    "DDOT_TOPS/MapServer/24"
)

# Fields pulled from the permit layer. Trimmed to what is actually used
# downstream; add more names here if you want extra columns in the CSV.
PERMIT_OUT_FIELDS = [
    "OBJECTID",
    "TrackingNumber",
    "PermitNumber",
    "EventTypeDescription",
    "Status",
    "StatusDescription",
    "ApplicationDate",
    "IssueDate",
    "EffectiveDate",
    "ExpirationDate",
    "ApplicantCompany",
    "PermitteeName",
    "WorkLocationFullAddress",
    "WorkLocationWard",
    "WorkLocationANC",
    "WorkLocationZip",
    "LocationID",
    "Longitude",
    "Latitude",
]

# ---------------------------------------------------------------------------
# FWHA Functional Class enrichment: DDOT Linear Referencing System (LRS)
# ---------------------------------------------------------------------------
LRS_GET_POINT_ON_SUBBLOCK_URL = (
    "https://rh.dcgis.dc.gov/dcgis/rest/services/DDOT/RoadwayBlocks/"
    "MapServer/exts/DdotLrsExtensions/getPointOnSubBlock"
)

# Coordinates from the permit layer are plain lon/lat (WGS84).
LRS_IN_SR = 4326
LRS_OUT_SR = 4326

# First pass: ask only for the single nearest feature at this radius (cheap,
# ~0.2-0.5s per call). If that nearest feature turns out to be an alley (no
# functional class), we fall back to a full candidate search - see
# SEARCH_RADIUS_ESCALATION below. 200m is the maximum this service allows.
SEARCH_RADIUS_FAST_METERS = 50
SEARCH_RADIUS_ESCALATION = [50, 100, 200]

# Alleys carry no FWHA functional class and must be skipped per the data
# source guidance (NOTE in the request: "Avoid blank results by filtering
# out alleys") - in practice driveways, walkways, and ramps turned out to
# have the same gap, so pso_enrichment.functional_class detects all of
# these the same way: by the functional class *code* being absent, not by
# matching a specific route-type label.

# Rank order of FWHA/DC functional classes, most significant first. This is
# the authoritative "DCFunctionalClasses" coded-value domain published on
# the Roadway SubBlock layer
# (DCGIS_DATA/Transportation_WebMercator/MapServer/162), and it is the same
# vocabulary getPointOnSubBlock returns in roadData.roadwayAttributes.other.
FUNCTIONAL_CLASS_RANK = [
    "Interstate",
    "Other Freeway and Expressway",
    "Principal Arterial",
    "Minor Arterial",
    "Major Collector",
    "Minor Collector",
    "Local",
]

# Network behavior
REQUEST_TIMEOUT_SECONDS = 30
REQUEST_RETRIES = 4
REQUEST_RETRY_BACKOFF_SECONDS = 3
# How many permit locations to look up in parallel. The LRS endpoint can be
# slow (multi-second) on the "full candidate list" fallback path, so a
# moderate amount of parallelism keeps a multi-thousand-row run from taking
# hours. Lower this if you see timeouts/connection resets from the DDOT
# server (observed occasionally on long runs at higher worker counts).
MAX_WORKERS = 6

# ---------------------------------------------------------------------------
# Optional QGIS (PyQGIS) fallback
# ---------------------------------------------------------------------------
# The live LRS API above (Approach 1 in the data request) is the primary
# enrichment method. If it is unreachable, or a handful of points fail to
# resolve to any non-alley roadway within SEARCH_RADIUS_ESCALATION, this
# project can optionally fall back to a local nearest-neighbor spatial join
# done entirely in PyQGIS against a downloaded copy of the Roadway SubBlock
# layer (Approach 2's underlying data, layer MapServer/162).
#
# Set to True only if QGIS (with its Python bindings) is installed on this
# machine. See README.md "QGIS fallback" section for Windows setup notes.
USE_QGIS_FALLBACK = False

# On Windows this is typically something like:
#   r"C:\Program Files\QGIS 3.34.0"
# On Linux, leave as None to let PyQGIS auto-detect from the environment
# (e.g. when running inside an OSGeo4W / QGIS python console).
QGIS_INSTALL_PREFIX = None

ROADWAY_SUBBLOCK_LAYER_URL = (
    "https://maps2.dcgis.dc.gov/dcgis/rest/services/DCGIS_DATA/"
    "Transportation_WebMercator/MapServer/162"
)
ROADWAY_SUBBLOCK_CACHE_PATH = DATA_DIR / "roadway_subblock_cache.geojson"
# Distance (in the layer's projected units, meters) beyond which a QGIS
# nearest-neighbor match is considered "no roadway found" rather than used.
QGIS_FALLBACK_MAX_DISTANCE_METERS = 200
