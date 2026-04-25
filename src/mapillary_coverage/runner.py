from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
import subprocess
import sys
from typing import Sequence


@dataclass(frozen=True)
class PipelineStep:
    step_id: str
    label: str
    cli_subcommand: str


PIPELINE_STEPS: tuple[PipelineStep, ...] = (
    PipelineStep(
        step_id="1a",
        label="Prepare OSM network from PBF per Bundesland",
        cli_subcommand="prepare-osm",
    ),
    PipelineStep(
        step_id="1b",
        label="Get Mapillary coverage",
        cli_subcommand="download-mapillary",
    ),
    PipelineStep(
        step_id="2",
        label="Create Mapillary coverage buffer",
        cli_subcommand="create-buffer",
    ),
    PipelineStep(
        step_id="3",
        label="Merge Mapillary coverage with OSM highways",
        cli_subcommand="merge-coverage",
    ),
    PipelineStep(
        step_id="4",
        label="Provide Mapillary OSM coverage CSV",
        cli_subcommand="export-csv",
    ),
)


def get_pipeline_steps() -> list[PipelineStep]:
    return list(PIPELINE_STEPS)


def _truthy_env(value: str | None) -> bool:
    if value is None:
        return False
    return value.strip().lower() in {"1", "true", "yes", "on"}


def build_step_command(
    step: PipelineStep,
    project_root: Path,
    *,
    dry_run: bool = False,
    env: dict[str, str] | None = None,
) -> list[str]:
    effective_env = env or os.environ.copy()
    command = [
        sys.executable,
        "-m",
        "mapillary_coverage",
        step.cli_subcommand,
        "--project-root",
        str(project_root),
    ]

    if step.step_id == "1a":
        if dry_run:
            command.append("--dry-run")
        if _truthy_env(effective_env.get("MAPILLARY_COVERAGE_NO_NETWORK")):
            command.append("--no-network")
        return command

    if step.step_id == "1b":
        if dry_run:
            command.append("--dry-run")
        output_folder = effective_env.get("MAPILLARY_COVERAGE_ML_OUTPUT_FOLDER")
        if output_folder:
            command.extend(["--output-folder", output_folder])
        metadata_output_folder = effective_env.get("MAPILLARY_COVERAGE_OUTPUT_FOLDER")
        if metadata_output_folder:
            command.extend(["--metadata-output-folder", metadata_output_folder])
        tile_cache_folder = effective_env.get("MAPILLARY_COVERAGE_TILE_CACHE_FOLDER")
        if tile_cache_folder:
            command.extend(["--tile-cache-folder", tile_cache_folder])
        limit_tiles = effective_env.get("MAPILLARY_COVERAGE_LIMIT_TILES")
        if limit_tiles:
            command.extend(["--limit-tiles", limit_tiles])
        return command

    if step.step_id == "2":
        if dry_run:
            command.append("--dry-run")
        source_folder = effective_env.get("MAPILLARY_COVERAGE_SOURCE_ML_OUTPUT_FOLDER")
        if source_folder:
            command.extend(["--source-folder", source_folder])
        output_folder = effective_env.get("MAPILLARY_COVERAGE_ML_OUTPUT_FOLDER")
        if output_folder:
            command.extend(["--output-folder", output_folder])
        return command

    if step.step_id == "3":
        if dry_run:
            command.append("--dry-run")
        else:
            command.append("--execute")
        output_folder = effective_env.get("MAPILLARY_COVERAGE_OUTPUT_FOLDER")
        if output_folder:
            command.extend(["--output-folder", output_folder])
        max_roads = effective_env.get("MAPILLARY_COVERAGE_MAX_ROADS")
        if max_roads:
            command.extend(["--max-roads", max_roads])
        return command

    if step.step_id == "4":
        if dry_run:
            command.append("--dry-run")
        source_output_folder = effective_env.get("MAPILLARY_COVERAGE_SOURCE_OUTPUT_FOLDER")
        if source_output_folder:
            command.extend(["--source-output-folder", source_output_folder])
        output_folder = effective_env.get("MAPILLARY_COVERAGE_OUTPUT_FOLDER")
        if output_folder:
            command.extend(["--output-folder", output_folder])
        return command

    return command


def run_step(
    step: PipelineStep,
    project_root: Path,
    *,
    dry_run: bool = False,
    env: dict[str, str] | None = None,
) -> int:
    command = build_step_command(
        step,
        project_root,
        dry_run=dry_run,
        env=env,
    )
    if dry_run:
        print(f"[dry-run] {' '.join(command)}")
        return 0

    completed = subprocess.run(
        command,
        check=False,
        cwd=project_root,
        env=env or os.environ.copy(),
    )
    return completed.returncode


def run_pipeline(
    steps: Sequence[PipelineStep],
    project_root: Path,
    *,
    dry_run: bool = False,
    env: dict[str, str] | None = None,
) -> int:
    for step in steps:
        print(f"Running step {step.step_id}: {step.label}")
        exit_code = run_step(
            step,
            project_root,
            dry_run=dry_run,
            env=env,
        )
        if exit_code != 0:
            return exit_code
        print(f"Finished step {step.step_id}: {step.label}")
    return 0