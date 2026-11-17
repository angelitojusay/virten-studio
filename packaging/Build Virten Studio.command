#!/bin/bash
# Double-click on a Mac to build and open the Virten Studio installer (.dmg).
# It downloads a private copy of Python 3.12 (via Astral's "uv" tool) so nothing else needs installing first.
# Takes about 5–10 minutes the first time.
set -euo pipefail
cd "$(dirname "$0")"
echo "Building Virten Studio for macOS…"
export PATH="$HOME/.local/bin:$PATH"
if ! command -v uv >/dev/null 2>&1; then
  echo "== Installing uv (Python manager)"
  curl -LsSf https://astral.sh/uv/install.sh | sh
  export PATH="$HOME/.local/bin:$PATH"
fi
uv python install 3.12
export PYTHON="$(uv python find 3.12)"
bash packaging/build_mac.sh
open dist/*.dmg
echo
echo "The installer is open: drag Virten Studio into Applications. You can close this window."
