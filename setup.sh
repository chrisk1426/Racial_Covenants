#!/bin/bash
# ── First-time setup for the Racial Covenant Detector ────────────────────────
# Run this once. After that, use start.sh to launch the tool.

set -e

echo ""
echo "=================================================="
echo "  Racial Covenant Detector — First-Time Setup"
echo "=================================================="
echo ""

# ── Check for Docker ──────────────────────────────────────────────────────────
if ! command -v docker &> /dev/null; then
  echo "ERROR: Docker is not installed."
  echo ""
  echo "Please install Docker Desktop from https://www.docker.com/products/docker-desktop/"
  echo "Then re-run this script."
  echo ""
  exit 1
fi

if ! docker info &> /dev/null; then
  echo "ERROR: Docker is installed but not running."
  echo ""
  echo "Please open Docker Desktop and wait for it to start, then re-run this script."
  echo ""
  exit 1
fi

echo "Docker found."
echo ""

# ── Get the API key ───────────────────────────────────────────────────────────
if [ -f .env ] && grep -q "ANTHROPIC_API_KEY=sk-" .env 2>/dev/null; then
  echo "An existing .env file with an API key was found. Skipping API key setup."
else
  echo "You need an Anthropic API key to use the AI detection features."
  echo "Get one at: https://console.anthropic.com/"
  echo ""
  read -rp "Paste your Anthropic API key here: " api_key

  if [ -z "$api_key" ]; then
    echo ""
    echo "ERROR: No API key entered. Setup cancelled."
    exit 1
  fi

  # Write the .env file
  cat > .env <<EOF
ANTHROPIC_API_KEY=${api_key}
CLAUDE_MODEL=claude-sonnet-4-6
OCR_CONFIDENCE_THRESHOLD=0.5
API_RATE_LIMIT_DELAY=0.5
EOF

  echo ""
  echo "API key saved to .env"
fi

echo ""
echo "Building and starting the app (this may take a few minutes the first time)..."
echo ""

docker compose up --build -d

echo ""
echo "Waiting for the app to be ready..."
sleep 5

# Initialize the database
docker compose exec app python -m src.cli init-db 2>/dev/null || true

echo ""
echo "=================================================="
echo "  Setup complete!"
echo ""
echo "  Open your browser and go to:"
echo "  http://localhost:8000"
echo ""
echo "  To stop the tool:  docker compose down"
echo "  To start it again: ./start.sh"
echo "=================================================="
echo ""

# Try to open the browser automatically
if command -v open &> /dev/null; then
  open http://localhost:8000
fi
