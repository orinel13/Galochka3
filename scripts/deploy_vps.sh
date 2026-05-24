#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/.."

git pull --ff-only
docker compose up -d --build
docker compose ps
echo "Deploy complete. Logs: docker compose logs -f"
