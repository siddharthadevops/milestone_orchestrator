#!/bin/bash
# Milestone Orchestrator — phone access via ngrok, basic-auth protected.
#   ./panel-remote.sh              tunnel to the panel on :8700
#   ./panel-remote.sh 9000         another port
#
# The panel is UNAUTHENTICATED and spawns full-permission LLM CLIs, so it
# must NEVER ride an unprotected public URL: this script always attaches
# ngrok edge basic-auth. Credentials are generated once into
# ~/.impl_roadmap/remote-auth (chmod 600) and printed on every start.
# The tunnel lives while this script runs — Ctrl-C kills it.
set -euo pipefail
PORT="${1:-8700}"
AUTH_FILE="$HOME/.impl_roadmap/remote-auth"
if [ ! -f "$AUTH_FILE" ]; then
  PASS=$(LC_ALL=C tr -dc 'a-z0-9' < /dev/urandom | head -c 20)
  printf 'operator:%s\n' "$PASS" > "$AUTH_FILE"
  chmod 600 "$AUTH_FILE"
fi
CREDS="$(cat "$AUTH_FILE")"
echo "== credentials (user:pass) =="
echo "$CREDS"
echo "============================="
exec ngrok http "$PORT" --basic-auth "$CREDS"
