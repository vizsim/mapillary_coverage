#!/usr/bin/env python3
"""Rekonstruiert output/coverage_history.json aus der git-History.

Einmal-Werkzeug (16.09.2026): Die Delta-Spalten im output/README.md brauchen die
Zahlen vergangener Läufe. Die stehen bereits in git — jeder `Auto-update`-Commit
hat eine output/README.md mit der Bundesland-Tabelle. Dieses Skript liest sie
rückwärts aus und schreibt daraus die History-Datei.

Berücksichtigt werden nur Läufe mit ROLLENDEM Mapillary-Fenster. Bis zum Lauf
2026-03-31 (Commit 65cb5af) stand der Fensteranfang fix auf 2023-01-01, erst
e1e35ce stellte auf `freshness_lookback_months` um. Ein Delta über diese Grenze
hinweg würde den Methodenwechsel als echte Veränderung ausweisen — die Zahlen
davor sind schlicht nicht vergleichbar. Erkannt wird das am Fenster selbst:
rollend heißt Ende minus `freshness_lookback_months` == Anfang.

Noch älter (vor 2025-12-11) hatte das README gar keine Bundesland-Tabelle, nur
Kopfzeilen im `**Key:** value<br>`-Format — diese Commits sind ohnehin raus.

Idempotent — schreibt die History jedes Mal komplett neu.

Aufruf (aus dem Repo-Wurzelverzeichnis):
    .venv/bin/python scripts/backfill_coverage_history.py --dry-run
    .venv/bin/python scripts/backfill_coverage_history.py
    .venv/bin/python scripts/backfill_coverage_history.py --readme   # + README neu rendern
    .venv/bin/python scripts/backfill_coverage_history.py --limit 5  # nur die neuesten 5
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from datetime import date
from pathlib import Path

REPO_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_DIR / "src"))

import pandas as pd  # noqa: E402
from dateutil.relativedelta import relativedelta  # noqa: E402

import mapillary_coverage.export as ex  # noqa: E402
from mapillary_coverage.settings import get_settings  # noqa: E402

OUTPUT_DIR = REPO_DIR / "output"
README_IN_GIT = "output/README.md"

# Das Fensterende schwankt um einen Tag (Laufzeitpunkt vs. Zeitzone), deshalb
# nicht auf Tagesgleichheit prüfen.
ROLLING_TOLERANCE_DAYS = 3

# "| DE-BB | 27,153.92 | 36,545.80 | 2026-09-13 | 2026-09-15 |"
ROW = re.compile(
    r"^\|\s*(DE-\w\w)\s*\|\s*([\d,]+\.\d+)\s*\|\s*([\d,]+\.\d+)\s*\|\s*([\d-]+|N/A)\s*\|\s*([\d-]+|N/A)\s*\|",
    re.M,
)
# Greift auf beide README-Generationen: "**Key:** value" und "| **Key** | value |".
CREATED = re.compile(r"\*\*Data created\*\*:?\s*\|?\s*(\d{4}-\d{2}-\d{2})")
OSM_DATA = re.compile(r"\*\*OSM data\*\*:?\s*\|?\s*(\d{4}-\d{2}-\d{2})")
ML_DATA = re.compile(r"\*\*Mapillary data\*\*:?\s*\|?\s*(\d{4}-\d{2}-\d{2})\s*→\s*(\d{4}-\d{2}-\d{2})")
BUFFER = re.compile(r"\*\*Buffer distance\*\*:?\s*\|?\s*(\d+)")
THRESHOLD = re.compile(r"\*\*Coverage ratio threshold\*\*:?\s*\|?\s*([\d.]+)")


def _git(*args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=REPO_DIR, capture_output=True, text=True, check=True
    ).stdout


def _km(raw: str) -> float:
    return round(float(raw.replace(",", "")), 2)


def parse_readme(text: str) -> dict | None:
    """Einen Lauf aus einem README-Stand lesen. None, wenn das Format zu alt ist."""
    created = CREATED.search(text)
    window = ML_DATA.search(text)
    rows = ROW.findall(text)
    if not created or not window or not rows:
        return None
    return {
        "date": created.group(1),
        "window": (date.fromisoformat(window.group(1)), date.fromisoformat(window.group(2))),
        "bundeslaender": {bl: {"pano": _km(pano), "regular": _km(regular)} for bl, pano, regular, _, _ in rows},
        "osm_bundeslaender": {bl: osm for bl, _, _, osm, _ in rows},
        "ml_bundeslaender": {bl: ml for bl, _, _, _, ml in rows},
        "text": text,
    }


def uses_rolling_window(run: dict, lookback_months: int) -> bool:
    """Rollend = Fensteranfang liegt `lookback_months` vor dem Fensterende."""
    start, end = run["window"]
    return abs((end - relativedelta(months=lookback_months) - start).days) <= ROLLING_TOLERANCE_DAYS


def collect_runs(lookback_months: int) -> tuple[list[dict], list[str]]:
    """Läufe mit rollendem Fenster, chronologisch aufsteigend."""
    shas = _git("log", "--format=%H", "--", README_IN_GIT).split()
    runs: list[dict] = []
    skipped: list[str] = []
    for sha in reversed(shas):
        try:
            text = _git("show", f"{sha}:{README_IN_GIT}")
        except subprocess.CalledProcessError:
            skipped.append(f"{sha[:7]}          Datei im Commit nicht vorhanden")
            continue
        run = parse_readme(text)
        if run is None:
            skipped.append(f"{sha[:7]}          altes README-Format ohne Bundesland-Tabelle")
            continue
        if not uses_rolling_window(run, lookback_months):
            start, end = run["window"]
            skipped.append(f"{sha[:7]}  {run['date']}  festes Fenster ab {start} (bis {end})")
            continue
        run["sha"] = sha[:7]
        runs.append(run)
    return runs, skipped


def render_readme(run: dict, previous_totals: dict) -> str:
    """Den Lauf im neuen Format neu rendern — gleiche Zahlen, plus Delta-Spalten."""
    text = run["text"]
    start, end = run["window"]
    metadata = {
        "osm_data_from": OSM_DATA.search(text).group(1),
        "ml_data_from": end.isoformat(),
        "freshness_cutoff_berlin": start.isoformat(),
        "osm_bundeslaender": run["osm_bundeslaender"],
        "ml_bundeslaender": run["ml_bundeslaender"],
    }
    processing = {
        "buffer_distance": int(BUFFER.search(text).group(1)),
        "mp_coverage_ratio_threshold": float(THRESHOLD.search(text).group(1)),
    }
    rows = [
        {"Bundesland": bl, "Typ": typ, "Gesamtlänge (km)": values[typ]}
        for bl, values in run["bundeslaender"].items()
        for typ in ("pano", "regular")
    ]
    return ex.create_readme(
        pd.DataFrame(rows),
        metadata,
        processing,
        previous_totals=previous_totals,
        run_date=run["date"],
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--limit", type=int, metavar="N", help="nur die N neuesten Läufe übernehmen")
    parser.add_argument("--readme", action="store_true", help="output/README.md im neuen Format neu schreiben")
    parser.add_argument("--dry-run", action="store_true", help="nur zeigen, was übernommen würde")
    args = parser.parse_args()

    lookback_months = get_settings().processing.freshness_lookback_months
    runs, skipped = collect_runs(lookback_months)
    if not runs:
        print("❌ Keine Läufe mit rollendem Fenster gefunden.")
        return 1

    if args.limit:
        runs = runs[-args.limit :]

    print(f"Rollendes Fenster: {lookback_months} Monate (config/default.toml)\n")
    print(f"Übernommen ({len(runs)}):")
    for run in runs:
        start, end = run["window"]
        print(f"  {run['sha']}  {run['date']}  {len(run['bundeslaender'])} BL  Fenster {start} → {end}")
    print(f"\nÜbersprungen ({len(skipped)}):")
    for entry in skipped:
        print(f"  {entry}")

    if args.dry_run:
        print("\n(dry-run — nichts geschrieben)")
        return 0

    history = ex.history_output_path(str(OUTPUT_DIR))
    history.unlink(missing_ok=True)
    for run in runs:
        ex.append_coverage_history(str(OUTPUT_DIR), run["date"], run["bundeslaender"], emit=None)

    written = ex.load_coverage_history(str(OUTPUT_DIR), emit=None)
    print(f"\n✅ {history.name}: {len(written)} Läufe ({written[0]['date']} bis {written[-1]['date']})")

    if args.readme:
        # Referenz ist der Stand VOR dem letzten Lauf — deshalb ohne dessen Eintrag.
        newest = runs[-1]
        previous_totals = ex.latest_totals_per_bundesland(
            [entry for entry in written if entry["date"] != newest["date"]]
        )
        readme_path = ex.readme_output_path(str(OUTPUT_DIR))
        readme_path.write_text(render_readme(newest, previous_totals), encoding="utf-8")
        print(f"✅ {readme_path.name} neu gerendert (Lauf {newest['date']}, Commit {newest['sha']})")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
