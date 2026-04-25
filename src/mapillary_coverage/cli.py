from __future__ import annotations

import argparse
import json
import logging
import os
from pathlib import Path

from mapillary_coverage.buffer import run_create_buffer_pipeline
from mapillary_coverage.bundeslaender import get_bundesland_urls
from mapillary_coverage.export import run_export_csv_pipeline
from mapillary_coverage.mapillary import run_mapillary_download_pipeline
from mapillary_coverage.merge import run_merge_coverage_pipeline
from mapillary_coverage.notebooks import NOTEBOOK_SPECS, get_notebook, get_pipeline
from mapillary_coverage.osm import run_osm_prepare_pipeline
from mapillary_coverage.runner import build_step_command, run_notebook, run_pipeline
from mapillary_coverage.settings import get_settings


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="mapillary-coverage",
        description="Mapillary coverage CLI.",
    )
    subparsers = parser.add_subparsers(dest="command")

    show_config = subparsers.add_parser(
        "show-config",
        help="Print the merged application settings.",
    )
    show_config.add_argument(
        "--project-root",
        type=Path,
        default=None,
        help="Project root that contains the config directory.",
    )
    show_config.add_argument(
        "--format",
        choices=("json",),
        default="json",
        help="Output format for rendered settings.",
    )

    list_notebooks = subparsers.add_parser(
        "list-notebooks",
        help="List registered notebook steps.",
    )
    list_notebooks.add_argument(
        "--include-optional",
        action="store_true",
        help="Include optional steps such as notebook 0.",
    )

    run_notebook_parser = subparsers.add_parser(
        "run-notebook",
        help="Execute a single notebook step via nbconvert.",
    )
    run_notebook_parser.add_argument("step_id", help="Notebook step id, for example 1a or 4.")
    run_notebook_parser.add_argument(
        "--project-root",
        type=Path,
        default=None,
        help="Project root that contains the notebooks.",
    )
    run_notebook_parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print the nbconvert command without executing it.",
    )

    run_pipeline_parser = subparsers.add_parser(
        "run-pipeline",
        help="Execute the notebook pipeline in the current production order.",
    )
    run_pipeline_parser.add_argument(
        "--project-root",
        type=Path,
        default=None,
        help="Project root that contains the notebooks.",
    )
    run_pipeline_parser.add_argument(
        "--include-prepare-tiles",
        action="store_true",
        help="Include notebook 0 before the default pipeline.",
    )
    run_pipeline_parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print notebook commands without executing them.",
    )

    download_mapillary_parser = subparsers.add_parser(
        "download-mapillary",
        help="Run or plan the Mapillary coverage download step from notebook 1b.",
    )
    download_mapillary_parser.add_argument(
        "--project-root",
        type=Path,
        default=None,
        help="Project root that contains config and output folders.",
    )
    download_mapillary_parser.add_argument(
        "--bundeslaender",
        nargs="+",
        default=None,
        help="Optional subset of Bundesland codes, for example DE-BE DE-BB.",
    )
    download_mapillary_parser.add_argument(
        "--output-folder",
        default=None,
        help="Optional destination folder for downloaded coverage parquet files.",
    )
    download_mapillary_parser.add_argument(
        "--metadata-output-folder",
        default=None,
        help="Optional destination folder for ml_metadata.json.",
    )
    download_mapillary_parser.add_argument(
        "--tile-cache-folder",
        default=None,
        help="Optional folder that contains the prepared tile JSON files.",
    )
    download_mapillary_parser.add_argument(
        "--limit-tiles",
        type=int,
        default=None,
        help="Optional tile limit per Bundesland, useful for small validation runs.",
    )
    download_mapillary_parser.add_argument(
        "--max-workers",
        type=int,
        default=3,
        help="Thread pool size for tile downloads.",
    )
    download_mapillary_parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Only inspect tile caches and current parquet freshness.",
    )

    prepare_osm_parser = subparsers.add_parser(
        "prepare-osm",
        help="Run or plan the OSM download and filtering step from notebook 1a.",
    )
    prepare_osm_parser.add_argument(
        "--project-root",
        type=Path,
        default=None,
        help="Project root that contains config and output folders.",
    )
    prepare_osm_parser.add_argument(
        "--bundeslaender",
        nargs="+",
        default=None,
        help="Optional subset of Bundesland codes, for example DE-BE DE-BB.",
    )
    prepare_osm_parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Only evaluate which Bundesländer would be processed without downloading or filtering.",
    )
    prepare_osm_parser.add_argument(
        "--no-network",
        action="store_true",
        help="Disable network access for the preparation step.",
    )

    create_buffer_parser = subparsers.add_parser(
        "create-buffer",
        help="Run or plan the Mapillary coverage buffering step from notebook 2.",
    )
    create_buffer_parser.add_argument(
        "--project-root",
        type=Path,
        default=None,
        help="Project root that contains config and output folders.",
    )
    create_buffer_parser.add_argument(
        "--bundeslaender",
        nargs="+",
        default=None,
        help="Optional subset of Bundesland codes, for example DE-BE DE-BB.",
    )
    create_buffer_parser.add_argument(
        "--source-folder",
        default=None,
        help="Optional folder with unbuffered mapillary coverage parquet files.",
    )
    create_buffer_parser.add_argument(
        "--output-folder",
        default=None,
        help="Optional destination folder for buffered parquet output.",
    )
    create_buffer_parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Only inspect files and determine which Bundesländer would be buffered.",
    )

    merge_coverage_parser = subparsers.add_parser(
        "merge-coverage",
        help="Plan the merge coverage step from notebook 3.",
    )
    merge_coverage_parser.add_argument(
        "--project-root",
        type=Path,
        default=None,
        help="Project root that contains config and output folders.",
    )
    merge_coverage_parser.add_argument(
        "--bundeslaender",
        nargs="+",
        default=None,
        help="Optional subset of Bundesland codes, for example DE-BE DE-BB.",
    )
    merge_coverage_parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Only plan which Bundesländer would be merged.",
    )
    merge_coverage_parser.add_argument(
        "--execute",
        action="store_true",
        help="Execute the merge coverage step for the selected Bundesländer.",
    )
    merge_coverage_parser.add_argument(
        "--output-folder",
        default=None,
        help="Optional output folder override, useful for local validation runs.",
    )
    merge_coverage_parser.add_argument(
        "--max-roads",
        type=int,
        default=None,
        help="Optional limit of OSM roads per Bundesland, useful for small validation runs.",
    )

    export_csv_parser = subparsers.add_parser(
        "export-csv",
        help="Run or plan the CSV and README export step from notebook 4.",
    )
    export_csv_parser.add_argument(
        "--project-root",
        type=Path,
        default=None,
        help="Project root that contains config and output folders.",
    )
    export_csv_parser.add_argument(
        "--bundeslaender",
        nargs="+",
        default=None,
        help="Optional subset of Bundesland codes, for example DE-BE DE-BB.",
    )
    export_csv_parser.add_argument(
        "--source-output-folder",
        default=None,
        help="Optional source folder for merge outputs and metadata. Defaults to the configured output folder.",
    )
    export_csv_parser.add_argument(
        "--output-folder",
        default=None,
        help="Optional destination folder for CSV and README output.",
    )
    export_csv_parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Only inspect available files and planned output paths.",
    )

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.command == "show-config":
        settings = get_settings(project_root=args.project_root)
        rendered = settings.to_dict()
        if rendered.get("mapillary"):
            rendered["mapillary"] = dict(rendered["mapillary"])
            if rendered["mapillary"].get("access_token"):
                rendered["mapillary"]["access_token"] = "<redacted>"
        print(json.dumps(rendered, indent=2, sort_keys=True))
        return 0

    if args.command == "list-notebooks":
        for spec in NOTEBOOK_SPECS:
            if not args.include_optional and not spec.default_pipeline:
                continue
            print(f"{spec.step_id}\t{spec.filename}\t{spec.label}")
        return 0

    if args.command == "run-notebook":
        project_root = args.project_root.resolve() if args.project_root else Path.cwd()
        notebook = get_notebook(args.step_id)
        command = build_step_command(
            notebook,
            project_root,
            dry_run=args.dry_run,
            env=os.environ.copy(),
        )
        print(f"Notebook {notebook.step_id}: {' '.join(command)}")
        return run_notebook(
            notebook,
            project_root,
            dry_run=args.dry_run,
            env=os.environ.copy(),
        )

    if args.command == "run-pipeline":
        project_root = args.project_root.resolve() if args.project_root else Path.cwd()
        notebooks = get_pipeline(include_prepare_tiles=args.include_prepare_tiles)
        return run_pipeline(
            notebooks,
            project_root,
            dry_run=args.dry_run,
            env=os.environ.copy(),
        )

    if args.command == "download-mapillary":
        project_root = args.project_root.resolve() if args.project_root else Path.cwd()
        os.chdir(project_root)
        settings = get_settings(project_root=project_root)
        selected_bundeslaender = args.bundeslaender or settings.geofabrik.bundeslaender
        result = run_mapillary_download_pipeline(
            processing_config=settings.legacy_processing_config,
            mapillary_config=settings.legacy_mapillary_config,
            tiles_config=settings.legacy_tiles_config,
            selected_bundeslaender=selected_bundeslaender,
            output_folder=args.output_folder,
            metadata_output_folder=args.metadata_output_folder,
            tile_cache_folder=args.tile_cache_folder,
            max_workers=args.max_workers,
            limit_tiles=args.limit_tiles,
            dry_run=args.dry_run,
        )
        print(json.dumps(result, indent=2, sort_keys=True))
        return 0

    if args.command == "prepare-osm":
        project_root = args.project_root.resolve() if args.project_root else Path.cwd()
        os.chdir(project_root)
        settings = get_settings(project_root=project_root)
        selected_bundeslaender = args.bundeslaender or settings.geofabrik.bundeslaender
        bundesland_urls = get_bundesland_urls(selected_bundeslaender)
        result = run_osm_prepare_pipeline(
            bundesland_urls,
            geofabrik_config=settings.legacy_geofabrik_config,
            processing_config=settings.legacy_processing_config,
            dry_run=args.dry_run,
            allow_network=not args.no_network,
        )
        if args.dry_run:
            print(json.dumps(result, indent=2, sort_keys=True))
        return 0 if not result.get("failed") else 1

    if args.command == "create-buffer":
        project_root = args.project_root.resolve() if args.project_root else Path.cwd()
        os.chdir(project_root)
        settings = get_settings(project_root=project_root)
        selected_bundeslaender = args.bundeslaender or settings.geofabrik.bundeslaender
        result = run_create_buffer_pipeline(
            geofabrik_config=settings.legacy_geofabrik_config,
            processing_config=settings.legacy_processing_config,
            selected_bundeslaender=selected_bundeslaender,
            source_folder=args.source_folder,
            output_folder=args.output_folder,
            dry_run=args.dry_run,
        )
        print(json.dumps(result, indent=2, sort_keys=True))
        return 0

    if args.command == "merge-coverage":
        project_root = args.project_root.resolve() if args.project_root else Path.cwd()
        os.chdir(project_root)
        settings = get_settings(project_root=project_root)
        selected_bundeslaender = args.bundeslaender or settings.geofabrik.bundeslaender
        execute = args.execute and not args.dry_run
        logger = None
        if execute:
            logger = logging.getLogger("mapillary_coverage.merge_cli")
            logger.setLevel(logging.INFO)
            if logger.hasHandlers():
                logger.handlers.clear()
            handler = logging.StreamHandler()
            handler.setLevel(logging.INFO)
            handler.setFormatter(logging.Formatter("%(message)s"))
            logger.addHandler(handler)

        result = run_merge_coverage_pipeline(
            geofabrik_config=settings.legacy_geofabrik_config,
            processing_config=settings.legacy_processing_config,
            selected_bundeslaender=selected_bundeslaender,
            output_folder=args.output_folder,
            max_roads=args.max_roads,
            dry_run=not execute,
            logger=logger,
        )
        print(json.dumps(result, indent=2, sort_keys=True))
        return 0 if not result.get("failed") else 1

    if args.command == "export-csv":
        project_root = args.project_root.resolve() if args.project_root else Path.cwd()
        os.chdir(project_root)
        settings = get_settings(project_root=project_root)
        selected_bundeslaender = args.bundeslaender or settings.geofabrik.bundeslaender
        result = run_export_csv_pipeline(
            geofabrik_config=settings.legacy_geofabrik_config,
            processing_config=settings.legacy_processing_config,
            source_output_folder=args.source_output_folder,
            output_folder=args.output_folder,
            selected_bundeslaender=selected_bundeslaender,
            dry_run=args.dry_run,
        )
        print(json.dumps(result, indent=2, sort_keys=True))
        return 0

    parser.print_help()
    return 0