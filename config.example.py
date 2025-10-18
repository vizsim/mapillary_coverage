# Mapillary Coverage Analysis Configuration
# This file contains all configuration settings used across the notebooks

# Mapillary API Configuration
MAPILLARY_ACCESS_TOKEN = "MLY|XYXYXYXYXYX"  # Replace with your actual token

# Geofabrik OSM Data Configuration
GEOFABRIK_PBF_URL = "https://download.geofabrik.de/europe/germany-latest.osm.pbf"  # Change this to switch regions
GEOFABRIK_DOWNLOAD_FOLDER = "osm_geofabrik_pbf"
GEOFABRIK_PROCESSED_FOLDER = "processed_osm_files"

# File Processing Configuration
BUFFER_DISTANCE = 10  # meters
OUTPUT_FOLDER = "output"
ML_OUTPUT_FOLDER = "ml_output"

# Tile Configuration (for Mapillary coverage)
TILE_CACHE_FOLDER = "prep/tile_cache"
TILE_ZOOM_LEVEL = 14

# Convenience dictionaries for easy access
GEOFABRIK_CONFIG = {
    'pbf_url': GEOFABRIK_PBF_URL,
    'download_folder': GEOFABRIK_DOWNLOAD_FOLDER,
    'processed_folder': GEOFABRIK_PROCESSED_FOLDER
}

PROCESSING_CONFIG = {
    'buffer_distance': BUFFER_DISTANCE,
    'output_folder': OUTPUT_FOLDER,
    'ml_output_folder': ML_OUTPUT_FOLDER
}

MAPILLARY_CONFIG = {
    'access_token': MAPILLARY_ACCESS_TOKEN
}

TILES_CONFIG = {
    'cache_folder': TILE_CACHE_FOLDER,
    'zoom_level': TILE_ZOOM_LEVEL
}
