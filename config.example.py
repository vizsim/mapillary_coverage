# Mapillary Coverage Analysis Configuration
# This file contains all configuration settings used across the notebooks

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
MIN_CAPTURE_DATE = "2023-01-01"  # YYYY-MM-DD
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
    'min_capture_date': MIN_CAPTURE_DATE,
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
