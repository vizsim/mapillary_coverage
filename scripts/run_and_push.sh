#!/usr/bin/env bash
set -euo pipefail

REPO_DIR="/home/simon/mapillary_coverage"
BRANCH="feature/docker-notebook"
CSV_PATH="output/germany_osm-highways_mp-coverage_latest.csv"  # HIER anpassen!
README_PATH="output/README.md"

cd "$REPO_DIR"

echo "🔄 Git: Hole neuesten Stand auf Branch $BRANCH..."
git checkout "$BRANCH"
git pull --rebase origin "$BRANCH"

echo "🐳 Starte Docker-Pipeline (mit VPN)..."
cd docker

# 1) Existierende Container sauber runterfahren
docker-compose -f docker-compose.yml -f docker-compose.vpn.yml down --remove-orphans || true

# 2) Worker im VPN laufen lassen (blockierend, bis fertig)
docker-compose -f docker-compose.yml -f docker-compose.vpn.yml up --build mapillary_worker

# Optional: danach alles wieder aufräumen
docker-compose -f docker-compose.yml -f docker-compose.vpn.yml down --remove-orphans

cd ..

echo "✅ Docker-Pipeline fertig."

# ---------------------------
# 🔎 Prüfen, ob Output-Dateien existieren
# ---------------------------

if [ ! -f "$CSV_PATH" ]; then
  echo "❌ CSV nicht gefunden: $CSV_PATH"
  exit 1
fi

if [ ! -f "$README_PATH" ]; then
  echo "❌ README nicht gefunden: $README_PATH"
  exit 1
fi

# ---------------------------
# ➕ Dateien zum Commit hinzufügen (Outputs, Notebooks, Metadata)
# ---------------------------
echo "➕ Füge Dateien zum Commit hinzu..."
git add -f "$CSV_PATH"
git add -f "$README_PATH"
git add -f 1a_prepare_osm-network_from_pbf_bundesland.ipynb
git add -f 1b_get_mapillary_coverage.ipynb
git add -f 2_create_mapillary_coverage_buffer.ipynb
git add -f 3_merge_mp-cov_with_osm_use_case_germany.ipynb
git add -f 4_provide_mp-osm_coverage_csv_new.ipynb
git add -f output/ml_metadata.json
git add -f output/osm_metadata.json

# ---------------------------
# 🧹 Prüfen, ob es Änderungen gibt
# ---------------------------
if git diff --cached --quiet; then
  echo "ℹ️ Keine Änderungen an Outputs, Notebooks oder Metadata — nichts zu committen."
  exit 0
fi

# ---------------------------
# ✍️ Commit erstellen
# ---------------------------
COMMIT_MSG="Auto-update: outputs, notebooks, metadata ($(date -Iseconds))"

echo "✍️ Committe Änderungen: $COMMIT_MSG"
git commit -m "$COMMIT_MSG"

# ---------------------------
# 🚀 Push
# ---------------------------
echo "🚀 Push nach GitHub..."
git push origin "$BRANCH"

echo "🎉 Fertig — Änderungen sind online!"
