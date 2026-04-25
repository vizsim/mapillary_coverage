from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class NotebookSpec:
    step_id: str
    filename: str
    label: str
    default_pipeline: bool = True
    cli_subcommand: str | None = None

    def path(self, project_root: Path) -> Path:
        return project_root / self.filename


NOTEBOOK_SPECS: tuple[NotebookSpec, ...] = (
    NotebookSpec(
        step_id="0",
        filename="0_prepare_tiles.ipynb",
        label="Prepare tiles",
        default_pipeline=False,
    ),
    NotebookSpec(
        step_id="1a",
        filename="1a_prepare_osm-network_from_pbf_bundesland.ipynb",
        label="Prepare OSM network from PBF per Bundesland",
        cli_subcommand="prepare-osm",
    ),
    NotebookSpec(
        step_id="1b",
        filename="1b_get_mapillary_coverage.ipynb",
        label="Get Mapillary coverage",
        cli_subcommand="download-mapillary",
    ),
    NotebookSpec(
        step_id="2",
        filename="2_create_mapillary_coverage_buffer.ipynb",
        label="Create Mapillary coverage buffer",
        cli_subcommand="create-buffer",
    ),
    NotebookSpec(
        step_id="3",
        filename="3_merge_mp-cov_with_osm_use_case_germany.ipynb",
        label="Merge Mapillary coverage with OSM highways",
        cli_subcommand="merge-coverage",
    ),
    NotebookSpec(
        step_id="4",
        filename="4_provide_mp-osm_coverage_csv_new.ipynb",
        label="Provide Mapillary OSM coverage CSV",
        cli_subcommand="export-csv",
    ),
)

NOTEBOOKS_BY_ID = {spec.step_id: spec for spec in NOTEBOOK_SPECS}
DEFAULT_PIPELINE_STEP_IDS = tuple(
    spec.step_id for spec in NOTEBOOK_SPECS if spec.default_pipeline
)


def get_notebook(step_id: str) -> NotebookSpec:
    try:
        return NOTEBOOKS_BY_ID[step_id]
    except KeyError as error:
        available = ", ".join(NOTEBOOKS_BY_ID)
        raise KeyError(f"Unknown notebook step '{step_id}'. Available: {available}") from error


def get_pipeline(include_prepare_tiles: bool = False) -> list[NotebookSpec]:
    step_ids = list(DEFAULT_PIPELINE_STEP_IDS)
    if include_prepare_tiles:
        step_ids.insert(0, "0")
    return [get_notebook(step_id) for step_id in step_ids]