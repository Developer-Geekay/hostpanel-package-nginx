#!/usr/bin/env bash
# Build hostpanel-nginx-<version>.zip for upload via the HostPanel Package Manager.
# The repo layout IS the zip layout — no staging needed.
# bin/nginx must be a compiled ARM64 binary committed to the repo.
set -euo pipefail

VERSION=$(python3 -c "import re; print(re.search(r'version=[\"\\x27]([^\"\\x27]+)', open('plugin/setup.py').read()).group(1))")
OUT="hostpanel-nginx-${VERSION}.zip"

echo "Building ${OUT}..."
rm -f "$OUT"

zip -r "$OUT" plugin/ bin/ conf/ service/ sudoers/ \
    --exclude "*/__pycache__/*" --exclude "*.pyc"

echo "Done -> ${OUT}"
