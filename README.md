# Mapillary Coverage

A set of Jupyter notebooks that return data on which streets (`osm_id`s) have `mapillary_coverage`, either `pano` for 360° imagery or `regular` for standard imagery.

## Process

The process downloads Mapillary sequence coverage tiles for Germany at zoom level 14. These tiles contain lines representing sequences. The sequences are filtered by date, keeping only those newer than 2023-01-01. A buffer of 10 meters is then created around the sequence lines, and the percentage of coverage per road is calculated. The output file includes only `osm_id`s with at least 60% coverage.

This process is not perfect but represents a good compromise in terms of data source, processing time, and the meaningfulness of the results.

## Result

The [`/output`folder](/mapillary_coverage/tree/main/output) holds CSV files of the last runs.

## License
See the [LICENSE](LICENSE.md) file for license rights and limitations (MIT).
