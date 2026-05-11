#!/usr/bin/env bash
# Builds hostpanel-nginx-<version>.zip for upload via the HostPanel Package Manager
set -euo pipefail

VERSION=$(python3 -c "import re; print(re.search(r\"version='(.+?)'\", open('setup.py').read()).group(1))")
OUT="hostpanel-nginx-${VERSION}.zip"

echo "Building ${OUT}..."
rm -f "$OUT"
zip -r "$OUT" \
    hostpanel_nginx/ \
    setup.py \
    service/ \
    conf/ \
    --exclude "**/__pycache__/*" --exclude "**/*.pyc"

echo "Done → ${OUT}"
