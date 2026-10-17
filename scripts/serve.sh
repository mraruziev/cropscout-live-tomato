#!/usr/bin/env bash
# Serve the site locally at http://localhost:8080/vision/ (camera works on localhost without HTTPS).
set -euo pipefail
cd "$(dirname "$0")/.."
exec php -S "localhost:${PORT:-8080}" -t .
