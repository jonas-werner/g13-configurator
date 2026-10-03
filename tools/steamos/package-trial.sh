#!/usr/bin/env bash
# Package application source only; never include VM images, SSH keys or logs.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT"
mkdir -p dist
ARCHIVE=g13-linux-steamos-experimental.tar.gz
tar --exclude=__pycache__ --exclude='*.pyc' \
    --transform='s,^,g13-linux-steamos-experimental/,' \
    -czf "dist/$ARCHIVE" \
    g13 assets docs tools/install tools/steamos tests \
    pyproject.toml README.md LICENSE install.sh udev systemd
(cd dist && sha256sum "$ARCHIVE" > "$ARCHIVE.sha256")
echo "Created dist/$ARCHIVE and checksum. No release was published."
