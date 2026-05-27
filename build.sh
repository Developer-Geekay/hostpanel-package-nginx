#!/usr/bin/env bash
# Build hostpanel-nginx-<version>.zip for upload via the HostPanel Package Manager.
# Uses Python's zipfile so paths always use forward slashes regardless of OS.
set -euo pipefail

VERSION=$(python3 -c "import re; print(re.search(r'version=[\"\'']([^\"\']+)[\"\'']', open('plugin/setup.py').read()).group(1))")
OUT="hostpanel-nginx-${VERSION}.zip"

echo "Building ${OUT}..."
rm -f "$OUT"

python3 - "$OUT" <<'PYEOF'
import sys, zipfile, os

out = sys.argv[1]
folders = ['plugin', 'bin', 'conf', 'service', 'sudoers', 'frontend']
skip_dirs = {'__pycache__'}

with zipfile.ZipFile(out, 'w', compression=zipfile.ZIP_DEFLATED) as zf:
    for folder in folders:
        for root, dirs, files in os.walk(folder):
            dirs[:] = [d for d in dirs if d not in skip_dirs]
            for file in files:
                if file.endswith('.pyc'):
                    continue
                filepath = os.path.join(root, file)
                arcname = filepath.replace(os.sep, '/')   # always forward slashes
                zf.write(filepath, arcname)
PYEOF

echo "Done -> ${OUT}"
