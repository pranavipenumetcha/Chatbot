#!/usr/bin/env bash
# ---------------------------------------------------------------------------
# Convenience launcher for the Nestara AI Assistant.
#   ./run.sh          -> start the web server (http://localhost:8000)
#   ./run.sh cli      -> start the terminal chat channel
#   ./run.sh test     -> run the test suite
# ---------------------------------------------------------------------------
set -euo pipefail
cd "$(dirname "$0")"

# Create a virtual environment on first run.
if [ ! -d ".venv" ]; then
  echo "==> Creating virtual environment (.venv)"
  python3 -m venv .venv
fi
# shellcheck disable=SC1091
source .venv/bin/activate

echo "==> Installing dependencies"
pip install --quiet --upgrade pip
pip install --quiet -r requirements.txt

# Make sure a .env exists so the app can find a key.
if [ ! -f ".env" ]; then
  echo "==> No .env found — copying .env.example. Add your API key to it!"
  cp .env.example .env
fi

case "${1:-web}" in
  cli)
    echo "==> Starting CLI channel"
    python -m app.channels.cli
    ;;
  test)
    echo "==> Running tests"
    PYTHONPATH=. python -m unittest discover -s tests -v
    ;;
  web|*)
    echo "==> Starting web server on http://localhost:8000"
    uvicorn app.main:app --reload --port 8000
    ;;
esac
