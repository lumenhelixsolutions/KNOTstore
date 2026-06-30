#!/usr/bin/env bash
# Install the KNOTstore application suite as console commands.
# Uses pipx if available (isolated), else falls back to pip --user.
set -euo pipefail
cd "$(dirname "$0")"

apps=(knot knotvault prefixforge driftledger checkpointtime)

if command -v pipx >/dev/null 2>&1; then
  installer=(pipx install --force)
else
  echo "pipx not found; falling back to 'pip install --user'." >&2
  installer=(python3 -m pip install --user)
fi

for app in "${apps[@]}"; do
  echo ">> installing $app"
  "${installer[@]}" "./apps/$app"
done

echo
echo "Done. Try:  knot list   &&   knot demo --all"
