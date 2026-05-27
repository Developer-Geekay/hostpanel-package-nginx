#!/usr/bin/env bash
# Build hostpanel-nginx-<version>.zip for upload via the HostPanel Package Manager.
# No frontend compilation — frontend/main.js is hand-written.
set -euo pipefail

VERSION=$(python3 -c "import re; print(re.search(r'version=[\"\\x27]([^\"\\x27]+)', open('plugin/setup.py').read()).group(1))")
OUT="hostpanel-nginx-${VERSION}.zip"

echo "Building ${OUT}..."
rm -f "$OUT"

zip -r "$OUT" plugin/ bin/ conf/ service/ sudoers/ frontend/ \
    --exclude "*/__pycache__/*" --exclude "*.pyc"

echo "Done -> ${OUT}"
