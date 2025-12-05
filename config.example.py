# Mapillary Coverage Analysis Configuration
# This file contains all configuration settings used across the notebooks

# Mapillary API Configuration
MAPILLARY_ACCESS_TOKEN = "MLY|XYXYXYXYXYX"  # Replace with your actual token

# Geofabrik OSM Data Configuration
GEOFABRIK_PBF_URL = "https://download.geofabrik.de/europe/germany-latest.osm.pbf"  # Change this to switch regions
GEOFABRIK_DOWNLOAD_FOLDER = "osm_geofabrik_pbf"
GEOFABRIK_PROCESSED_FOLDER = "processed_osm_files"

# Bundesländer Selection
# List of German federal states to process. 
# Use None or empty list [] to process all 16 Bundesländer.
# Examples: ["DE-BE"] for Berlin only, ["DE-BE", "DE-BB"] for Berlin and Brandenburg
# Available: DE-BW, DE-BY, DE-BE, DE-BB, DE-HB, DE-HH, DE-HE, DE-MV, DE-NI, DE-NW, DE-RP, DE-SL, DE-SN, DE-ST, DE-SH, DE-TH
BUNDESLAENDER = None  # Process all by default

# File Processing Configuration
MIN_CAPTURE_DATE = "2023-01-01"  # YYYY-MM-DD
BUFFER_DISTANCE = 10  # meters
MP_COVERAGE_RATIO_THRESHOLD = 0.6 # 60% coverage
OUTPUT_FOLDER = "output"
ML_OUTPUT_FOLDER = "ml_output"
PBF_TO_PARQUET = "ogr2ogr" #["geopandas","ogr2ogr"]

# Tile Configuration (for Mapillary coverage)
TILE_CACHE_FOLDER = "prep/tile_cache"
#TILE_ZOOM_LEVEL = 14  # only 14 works anyway

# Convenience dictionaries for easy access
GEOFABRIK_CONFIG = {
    'pbf_url': GEOFABRIK_PBF_URL,
    'download_folder': GEOFABRIK_DOWNLOAD_FOLDER,
    'processed_folder': GEOFABRIK_PROCESSED_FOLDER,
    'bundeslaender': BUNDESLAENDER
}

PROCESSING_CONFIG = {
    'min_capture_date': MIN_CAPTURE_DATE,
    'buffer_distance': BUFFER_DISTANCE,
    'mp_coverage_ratio_threshold': MP_COVERAGE_RATIO_THRESHOLD,
    'output_folder': OUTPUT_FOLDER,
    'ml_output_folder': ML_OUTPUT_FOLDER,
    'pbf_to_parquet': PBF_TO_PARQUET
}

MAPILLARY_CONFIG = {
    'access_token': MAPILLARY_ACCESS_TOKEN
}

TILES_CONFIG = {
    'cache_folder': TILE_CACHE_FOLDER,
#    'zoom_level': TILE_ZOOM_LEVEL
}
