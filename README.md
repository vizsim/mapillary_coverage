# Mapillary Coverage

A pipeline for determining which streets (`osm_id`s) have `mapillary_coverage`, either `pano` for 360° imagery or `regular` for standard imagery.
For detailed information on Mapillary coverage tiles, refer to the [official Mapillary API documentation](https://www.mapillary.com/developer/api-documentation?locale=de_DE#coverage-tiles-computed).

The repository still contains the original notebooks, but the main pipeline steps can now be executed through the Python package and CLI as well.

## Secrets

Do not commit the Mapillary API token into the repository.

Use one of these two paths instead:

- Set `MAPILLARY_ACCESS_TOKEN` in the shell or server environment.
- Copy `config/local.toml.example` to `config/local.toml` and set the token there. `config/local.toml` is ignored by git.

If no token is configured, the Mapillary download step fails fast with a clear error message.

## Process

The process downloads Mapillary sequence coverage tiles for Germany at zoom level 14. These tiles contain lines representing sequences. The sequences are filtered by date, keeping only those captured on or after a **rolling cutoff**: Berlin local midnight of the processing day minus **30 months** (2.5 years). A buffer of 10 meters is then created around the sequence lines, and the percentage of coverage per road is calculated. The output file includes only `osm_id`s with at least 60% coverage.

This process is not perfect but represents a good compromise in terms of data source, processing time, and the meaningfulness of the results.

## CLI Workflow

After creating or activating the virtual environment, the package can be executed through `python -m mapillary_coverage ...` or the console script `mapillary-coverage ...`.

Useful commands:

- `mapillary-coverage show-config`
- `mapillary-coverage list-notebooks`
- `mapillary-coverage run-pipeline --dry-run`
- `mapillary-coverage prepare-osm --dry-run --no-network --bundeslaender DE-HH`
- `mapillary-coverage download-mapillary --dry-run --bundeslaender DE-HH`
- `mapillary-coverage create-buffer --dry-run --bundeslaender DE-HH`
- `mapillary-coverage merge-coverage --dry-run --bundeslaender DE-HH`
- `mapillary-coverage export-csv --dry-run --bundeslaender DE-HH`

The production shell entrypoint is [scripts/run_mapillary_notebooks.sh](/home/simon/mapillary_coverage/scripts/run_mapillary_notebooks.sh). Despite the historic name, it now delegates to the CLI pipeline runner.

## Targeted Validation

Long-running steps can be validated on a smaller slice before starting a full Germany run.

Example: real Hamburg-only Mapillary download test with a tile limit and temporary output folders:

```bash
OUT_DIR="$(mktemp -d /tmp/mapillary-hh-out-XXXXXX)"
META_DIR="$(mktemp -d /tmp/mapillary-hh-meta-XXXXXX)"
TQDM_DISABLE=1 mapillary-coverage download-mapillary \
  --bundeslaender DE-HH \
  --limit-tiles 20 \
  --output-folder "$OUT_DIR" \
  --metadata-output-folder "$META_DIR"
```

This exercises the real download path without overwriting the normal repository outputs.

## Interrupted Runs

If a terminal shows `exit code: 130`, that means the process was interrupted, usually via `Ctrl+C`. It does not by itself indicate a code defect.

## Result

The [`/output` folder](https://github.com/vizsim/mapillary_coverage/tree/main/output) holds CSV files of the last runs.

## License

See the [LICENSE](LICENSE) file for license rights and limitations (MIT).
