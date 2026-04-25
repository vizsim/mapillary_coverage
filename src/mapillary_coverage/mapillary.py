from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
import json
import logging
import os
from pathlib import Path
import sys
import threading
import time
from typing import Any, Callable
from zoneinfo import ZoneInfo

from dateutil import parser as dateutil_parser
from dateutil.relativedelta import relativedelta
import geopandas as gpd
import mercantile
import pandas as pd
import requests
from requests.adapters import HTTPAdapter
from requests.exceptions import ConnectionError, ReadTimeout, SSLError, Timeout
from tqdm import tqdm
from urllib3.util.retry import Retry
from vt2geojson.tools import vt_bytes_to_geojson

from mapillary_coverage.settings import get_settings


MessageEmitter = Callable[[str], None]


def _emit(message: str, emit: MessageEmitter | None) -> None:
    if emit is not None:
        emit(message)


def _resolve_configs(
    processing_config: dict[str, Any] | None = None,
    mapillary_config: dict[str, Any] | None = None,
    tiles_config: dict[str, Any] | None = None,
    reference_config: dict[str, Any] | None = None,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any]]:
    settings = get_settings()
    return (
        processing_config or settings.legacy_processing_config,
        mapillary_config or settings.legacy_mapillary_config,
        tiles_config or settings.legacy_tiles_config,
        reference_config or settings.legacy_reference_config,
    )


def _tqdm_enabled_from_env() -> bool:
    return os.environ.get("TQDM_DISABLE", "0") != "1"


def compute_mapillary_freshness_times(processing_config: dict[str, Any]) -> tuple[datetime, datetime, datetime]:
    timezone_name = processing_config["freshness_timezone"]
    run_timezone = ZoneInfo(timezone_name)
    now = datetime.now(run_timezone)
    run_day_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    lookback_months = int(processing_config["freshness_lookback_months"])
    cutoff_berlin = run_day_start - relativedelta(months=lookback_months)
    cutoff_utc = cutoff_berlin.astimezone(timezone.utc)
    return run_day_start, cutoff_berlin, cutoff_utc


def datetime_iso_to_berlin(iso_string: str, freshness_timezone: str) -> str:
    dt = dateutil_parser.isoparse(iso_string)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(ZoneInfo(freshness_timezone)).isoformat()


def build_mapillary_logger(log_folder: str) -> tuple[logging.Logger, str]:
    os.makedirs(log_folder, exist_ok=True)
    log_file = os.path.join(log_folder, f"mapillary_download_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log")
    logger = logging.getLogger("mapillary_coverage.download")
    logger.setLevel(logging.INFO)
    logger.propagate = False
    if logger.hasHandlers():
        logger.handlers.clear()

    formatter = logging.Formatter("%(asctime)s - %(levelname)s - %(message)s")
    file_handler = logging.FileHandler(log_file, encoding="utf-8")
    file_handler.setFormatter(formatter)
    stream_handler = logging.StreamHandler(sys.stdout)
    stream_handler.setFormatter(formatter)
    logger.addHandler(file_handler)
    logger.addHandler(stream_handler)
    return logger, log_file


def load_tiles_from_json(bundesland_id: str, input_folder: str) -> list[mercantile.Tile]:
    path = os.path.join(input_folder, f"{bundesland_id}_tiles.json")
    with open(path, "r", encoding="utf-8") as file_handle:
        tile_list = json.load(file_handle)
    return [mercantile.Tile(**tile_data) for tile_data in tile_list]


def export_geodata(
    geodataframes: list[gpd.GeoDataFrame] | gpd.GeoDataFrame | pd.DataFrame | None,
    *,
    output_folder: str,
    base_name: str = "mapillary_coverage",
    region: str = "ger",
    logger: logging.Logger | None = None,
) -> str | None:
    if geodataframes is None:
        if logger is not None:
            logger.warning("No data to export.")
        return None

    if isinstance(geodataframes, (gpd.GeoDataFrame, pd.DataFrame)):
        if geodataframes.empty:
            if logger is not None:
                logger.warning("No data to export.")
            return None
        geodataframe = geodataframes
    else:
        if not geodataframes:
            if logger is not None:
                logger.warning("No data to export.")
            return None
        geodataframe = gpd.GeoDataFrame(pd.concat(geodataframes, ignore_index=True))

    os.makedirs(output_folder, exist_ok=True)
    current_timestamp = datetime.now(timezone.utc).isoformat()
    parquet_path = os.path.join(output_folder, f"{base_name}_{region}_latest.parquet")
    geodataframe.to_parquet(parquet_path, index=False)
    if logger is not None:
        logger.info(f"✔ Parquet saved to: {parquet_path}")
    return current_timestamp


def should_download_mapillary_output(
    bundesland_id: str,
    output_folder: str,
    max_age_days: int,
    *,
    now: datetime | None = None,
    logger: logging.Logger | None = None,
) -> tuple[bool, float | None]:
    parquet_path = os.path.join(output_folder, f"mapillary_coverage_{bundesland_id}_latest.parquet")
    if not os.path.exists(parquet_path):
        return True, None

    current_time = now.timestamp() if now else datetime.now().timestamp()
    file_mtime = os.path.getmtime(parquet_path)
    file_age_days = (current_time - file_mtime) / 86400
    if file_age_days < max_age_days:
        if logger is not None:
            logger.info(f"⏩ {bundesland_id}: Datei ist {file_age_days:.1f} Tage alt, überspringe Download")
        return False, file_mtime

    if logger is not None:
        logger.info(f"🔄 {bundesland_id}: Datei ist {file_age_days:.1f} Tage alt, lade neu")
    return True, file_mtime


def process_bundesland(
    bundesland_id: str,
    *,
    tile_cache_folder: str,
    output_folder: str,
    mapillary_access_token: str,
    max_workers: int = 3,
    limit_tiles: int | None = None,
    min_capture_dt_utc: datetime,
    logger: logging.Logger,
    tqdm_enabled: bool = True,
) -> str | None:
    logger.info(f"▶️ Starte Verarbeitung für {bundesland_id}...")

    tiles = load_tiles_from_json(bundesland_id, input_folder=tile_cache_folder)
    if limit_tiles is not None:
        tiles = tiles[:limit_tiles]

    total_tiles = len(tiles)
    logger.info(f"📊 {bundesland_id}: {total_tiles} Tiles zu verarbeiten")

    tile_layer = "sequence"
    tile_coverage = "mly1_computed_public"
    consecutive_parse_errors = 0
    max_consecutive_errors = 5
    processed_count = 0
    successful_count = 0

    retry_strategy = Retry(
        total=3,
        connect=3,
        read=3,
        status=3,
        backoff_factor=1.5,
        status_forcelist=[429, 500, 502, 503, 504],
        allowed_methods=["GET"],
        raise_on_status=False,
    )
    adapter = HTTPAdapter(
        max_retries=retry_strategy,
        pool_connections=max_workers * 2,
        pool_maxsize=max_workers * 4,
    )
    thread_local = threading.local()

    def get_session() -> requests.Session:
        session = getattr(thread_local, "session", None)
        if session is None:
            session = requests.Session()
            session.mount("https://", adapter)
            session.mount("http://", adapter)
            thread_local.session = session
        return session

    def tile_key(tile: mercantile.Tile) -> str:
        return f"{tile.z}/{tile.x}/{tile.y}"

    def is_name_resolution_error(error: Exception) -> bool:
        message = str(error)
        return (
            "NameResolutionError" in message
            or "Temporary failure in name resolution" in message
            or "Failed to resolve" in message
            or "gaierror" in message
        )

    def process_tile(tile: mercantile.Tile, max_retries: int = 3) -> tuple[str, gpd.GeoDataFrame | None]:
        nonlocal consecutive_parse_errors
        url = (
            f"https://tiles.mapillary.com/maps/vtp/{tile_coverage}/2/{tile.z}/{tile.x}/{tile.y}"
            f"?access_token={mapillary_access_token}"
        )

        for attempt in range(max_retries + 1):
            try:
                session = get_session()
                response = session.get(url, timeout=(10, 30))

                if response.status_code == 429:
                    if attempt < max_retries:
                        logger.warning(
                            f"⚠️ Rate Limit bei Tile {tile.x}/{tile.y} "
                            f"(Versuch {attempt + 1}/{max_retries + 1}). Pausiere 5 Minuten..."
                        )
                        time.sleep(300)
                        continue
                    logger.error(
                        f"❌ Tile {tile.x}/{tile.y} nach {max_retries + 1} Versuchen wegen Rate Limit fehlgeschlagen"
                    )
                    return "failed", None

                if response.status_code != 200:
                    if response.status_code >= 500 and attempt < max_retries:
                        logger.warning(
                            f"⚠️ HTTP {response.status_code} bei Tile {tile.x}/{tile.y} "
                            f"(Versuch {attempt + 1}/{max_retries + 1}). Retry in 60s..."
                        )
                        time.sleep(60)
                        continue
                    if response.status_code >= 500:
                        logger.error(f"❌ HTTP {response.status_code} bei Tile {tile.x}/{tile.y} nach allen Versuchen")
                        return "failed", None
                    logger.warning(f"⚠️ HTTP {response.status_code} bei Tile {tile.x}/{tile.y}")
                    return "empty", None

                geojson = vt_bytes_to_geojson(response.content, tile.x, tile.y, tile.z, layer=tile_layer)
                features = geojson.get("features", [])
                if not features:
                    return "empty", None

                tile_geodataframe = gpd.GeoDataFrame.from_features(features, crs="EPSG:4326")
                tile_geodataframe["captured_at"] = tile_geodataframe["captured_at"].apply(
                    lambda value: datetime.fromtimestamp(value / 1000, tz=timezone.utc)
                )
                tile_geodataframe = tile_geodataframe[tile_geodataframe["captured_at"] >= min_capture_dt_utc]
                if tile_geodataframe.empty:
                    return "empty", None

                tile_geodataframe["captured_at"] = tile_geodataframe["captured_at"].dt.strftime("%Y-%m-%d")
                tile_geodataframe["tile_x"] = tile.x
                tile_geodataframe["tile_y"] = tile.y
                consecutive_parse_errors = 0
                return "ok", tile_geodataframe
            except (ConnectionError, ReadTimeout, Timeout, SSLError) as error:
                wait_seconds = 300 if is_name_resolution_error(error) else 60
                if attempt < max_retries:
                    logger.warning(
                        f"⚠️ Netzwerkfehler bei Tile {tile.x}/{tile.y} "
                        f"(Versuch {attempt + 1}/{max_retries + 1}): {error}. "
                        f"Pausiere {wait_seconds}s..."
                    )
                    time.sleep(wait_seconds)
                    continue
                logger.error(
                    f"❌ Netzwerkfehler bei Tile {tile.x}/{tile.y} nach {max_retries + 1} Versuchen: {error}"
                )
                return "failed", None
            except Exception as error:
                error_message = str(error)
                if "Error parsing message" in error_message or "vector_tile" in error_message:
                    consecutive_parse_errors += 1
                    if consecutive_parse_errors >= max_consecutive_errors:
                        logger.error(
                            f"🛑 {max_consecutive_errors} aufeinanderfolgende Parsing-Fehler! API scheint blockiert zu sein."
                        )
                        logger.warning("⏸️  LANGE PAUSE: 30 Minuten warten...")
                        time.sleep(1800)
                        consecutive_parse_errors = 0
                        logger.info("▶️ Setze Verarbeitung fort nach langer Pause...")

                    if attempt < max_retries:
                        logger.warning(
                            f"⚠️ Parsing-Fehler bei Tile {tile.x}/{tile.y} "
                            f"(Versuch {attempt + 1}/{max_retries + 1}, konsekutiv: {consecutive_parse_errors}). "
                            f"Pausiere für 5 Minuten..."
                        )
                        time.sleep(300)
                        continue

                    logger.error(
                        f"❌ Tile {tile.x}/{tile.y} nach {max_retries + 1} Parsing-Versuchen fehlgeschlagen: {error_message}"
                    )
                    return "failed", None

                if attempt < max_retries:
                    logger.warning(
                        f"⚠️ Unbekannter Fehler bei Tile {tile.x}/{tile.y} "
                        f"(Versuch {attempt + 1}/{max_retries + 1}): {error_message}. Retry in 60s..."
                    )
                    time.sleep(60)
                    continue

                logger.error(f"❌ Fehler bei Tile {tile.x}/{tile.y}: {error_message}")
                return "failed", None

        return "failed", None

    def run_batch(
        tile_batch: list[mercantile.Tile],
        description: str,
    ) -> tuple[list[gpd.GeoDataFrame], list[mercantile.Tile], int, int]:
        local_geodataframes: list[gpd.GeoDataFrame] = []
        local_failed_tiles: list[mercantile.Tile] = []
        local_processed = 0
        local_successful = 0

        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = {executor.submit(process_tile, tile): tile for tile in tile_batch}
            for future in tqdm(as_completed(futures), total=len(futures), desc=description, disable=not tqdm_enabled):
                tile = futures[future]
                try:
                    status, result = future.result()
                    local_processed += 1
                    if status == "ok" and result is not None:
                        local_geodataframes.append(result)
                        local_successful += 1
                    elif status == "failed":
                        local_failed_tiles.append(tile)
                except Exception as error:
                    logger.error(f"⚠️ Unbekannter Fehler bei Future {tile_key(tile)}: {error}")
                    local_failed_tiles.append(tile)

        return local_geodataframes, local_failed_tiles, local_processed, local_successful

    bundesland_geodataframes: list[gpd.GeoDataFrame] = []
    round_geodataframes, failed_tiles, processed, successful = run_batch(tiles, f"🧩 {bundesland_id}")
    bundesland_geodataframes.extend(round_geodataframes)
    processed_count += processed
    successful_count += successful

    if failed_tiles:
        failed_tiles = list({tile_key(tile): tile for tile in failed_tiles}.values())
        logger.warning(
            f"🔁 {bundesland_id}: {len(failed_tiles)} fehlgeschlagene Tiles. Pausiere 5 Minuten vor Retry-Runde 1..."
        )
        time.sleep(300)
        round_geodataframes, failed_tiles, processed, successful = run_batch(
            failed_tiles,
            f"🔁 {bundesland_id} retry-1",
        )
        bundesland_geodataframes.extend(round_geodataframes)
        processed_count += processed
        successful_count += successful

    if failed_tiles:
        failed_tiles = list({tile_key(tile): tile for tile in failed_tiles}.values())
        logger.warning(
            f"🔁 {bundesland_id}: Noch {len(failed_tiles)} fehlgeschlagene Tiles. Pausiere 5 Minuten vor Retry-Runde 2..."
        )
        time.sleep(300)
        round_geodataframes, failed_tiles, processed, successful = run_batch(
            failed_tiles,
            f"🔁 {bundesland_id} retry-2",
        )
        bundesland_geodataframes.extend(round_geodataframes)
        processed_count += processed
        successful_count += successful

    logger.info(
        f"✅ {bundesland_id}: {processed_count} Tile-Versuche abgeschlossen "
        f"({successful_count} erfolgreich, {processed_count - successful_count} fehlgeschlagen/ohne Daten)"
    )
    if failed_tiles:
        logger.error(f"❌ {bundesland_id}: Nach finalen Retries bleiben {len(failed_tiles)} Tiles fehlgeschlagen.")

    if bundesland_geodataframes:
        timestamp = export_geodata(
            bundesland_geodataframes,
            output_folder=output_folder,
            region=bundesland_id,
            logger=logger,
        )
        return timestamp

    logger.warning(f"⚠️ Keine Daten für {bundesland_id}.")
    return None


def run_mapillary_download_pipeline(
    *,
    processing_config: dict[str, Any] | None = None,
    mapillary_config: dict[str, Any] | None = None,
    tiles_config: dict[str, Any] | None = None,
    selected_bundeslaender: list[str] | tuple[str, ...] | None = None,
    reference_config: dict[str, Any] | None = None,
    bundesland_cache_path: str | None = None,
    output_folder: str | None = None,
    metadata_output_folder: str | None = None,
    tile_cache_folder: str | None = None,
    max_workers: int = 3,
    limit_tiles: int | None = None,
    dry_run: bool = False,
    tqdm_enabled: bool | None = None,
    emit: MessageEmitter | None = print,
) -> dict[str, Any]:
    resolved_processing, resolved_mapillary, resolved_tiles, resolved_reference = _resolve_configs(
        processing_config=processing_config,
        mapillary_config=mapillary_config,
        tiles_config=tiles_config,
        reference_config=reference_config,
    )
    if not str(resolved_mapillary.get("access_token", "")).strip():
        raise ValueError(
            "Mapillary access token is missing. Set MAPILLARY_ACCESS_TOKEN or config/local.toml."
        )

    effective_output_folder = output_folder or resolved_processing["ml_output_folder"]
    effective_metadata_output_folder = metadata_output_folder or resolved_processing["output_folder"]
    effective_tile_cache_folder = tile_cache_folder or resolved_tiles["cache_folder"]
    effective_bundesland_cache_path = bundesland_cache_path or resolved_reference["bundeslaender_geojson"]
    tqdm_is_enabled = _tqdm_enabled_from_env() if tqdm_enabled is None else tqdm_enabled

    if not os.path.exists(effective_bundesland_cache_path):
        raise FileNotFoundError(f"Bundesland-GeoJSON fehlt: {effective_bundesland_cache_path}")

    bland = gpd.read_file(effective_bundesland_cache_path)
    if selected_bundeslaender:
        bland_filtered = bland[bland["id"].isin(selected_bundeslaender)]
    else:
        bland_filtered = bland

    run_day_start_berlin, freshness_cutoff_berlin, min_capture_dt_utc = compute_mapillary_freshness_times(
        resolved_processing
    )

    if dry_run:
        if selected_bundeslaender:
            _emit(
                f"🎯 Verarbeite {len(bland_filtered)} ausgewählte Bundesländer: {', '.join(selected_bundeslaender)}",
                emit,
            )
        else:
            _emit(f"📍 Verarbeite alle {len(bland_filtered)} Bundesländer", emit)
        _emit(
            "📅 Freshness-Filter: "
            f"Berlin Lauf-Tag-Start {run_day_start_berlin.isoformat()}, "
            f"Cutoff {freshness_cutoff_berlin.isoformat()} (Vergleich UTC: {min_capture_dt_utc.isoformat()})",
            emit,
        )

        planned: list[str] = []
        skipped_current: list[str] = []
        missing_tiles: list[str] = []
        for _, row in bland_filtered.iterrows():
            bundesland_id = row["id"]
            tile_json_path = os.path.join(effective_tile_cache_folder, f"{bundesland_id}_tiles.json")
            if not os.path.exists(tile_json_path):
                missing_tiles.append(bundesland_id)
                _emit(f"⏩ Überspringe {bundesland_id}, keine Tiles gefunden.", emit)
                continue

            should_process, _ = should_download_mapillary_output(
                bundesland_id,
                effective_output_folder,
                int(resolved_processing.get("max_file_age_days", 4)),
            )
            if should_process:
                planned.append(bundesland_id)
            else:
                skipped_current.append(bundesland_id)

        return {
            "dry_run": True,
            "planned": planned,
            "skipped_current": skipped_current,
            "missing_tiles": missing_tiles,
            "bundeslaender": list(bland_filtered["id"]),
            "output_folder": effective_output_folder,
            "metadata_output_folder": effective_metadata_output_folder,
            "tile_cache_folder": effective_tile_cache_folder,
            "bundesland_cache_path": effective_bundesland_cache_path,
            "limit_tiles": limit_tiles,
        }

    logger, log_file = build_mapillary_logger(effective_output_folder)
    logger.info("=== Mapillary Coverage Download gestartet ===")
    logger.info(f"Log-Datei: {log_file}")
    logger.info(f"📂 Lade Bundesländer aus: {effective_bundesland_cache_path}")
    if selected_bundeslaender:
        logger.info(f"🎯 Verarbeite {len(bland_filtered)} ausgewählte Bundesländer: {', '.join(selected_bundeslaender)}")
    else:
        logger.info(f"📍 Verarbeite alle {len(bland_filtered)} Bundesländer")
    logger.info(
        "📅 Freshness-Filter: "
        f"Berlin Lauf-Tag-Start {run_day_start_berlin.isoformat()}, "
        f"Cutoff {freshness_cutoff_berlin.isoformat()} (Vergleich UTC: {min_capture_dt_utc.isoformat()})"
    )

    ml_timestamps: dict[str, str] = {}
    skipped_current: list[str] = []
    missing_tiles: list[str] = []
    processed: list[str] = []

    for _, row in bland_filtered.iterrows():
        bundesland_id = row["id"]
        tile_json_path = os.path.join(effective_tile_cache_folder, f"{bundesland_id}_tiles.json")
        if not os.path.exists(tile_json_path):
            logger.warning(f"⏩ Überspringe {bundesland_id}, keine Tiles gefunden.")
            missing_tiles.append(bundesland_id)
            continue

        should_process, file_mtime = should_download_mapillary_output(
            bundesland_id,
            effective_output_folder,
            int(resolved_processing.get("max_file_age_days", 4)),
            logger=logger,
        )
        if not should_process:
            skipped_current.append(bundesland_id)
            if file_mtime is not None:
                ml_timestamps[bundesland_id] = datetime.fromtimestamp(file_mtime, tz=timezone.utc).isoformat()
            continue

        timestamp = process_bundesland(
            bundesland_id,
            tile_cache_folder=effective_tile_cache_folder,
            output_folder=effective_output_folder,
            mapillary_access_token=resolved_mapillary["access_token"],
            max_workers=max_workers,
            limit_tiles=limit_tiles,
            min_capture_dt_utc=min_capture_dt_utc,
            logger=logger,
            tqdm_enabled=tqdm_is_enabled,
        )
        if timestamp:
            ml_timestamps[bundesland_id] = timestamp
            processed.append(bundesland_id)

    metadata_path: str | None = None
    if ml_timestamps:
        oldest_ml_timestamp = min(ml_timestamps.values())
        berlin_timestamps = {
            bundesland_id: datetime_iso_to_berlin(timestamp, resolved_processing["freshness_timezone"])
            for bundesland_id, timestamp in ml_timestamps.items()
        }
        processed_date_berlin = datetime_iso_to_berlin(
            datetime.now(timezone.utc).isoformat(),
            resolved_processing["freshness_timezone"],
        )
        metadata = {
            "ml_data_from": datetime_iso_to_berlin(oldest_ml_timestamp, resolved_processing["freshness_timezone"]),
            "bundeslaender": berlin_timestamps,
            "processed_date": processed_date_berlin,
            "freshness_timezone": resolved_processing["freshness_timezone"],
            "freshness_lookback_months": resolved_processing["freshness_lookback_months"],
            "run_day_start_berlin": run_day_start_berlin.isoformat(),
            "freshness_cutoff_berlin": freshness_cutoff_berlin.isoformat(),
        }
        os.makedirs(effective_metadata_output_folder, exist_ok=True)
        metadata_path = os.path.join(effective_metadata_output_folder, "ml_metadata.json")
        with open(metadata_path, "w", encoding="utf-8") as file_handle:
            json.dump(metadata, file_handle, ensure_ascii=False, indent=2)
        logger.info(f"📅 Ältester Mapillary-Timestamp (Roh): {oldest_ml_timestamp}")
        logger.info(f"💾 Metadata gespeichert: {metadata_path}")
        logger.info(f"📄 Log-Datei: {log_file}")
    else:
        logger.warning("\n⚠️  Keine Mapillary-Daten verarbeitet, keine Metadata erstellt.")

    logger.info("=== Mapillary Coverage Download abgeschlossen ===")
    return {
        "dry_run": False,
        "processed": processed,
        "skipped_current": skipped_current,
        "missing_tiles": missing_tiles,
        "timestamps": ml_timestamps,
        "metadata_path": metadata_path,
        "output_folder": effective_output_folder,
        "metadata_output_folder": effective_metadata_output_folder,
        "log_file": log_file,
        "limit_tiles": limit_tiles,
    }