#!/bin/bash
# Re-syncs this webapp's data/ folder from the master DB and dedupe report at
# the MVP project (where the scrapers and build_*.py scripts live). Run this
# after re-running any scripts/build_*.py or dedupe_ncsl_fpf.py there, then
# restart app.py to pick up the changes.
set -e
MVP="/Users/katebarranco/Desktop/MVP/State-Federal AI Legislation Tracker"
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cp "$MVP/data/ai_legislation.db" "$HERE/data/"
cp "$MVP/data/dedupe_report_ncsl_fpf.json" "$HERE/data/"
echo "Synced ai_legislation.db and dedupe_report_ncsl_fpf.json from $MVP"
