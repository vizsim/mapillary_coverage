# Mapillary Coverage

A set of Jupyter notebooks that return data on which streets (`osm_id`s) have `mapillary_coverage`, either `pano` for 360° imagery or `regular` for standard imagery.
For detailed information on Mapillary coverage tiles, refer to the [official Mapillary API documentation](https://www.mapillary.com/developer/api-documentation?locale=de_DE#coverage-tiles-computed).

## Process

The process downloads Mapillary sequence coverage tiles for Germany at zoom level 14. These tiles contain lines representing sequences. The sequences are filtered by date, keeping only those captured on or after a **rolling cutoff**: Berlin local midnight of the processing day minus **30 months** (2.5 years). A buffer of 10 meters is then created around the sequence lines, and the percentage of coverage per road is calculated. The output file includes only `osm_id`s with at least 60% coverage.

This process is not perfect but represents a good compromise in terms of data source, processing time, and the meaningfulness of the results.

## Result

The [`/output` folder](https://github.com/vizsim/mapillary_coverage/tree/main/output) holds CSV files of the last runs.

## License

See the [LICENSE](LICENSE) file for license rights and limitations (MIT).
