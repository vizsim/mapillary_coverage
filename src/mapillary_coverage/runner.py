from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys
from typing import Sequence

from mapillary_coverage.notebooks import NotebookSpec


def build_nbconvert_command(notebook_path: Path) -> list[str]:
    return [
        "jupyter",
        "nbconvert",
        "--to",
        "notebook",
        "--inplace",
        "--execute",
        str(notebook_path.name),
    ]


def _truthy_env(value: str | None) -> bool:
    if value is None:
        return False
    return value.strip().lower() in {"1", "true", "yes", "on"}


def build_step_command(
    notebook: NotebookSpec,
    project_root: Path,
    *,
    dry_run: bool = False,
    env: dict[str, str] | None = None,
) -> list[str]:
    notebook_path = notebook.path(project_root)
    if not notebook_path.exists():
        raise FileNotFoundError(f"Notebook not found: {notebook_path}")

    if notebook.cli_subcommand is None:
        return build_nbconvert_command(notebook_path)

    effective_env = env or os.environ.copy()
    command = [
        sys.executable,
        "-m",
        "mapillary_coverage",
        notebook.cli_subcommand,
        "--project-root",
        str(project_root),
    ]

    if notebook.step_id == "1a":
        if dry_run:
            command.append("--dry-run")
        if _truthy_env(effective_env.get("MAPILLARY_COVERAGE_NO_NETWORK")):
            command.append("--no-network")
        return command

    if notebook.step_id == "1b":
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

    if notebook.step_id == "2":
        if dry_run:
            command.append("--dry-run")
        source_folder = effective_env.get("MAPILLARY_COVERAGE_SOURCE_ML_OUTPUT_FOLDER")
        if source_folder:
            command.extend(["--source-folder", source_folder])
        output_folder = effective_env.get("MAPILLARY_COVERAGE_ML_OUTPUT_FOLDER")
        if output_folder:
            command.extend(["--output-folder", output_folder])
        return command

    if notebook.step_id == "3":
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

    if notebook.step_id == "4":
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


def run_notebook(
    notebook: NotebookSpec,
    project_root: Path,
    *,
    dry_run: bool = False,
    env: dict[str, str] | None = None,
) -> int:
    command = build_step_command(
        notebook,
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
    notebooks: Sequence[NotebookSpec],
    project_root: Path,
    *,
    dry_run: bool = False,
    env: dict[str, str] | None = None,
) -> int:
    for notebook in notebooks:
        print(f"Running notebook {notebook.step_id}: {notebook.filename}")
        exit_code = run_notebook(
            notebook,
            project_root,
            dry_run=dry_run,
            env=env,
        )
        if exit_code != 0:
            return exit_code
        print(f"Finished notebook {notebook.step_id}: {notebook.filename}")
    return 0