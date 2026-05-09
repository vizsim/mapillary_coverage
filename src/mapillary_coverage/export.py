from __future__ import annotations

from datetime import datetime, timezone
import glob
import json
import os
from pathlib import Path
from typing import Any, Callable
from zoneinfo import ZoneInfo

import pandas as pd
from dateutil.relativedelta import relativedelta

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


def compute_freshness_cutoff_date(processing_config: dict[str, Any]) -> str:
    tz = ZoneInfo(processing_config["freshness_timezone"])
    now = datetime.now(tz)
    run_day_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    months = int(processing_config["freshness_lookback_months"])
    cutoff_berlin = run_day_start - relativedelta(months=months)
    return cutoff_berlin.date().isoformat()


def csv_output_path(output_folder: str) -> Path:
    return Path(output_folder) / "germany_osm-highways_mp-coverage_latest.csv"


def readme_output_path(output_folder: str) -> Path:
    return Path(output_folder) / "README.md"


def should_process_csv(
    output_file: str | Path,
    max_age_days: int | None = None,
    *,
    processing_config: dict[str, Any] | None = None,
    now: datetime | None = None,
    emit: MessageEmitter | None = print,
) -> bool:
    _, resolved_processing = _resolve_configs(processing_config=processing_config)
    if max_age_days is None:
        max_age_days = resolved_processing.get("max_file_age_days", 4)

    output_path = Path(output_file)
    if not output_path.exists():
        return True

    try:
        current_time = now.timestamp() if now else datetime.now().timestamp()
        file_age_days = (current_time - output_path.stat().st_mtime) / 86400
        if file_age_days >= max_age_days:
            _emit(f"  ℹ️  CSV ist {file_age_days:.1f} Tage alt → Erneuerung nötig", emit)
            return True
        _emit(f"  ✓ CSV ist {file_age_days:.1f} Tage alt → aktuell genug", emit)
        return False
    except Exception as error:
        _emit(f"  ⚠️  Fehler beim Prüfen: {error}", emit)
        return True


def load_export_metadata(source_output_folder: str, emit: MessageEmitter | None = print) -> dict[str, Any]:
    files = {
        Path(source_output_folder) / "osm_metadata.json": "osm_data_from",
        Path(source_output_folder) / "ml_metadata.json": "ml_data_from",
    }
    metadata: dict[str, Any] = {
        "osm_data_from": None,
        "ml_data_from": None,
        "osm_bundeslaender": {},
        "ml_bundeslaender": {},
        "freshness_timezone": None,
        "freshness_lookback_months": None,
        "run_day_start_berlin": None,
        "freshness_cutoff_berlin": None,
    }

    for path, primary_key in files.items():
        if not path.exists():
            _emit(f"⚠️  {path} nicht gefunden", emit)
            continue

        with path.open("r", encoding="utf-8") as file_handle:
            raw_metadata = json.load(file_handle)

        if primary_key in raw_metadata:
            metadata[primary_key] = raw_metadata[primary_key]

        if "bundeslaender" in raw_metadata:
            if primary_key == "osm_data_from":
                metadata["osm_bundeslaender"] = raw_metadata["bundeslaender"]
            else:
                metadata["ml_bundeslaender"] = raw_metadata["bundeslaender"]

        if primary_key == "ml_data_from":
            for key in (
                "freshness_timezone",
                "freshness_lookback_months",
                "run_day_start_berlin",
                "freshness_cutoff_berlin",
            ):
                if key in raw_metadata:
                    metadata[key] = raw_metadata[key]

    return metadata


def discover_coverage_files(
    coverage_type: str,
    source_output_folder: str,
    selected_bundeslaender: list[str] | tuple[str, ...] | None = None,
) -> list[str]:
    files = glob.glob(f"{source_output_folder}/DE-*_osm-highways_mp_{coverage_type}_coverage_latest.parquet")
    if selected_bundeslaender:
        files = [file_path for file_path in files if any(code in file_path for code in selected_bundeslaender)]
    return sorted(files)


def load_coverage_data(
    coverage_type: str,
    *,
    source_output_folder: str,
    selected_bundeslaender: list[str] | tuple[str, ...] | None = None,
    emit: MessageEmitter | None = print,
) -> tuple[pd.DataFrame, list[dict[str, Any]]]:
    files = discover_coverage_files(coverage_type, source_output_folder, selected_bundeslaender)

    _emit(f"\n{'─' * 70}", emit)
    _emit(f"Lade {coverage_type.upper()} Coverage-Daten:", emit)
    _emit(f"  Dateien gefunden: {len(files)}", emit)

    all_dfs: list[pd.DataFrame] = []
    summary_list: list[dict[str, Any]] = []
    for file_path in files:
        df = pd.read_parquet(file_path, columns=["osm_id", "mp_coverage_ratio", "length_m_before_clip"])
        bundesland = Path(file_path).name.split("_")[0]
        total_length = df["length_m_before_clip"].sum()
        summary_list.append(
            {
                "Bundesland": bundesland,
                "Typ": coverage_type,
                "Anzahl Segmente": len(df),
                "Gesamtlänge (km)": total_length / 1000,
            }
        )
        all_dfs.append(df)
        _emit(f"    {bundesland}: {len(df):,} Segmente, {total_length / 1000:,.2f} km", emit)

    if not all_dfs:
        _emit("  ⚠️  Keine Daten gefunden!", emit)
        return pd.DataFrame(columns=["osm_id", "mp_coverage_ratio"]), []

    combined_df = pd.concat(all_dfs, ignore_index=True)
    _emit(f"  ✓ Gesamt: {len(combined_df):,} Segmente", emit)
    return combined_df, summary_list


def build_summary_df(pano_summary: list[dict[str, Any]], regular_summary: list[dict[str, Any]]) -> pd.DataFrame:
    if not pano_summary and not regular_summary:
        return pd.DataFrame()
    return pd.concat(
        [pd.DataFrame(pano_summary), pd.DataFrame(regular_summary)],
        ignore_index=True,
    ).sort_values(["Bundesland", "Typ"])


def filter_and_tag(df: pd.DataFrame, coverage_type: str, coverage_threshold: float, emit: MessageEmitter | None = print) -> pd.DataFrame:
    if df.empty:
        return pd.DataFrame(columns=["osm_id", "mapillary_coverage"])

    filtered = df[["osm_id", "mp_coverage_ratio"]].copy()
    filtered = filtered[filtered["mp_coverage_ratio"] >= coverage_threshold].copy()
    filtered["mapillary_coverage"] = coverage_type
    filtered = filtered[["osm_id", "mapillary_coverage"]]
    _emit(
        f"  {coverage_type}: {len(filtered):,} Segmente über Threshold ({coverage_threshold * 100:.0f}%)",
        emit,
    )
    return filtered


def combine_coverage_frames(
    pano_filtered: pd.DataFrame,
    regular_filtered: pd.DataFrame,
    emit: MessageEmitter | None = print,
) -> pd.DataFrame:
    both_concat = pd.concat([pano_filtered, regular_filtered], ignore_index=True)
    _emit(f"\n{'─' * 70}", emit)
    _emit("Vor Duplikat-Entfernung:", emit)
    if not both_concat.empty:
        _emit(both_concat["mapillary_coverage"].value_counts().to_string(), emit)

    both_concat = both_concat.sort_values(by="mapillary_coverage", ascending=True).drop_duplicates(
        subset="osm_id",
        keep="first",
    )

    _emit("\nNach Duplikat-Entfernung (Pano bevorzugt):", emit)
    if not both_concat.empty:
        _emit(both_concat["mapillary_coverage"].value_counts().to_string(), emit)
    _emit(f"\nGesamt eindeutige Segmente: {len(both_concat):,}", emit)
    return both_concat


def create_readme(summary_df: pd.DataFrame, metadata: dict[str, Any], processing_config: dict[str, Any]) -> str:
    current_date = datetime.now().strftime("%Y-%m-%d")
    summary_table = summary_df.pivot(index="Bundesland", columns="Typ", values="Gesamtlänge (km)").fillna(0).reset_index()

    osm_bl = metadata.get("osm_bundeslaender", {})
    ml_bl = metadata.get("ml_bundeslaender", {})
    table_header = "| Bundesland | Pano (km) | Regular (km) | OSM Datum | Mapillary Datum |\n|------------|-----------|--------------|-----------|-----------------|"
    table_rows: list[str] = []

    for _, row in summary_table.iterrows():
        bundesland = row["Bundesland"]
        pano_km = f"{row.get('pano', 0):,.2f}" if "pano" in row else "0.00"
        regular_km = f"{row.get('regular', 0):,.2f}" if "regular" in row else "0.00"
        osm_date = osm_bl.get(bundesland, "N/A")
        ml_date = ml_bl.get(bundesland, "N/A")
        if osm_date != "N/A":
            osm_date = osm_date.split("T")[0]
        if ml_date != "N/A":
            ml_date = ml_date.split("T")[0]
        table_rows.append(f"| {bundesland} | {pano_km} | {regular_km} | {osm_date} | {ml_date} |")

    markdown_table = "\n".join([table_header] + table_rows)
    osm_date = metadata["osm_data_from"].split("T")[0] if metadata["osm_data_from"] else "N/A"
    ml_date = metadata["ml_data_from"].split("T")[0] if metadata["ml_data_from"] else "N/A"
    freshness_start = metadata.get("freshness_cutoff_berlin")
    if freshness_start:
        freshness_start = freshness_start.split("T")[0]
    else:
        freshness_start = compute_freshness_cutoff_date(processing_config)

    return f"""# Mapillary Coverage per OSM Highway — Output

This folder contains the **latest** output file for *Mapillary coverage per OSM highway analysis*.

| Property | Value |
|----------|-------|
| **Data created** | {current_date} |
| **OSM data** | {osm_date} |
| **Mapillary data** | {freshness_start} → {ml_date} |
| **Buffer distance** | {processing_config['buffer_distance']} meters |
| **Coverage ratio threshold** | {processing_config['mp_coverage_ratio_threshold']} ({int(processing_config['mp_coverage_ratio_threshold'] * 100)}%) |

Segments are considered *covered* if at least {int(processing_config['mp_coverage_ratio_threshold'] * 100)}% of their length falls within {processing_config['buffer_distance']} meters of Mapillary images.

## Summary by Bundesland

{markdown_table}
"""


def run_export_csv_pipeline(
    *,
    geofabrik_config: dict[str, Any] | None = None,
    processing_config: dict[str, Any] | None = None,
    source_output_folder: str | None = None,
    output_folder: str | None = None,
    selected_bundeslaender: list[str] | tuple[str, ...] | None = None,
    dry_run: bool = False,
    emit: MessageEmitter | None = print,
) -> dict[str, Any]:
    resolved_geofabrik, resolved_processing = _resolve_configs(
        geofabrik_config=geofabrik_config,
        processing_config=processing_config,
    )
    selected_bundeslaender = selected_bundeslaender or resolved_geofabrik.get("bundeslaender")
    source_folder = source_output_folder or resolved_processing["output_folder"]
    target_folder = output_folder or resolved_processing["output_folder"]
    coverage_threshold = resolved_processing["mp_coverage_ratio_threshold"]
    Path(target_folder).mkdir(parents=True, exist_ok=True)

    csv_path = csv_output_path(target_folder)
    should_process = should_process_csv(csv_path, processing_config=resolved_processing, emit=emit)

    pano_files = discover_coverage_files("pano", source_folder, selected_bundeslaender)
    regular_files = discover_coverage_files("regular", source_folder, selected_bundeslaender)
    if dry_run:
        summary = {
            "dry_run": True,
            "should_process": should_process,
            "csv_output_file": str(csv_path),
            "readme_output_file": str(readme_output_path(target_folder)),
            "pano_files": pano_files,
            "regular_files": regular_files,
            "selected_bundeslaender": selected_bundeslaender,
        }
        _emit(f"\n{'=' * 70}", emit)
        _emit("EXPORT-CSV DRY-RUN", emit)
        _emit(f"{'=' * 70}", emit)
        _emit(f"CSV Ziel: {csv_path}", emit)
        _emit(f"README Ziel: {readme_output_path(target_folder)}", emit)
        _emit(f"Pano-Dateien: {len(pano_files)}", emit)
        _emit(f"Regular-Dateien: {len(regular_files)}", emit)
        _emit(f"Verarbeitung nötig: {should_process}", emit)
        return summary

    if not should_process:
        _emit(f"\n✅ CSV ist aktuell genug - keine Verarbeitung nötig!", emit)
        _emit(f"   Datei: {csv_path}", emit)
        return {
            "dry_run": False,
            "should_process": False,
            "csv_output_file": str(csv_path),
            "readme_output_file": str(readme_output_path(target_folder)),
            "rows": 0,
        }

    metadata = load_export_metadata(source_folder, emit=emit)
    pano_df, pano_summary = load_coverage_data(
        "pano",
        source_output_folder=source_folder,
        selected_bundeslaender=selected_bundeslaender,
        emit=emit,
    )
    regular_df, regular_summary = load_coverage_data(
        "regular",
        source_output_folder=source_folder,
        selected_bundeslaender=selected_bundeslaender,
        emit=emit,
    )
    summary_df = build_summary_df(pano_summary, regular_summary)

    _emit(f"\n{'─' * 70}", emit)
    _emit(f"Filtere nach Coverage-Threshold >= {coverage_threshold * 100:.0f}%:", emit)
    pano_filtered = filter_and_tag(pano_df, "pano", coverage_threshold, emit=emit)
    regular_filtered = filter_and_tag(regular_df, "regular", coverage_threshold, emit=emit)
    combined = combine_coverage_frames(pano_filtered, regular_filtered, emit=emit)

    if combined.empty:
        _emit("\n⏩ Kein CSV-Export", emit)
        _emit("\n⏩ Kein README-Export", emit)
        _emit(f"\n{'=' * 70}", emit)
        _emit("✅ FERTIG!", emit)
        _emit(f"{'=' * 70}", emit)
        return {
            "dry_run": False,
            "should_process": True,
            "csv_output_file": str(csv_path),
            "readme_output_file": str(readme_output_path(target_folder)),
            "rows": 0,
            "summary_rows": len(summary_df),
            "exported": False,
        }

    combined.to_csv(csv_path, index=False)
    _emit(f"\n{'=' * 70}", emit)
    _emit("✅ CSV exportiert:", emit)
    _emit(f"   {csv_path}", emit)
    _emit(f"   {len(combined):,} Zeilen", emit)
    _emit(f"{'=' * 70}", emit)

    if not summary_df.empty:
        readme_content = create_readme(summary_df, metadata, resolved_processing)
        readme_path = readme_output_path(target_folder)
        with readme_path.open("w", encoding="utf-8") as file_handle:
            file_handle.write(readme_content)
        _emit(f"\n✅ README erstellt: {readme_path}", emit)

    _emit(f"\n{'=' * 70}", emit)
    _emit("✅ FERTIG!", emit)
    _emit(f"{'=' * 70}", emit)
    return {
        "dry_run": False,
        "should_process": True,
        "csv_output_file": str(csv_path),
        "readme_output_file": str(readme_output_path(target_folder)),
        "rows": len(combined),
        "summary_rows": len(summary_df),
        "exported": True,
    }