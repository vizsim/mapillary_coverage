#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="${REPO_DIR:-$(cd "${SCRIPT_DIR}/.." && pwd)}"
CSV_PATH="output/germany_osm-highways_mp-coverage_latest.csv"  # HIER anpassen!
README_PATH="output/README.md"

cd "$REPO_DIR"

# ---------------------------
# 📝 Logging: jeder Lauf in logs/run_<ts>.log, alte Läufe aufräumen
# ---------------------------
LOG_DIR="${REPO_DIR}/logs"
mkdir -p "$LOG_DIR"
LOG_FILE="${LOG_DIR}/run_$(date +%Y-%m-%d_%H%M%S).log"
# gesamte Ausgabe (stdout + stderr) zusätzlich ins Logfile spiegeln
exec > >(tee -a "$LOG_FILE") 2>&1
# bequemer Zugriff auf den letzten Lauf: logs/latest.log
ln -sfn "$(basename "$LOG_FILE")" "${LOG_DIR}/latest.log"
# nur die letzten 20 Läufe behalten
ls -1t "${LOG_DIR}"/run_*.log 2>/dev/null | tail -n +21 | xargs -r rm -f || true
echo "📝 Log: $LOG_FILE"

BRANCH="${BRANCH:-$(git rev-parse --abbrev-ref HEAD)}"

if ! docker compose version >/dev/null 2>&1; then
  echo "❌ 'docker compose' (v2) nicht gefunden — wird benötigt."
  exit 127
fi
DOCKER_COMPOSE=(docker compose)

echo "🔄 Git: Hole neuesten Stand auf Branch $BRANCH..."
git checkout "$BRANCH"
git pull --rebase --autostash origin "$BRANCH"

echo "🐳 Starte Docker-Pipeline (mit VPN)..."
cd docker

# 1) Existierende Container sauber runterfahren
"${DOCKER_COMPOSE[@]}" -f docker-compose.yml -f docker-compose.vpn.yml down --remove-orphans || true

# 2) Gluetun separat starten und kurz hochkommen lassen
echo "🛡️ Starte Gluetun..."
"${DOCKER_COMPOSE[@]}" -f docker-compose.yml -f docker-compose.vpn.yml up -d gluetun

echo "⏳ Warte 40 Sekunden auf VPN-Initialisierung..."
sleep 40

# 3) Worker im bereits laufenden VPN starten und echten Worker-Exitcode übernehmen
set +e
"${DOCKER_COMPOSE[@]}" -f docker-compose.yml -f docker-compose.vpn.yml \
  up --build --no-deps --abort-on-container-exit --exit-code-from mapillary_worker mapillary_worker
compose_status=$?
set -e

# 4) Danach alles wieder aufräumen
"${DOCKER_COMPOSE[@]}" -f docker-compose.yml -f docker-compose.vpn.yml down --remove-orphans || true

if [[ "$compose_status" -ne 0 ]]; then
  echo "❌ Docker-Pipeline fehlgeschlagen (Exitcode: $compose_status)"
  exit "$compose_status"
fi

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
# ➕ Dateien zum Commit hinzufügen (Outputs und Metadata)
# ---------------------------
echo "➕ Füge Dateien zum Commit hinzu..."
git add -f "$CSV_PATH"
git add -f "$README_PATH"
git add -f output/ml_metadata.json
git add -f output/osm_metadata.json

# ---------------------------
# 🧹 Prüfen, ob es Änderungen gibt
# ---------------------------
if git diff --cached --quiet; then
  echo "ℹ️ Keine Änderungen an Outputs oder Metadata — nichts zu committen."
  exit 0
fi

# ---------------------------
# ✍️ Commit erstellen
# ---------------------------
COMMIT_MSG="Auto-update: outputs and metadata ($(date -Iseconds))"

echo "✍️ Committe Änderungen: $COMMIT_MSG"
git commit -m "$COMMIT_MSG"

# ---------------------------
# 🚀 Push
# ---------------------------
echo "🚀 Push nach GitHub..."
git push origin "$BRANCH"

echo "🎉 Fertig — Änderungen sind online!"
