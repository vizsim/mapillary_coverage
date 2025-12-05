#!/usr/bin/env bash
set -e

cd /app   # im Container ist /app dein Repo

# tqdm in Docker-Run deaktivieren, damit die Logs nicht zugespammt werden
export TQDM_DISABLE=1

echo "🚀 Starting"
echo

# Hintergrundprozess: RAM alle 5 Sekunden loggen
(
  while true; do
    ts=$(date +"%H:%M:%S")
    mem=$(cat /sys/fs/cgroup/memory.current 2>/dev/null || cat /sys/fs/cgroup/memory/memory.usage_in_bytes)
    mem_mb=$(awk "BEGIN {printf \"%.2f\", $mem/1024/1024}")
    echo "[$ts] RAM usage: ${mem_mb} MB"
    sleep 5
  done
) &

LOGGER_PID=$!


echo "🚀 Running Notebook: 1a"

## braucht peak 7,5gb könnte klappen in 8gb container
jupyter nbconvert \
  --to notebook \
  --inplace \
  --execute 1a_prepare_osm-network_from_pbf_bundesland.ipynb

echo "✅ Notebook 1a execution finished"



echo "🚀 Running Notebook: 1b_get_mapillary_coverage.ipynb"

# hier könntest du später auch config.py generieren od. envs auslesen
jupyter nbconvert \
  --to notebook \
  --inplace \
  --execute 1b_get_mapillary_coverage.ipynb

echo "✅ Notebook 1b execution finished"


echo "🚀 Running Notebook: 2"

jupyter nbconvert \
  --to notebook \
  --inplace \
  --execute 2_create_mapillary_coverage_buffer.ipynb

echo "✅ Notebook 2 execution finished"


echo "🚀 Running Notebook: 3"

jupyter nbconvert \
  --to notebook \
  --inplace \
  --execute 3_merge_mp-cov_with_osm_use_case_germany.ipynb

echo "✅ Notebook 3 execution finished"


echo "🚀 Running Notebook: 4"
jupyter nbconvert \
  --to notebook \
  --inplace \
  --execute 4_provide_mp-osm_coverage_csv_new.ipynb

echo "✅ Notebook 4 execution finished"


# Logger stoppen
kill $LOGGER_PID || true


echo "done."