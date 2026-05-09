from __future__ import annotations


ALL_BUNDESLAND_URLS: dict[str, str] = {
    "DE-BW": "https://download.geofabrik.de/europe/germany/baden-wuerttemberg-latest.osm.pbf",
    "DE-BY": "https://download.geofabrik.de/europe/germany/bayern-latest.osm.pbf",
    "DE-BE": "https://download.geofabrik.de/europe/germany/berlin-latest.osm.pbf",
    "DE-BB": "https://download.geofabrik.de/europe/germany/brandenburg-latest.osm.pbf",
    "DE-HB": "https://download.geofabrik.de/europe/germany/bremen-latest.osm.pbf",
    "DE-HH": "https://download.geofabrik.de/europe/germany/hamburg-latest.osm.pbf",
    "DE-HE": "https://download.geofabrik.de/europe/germany/hessen-latest.osm.pbf",
    "DE-MV": "https://download.geofabrik.de/europe/germany/mecklenburg-vorpommern-latest.osm.pbf",
    "DE-NI": "https://download.geofabrik.de/europe/germany/niedersachsen-latest.osm.pbf",
    "DE-NW": "https://download.geofabrik.de/europe/germany/nordrhein-westfalen-latest.osm.pbf",
    "DE-RP": "https://download.geofabrik.de/europe/germany/rheinland-pfalz-latest.osm.pbf",
    "DE-SL": "https://download.geofabrik.de/europe/germany/saarland-latest.osm.pbf",
    "DE-SN": "https://download.geofabrik.de/europe/germany/sachsen-latest.osm.pbf",
    "DE-ST": "https://download.geofabrik.de/europe/germany/sachsen-anhalt-latest.osm.pbf",
    "DE-SH": "https://download.geofabrik.de/europe/germany/schleswig-holstein-latest.osm.pbf",
    "DE-TH": "https://download.geofabrik.de/europe/germany/thueringen-latest.osm.pbf",
}


def normalize_selected_bundeslaender(selected_bundeslaender: list[str] | tuple[str, ...] | None) -> list[str] | None:
    if not selected_bundeslaender:
        return None
    return [str(code) for code in selected_bundeslaender]


def filter_mapping_by_bundeslaender(
    mapping: dict[str, str],
    selected_bundeslaender: list[str] | tuple[str, ...] | None,
) -> dict[str, str]:
    normalized_selection = normalize_selected_bundeslaender(selected_bundeslaender)
    if not normalized_selection:
        return dict(mapping)
    return {code: value for code, value in mapping.items() if code in normalized_selection}


def get_bundesland_urls(selected_bundeslaender: list[str] | tuple[str, ...] | None = None) -> dict[str, str]:
    return filter_mapping_by_bundeslaender(ALL_BUNDESLAND_URLS, selected_bundeslaender)