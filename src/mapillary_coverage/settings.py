from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
import os
from pathlib import Path
from typing import Any
import tomllib


DEFAULT_CONFIG_DIRNAME = "config"
DEFAULT_CONFIG_FILENAME = "default.toml"
LOCAL_CONFIG_FILENAME = "local.toml"


@dataclass(frozen=True)
class GeofabrikSettings:
    download_folder: str
    processed_folder: str
    bundeslaender: list[str] | None = None

    def to_dict(self) -> dict[str, Any]:
        data: dict[str, Any] = {
            "download_folder": self.download_folder,
            "processed_folder": self.processed_folder,
        }
        if self.bundeslaender is not None:
            data["bundeslaender"] = self.bundeslaender
        return data


@dataclass(frozen=True)
class ProcessingSettings:
    freshness_timezone: str
    freshness_lookback_months: int
    buffer_distance: int
    mp_coverage_ratio_threshold: float
    max_file_age_days: int
    output_folder: str
    ml_output_folder: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "freshness_timezone": self.freshness_timezone,
            "freshness_lookback_months": self.freshness_lookback_months,
            "buffer_distance": self.buffer_distance,
            "mp_coverage_ratio_threshold": self.mp_coverage_ratio_threshold,
            "max_file_age_days": self.max_file_age_days,
            "output_folder": self.output_folder,
            "ml_output_folder": self.ml_output_folder,
        }


@dataclass(frozen=True)
class MapillarySettings:
    access_token: str

    def to_dict(self) -> dict[str, Any]:
        return {"access_token": self.access_token}


@dataclass(frozen=True)
class TilesSettings:
    cache_folder: str

    def to_dict(self) -> dict[str, Any]:
        return {"cache_folder": self.cache_folder}


@dataclass(frozen=True)
class ReferenceSettings:
    bundeslaender_geojson: str

    def to_dict(self) -> dict[str, Any]:
        return {"bundeslaender_geojson": self.bundeslaender_geojson}


@dataclass(frozen=True)
class Settings:
    geofabrik: GeofabrikSettings
    processing: ProcessingSettings
    mapillary: MapillarySettings
    tiles: TilesSettings
    reference: ReferenceSettings
    project_root: Path
    config_dir: Path

    def to_dict(self) -> dict[str, Any]:
        return {
            "geofabrik": self.geofabrik.to_dict(),
            "processing": self.processing.to_dict(),
            "mapillary": self.mapillary.to_dict(),
            "tiles": self.tiles.to_dict(),
            "reference": self.reference.to_dict(),
            "project_root": str(self.project_root),
            "config_dir": str(self.config_dir),
        }

    @property
    def legacy_geofabrik_config(self) -> dict[str, Any]:
        return self.geofabrik.to_dict()

    @property
    def legacy_processing_config(self) -> dict[str, Any]:
        return self.processing.to_dict()

    @property
    def legacy_mapillary_config(self) -> dict[str, Any]:
        return self.mapillary.to_dict()

    @property
    def legacy_tiles_config(self) -> dict[str, Any]:
        return self.tiles.to_dict()

    @property
    def legacy_reference_config(self) -> dict[str, Any]:
        return self.reference.to_dict()


def _project_root_from_here() -> Path:
    return Path(__file__).resolve().parents[2]


def _config_dir(project_root: Path) -> Path:
    return project_root / DEFAULT_CONFIG_DIRNAME


def _load_toml_file(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    with path.open("rb") as file_handle:
        return tomllib.load(file_handle)


def _deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    merged = dict(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _deep_merge(merged[key], value)
            continue
        merged[key] = value
    return merged


def _normalize_bundeslaender(value: Any) -> list[str] | None:
    if value in (None, []):
        return None
    return [str(entry) for entry in value]


def _apply_environment_overrides(data: dict[str, Any]) -> dict[str, Any]:
    mapillary = dict(data.get("mapillary", {}))
    access_token = os.getenv("MAPILLARY_ACCESS_TOKEN")
    if access_token:
        mapillary["access_token"] = access_token

    if mapillary:
        data = dict(data)
        data["mapillary"] = mapillary
    return data


def _build_settings(data: dict[str, Any], project_root: Path, config_dir: Path) -> Settings:
    geofabrik_data = data.get("geofabrik", {})
    processing_data = data.get("processing", {})
    mapillary_data = data.get("mapillary", {})
    tiles_data = data.get("tiles", {})
    reference_data = data.get("reference", {})

    return Settings(
        geofabrik=GeofabrikSettings(
            download_folder=str(geofabrik_data["download_folder"]),
            processed_folder=str(geofabrik_data["processed_folder"]),
            bundeslaender=_normalize_bundeslaender(geofabrik_data.get("bundeslaender")),
        ),
        processing=ProcessingSettings(
            freshness_timezone=str(processing_data["freshness_timezone"]),
            freshness_lookback_months=int(processing_data["freshness_lookback_months"]),
            buffer_distance=int(processing_data["buffer_distance"]),
            mp_coverage_ratio_threshold=float(processing_data["mp_coverage_ratio_threshold"]),
            max_file_age_days=int(processing_data["max_file_age_days"]),
            output_folder=str(processing_data["output_folder"]),
            ml_output_folder=str(processing_data["ml_output_folder"]),
        ),
        mapillary=MapillarySettings(
            access_token=str(mapillary_data.get("access_token", "")),
        ),
        tiles=TilesSettings(
            cache_folder=str(tiles_data["cache_folder"]),
        ),
        reference=ReferenceSettings(
            bundeslaender_geojson=str(reference_data["bundeslaender_geojson"]),
        ),
        project_root=project_root,
        config_dir=config_dir,
    )


@lru_cache(maxsize=8)
def get_settings(project_root: str | Path | None = None) -> Settings:
    resolved_root = Path(project_root).resolve() if project_root else _project_root_from_here()
    config_dir = _config_dir(resolved_root)

    default_data = _load_toml_file(config_dir / DEFAULT_CONFIG_FILENAME)
    local_data = _load_toml_file(config_dir / LOCAL_CONFIG_FILENAME)
    merged = _deep_merge(default_data, local_data)
    merged = _apply_environment_overrides(merged)

    return _build_settings(merged, resolved_root, config_dir)


def reload_settings(project_root: str | Path | None = None) -> Settings:
    get_settings.cache_clear()
    return get_settings(project_root=project_root)