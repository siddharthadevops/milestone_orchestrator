#!/bin/bash
# impl roadmap — local programming service panel.
#   ./panel.sh                 http://127.0.0.1:8700
#   ./panel.sh --port 9000 --open
set -euo pipefail
cd "$(dirname "$0")"
exec python3 -m orchestrator.service "$@"
