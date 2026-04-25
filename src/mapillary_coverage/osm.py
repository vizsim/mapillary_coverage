from __future__ import annotations

from datetime import datetime
import json
import os
from pathlib import Path
import random
import subprocess
import time
from typing import Any, Callable

import geopandas as gpd
import osmium
import requests
from requests.adapters import HTTPAdapter
import shapely.wkb as wkblib
from tqdm import tqdm
from urllib3.util import Retry

from mapillary_coverage.settings import get_settings


MessageEmitter = Callable[[str], None]


class HighwayHandler(osmium.SimpleHandler):
    def __init__(self) -> None:
        super().__init__()
        self.wkbfab = osmium.geom.WKBFactory()
        self.data: list[dict[str, Any]] = []

    def way(self, way: Any) -> None:
        if "highway" not in way.tags:
            return

        try:
            wkb = self.wkbfab.create_linestring(way)
            linestring = wkblib.loads(wkb, hex=True)
            self.data.append(
                {
                    "osm_id": way.id,
                    "highway": way.tags.get("highway"),
                    "geometry": linestring,
                }
            )
        except Exception:
            pass


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


def get_osm_metadata_path(processing_config: dict[str, Any] | None = None) -> Path:
    _, resolved_processing = _resolve_configs(processing_config=processing_config)
    return Path(resolved_processing["output_folder"]) / "osm_metadata.json"


def get_processed_highways_path(
    bundesland_code: str,
    geofabrik_config: dict[str, Any] | None = None,
) -> Path:
    resolved_geofabrik, _ = _resolve_configs(geofabrik_config=geofabrik_config)
    return Path(resolved_geofabrik["processed_folder"]) / f"processed_highways_{bundesland_code}_latest.pbf"


def get_downloaded_pbf_path(
    bundesland_code: str,
    url: str,
    geofabrik_config: dict[str, Any] | None = None,
) -> Path:
    resolved_geofabrik, _ = _resolve_configs(geofabrik_config=geofabrik_config)
    filename = f"{bundesland_code}_{url.split('/')[-1]}"
    return Path(resolved_geofabrik["download_folder"]) / filename


def load_osm_metadata(
    metadata_path: str | Path | None = None,
    processing_config: dict[str, Any] | None = None,
) -> dict[str, Any]:
    resolved_path = Path(metadata_path) if metadata_path else get_osm_metadata_path(processing_config)
    with resolved_path.open("r", encoding="utf-8") as file_handle:
        return json.load(file_handle)


def should_download_osm_data(
    bundesland_code: str,
    max_age_days: int | None = None,
    *,
    geofabrik_config: dict[str, Any] | None = None,
    processing_config: dict[str, Any] | None = None,
    metadata_path: str | Path | None = None,
    now: datetime | None = None,
    emit: MessageEmitter | None = print,
) -> bool:
    resolved_geofabrik, resolved_processing = _resolve_configs(
        geofabrik_config=geofabrik_config,
        processing_config=processing_config,
    )
    if max_age_days is None:
        max_age_days = resolved_processing.get("max_file_age_days", 4)

    processed_file = get_processed_highways_path(
        bundesland_code,
        geofabrik_config=resolved_geofabrik,
    )
    if not processed_file.exists():
        _emit(f"  ℹ️  Keine Datei vorhanden für {bundesland_code} → Download nötig", emit)
        return True

    resolved_metadata_path = Path(metadata_path) if metadata_path else get_osm_metadata_path(resolved_processing)
    if not resolved_metadata_path.exists():
        _emit("  ℹ️  Keine Metadata vorhanden → Download nötig", emit)
        return True

    try:
        metadata = load_osm_metadata(resolved_metadata_path)
        bundeslaender = metadata.get("bundeslaender", {})
        if bundesland_code not in bundeslaender:
            _emit(f"  ℹ️  {bundesland_code} nicht in Metadata → Download nötig", emit)
            return True

        processed_date_str = metadata.get("processed_date")
        if not processed_date_str:
            _emit("  ℹ️  Kein processed_date in Metadata → Download nötig", emit)
            return True

        processed_date = datetime.fromisoformat(str(processed_date_str).replace("Z", "+00:00"))
        current_time = now or datetime.now(processed_date.tzinfo)
        age_days = (current_time - processed_date).days

        if age_days >= max_age_days:
            _emit(f"  ℹ️  OSM-Daten für {bundesland_code} sind {age_days} Tage alt → Download nötig", emit)
            return True

        _emit(f"  ✓ OSM-Daten für {bundesland_code} sind {age_days} Tage alt → aktuell genug", emit)
        return False
    except Exception as error:
        _emit(f"  ⚠️  Fehler beim Lesen der Metadata: {error} → Download wird durchgeführt", emit)
        return True


def create_retry_session(
    total_retries: int | None = None,
    backoff_factor: float | None = None,
    *,
    processing_config: dict[str, Any] | None = None,
) -> requests.Session:
    _, resolved_processing = _resolve_configs(processing_config=processing_config)
    if total_retries is None:
        total_retries = resolved_processing.get("osm_download_retries", 5)
    if backoff_factor is None:
        backoff_factor = resolved_processing.get("osm_download_backoff_factor", 1.5)

    retry_strategy = Retry(
        total=total_retries,
        connect=total_retries,
        read=total_retries,
        status=total_retries,
        backoff_factor=backoff_factor,
        status_forcelist=[429, 500, 502, 503, 504],
        allowed_methods=frozenset(["GET"]),
        raise_on_status=False,
    )
    adapter = HTTPAdapter(max_retries=retry_strategy)
    session = requests.Session()
    session.mount("https://", adapter)
    session.mount("http://", adapter)
    return session


def is_temporary_network_error(error: Exception) -> bool:
    error_text = str(error).lower()
    transient_markers = [
        "name resolution",
        "temporary failure in name resolution",
        "failed to resolve",
        "nodename nor servname provided",
        "connection reset",
        "timed out",
        "read timeout",
        "connect timeout",
        "newconnectionerror",
    ]
    return any(marker in error_text for marker in transient_markers)


def download_bundesland_pbf(
    bundesland_code: str,
    url: str,
    force_download: bool = False,
    use_stale_fallback: bool | None = None,
    *,
    allow_network: bool = True,
    geofabrik_config: dict[str, Any] | None = None,
    processing_config: dict[str, Any] | None = None,
    emit: MessageEmitter | None = print,
) -> tuple[str | None, bool]:
    resolved_geofabrik, resolved_processing = _resolve_configs(
        geofabrik_config=geofabrik_config,
        processing_config=processing_config,
    )
    if use_stale_fallback is None:
        use_stale_fallback = resolved_processing.get("allow_stale_on_download_failure", True)

    folder_download = Path(resolved_geofabrik["download_folder"])
    folder_download.mkdir(parents=True, exist_ok=True)

    file_path = get_downloaded_pbf_path(
        bundesland_code,
        url,
        geofabrik_config=resolved_geofabrik,
    )
    temp_path = file_path.with_suffix(f"{file_path.suffix}.tmp")
    filename = file_path.name

    if file_path.exists() and not force_download:
        _emit(f"  ✓ Bereits vorhanden: {filename}", emit)
        return str(file_path), False

    if temp_path.exists():
        temp_path.unlink()

    if not allow_network:
        _emit(f"  ℹ️  Netzwerk deaktiviert → überspringe Download für {bundesland_code}", emit)
        if use_stale_fallback and file_path.exists():
            _emit("  ⚠️  Fallback aktiv: Nutze vorhandene lokale Datei", emit)
            return str(file_path), False
        return None, False

    max_attempts = resolved_processing.get("osm_download_manual_attempts", 3)
    base_delay_seconds = resolved_processing.get("osm_download_manual_base_delay", 5)
    session = create_retry_session(processing_config=resolved_processing)

    _emit(f"  📥 Lade herunter: {filename}", emit)
    try:
        for attempt in range(1, max_attempts + 1):
            try:
                response = session.get(
                    url,
                    stream=True,
                    timeout=(20, 300),
                    allow_redirects=True,
                )
                response.raise_for_status()

                total_size = int(response.headers.get("content-length", 0))
                with open(temp_path, "wb") as file_handle, tqdm(
                    total=total_size,
                    unit="B",
                    unit_scale=True,
                    desc=f"    {bundesland_code}",
                    leave=False,
                ) as progress_bar:
                    for chunk in response.iter_content(chunk_size=8192):
                        if chunk:
                            file_handle.write(chunk)
                            progress_bar.update(len(chunk))

                os.replace(temp_path, file_path)
                _emit(f"  ✓ Download abgeschlossen: {filename}", emit)
                return str(file_path), True
            except Exception as error:
                if temp_path.exists():
                    temp_path.unlink()

                transient = is_temporary_network_error(error)
                _emit(
                    f"  ⚠️  Download-Versuch {attempt}/{max_attempts} für {bundesland_code} fehlgeschlagen: {error}",
                    emit,
                )
                if attempt < max_attempts and transient:
                    sleep_seconds = base_delay_seconds * (2 ** (attempt - 1)) + random.uniform(0, 1.5)
                    _emit(f"     ↻ Warte {sleep_seconds:.1f}s und versuche erneut...", emit)
                    time.sleep(sleep_seconds)
                    continue
                break
    finally:
        session.close()

    _emit(f"  ❌ Fehler beim Download von {bundesland_code}: alle Versuche fehlgeschlagen", emit)
    if use_stale_fallback and file_path.exists():
        _emit("  ⚠️  Fallback aktiv: Nutze vorhandene lokale Datei trotz fehlgeschlagenem Download", emit)
        return str(file_path), False
    return None, False


def filter_highways_osmium(
    input_pbf: str | Path,
    output_pbf: str | Path,
    bundesland_code: str,
    force_filter: bool = False,
    *,
    emit: MessageEmitter | None = print,
) -> bool:
    output_path = Path(output_pbf)
    if output_path.exists() and not force_filter:
        _emit(f"  ✓ Bereits gefiltert: {output_path.name}", emit)
        return True

    if output_path.exists():
        _emit("  🔄 Überschreibe vorhandene gefilterte Datei", emit)
        output_path.unlink()

    _emit(f"  🔧 Filtere Highways für {bundesland_code}...", emit)
    try:
        filter_command = [
            "osmium",
            "tags-filter",
            str(input_pbf),
            "w/highway",
            "-o",
            str(output_path),
        ]
        subprocess.run(filter_command, check=True, capture_output=True)
        _emit(f"  ✓ Filterung abgeschlossen: {output_path.name}", emit)
        return True
    except subprocess.CalledProcessError as error:
        _emit(f"  ❌ Fehler bei Osmium-Filterung für {bundesland_code}: {error}", emit)
        if output_path.exists():
            output_path.unlink()
        return False


def get_osm_timestamp(pbf_file: str | Path) -> str | None:
    try:
        result = subprocess.run(
            ["osmium", "fileinfo", str(pbf_file), "-g", "header.option.timestamp"],
            capture_output=True,
            text=True,
            check=True,
        )
        return result.stdout.strip()
    except subprocess.CalledProcessError:
        return None


def load_osm_highways_pbf(file_path: str | Path, crs: str = "EPSG:4326") -> gpd.GeoDataFrame:
    handler = HighwayHandler()
    handler.apply_file(str(file_path), locations=True)
    return gpd.GeoDataFrame(handler.data, geometry="geometry", crs=crs)


def run_osm_prepare_pipeline(
    bundesland_urls: dict[str, str],
    *,
    geofabrik_config: dict[str, Any] | None = None,
    processing_config: dict[str, Any] | None = None,
    dry_run: bool = False,
    allow_network: bool = True,
    emit: MessageEmitter | None = print,
) -> dict[str, Any]:
    resolved_geofabrik, resolved_processing = _resolve_configs(
        geofabrik_config=geofabrik_config,
        processing_config=processing_config,
    )
    folder_download = Path(resolved_geofabrik["download_folder"])
    folder_processed = Path(resolved_geofabrik["processed_folder"])
    folder_download.mkdir(parents=True, exist_ok=True)
    folder_processed.mkdir(parents=True, exist_ok=True)

    successful: list[str] = []
    failed: list[str] = []
    skipped: list[str] = []
    used_stale_fallback: list[str] = []
    timestamps: dict[str, str] = {}
    planned_downloads: list[str] = []
    planned_skips: list[str] = []

    _emit(f"\n{'=' * 70}", emit)
    _emit(f"Download und Filterung OSM-Daten für {len(bundesland_urls)} Bundesländer", emit)
    _emit(f"{'=' * 70}\n", emit)

    for bundesland_code, url in bundesland_urls.items():
        _emit(f"{'─' * 70}", emit)
        _emit(f"Bundesland: {bundesland_code}", emit)
        _emit(f"{'─' * 70}", emit)

        try:
            needs_download = should_download_osm_data(
                bundesland_code,
                geofabrik_config=resolved_geofabrik,
                processing_config=resolved_processing,
                emit=emit,
            )

            if dry_run:
                if needs_download:
                    planned_downloads.append(bundesland_code)
                    _emit(f"  🧪 Dry-run: {bundesland_code} würde heruntergeladen und gefiltert", emit)
                else:
                    planned_skips.append(bundesland_code)
                    _emit(f"  🧪 Dry-run: {bundesland_code} würde übersprungen", emit)
                _emit("", emit)
                continue

            if not needs_download:
                skipped.append(bundesland_code)
                try:
                    metadata = load_osm_metadata(processing_config=resolved_processing)
                    bundeslaender = metadata.get("bundeslaender", {})
                    if bundesland_code in bundeslaender:
                        timestamps[bundesland_code] = bundeslaender[bundesland_code]
                except Exception:
                    pass

                _emit(f"  ⏩ {bundesland_code} übersprungen (Daten aktuell genug)\n", emit)
                continue

            downloaded_pbf, is_fresh_download = download_bundesland_pbf(
                bundesland_code,
                url,
                force_download=needs_download,
                allow_network=allow_network,
                geofabrik_config=resolved_geofabrik,
                processing_config=resolved_processing,
                emit=emit,
            )
            if not downloaded_pbf:
                failed.append(bundesland_code)
                _emit("", emit)
                continue

            output_pbf = folder_processed / f"processed_highways_{bundesland_code}_latest.pbf"
            if needs_download and not is_fresh_download:
                used_stale_fallback.append(bundesland_code)
                _emit("  ⚠️  Netzwerkproblem: Weiterarbeit mit vorhandenen lokalen Daten", emit)

                if output_pbf.exists():
                    timestamp = get_osm_timestamp(output_pbf)
                    if timestamp:
                        timestamps[bundesland_code] = timestamp
                    skipped.append(bundesland_code)
                    _emit(f"  ⏩ {bundesland_code} ohne Re-Filterung weiterverwendet\n", emit)
                    continue

            success = filter_highways_osmium(
                downloaded_pbf,
                output_pbf,
                bundesland_code,
                force_filter=needs_download and is_fresh_download,
                emit=emit,
            )
            if success:
                timestamp = get_osm_timestamp(output_pbf)
                if timestamp:
                    timestamps[bundesland_code] = timestamp
                    _emit(f"  📅 OSM-Daten vom: {timestamp}", emit)

                successful.append(bundesland_code)
                _emit(f"  ✅ {bundesland_code} erfolgreich verarbeitet!\n", emit)
            else:
                failed.append(bundesland_code)
        except Exception as error:
            _emit(f"  ❌ Fehler bei {bundesland_code}: {error}\n", emit)
            failed.append(bundesland_code)

    if dry_run:
        summary = {
            "dry_run": True,
            "planned_downloads": planned_downloads,
            "planned_skips": planned_skips,
            "bundeslaender": list(bundesland_urls),
        }
        _emit(f"\n{'=' * 70}", emit)
        _emit("DRY-RUN ZUSAMMENFASSUNG", emit)
        _emit(f"{'=' * 70}", emit)
        _emit(f"🧪 Geplante Downloads: {len(planned_downloads)}/{len(bundesland_urls)}", emit)
        if planned_downloads:
            _emit(f"   {', '.join(planned_downloads)}", emit)
        _emit(f"🧪 Geplante Skips: {len(planned_skips)}/{len(bundesland_urls)}", emit)
        if planned_skips:
            _emit(f"   {', '.join(planned_skips)}", emit)
        return summary

    _emit(f"\n{'=' * 70}", emit)
    _emit("ZUSAMMENFASSUNG", emit)
    _emit(f"{'=' * 70}", emit)
    _emit(f"✅ Erfolgreich: {len(successful)}/{len(bundesland_urls)}", emit)
    if successful:
        _emit(f"   {', '.join(successful)}", emit)

    if skipped:
        _emit(f"\n⏩ Übersprungen (aktuell/weiterverwendet): {len(skipped)}/{len(bundesland_urls)}", emit)
        _emit(f"   {', '.join(skipped)}", emit)

    if used_stale_fallback:
        _emit(f"\n⚠️  Netzwerk-Fallback genutzt: {len(used_stale_fallback)}/{len(bundesland_urls)}", emit)
        _emit(f"   {', '.join(used_stale_fallback)}", emit)

    if failed:
        _emit(f"\n❌ Fehlgeschlagen: {len(failed)}/{len(bundesland_urls)}", emit)
        _emit(f"   {', '.join(failed)}", emit)

    if successful and timestamps:
        oldest_date = min(timestamps.values())
        metadata = {
            "osm_data_from": oldest_date,
            "bundeslaender": timestamps,
            "processed_date": datetime.now().isoformat(),
            "download_fallback_used": used_stale_fallback,
        }
        metadata_path = get_osm_metadata_path(resolved_processing)
        with metadata_path.open("w", encoding="utf-8") as file_handle:
            json.dump(metadata, file_handle, indent=2)

        _emit(f"\n📅 Ältestes OSM-Datum: {oldest_date}", emit)
        _emit(f"💾 Metadata gespeichert: {metadata_path}", emit)
    elif used_stale_fallback:
        _emit("\nℹ️  Metadata nicht überschrieben, da keine frischen Downloads verarbeitet wurden.", emit)

    _emit(f"\n{'=' * 70}", emit)
    _emit("✅ FERTIG!", emit)
    _emit(f"{'=' * 70}", emit)
    return {
        "dry_run": False,
        "successful": successful,
        "failed": failed,
        "skipped": skipped,
        "used_stale_fallback": used_stale_fallback,
        "timestamps": timestamps,
    }