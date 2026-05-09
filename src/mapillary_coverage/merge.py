from __future__ import annotations

from datetime import datetime
import glob
import gc
import logging
import os
from pathlib import Path
from typing import Any, Callable

import geopandas as gpd
import pandas as pd
from shapely.geometry import box
from tqdm import tqdm

from mapillary_coverage.bundeslaender import filter_mapping_by_bundeslaender
from mapillary_coverage.osm import load_osm_highways_pbf
from mapillary_coverage.settings import get_settings


MessageEmitter = Callable[[str], None]


def _emit(message: str, emit: MessageEmitter | None) -> None:
    if emit is not None:
        emit(message)


def _log(
    message: str,
    *,
    logger: logging.Logger | None = None,
    level: str = "info",
    emit: MessageEmitter | None = print,
) -> None:
    if logger is not None:
        getattr(logger, level)(message)
        return
    _emit(message, emit)


def _resolve_configs(
    geofabrik_config: dict[str, Any] | None = None,
    processing_config: dict[str, Any] | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    settings = get_settings()
    return (
        geofabrik_config or settings.legacy_geofabrik_config,
        processing_config or settings.legacy_processing_config,
    )


def extract_bundesland_code(filename: str) -> str | None:
    parts = os.path.basename(filename).split("_")
    for part in parts:
        if part.startswith("DE-") and len(part) == 5:
            return part
    return None


def discover_buffered_mapillary_files(
    processing_config: dict[str, Any] | None = None,
    selected_bundeslaender: list[str] | tuple[str, ...] | None = None,
) -> dict[str, str]:
    _, resolved_processing = _resolve_configs(processing_config=processing_config)
    pattern = str(Path(resolved_processing["ml_output_folder"]) / "mapillary_coverage_DE-*_buffered_latest.parquet")
    buffered_files = glob.glob(pattern)

    bundeslaender: dict[str, str] = {}
    for file_path in buffered_files:
        bundesland = extract_bundesland_code(file_path)
        if bundesland:
            bundeslaender[bundesland] = file_path
    return filter_mapping_by_bundeslaender(bundeslaender, selected_bundeslaender)


def discover_osm_bundesland_files(
    geofabrik_config: dict[str, Any] | None = None,
    selected_bundeslaender: list[str] | tuple[str, ...] | None = None,
) -> dict[str, str]:
    resolved_geofabrik, _ = _resolve_configs(geofabrik_config=geofabrik_config)
    pattern = str(Path(resolved_geofabrik["processed_folder"]) / "processed_highways_DE-*_latest.pbf")
    osm_files = glob.glob(pattern)

    bundeslaender: dict[str, str] = {}
    for file_path in osm_files:
        bundesland = extract_bundesland_code(file_path)
        if bundesland:
            bundeslaender[bundesland] = file_path
    return filter_mapping_by_bundeslaender(bundeslaender, selected_bundeslaender)


def select_bundeslaender_to_process(
    bundeslaender: dict[str, str],
    selected_bundeslaender: list[str] | tuple[str, ...] | None = None,
) -> list[str]:
    if selected_bundeslaender:
        return sorted([code for code in selected_bundeslaender if code in bundeslaender])
    return sorted(bundeslaender.keys())


def should_process_coverage(
    bundesland: str,
    output_folder: str,
    max_age_days: int | None = None,
    *,
    processing_config: dict[str, Any] | None = None,
    now: datetime | None = None,
    emit: MessageEmitter | None = None,
) -> bool:
    _, resolved_processing = _resolve_configs(processing_config=processing_config)
    if max_age_days is None:
        max_age_days = resolved_processing.get("max_file_age_days", 4)

    pano_file = Path(output_folder) / f"{bundesland}_osm-highways_mp_pano_coverage_latest.parquet"
    regular_file = Path(output_folder) / f"{bundesland}_osm-highways_mp_regular_coverage_latest.parquet"

    if not pano_file.exists() or not regular_file.exists():
        missing: list[str] = []
        if not pano_file.exists():
            missing.append("pano")
        if not regular_file.exists():
            missing.append("regular")
        _emit(f"  ℹ️  Fehlende Dateien für {bundesland} ({', '.join(missing)}) → Berechnung nötig", emit)
        return True

    try:
        oldest_mtime = min(pano_file.stat().st_mtime, regular_file.stat().st_mtime)
        current_time = now.timestamp() if now else datetime.now().timestamp()
        file_age_days = (current_time - oldest_mtime) / 86400
        if file_age_days >= max_age_days:
            _emit(f"  ℹ️  Coverage für {bundesland} ist {file_age_days:.1f} Tage alt → Erneuerung nötig", emit)
            return True
        _emit(f"  ✓ Coverage für {bundesland} ist {file_age_days:.1f} Tage alt → aktuell genug", emit)
        return False
    except Exception as error:
        _emit(f"  ⚠️  Fehler beim Prüfen der Dateien: {error} → Berechnung wird durchgeführt", emit)
        return True


def spatial_filter(gdf: gpd.GeoDataFrame, geom: Any) -> gpd.GeoDataFrame:
    if gdf.empty:
        return gdf
    idx = gdf.sindex.query(geom, predicate="intersects")
    return gdf.iloc[idx]


def _materialize_coverage_parts(
    clipped_parts: list[gpd.GeoDataFrame],
    temp_files: list[str],
    *,
    crs: Any,
) -> list[gpd.GeoDataFrame]:
    all_parts: list[gpd.GeoDataFrame] = []
    if clipped_parts:
        all_parts.append(gpd.GeoDataFrame(pd.concat(clipped_parts, ignore_index=True), crs=crs))
    for temp_file in temp_files:
        all_parts.append(gpd.read_parquet(temp_file))
        os.remove(temp_file)
    return all_parts


def _compute_coverage_variant(
    mapillary_variant: gpd.GeoDataFrame,
    osm_bundesland: gpd.GeoDataFrame,
    *,
    bundesland_code: str,
    variant_name: str,
    output_folder: str,
    write_chunk_size: int,
    logger: logging.Logger | None = None,
    emit: MessageEmitter | None = print,
) -> dict[str, Any]:
    variant_title = "Pano" if variant_name == "pano" else "Regular"
    _log(
        f"  [4/6] Berechne {variant_title} Coverage (Chunk-Size: {write_chunk_size:,})..."
        if variant_name == "regular"
        else f"  [3/6] Berechne {variant_title} Coverage (Chunk-Size: {write_chunk_size:,})...",
        logger=logger,
        emit=emit,
    )

    clipped_parts: list[gpd.GeoDataFrame] = []
    temp_files: list[str] = []
    total_roads = len(osm_bundesland)

    for road_idx, (_, road) in enumerate(
        tqdm(osm_bundesland.iterrows(), total=total_roads, desc=f"{bundesland_code} {variant_title}", leave=False),
        1,
    ):
        bbox = box(*road.geometry.bounds)
        filtered = spatial_filter(mapillary_variant, bbox)
        if not filtered.empty:
            clipped = gpd.clip(gpd.GeoDataFrame([road], crs=osm_bundesland.crs), filtered)
            if not clipped.empty:
                clipped_parts.append(clipped)

        if road_idx % write_chunk_size == 0 and clipped_parts:
            chunk_gdf = gpd.GeoDataFrame(pd.concat(clipped_parts, ignore_index=True), crs=osm_bundesland.crs)
            temp_file = f"{output_folder}/.temp_{bundesland_code}_{variant_name}_chunk_{road_idx}.parquet"
            chunk_gdf.to_parquet(temp_file)
            temp_files.append(temp_file)
            _log(
                f"    Chunk {road_idx:,}/{total_roads:,} → temp file ({len(chunk_gdf):,} Straßen)",
                logger=logger,
                level="debug",
                emit=emit,
            )
            del chunk_gdf
            clipped_parts = []
            gc.collect()

    all_parts = _materialize_coverage_parts(clipped_parts, temp_files, crs=osm_bundesland.crs)
    if not all_parts:
        _log(f"        → 0 Straßen mit {variant_title}-Abdeckung", logger=logger, emit=emit)
        gc.collect()
        return {"count": 0, "output_path": None}

    gdf_variant = gpd.GeoDataFrame(pd.concat(all_parts, ignore_index=True), crs=osm_bundesland.crs)
    gdf_variant["length_m_after_clip"] = gdf_variant.geometry.length
    gdf_variant["mp_coverage_ratio"] = gdf_variant["length_m_after_clip"] / gdf_variant["length_m_before_clip"]
    gdf_variant = gdf_variant[
        ["osm_id", "highway", "mp_coverage_ratio", "length_m_before_clip", "length_m_after_clip", "geometry"]
    ]
    output_path = f"{output_folder}/{bundesland_code}_osm-highways_mp_{variant_name}_coverage_latest.parquet"
    gdf_variant.to_parquet(output_path)
    _log(
        f"        → {len(gdf_variant):,} Straßen mit {variant_title}-Abdeckung → {output_path}",
        logger=logger,
        emit=emit,
    )
    count = len(gdf_variant)
    del gdf_variant, all_parts
    gc.collect()
    return {"count": count, "output_path": output_path}


def run_merge_for_bundesland(
    bundesland_code: str,
    *,
    mapillary_file: str,
    osm_pbf_file: str,
    output_folder: str,
    write_chunk_size: int = 50000,
    max_roads: int | None = None,
    logger: logging.Logger | None = None,
    emit: MessageEmitter | None = print,
) -> dict[str, Any]:
    _log(f"  [1/6] Lade Mapillary Coverage für {bundesland_code}...", logger=logger, emit=emit)
    mapillary_coverage = gpd.read_parquet(mapillary_file, columns=["geometry", "is_pano"])
    mapillary_coverage = mapillary_coverage.explode(index_parts=False, ignore_index=True)
    mapillary_pano = mapillary_coverage[mapillary_coverage.is_pano == True].copy()
    mapillary_regular = mapillary_coverage[mapillary_coverage.is_pano == False].copy()
    del mapillary_coverage
    gc.collect()

    _log(f"        → Pano: {len(mapillary_pano):,} Polygone", logger=logger, emit=emit)
    _log(f"        → Regular: {len(mapillary_regular):,} Polygone", logger=logger, emit=emit)

    _log(f"  [2/6] Lade OSM-Highways für {bundesland_code} aus PBF...", logger=logger, emit=emit)
    osm_bundesland = load_osm_highways_pbf(osm_pbf_file)
    osm_bundesland = osm_bundesland.to_crs(25832)
    osm_bundesland["length_m_before_clip"] = osm_bundesland.geometry.length
    osm_bundesland = osm_bundesland[["osm_id", "highway", "geometry", "length_m_before_clip"]].copy()
    if max_roads is not None:
        osm_bundesland = osm_bundesland.head(max_roads).copy()
        _log(f"        → Road-Limit aktiv: {len(osm_bundesland):,} Straßen", logger=logger, emit=emit)

    total_roads = len(osm_bundesland)
    _log(f"        → {total_roads:,} Straßen geladen", logger=logger, emit=emit)
    if osm_bundesland.empty:
        _log(f"        ⚠️  Keine Straßen in {bundesland_code}, überspringe...", logger=logger, level="warning", emit=emit)
        del mapillary_pano, mapillary_regular, osm_bundesland
        gc.collect()
        return {"bundesland": bundesland_code, "status": "empty", "pano_count": 0, "regular_count": 0}

    try:
        pano_result = _compute_coverage_variant(
            mapillary_pano,
            osm_bundesland,
            bundesland_code=bundesland_code,
            variant_name="pano",
            output_folder=output_folder,
            write_chunk_size=write_chunk_size,
            logger=logger,
            emit=emit,
        )
        regular_result = _compute_coverage_variant(
            mapillary_regular,
            osm_bundesland,
            bundesland_code=bundesland_code,
            variant_name="regular",
            output_folder=output_folder,
            write_chunk_size=write_chunk_size,
            logger=logger,
            emit=emit,
        )
        _log(f"  ✅ {bundesland_code} erfolgreich verarbeitet!", logger=logger, emit=emit)
        _log("  [5/6] RAM Cleanup...", logger=logger, emit=emit)
        return {
            "bundesland": bundesland_code,
            "status": "success",
            "pano_count": pano_result["count"],
            "regular_count": regular_result["count"],
            "pano_output": pano_result["output_path"],
            "regular_output": regular_result["output_path"],
            "roads_processed": total_roads,
        }
    finally:
        _log("  [6/6] Speicher freigeben...", logger=logger, emit=emit)
        try:
            del mapillary_pano, mapillary_regular, osm_bundesland
        except Exception:
            pass
        gc.collect()
        gc.collect()
        _log("  💾 RAM freigegeben", logger=logger, emit=emit)


def run_merge_coverage_dry_run(
    *,
    geofabrik_config: dict[str, Any] | None = None,
    processing_config: dict[str, Any] | None = None,
    selected_bundeslaender: list[str] | tuple[str, ...] | None = None,
    emit: MessageEmitter | None = print,
) -> dict[str, Any]:
    resolved_geofabrik, resolved_processing = _resolve_configs(
        geofabrik_config=geofabrik_config,
        processing_config=processing_config,
    )
    output_folder = resolved_processing["output_folder"]

    mapillary_files = discover_buffered_mapillary_files(
        processing_config=resolved_processing,
        selected_bundeslaender=selected_bundeslaender,
    )
    osm_files = discover_osm_bundesland_files(
        geofabrik_config=resolved_geofabrik,
        selected_bundeslaender=selected_bundeslaender,
    )
    bundeslaender_to_process = select_bundeslaender_to_process(mapillary_files, selected_bundeslaender)

    planned: list[str] = []
    skipped_current: list[str] = []
    missing_osm: list[str] = []

    _emit(f"\n{'=' * 70}", emit)
    _emit("MERGE-COVERAGE DRY-RUN", emit)
    _emit(f"{'=' * 70}", emit)
    _emit(f"Mapillary buffered Dateien: {len(mapillary_files)}", emit)
    _emit(f"OSM PBF-Dateien: {len(osm_files)}", emit)
    _emit(f"Ausgewählte Bundesländer im Lauf: {len(bundeslaender_to_process)}", emit)

    for bundesland_code in bundeslaender_to_process:
        _emit(f"\n{'─' * 70}", emit)
        _emit(f"Bundesland: {bundesland_code}", emit)
        _emit(f"{'─' * 70}", emit)
        if bundesland_code not in osm_files:
            missing_osm.append(bundesland_code)
            _emit(f"  ⚠️  Keine OSM-Daten für {bundesland_code}, würde übersprungen", emit)
            continue

        needs_processing = should_process_coverage(
            bundesland_code,
            output_folder,
            processing_config=resolved_processing,
            emit=emit,
        )
        if needs_processing:
            planned.append(bundesland_code)
            _emit(f"  🧪 Dry-run: {bundesland_code} würde berechnet", emit)
        else:
            skipped_current.append(bundesland_code)
            _emit(f"  🧪 Dry-run: {bundesland_code} würde übersprungen", emit)

    summary = {
        "dry_run": True,
        "planned": planned,
        "skipped_current": skipped_current,
        "missing_osm": missing_osm,
        "bundeslaender": bundeslaender_to_process,
        "mapillary_files": mapillary_files,
        "osm_files": osm_files,
    }
    _emit(f"\n{'=' * 70}", emit)
    _emit("DRY-RUN ZUSAMMENFASSUNG", emit)
    _emit(f"{'=' * 70}", emit)
    _emit(f"🧪 Geplante Berechnungen: {len(planned)}/{len(bundeslaender_to_process)}", emit)
    if planned:
        _emit(f"   {', '.join(planned)}", emit)
    _emit(f"🧪 Aktuell genug: {len(skipped_current)}/{len(bundeslaender_to_process)}", emit)
    if skipped_current:
        _emit(f"   {', '.join(skipped_current)}", emit)
    _emit(f"⚠️  Ohne OSM-Datei: {len(missing_osm)}/{len(bundeslaender_to_process)}", emit)
    if missing_osm:
        _emit(f"   {', '.join(missing_osm)}", emit)
    return summary


def run_merge_coverage_pipeline(
    *,
    geofabrik_config: dict[str, Any] | None = None,
    processing_config: dict[str, Any] | None = None,
    selected_bundeslaender: list[str] | tuple[str, ...] | None = None,
    output_folder: str | None = None,
    write_chunk_size: int = 50000,
    max_roads: int | None = None,
    dry_run: bool = False,
    logger: logging.Logger | None = None,
    emit: MessageEmitter | None = print,
) -> dict[str, Any]:
    resolved_geofabrik, resolved_processing = _resolve_configs(
        geofabrik_config=geofabrik_config,
        processing_config=processing_config,
    )
    effective_output_folder = output_folder or resolved_processing["output_folder"]
    Path(effective_output_folder).mkdir(parents=True, exist_ok=True)

    if dry_run:
        return run_merge_coverage_dry_run(
            geofabrik_config=resolved_geofabrik,
            processing_config={**resolved_processing, "output_folder": effective_output_folder},
            selected_bundeslaender=selected_bundeslaender,
            emit=emit,
        )

    mapillary_files = discover_buffered_mapillary_files(
        processing_config=resolved_processing,
        selected_bundeslaender=selected_bundeslaender,
    )
    osm_files = discover_osm_bundesland_files(
        geofabrik_config=resolved_geofabrik,
        selected_bundeslaender=selected_bundeslaender,
    )
    bundeslaender_to_process = select_bundeslaender_to_process(mapillary_files, selected_bundeslaender)

    results: list[dict[str, Any]] = []
    skipped_current: list[str] = []
    missing_osm: list[str] = []
    failed: list[str] = []

    total_bundeslaender = len(bundeslaender_to_process)
    for idx, bundesland_code in enumerate(bundeslaender_to_process, 1):
        _log(f"\n{'=' * 70}", logger=logger, emit=emit)
        _log(f"🏛️  Bundesland {idx}/{total_bundeslaender}: {bundesland_code}", logger=logger, emit=emit)
        _log(f"{'=' * 70}", logger=logger, emit=emit)

        if bundesland_code not in osm_files:
            missing_osm.append(bundesland_code)
            _log(f"⚠️  Keine OSM-Daten für {bundesland_code}, überspringe...", logger=logger, level="warning", emit=emit)
            continue

        if not should_process_coverage(
            bundesland_code,
            effective_output_folder,
            processing_config=resolved_processing,
            emit=None if logger else emit,
        ):
            skipped_current.append(bundesland_code)
            _log(f"  ⏩ Überspringe {bundesland_code}, Coverage ist aktuell genug", logger=logger, emit=emit)
            continue

        try:
            result = run_merge_for_bundesland(
                bundesland_code,
                mapillary_file=mapillary_files[bundesland_code],
                osm_pbf_file=osm_files[bundesland_code],
                output_folder=effective_output_folder,
                write_chunk_size=write_chunk_size,
                max_roads=max_roads,
                logger=logger,
                emit=emit,
            )
            results.append(result)
        except Exception as error:
            failed.append(bundesland_code)
            _log(f"  ❌ Fehler bei {bundesland_code}: {error}", logger=logger, level="error", emit=emit)
            if logger is not None:
                import traceback

                logger.error(traceback.format_exc())

    _log(f"\n{'=' * 70}", logger=logger, emit=emit)
    _log("✅ FERTIG! Merge Coverage abgeschlossen.", logger=logger, emit=emit)
    _log(f"   Ergebnisse in: {effective_output_folder}", logger=logger, emit=emit)
    _log(f"{'=' * 70}", logger=logger, emit=emit)
    return {
        "dry_run": False,
        "results": results,
        "skipped_current": skipped_current,
        "missing_osm": missing_osm,
        "failed": failed,
        "output_folder": effective_output_folder,
        "bundeslaender": bundeslaender_to_process,
    }