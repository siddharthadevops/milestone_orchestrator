#!/bin/bash
# End-to-end demo: the deterministic driver runs the full canon flow on the
# calculator example using the fake LLM CLI (no real LLMs, no network).
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
REPO="$(cd "$HERE/../../.." && pwd)"
WORK="${1:-$HERE/work}"

rm -rf "$WORK"
mkdir -p "$WORK"
git -C "$WORK" init -q   # the ledger repo is created deliberately (no auto-init)
CFG="$WORK/.demo-config.json"
cat > "$CFG" <<EOF
{
  "commands": {
    "codex":  ["python3", "$HERE/fake_llm.py", "--workspace", "{workspace}"],
    "claude": ["python3", "$HERE/fake_llm.py", "--workspace", "{workspace}"]
  },
  "timeouts": {"codex": 60, "claude": 60},
  "verification": ["python3 run_checks.py"],
  "max_rounds_per_family": 6,
  "max_seal_attempts": 4,
  "git": {"enabled": true},
  "acts": {"fixer": "codex", "delta_review": "codex", "consultation": "opposite"},
  "max_fix_loops": 4
}
EOF

cd "$REPO"
python3 -m orchestrator.driver init \
  --goal "Build a small CLI calculator (add/sub/mul/div) with unit tests" \
  --workspace "$WORK" --config "$CFG"
python3 -m orchestrator.driver run --workspace "$WORK"
python3 -m orchestrator.driver status --workspace "$WORK"
echo
echo "--- gate commits ---"
git -C "$WORK" log --oneline
echo
echo "dashboard: python3 -m orchestrator.driver serve --workspace $WORK"
