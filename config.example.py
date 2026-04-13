# Mapillary Coverage Analysis Configuration
# This file contains all configuration settings used across the notebooks

from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from dateutil.relativedelta import relativedelta
from dateutil import parser as dateutil_parser

# Mapillary API Configuration
MAPILLARY_ACCESS_TOKEN = "MLY|XYXYXYXYXYX"  # Replace with your actual token

# Geofabrik OSM Data Configuration
GEOFABRIK_DOWNLOAD_FOLDER = "osm_geofabrik_pbf"
GEOFABRIK_PROCESSED_FOLDER = "processed_osm_files"

# Bundesländer Selection
# List of German federal states to process.
# Use None or empty list [] to process all 16 Bundesländer.
# Examples: ["DE-BE"] for Berlin only, ["DE-BE", "DE-BB"] for Berlin and Brandenburg
# Available: DE-BW, DE-BY, DE-BE, DE-BB, DE-HB, DE-HH, DE-HE, DE-MV, DE-NI, DE-NW, DE-RP, DE-SL, DE-SN, DE-ST, DE-SH, DE-TH
BUNDESLAENDER = None  # Process all by default
# BUNDESLAENDER = ["DE-HB"]

# File Processing Configuration
# Imagery "freshness": only sequences captured on/after this instant are kept.
# Computed at run time as Berlin start-of-day minus FRESHNESS_LOOKBACK_MONTHS (2.5 years = 30 months).
FRESHNESS_TIMEZONE = "Europe/Berlin"
FRESHNESS_LOOKBACK_MONTHS = 30  # 2.5 years
BUFFER_DISTANCE = 10  # meters
MP_COVERAGE_RATIO_THRESHOLD = 0.6 # 60% coverage
MAX_FILE_AGE_DAYS = 4  # Maximum age in days before reprocessing files
OUTPUT_FOLDER = "output"
ML_OUTPUT_FOLDER = "ml_output"

# Tile Configuration (for Mapillary coverage)
TILE_CACHE_FOLDER = "prep/tile_cache"

# Convenience dictionaries for easy access
GEOFABRIK_CONFIG = {
    'download_folder': GEOFABRIK_DOWNLOAD_FOLDER,
    'processed_folder': GEOFABRIK_PROCESSED_FOLDER,
    'bundeslaender': BUNDESLAENDER
}

PROCESSING_CONFIG = {
    'freshness_timezone': FRESHNESS_TIMEZONE,
    'freshness_lookback_months': FRESHNESS_LOOKBACK_MONTHS,
    'buffer_distance': BUFFER_DISTANCE,
    'mp_coverage_ratio_threshold': MP_COVERAGE_RATIO_THRESHOLD,
    'max_file_age_days': MAX_FILE_AGE_DAYS,
    'output_folder': OUTPUT_FOLDER,
    'ml_output_folder': ML_OUTPUT_FOLDER
}

MAPILLARY_CONFIG = {
    'access_token': MAPILLARY_ACCESS_TOKEN
}

TILES_CONFIG = {
    'cache_folder': TILE_CACHE_FOLDER
}


def compute_mapillary_freshness_times(processing_config=None):
    """
    Freshness window: imagery captured on/after (Berlin local midnight of run day
    minus freshness_lookback_months), compared to UTC capture timestamps using
    the same instant (via astimezone UTC).
    """
    pc = processing_config or PROCESSING_CONFIG
    tz = ZoneInfo(pc["freshness_timezone"])
    now = datetime.now(tz)
    run_day_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    months = int(pc["freshness_lookback_months"])
    cutoff_berlin = run_day_start - relativedelta(months=months)
    cutoff_utc = cutoff_berlin.astimezone(timezone.utc)
    return run_day_start, cutoff_berlin, cutoff_utc


def datetime_iso_to_berlin(iso_str, freshness_timezone=None):
    """Parse an ISO datetime string and return ISO format in Europe/Berlin."""
    tz_name = freshness_timezone or PROCESSING_CONFIG["freshness_timezone"]
    tz = ZoneInfo(tz_name)
    dt = dateutil_parser.isoparse(iso_str)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(tz).isoformat()
