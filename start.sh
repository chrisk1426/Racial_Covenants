#!/bin/bash
# ── Start the Racial Covenant Detector ───────────────────────────────────────
# Run this each time you want to use the tool.

set -e

echo ""
echo "Starting Racial Covenant Detector..."

if ! docker info &> /dev/null; then
  echo ""
  echo "ERROR: Docker is not running."
  echo "Please open Docker Desktop and wait for it to start, then try again."
  echo ""
  exit 1
fi

docker compose up -d

echo ""
echo "=================================================="
echo "  Ready! Open your browser and go to:"
echo "  http://localhost:8000"
echo ""
echo "  To stop the tool: docker compose down"
echo "=================================================="
echo ""

# Open the browser automatically
if command -v open &> /dev/null; then
  open http://localhost:8000
fi
