from __future__ import annotations

from datetime import datetime
import gc
import glob
import os
from pathlib import Path
from typing import Any, Callable

import geopandas as gpd
import pandas as pd

from mapillary_coverage.bundeslaender import filter_mapping_by_bundeslaender
from mapillary_coverage.settings import get_settings


MessageEmitter = Callable[[str], None]


def _emit(message: str, emit: MessageEmitter | None) -> None:
    if emit is not None:
        emit(message)


def _resolve_configs(
    geofabrik_config: dict[str, Any] | None = None,
    processing_config: dict[str, Any] | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    settings = get_settings()
    return (
        geofabrik_config or settings.legacy_geofabrik_config,
        processing_config or settings.legacy_processing_config,
    )


def should_process_buffer(
    bundesland: str,
    output_folder: str,
    max_age_days: int | None = None,
    *,
    processing_config: dict[str, Any] | None = None,
    now: datetime | None = None,
    emit: MessageEmitter | None = print,
) -> bool:
    _, resolved_processing = _resolve_configs(processing_config=processing_config)
    if max_age_days is None:
        max_age_days = resolved_processing.get("max_file_age_days", 4)

    output_file = Path(output_folder) / f"mapillary_coverage_{bundesland}_buffered_latest.parquet"
    if not output_file.exists():
        _emit(f"  ℹ️  Keine Buffer-Datei vorhanden für {bundesland} → Erstellung nötig", emit)
        return True

    try:
        current_time = now.timestamp() if now else datetime.now().timestamp()
        file_age_days = (current_time - output_file.stat().st_mtime) / 86400
        if file_age_days >= max_age_days:
            _emit(f"  ℹ️  Buffer für {bundesland} ist {file_age_days:.1f} Tage alt → Erneuerung nötig", emit)
            return True
        _emit(f"  ✓ Buffer für {bundesland} ist {file_age_days:.1f} Tage alt → aktuell genug", emit)
        return False
    except Exception as error:
        _emit(f"  ⚠️  Fehler beim Prüfen der Datei: {error} → Buffer-Erstellung wird durchgeführt", emit)
        return True


def discover_unbuffered_coverage_files(
    source_folder: str,
    selected_bundeslaender: list[str] | tuple[str, ...] | None = None,
) -> dict[str, list[str]]:
    parquet_files = glob.glob(f"{source_folder}/mapillary_coverage_DE-*_latest.parquet")
    bundesland_files: dict[str, list[str]] = {}
    for file_path in parquet_files:
        if "buffered" in os.path.basename(file_path):
            continue

        basename = os.path.basename(file_path)
        parts = basename.split("_")
        if len(parts) >= 3:
            bundesland = parts[2]
            bundesland_files.setdefault(bundesland, []).append(file_path)

    return filter_mapping_by_bundeslaender(bundesland_files, selected_bundeslaender)


def run_buffer_for_bundesland(
    bundesland: str,
    files: list[str],
    *,
    buffer_distance: int,
    output_folder: str,
    emit: MessageEmitter | None = print,
) -> dict[str, Any]:
    data: gpd.GeoDataFrame | None = None
    dfs: list[gpd.GeoDataFrame] | None = None
    try:
        _emit(f"\n{'=' * 60}", emit)
        _emit(f"Verarbeite Bundesland: {bundesland}", emit)
        _emit(f"Anzahl Dateien: {len(files)}", emit)
        _emit(f"{'=' * 60}", emit)

        _emit("  [1/5] Lade Daten...", emit)
        dfs = [gpd.read_parquet(file_path) for file_path in files]
        data = gpd.GeoDataFrame(pd.concat(dfs, ignore_index=True))
        del dfs
        dfs = None
        _emit(f"        → {len(data):,} Zeilen geladen", emit)

        _emit("  [2/5] Explode Geometrie...", emit)
        data = data.explode(index_parts=False, ignore_index=True)
        _emit(f"        → {len(data):,} Zeilen nach Explode", emit)

        _emit(f"  [3/5] Transformiere zu EPSG:25832 und erstelle {buffer_distance}m Buffer...", emit)
        data = data.to_crs(25832)
        data["geometry"] = data["geometry"].buffer(buffer_distance)

        _emit("  [4/5] Dissolve nach tile_x, tile_y, is_pano...", emit)
        data = data.dissolve(by=["tile_x", "tile_y", "is_pano"]).reset_index()
        data = data[["tile_x", "tile_y", "is_pano", "geometry"]]

        output_file = Path(output_folder) / f"mapillary_coverage_{bundesland}_buffered_latest.parquet"
        _emit(f"  [5/5] Speichere zu: {output_file}", emit)
        data.to_parquet(output_file)
        _emit(f"        → {len(data):,} Zeilen gespeichert", emit)
        _emit(f"  ✓ {bundesland} erfolgreich verarbeitet!", emit)
        return {
            "bundesland": bundesland,
            "status": "success",
            "input_files": len(files),
            "rows": len(data),
            "output_file": str(output_file),
        }
    finally:
        try:
            data = gpd.GeoDataFrame()
            del data
        except Exception:
            pass
        gc.collect()
        gc.collect()


def run_create_buffer_pipeline(
    *,
    geofabrik_config: dict[str, Any] | None = None,
    processing_config: dict[str, Any] | None = None,
    selected_bundeslaender: list[str] | tuple[str, ...] | None = None,
    source_folder: str | None = None,
    output_folder: str | None = None,
    dry_run: bool = False,
    emit: MessageEmitter | None = print,
) -> dict[str, Any]:
    resolved_geofabrik, resolved_processing = _resolve_configs(
        geofabrik_config=geofabrik_config,
        processing_config=processing_config,
    )
    selected_bundeslaender = selected_bundeslaender or resolved_geofabrik.get("bundeslaender")
    effective_source_folder = source_folder or resolved_processing["ml_output_folder"]
    effective_output_folder = output_folder or resolved_processing["ml_output_folder"]
    Path(effective_output_folder).mkdir(parents=True, exist_ok=True)

    bundesland_files = discover_unbuffered_coverage_files(
        effective_source_folder,
        selected_bundeslaender=selected_bundeslaender,
    )

    if selected_bundeslaender:
        _emit(
            f"🎯 Verarbeite {len(bundesland_files)} ausgewählte Bundesländer: {', '.join(selected_bundeslaender)}",
            emit,
        )
    else:
        _emit(f"📍 Verarbeite alle {len(bundesland_files)} Bundesländer", emit)

    for bundesland, files in bundesland_files.items():
        _emit(f"  {bundesland}: {len(files)} Datei(en)", emit)

    planned: list[str] = []
    skipped_current: list[str] = []
    results: list[dict[str, Any]] = []

    if dry_run:
        for bundesland in sorted(bundesland_files):
            if should_process_buffer(
                bundesland,
                effective_output_folder,
                processing_config=resolved_processing,
                emit=emit,
            ):
                planned.append(bundesland)
            else:
                skipped_current.append(bundesland)
        return {
            "dry_run": True,
            "bundesland_files": bundesland_files,
            "planned": planned,
            "skipped_current": skipped_current,
            "source_folder": effective_source_folder,
            "output_folder": effective_output_folder,
        }

    for bundesland, files in bundesland_files.items():
        if not should_process_buffer(
            bundesland,
            effective_output_folder,
            processing_config=resolved_processing,
            emit=emit,
        ):
            _emit(f"  ⏩ Überspringe {bundesland}, Buffer ist aktuell genug", emit)
            skipped_current.append(bundesland)
            continue

        result = run_buffer_for_bundesland(
            bundesland,
            files,
            buffer_distance=resolved_processing["buffer_distance"],
            output_folder=effective_output_folder,
            emit=emit,
        )
        results.append(result)

    _emit(f"\n{'=' * 60}", emit)
    _emit(f"FERTIG! Alle {len(bundesland_files)} Bundesländer verarbeitet.", emit)
    _emit(f"{'=' * 60}", emit)
    return {
        "dry_run": False,
        "bundesland_files": bundesland_files,
        "results": results,
        "skipped_current": skipped_current,
        "source_folder": effective_source_folder,
        "output_folder": effective_output_folder,
    }