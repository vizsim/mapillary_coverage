"""Tests fuer den README-Export: Delta-Spalten, Ausrichtung und Coverage-History.

Ohne Netz und ohne Pipeline-Lauf: gearbeitet wird auf einem handgebauten
summary_df, die History liegt in tmp_path.
Ausfuehren: .venv/bin/python -m pytest
"""

import json

import pandas as pd
import pytest

import mapillary_coverage.export as ex

METADATA = {
    "osm_data_from": "2026-09-13T00:00:00",
    "ml_data_from": "2026-09-15T00:00:00",
    "freshness_cutoff_berlin": "2024-03-14T00:00:00",
    "osm_bundeslaender": {"DE-BB": "2026-09-13T00:00:00", "DE-HB": "2026-09-13T00:00:00"},
    "ml_bundeslaender": {"DE-BB": "2026-09-15T00:00:00", "DE-HB": "2026-09-15T00:00:00"},
}
PROCESSING = {"buffer_distance": 10, "mp_coverage_ratio_threshold": 0.6}


def _summary_df(values):
    """values: {Bundesland: (pano_km, regular_km)}"""
    rows = []
    for bundesland, (pano, regular) in values.items():
        rows.append({"Bundesland": bundesland, "Typ": "pano", "Gesamtlänge (km)": pano})
        rows.append({"Bundesland": bundesland, "Typ": "regular", "Gesamtlänge (km)": regular})
    return pd.DataFrame(rows)


def _row(readme, bundesland):
    return next(line for line in readme.splitlines() if line.startswith(f"| {bundesland} "))


# --------------------------------------------------------------------------
# Tabellen-Kopf: englische Header, Zahlen rechtsbuendig
# --------------------------------------------------------------------------


def test_summary_header_is_english_and_right_aligned():
    readme = ex.create_readme(_summary_df({"DE-BB": (27153.92, 36545.80)}), METADATA, PROCESSING)

    assert "| Bundesland | Pano (km) | Δ Pano (km) | Regular (km) | Δ Regular (km) | OSM Date | Mapillary Date |" in readme
    assert "Datum" not in readme
    # Zahlenspalten rechtsbuendig (---:), Textspalten links (:---).
    assert "|:-----------|----------:|------------:|-------------:|---------------:|:---------|:---------------|" in readme


def test_property_table_values_are_right_aligned():
    readme = ex.create_readme(_summary_df({"DE-BB": (1.0, 2.0)}), METADATA, PROCESSING)

    assert "| Property | Value |\n|:---------|------:|" in readme


# --------------------------------------------------------------------------
# Delta-Spalten
# --------------------------------------------------------------------------


def test_delta_shows_signed_difference_to_previous_run():
    previous = {"DE-BB": {"pano": 27000.00, "regular": 36600.00, "date": "2026-09-08"}}

    readme = ex.create_readme(
        _summary_df({"DE-BB": (27153.92, 36545.80)}),
        METADATA,
        PROCESSING,
        previous_totals=previous,
        run_date="2026-09-15",
    )

    row = _row(readme, "DE-BB")
    assert "| +153.92 |" in row  # mehr Pano
    assert "| -54.20 |" in row  # weniger Regular
    assert "| **Previous run** | 2026-09-08 |" in readme
    assert "change since the previous run (2026-09-08)" in readme


def test_delta_is_empty_without_history():
    readme = ex.create_readme(_summary_df({"DE-BB": (1.0, 2.0)}), METADATA, PROCESSING, run_date="2026-09-15")

    row = _row(readme, "DE-BB")
    assert row.count(ex.NO_VALUE) == 2
    assert "**Previous run**" not in readme
    assert "stay empty until a second run" in readme


def test_delta_falls_back_for_bundesland_missing_from_history():
    previous = {"DE-BB": {"pano": 1.0, "regular": 1.0, "date": "2026-09-08"}}

    readme = ex.create_readme(
        _summary_df({"DE-BB": (2.0, 2.0), "DE-HB": (5.0, 5.0)}),
        METADATA,
        PROCESSING,
        previous_totals=previous,
        run_date="2026-09-15",
    )

    assert "| +1.00 |" in _row(readme, "DE-BB")
    assert _row(readme, "DE-HB").count(ex.NO_VALUE) == 2


def test_mixed_reference_dates_are_reported_as_span():
    previous = {
        "DE-BB": {"pano": 1.0, "regular": 1.0, "date": "2026-09-08"},
        "DE-HB": {"pano": 1.0, "regular": 1.0, "date": "2026-08-25"},
    }

    readme = ex.create_readme(
        _summary_df({"DE-BB": (2.0, 2.0), "DE-HB": (2.0, 2.0)}),
        METADATA,
        PROCESSING,
        previous_totals=previous,
        run_date="2026-09-15",
    )

    assert "| **Previous run** | 2026-08-25 – 2026-09-08 |" in readme
    assert "covered only a subset" in readme


@pytest.mark.parametrize(
    "current, previous, expected",
    [
        (100.0, 90.0, "+10.00"),
        (90.0, 100.0, "-10.00"),
        (100.0, 100.0, "+0.00"),
        (1234.5, 0.0, "+1,234.50"),
        (100.0, None, ex.NO_VALUE),
        (100.0, "kaputt", ex.NO_VALUE),
    ],
)
def test_format_delta(current, previous, expected):
    assert ex.format_delta(current, previous) == expected


# --------------------------------------------------------------------------
# History-Datei
# --------------------------------------------------------------------------


def test_history_roundtrip(tmp_path):
    folder = str(tmp_path)
    ex.append_coverage_history(folder, "2026-09-15", {"DE-BB": {"pano": 1.0, "regular": 2.0}}, emit=None)

    runs = ex.load_coverage_history(folder, emit=None)
    assert runs == [{"date": "2026-09-15", "bundeslaender": {"DE-BB": {"pano": 1.0, "regular": 2.0}}}]


def test_history_missing_file_is_not_an_error(tmp_path):
    assert ex.load_coverage_history(str(tmp_path), emit=None) == []


def test_history_corrupt_file_is_not_an_error(tmp_path):
    ex.history_output_path(str(tmp_path)).write_text("{kein json", encoding="utf-8")

    assert ex.load_coverage_history(str(tmp_path), emit=None) == []


def test_same_day_rerun_updates_instead_of_appending(tmp_path):
    """Sonst waere die Referenz des naechsten Laufs der Rerun von heute."""
    folder = str(tmp_path)
    ex.append_coverage_history(folder, "2026-09-15", {"DE-BB": {"pano": 1.0, "regular": 1.0}}, emit=None)
    ex.append_coverage_history(folder, "2026-09-15", {"DE-HB": {"pano": 5.0, "regular": 5.0}}, emit=None)

    runs = ex.load_coverage_history(folder, emit=None)
    assert len(runs) == 1
    assert set(runs[0]["bundeslaender"]) == {"DE-BB", "DE-HB"}


def test_latest_totals_prefers_most_recent_run_containing_the_bundesland():
    runs = [
        {"date": "2026-09-01", "bundeslaender": {"DE-BB": {"pano": 1.0, "regular": 1.0}, "DE-HB": {"pano": 9.0, "regular": 9.0}}},
        # Teilmengen-Lauf (config/local.toml-Override): nur DE-BB.
        {"date": "2026-09-08", "bundeslaender": {"DE-BB": {"pano": 2.0, "regular": 2.0}}},
    ]

    totals = ex.latest_totals_per_bundesland(runs)

    assert totals["DE-BB"] == {"pano": 2.0, "regular": 2.0, "date": "2026-09-08"}
    assert totals["DE-HB"] == {"pano": 9.0, "regular": 9.0, "date": "2026-09-01"}


def test_summary_totals_matches_history_shape():
    totals = ex.summary_totals(_summary_df({"DE-BB": (27153.921, 36545.804)}))

    assert totals == {"DE-BB": {"pano": 27153.92, "regular": 36545.8}}


def test_history_survives_a_full_cycle(tmp_path):
    """Lauf 1 schreibt History, Lauf 2 liest sie und zeigt das Delta."""
    folder = str(tmp_path)
    ex.append_coverage_history(folder, "2026-09-08", ex.summary_totals(_summary_df({"DE-BB": (100.0, 200.0)})), emit=None)

    previous = ex.latest_totals_per_bundesland(ex.load_coverage_history(folder, emit=None))
    readme = ex.create_readme(
        _summary_df({"DE-BB": (150.0, 180.0)}),
        METADATA,
        PROCESSING,
        previous_totals=previous,
        run_date="2026-09-15",
    )

    row = _row(readme, "DE-BB")
    assert "| +50.00 |" in row
    assert "| -20.00 |" in row


def test_history_file_is_valid_json_with_trailing_newline(tmp_path):
    folder = str(tmp_path)
    ex.append_coverage_history(folder, "2026-09-15", {"DE-BB": {"pano": 1.0, "regular": 2.0}}, emit=None)

    raw = ex.history_output_path(folder).read_text(encoding="utf-8")
    assert raw.endswith("\n")
    assert json.loads(raw)["runs"][0]["date"] == "2026-09-15"
