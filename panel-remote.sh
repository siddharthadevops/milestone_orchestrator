#!/bin/bash
# Milestone Orchestrator — phone access via ngrok, Google OAuth protected.
#   ./panel-remote.sh                          tunnel to the panel on :8700
#   ./panel-remote.sh 9000                     another port
#   NGROK_DOMAIN=x.ngrok.app ./panel-remote.sh reserved stable domain
#
# The panel spawns full-permission LLM CLIs, so it must NEVER ride an
# unprotected public URL. The access module generates a fail-closed ngrok
# Traffic Policy with Google OAuth, an exact email allowlist, and trusted
# identity headers consumed by the local service.
# NGROK_DOMAIN must be a domain reserved to the account (dashboard ->
# Domains); prefer an ngrok-branded one — the panel recognizes ngrok
# hostnames and relaxes its poll to 30s through the tunnel.
# The tunnel lives while this script runs — Ctrl-C kills it.
set -euo pipefail
PORT="${1:-8700}"
POLICY_FILE="$HOME/.impl_roadmap/remote-policy.json"
mkdir -p "$(dirname "$POLICY_FILE")"
python3 -m orchestrator.access "$POLICY_FILE"
chmod 600 "$POLICY_FILE"
DOMAIN_ARGS=()
if [ -n "${NGROK_DOMAIN:-}" ]; then
  DOMAIN_ARGS=(--url "https://${NGROK_DOMAIN#https://}")
fi
exec ngrok http "$PORT" --traffic-policy-file "$POLICY_FILE" "${DOMAIN_ARGS[@]+"${DOMAIN_ARGS[@]}"}"
