#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="${REPO_DIR:-$(cd "${SCRIPT_DIR}/.." && pwd)}"
CSV_PATH="output/germany_osm-highways_mp-coverage_latest.csv"  # HIER anpassen!
README_PATH="output/README.md"
HISTORY_PATH="output/coverage_history.json"

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

# 2) Serverliste aktualisieren, dann Gluetun separat starten.
# Die in gluetun eingebaute Liste enthielt am 14.09.2026 zu 56 % Server, die es
# nicht mehr gibt; gluetun waehlt zufaellig und brauchte dann etliche Anlaeufe.
# Mit aktueller Liste stand der Tunnel im Test beim ersten Versuch nach 6 s.
# Scheitert das Update, geht es mit der zuletzt gespeicherten Liste weiter.
# Image-Version wie in docker-compose.vpn.yml.
echo "🗺️ Aktualisiere VPN-Serverliste..."
mkdir -p "${REPO_DIR}/data/gluetun"
if timeout 300 docker run --rm -v "${REPO_DIR}/data/gluetun:/gluetun" \
     qmcgaw/gluetun:v3.40.0 update -enduser -providers nordvpn >/dev/null 2>&1; then
  echo "✅ Serverliste aktualisiert"
else
  echo "⚠️  Serverliste nicht aktualisiert — nutze die vorhandene"
fi

echo "🛡️ Starte Gluetun..."
"${DOCKER_COMPOSE[@]}" -f docker-compose.yml -f docker-compose.vpn.yml up -d gluetun

# Auf den Healthcheck warten statt fest zu schlafen. Steht der Tunnel noch
# nicht, blockiert gluetun jeden Netzverkehr — der Worker lief dann in
# DNS-Fehler und drehte stundenlang leer (07.09.2026: 62 h, null Ergebnisse).
# Kommt der Tunnel nicht hoch, wird abgebrochen statt blind weiterzumachen.
echo "⏳ Warte auf VPN (Healthcheck, max. ${VPN_WAIT_SECONDS:-900}s)..."
GLUETUN_CID="$("${DOCKER_COMPOSE[@]}" -f docker-compose.yml -f docker-compose.vpn.yml ps -q gluetun)"
vpn_ready=0
for _ in $(seq 1 $(( ${VPN_WAIT_SECONDS:-900} / 5 ))); do
  if [[ "$(docker inspect -f '{{.State.Health.Status}}' "$GLUETUN_CID" 2>/dev/null)" == "healthy" ]]; then
    vpn_ready=1
    break
  fi
  sleep 5
done

if [[ "$vpn_ready" -ne 1 ]]; then
  echo "❌ VPN wurde nicht healthy — Abbruch (Worker wird nicht gestartet)."
  docker logs --tail 30 "$GLUETUN_CID" 2>&1 | sed 's/^/   gluetun| /' || true
  "${DOCKER_COMPOSE[@]}" -f docker-compose.yml -f docker-compose.vpn.yml down --remove-orphans || true
  exit 1
fi
# Exit-IP aus dem gluetun-Log - braucht keinen API-Key.
echo "✅ VPN steht — $(docker logs "$GLUETUN_CID" 2>&1 | grep -a 'Public IP address' | tail -1 | sed 's/.*Public IP address/Exit:/' || echo 'Exit-IP unbekannt')"

# 3) Worker im bereits laufenden VPN starten und echten Worker-Exitcode übernehmen
set +e
"${DOCKER_COMPOSE[@]}" -f docker-compose.yml -f docker-compose.vpn.yml \
  up --build --no-deps --abort-on-container-exit --exit-code-from mapillary_worker mapillary_worker
compose_status=$?
set -e

# 4) gluetun-Log sichern, BEVOR der Container weg ist. Compose hängt nur an den
# Worker-Logs; was das VPN getan hat, war hinterher nicht mehr rekonstruierbar.
docker logs "$GLUETUN_CID" > "${LOG_DIR}/gluetun_latest.log" 2>&1 || true

# 5) Danach alles wieder aufräumen
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
# ☁️ Outputs nach B2 hochladen (öffentliches Archiv → data.vizsim.de/mapillary_coverage)
# ---------------------------
# Der B2-Upload ist der Veröffentlichungsweg für die CSV. Er läuft unabhängig vom
# git-Commit (auch wenn es keine Diffs gibt). Defensive — fehlt b2-CLI/Creds,
# wird nur gewarnt und der Lauf NICHT abgebrochen.
echo "☁️ Lade Outputs nach B2..."
"${SCRIPT_DIR}/upload_outputs_to_b2.sh" || \
  echo "⚠️  B2-Upload meldete einen Fehler — Lauf wird trotzdem fortgesetzt."

# ---------------------------
# ➕ Dateien zum Commit hinzufügen (nur Metadata, nicht die CSV)
# ---------------------------
# Die 33-MB-CSV wird seit dem 16.09.2026 NICHT mehr committet — sie kam über B2
# ohnehin nach data.vizsim.de, und jeder wöchentliche Lauf hat .git um weitere
# 33 MB wachsen lassen (Stand vorher: 346 MB). Die kleinen Begleitdateien bleiben
# im Repo (wenige KB pro Lauf), damit der Stand des letzten Laufs auf GitHub
# sichtbar ist und osm_metadata.json als Cache-Marker im Tree liegen bleibt.
echo "➕ Füge Dateien zum Commit hinzu..."
git add -f "$README_PATH"
git add -f output/ml_metadata.json
git add -f output/osm_metadata.json

# Die History schreibt der Export-Schritt. Beim allerersten Lauf — und wenn der
# Export übersprungen wurde, weil die CSV noch aktuell genug war — gibt es sie
# nicht. `git add -f` auf eine fehlende Datei wäre unter `set -e` ein Abbruch.
if [ -f "$HISTORY_PATH" ]; then
  git add -f "$HISTORY_PATH"
else
  echo "ℹ️ Keine $HISTORY_PATH — Delta-Historie wird beim nächsten Export angelegt."
fi

# ---------------------------
# 🧹 Prüfen, ob es Änderungen gibt
# ---------------------------
if git diff --cached --quiet; then
  echo "ℹ️ Keine Änderungen an Metadata — nichts zu committen."
  echo "🎉 Fertig — CSV liegt unter https://data.vizsim.de/mapillary_coverage/"
  exit 0
fi

# ---------------------------
# ✍️ Commit erstellen
# ---------------------------
COMMIT_MSG="Auto-update: metadata ($(date -Iseconds))"

echo "✍️ Committe Änderungen: $COMMIT_MSG"
git commit -m "$COMMIT_MSG"

# ---------------------------
# 🚀 Push
# ---------------------------
echo "🚀 Push nach GitHub..."
git push origin "$BRANCH"

echo "🎉 Fertig — CSV liegt unter https://data.vizsim.de/mapillary_coverage/"
