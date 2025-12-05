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

echo "🐳 Starte Docker-Pipeline..."
cd docker
docker-compose up --build
cd ..

echo "✅ Docker-Pipeline fertig."

# ---------------------------
# 🔎 Prüfen, ob Dateien existieren
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
# ➕ Dateien zum Commit hinzufügen
# ---------------------------
echo "➕ Füge Dateien zum Commit hinzu..."
git add "$CSV_PATH"
git add "$README_PATH"

# ---------------------------
# 🧹 Prüfen, ob es Änderungen gibt
# ---------------------------
if git diff --cached --quiet; then
  echo "ℹ️ Keine Änderungen an CSV oder README — nichts zu committen."
  exit 0
fi

# ---------------------------
# ✍️ Commit erstellen
# ---------------------------
COMMIT_MSG="Auto-update CSV + README ($(date -Iseconds))"

echo "✍️ Committe Änderungen: $COMMIT_MSG"
git commit -m "$COMMIT_MSG"

# ---------------------------
# 🚀 Push
# ---------------------------
echo "🚀 Push nach GitHub..."
git push origin "$BRANCH"

echo "🎉 Fertig — Änderungen sind online!"








