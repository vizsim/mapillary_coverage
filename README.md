# Mapillary Coverage

A pipeline for determining which streets (`osm_id`s) have `mapillary_coverage`, either `pano` for 360° imagery or `regular` for standard imagery.
For detailed information on Mapillary coverage tiles, refer to the [official Mapillary API documentation](https://www.mapillary.com/developer/api-documentation?locale=de_DE#coverage-tiles-computed).

The production workflow is CLI-only.

## Process

The process downloads Mapillary sequence coverage tiles for Germany at zoom level 14. These tiles contain lines representing sequences. The sequences are filtered by date, keeping only those captured on or after a **rolling cutoff**: Berlin local midnight of the processing day minus **30 months** (2.5 years). A buffer of 10 meters is then created around the sequence lines, and the percentage of coverage per road is calculated. The output file includes only `osm_id`s with at least 60% coverage.

This process is not perfect but represents a good compromise in terms of data source, processing time, and the meaningfulness of the results.

## Configuration

The config surface is now:

- `config/default.toml`: tracked project defaults
- `config/local.toml`: optional local overrides, ignored by git
- `config/local.toml.example`: copy template for local overrides
- `docker/.env`: optional VPN credentials for the Gluetun sidecar
- `docker/.env.example`: example for the VPN environment file

Default internal paths are now grouped more clearly:

- `resources/bundeslaender.geojson`: checked-in reference geometry
- `data/cache/tile_cache`: checked-in tile cache JSONs
- `data/osm/raw`: downloaded Geofabrik PBFs
- `data/osm/processed`: processed OSM highway PBFs
- `data/mapillary/coverage`: intermediate Mapillary artifacts and logs
- `output`: final externally consumed deliverables

## Local Setup

```bash
uv sync
cp config/local.toml.example config/local.toml
```

Set the Mapillary token in `config/local.toml`:

```toml
[mapillary]
access_token = "..."
```

## CLI Workflow

After `uv sync`, the package can be executed through `uv run mapillary-coverage ...`, `python -m mapillary_coverage ...`, or the console script `mapillary-coverage ...` from the synced `.venv`.

Useful commands:

- `mapillary-coverage show-config`
- `mapillary-coverage run-pipeline --dry-run`
- `mapillary-coverage prepare-osm --dry-run --no-network --bundeslaender DE-HH`
- `mapillary-coverage download-mapillary --dry-run --bundeslaender DE-HH`
- `mapillary-coverage create-buffer --dry-run --bundeslaender DE-HH`
- `mapillary-coverage merge-coverage --dry-run --bundeslaender DE-HH`
- `mapillary-coverage export-csv --dry-run --bundeslaender DE-HH`

The production shell entrypoint is **scripts/run_mapillary_pipeline.sh**

## Docker / Server Run

Validated server setup uses Docker Compose v2 plus the checked-out repository state on disk.

First-time server preparation:

```bash
cp config/local.toml.example config/local.toml
cp docker/.env.example docker/.env
mkdir -p output data/osm/raw data/osm/processed data/mapillary/coverage
```

Set the Mapillary token in `config/local.toml` and, when using VPN, set `NORD_USER` and `NORD_PASS` in `docker/.env`.

Check Compose v2:

```bash
docker compose version
```

Start the full pipeline with VPN:

```bash
cd docker
docker compose -f docker-compose.yml -f docker-compose.vpn.yml up --build mapillary_worker
```

Stop and clean up:

```bash
cd docker
docker compose -f docker-compose.yml -f docker-compose.vpn.yml down --remove-orphans
```

For a smaller validation run, temporarily set a subset in `config/local.toml`, for example:

```toml
[geofabrik]
bundeslaender = ["DE-HB"]
```

Remove the override again before a full Germany run.

## Result

The [`/output` folder](https://github.com/vizsim/mapillary_coverage/tree/main/output) holds CSV files of the last runs.

## License

See the [LICENSE](LICENSE) file for license rights and limitations (MIT).
