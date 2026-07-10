#!/bin/bash
# Milestone Orchestrator — phone access via ngrok, Google OAuth protected.
#   ./panel-remote.sh              tunnel to the panel on :8700
#   ./panel-remote.sh 9000         another port
#
# The panel spawns full-permission LLM CLIs, so it must NEVER ride an
# unprotected public URL. The access module generates a fail-closed ngrok
# Traffic Policy with Google OAuth, an exact email allowlist, and trusted
# identity headers consumed by the local service.
# The tunnel lives while this script runs — Ctrl-C kills it.
set -euo pipefail
PORT="${1:-8700}"
POLICY_FILE="$HOME/.impl_roadmap/remote-policy.json"
mkdir -p "$(dirname "$POLICY_FILE")"
python3 -m orchestrator.access "$POLICY_FILE"
chmod 600 "$POLICY_FILE"
exec ngrok http "$PORT" --traffic-policy-file "$POLICY_FILE"
