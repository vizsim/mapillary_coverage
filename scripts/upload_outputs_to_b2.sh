#!/usr/bin/env bash
# ---------------------------------------------------------------------------
# Lädt die Coverage-Outputs nach Backblaze B2 (öffentliches Archiv). Der Bucket
# wird unter https://data.vizsim.de/mapillary_coverage/ ausgeliefert.
# Bucket:  vizsim-public-archive  (Endpoint s3.eu-central-003.backblazeb2.com)
#
# Analog zu mapillary_trafficsigns/scripts/upload_outputs_to_b2.sh — nur dass
# es hier genau EINEN Output-Satz gibt, daher kein SERVICE-Argument.
#
# Defensive: fehlt b2-CLI oder Credentials, wird NUR gewarnt und übersprungen —
# ein Pipeline-Lauf darf daran NICHT scheitern.
# ---------------------------------------------------------------------------
set -euo pipefail
cd "$(dirname "$0")/.."

# b2 wird per `uv tool install b2` nach ~/.local/bin gelegt. Cron hat einen
# minimalen PATH (oft nur /usr/bin:/bin), in dem das fehlt → vorsorglich ergänzen,
# damit `command -v b2` auch im Cron-Kontext greift.
export PATH="$HOME/.local/bin:$PATH"

# Credentials optional aus gitignored docker/.env ziehen (dort liegen schon die
# VPN-Creds). Erwartet: B2_ARCHIVE_KEY_ID / B2_ARCHIVE_KEY.
if [[ -f docker/.env ]]; then
  set -a
  # shellcheck disable=SC1091
  . docker/.env
  set +a
fi

SRC_DIR="output"
DEST="b2://vizsim-public-archive/mapillary_coverage/"

# Was wird hochgeladen? Bewusst OHNE führendes '.*' — b2sdk matcht die Regexes
# per re.match (am Pfad-Anfang verankert), relativ zu SRC_DIR. So trifft die
# CSV-Regex NUR die Top-Level-Datei und NICHT die gleichnamige unter
# output/berlin_de-be/germany_...csv.
INCLUDE_REGEXES=(
  "germany_osm-highways_mp-coverage_latest\.csv$"
  "README\.md$"
  "ml_metadata\.json$"
  "osm_metadata\.json$"
)

# b2-CLI vorhanden?
if ! command -v b2 >/dev/null 2>&1; then
  echo "⚠️  b2-CLI nicht installiert ('uv tool install b2') — B2-Upload übersprungen."
  exit 0
fi

# Credentials vorhanden? Nötig: App-Key mit Schreibrecht auf vizsim-public-archive
# (derselbe Key wie in mapillary_trafficsigns/docker/.env kann wiederverwendet werden).
if [[ -z "${B2_ARCHIVE_KEY_ID:-}" || -z "${B2_ARCHIVE_KEY:-}" ]]; then
  echo "⚠️  B2_ARCHIVE_KEY_ID/B2_ARCHIVE_KEY nicht gesetzt — B2-Upload übersprungen."
  echo "    App-Key mit Schreibrecht auf vizsim-public-archive in docker/.env hinterlegen."
  exit 0
fi

# b2 v4 nutzt diese Env-Vars in-memory und fasst eine ggf. gecachte Default-Auth
# NICHT an — so wird kein fremder Key überschrieben.
export B2_APPLICATION_KEY_ID="$B2_ARCHIVE_KEY_ID"
export B2_APPLICATION_KEY="$B2_ARCHIVE_KEY"

echo "☁️  Sync Coverage-Outputs → $DEST"
# Alles ausschließen, dann gezielt re-includen (CSV + README + Metadata-JSON).
include_args=()
for re in "${INCLUDE_REGEXES[@]}"; do
  include_args+=(--include-regex "$re")
done
# Ohne --delete: alte Stände bleiben (Bucket ist ohnehin 'Keep all versions').
b2 sync --no-progress \
  --exclude-regex ".*" \
  "${include_args[@]}" \
  "$SRC_DIR" "$DEST"

echo "✅ B2-Upload fertig."
