#!/usr/bin/env bash
# Builds hostpanel-nginx-<version>.zip for upload via the HostPanel Package Manager
set -euo pipefail

VERSION=$(python3 -c "import re; print(re.search(r'version=[\"\\x27]([^\"\\x27]+)', open('setup.py').read()).group(1))")
OUT="hostpanel-nginx-${VERSION}.zip"

echo "Building ${OUT}..."
rm -f "$OUT"

# Assemble plugin/ subdir (pip-installable root expected by package manager)
mkdir -p plugin
cp -r hostpanel_nginx setup.py plugin/

zip -r "$OUT" \
    plugin/ \
    service/ \
    conf/ \
    --exclude "**/__pycache__/*" --exclude "**/*.pyc"

rm -rf plugin/
echo "Done → ${OUT}"
