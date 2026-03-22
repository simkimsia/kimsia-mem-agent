#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'EOF'
Usage:
  ./scripts/quick_summary.sh [run_name] [--harness <harness_dir>] [--list]

Examples:
  ./scripts/quick_summary.sh kimsia_glm47_nomem_v1
  ./scripts/quick_summary.sh
  ./scripts/quick_summary.sh kimsia_glm47_nomem_v1 --harness ~/projects/mem-comp-26/harness
EOF
}

RUN_NAME=""
HARNESS_DIR="${HOME}/projects/mem-comp-26/harness"
LIST_ONLY=0

while [[ $# -gt 0 ]]; do
  case "$1" in
    --harness)
      [[ $# -ge 2 ]] || { echo "missing value for --harness" >&2; exit 1; }
      HARNESS_DIR="$2"
      shift 2
      ;;
    --list)
      LIST_ONLY=1
      shift
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      if [[ -z "$RUN_NAME" ]]; then
        RUN_NAME="$1"
        shift
      else
        echo "unexpected argument: $1" >&2
        usage
        exit 1
      fi
      ;;
  esac
done

cd "$HARNESS_DIR"

mapfile -t RUNS < <(for d in results/*; do [[ -d "$d" ]] && basename "$d"; done | sort)
if [[ ${#RUNS[@]} -eq 0 ]]; then
  echo "no runs found in $HARNESS_DIR/results" >&2
  exit 1
fi

if [[ "$LIST_ONLY" -eq 1 ]]; then
  printf '%s\n' "${RUNS[@]}"
  exit 0
fi

if [[ -z "$RUN_NAME" ]]; then
  echo "Select a run from results/:"
  i=1
  for run in "${RUNS[@]}"; do
    printf "  %d) %s\n" "$i" "$run"
    i=$((i + 1))
  done
  read -r -p "Enter run number: " choice
  if ! [[ "$choice" =~ ^[0-9]+$ ]] || (( choice < 1 || choice > ${#RUNS[@]} )); then
    echo "invalid selection: $choice" >&2
    exit 1
  fi
  RUN_NAME="${RUNS[$((choice - 1))]}"
fi

if [[ ! -d "results/$RUN_NAME" ]]; then
  echo "run not found: results/$RUN_NAME" >&2
  exit 1
fi

echo "=== quick summary ($RUN_NAME) ==="
python3 - "$RUN_NAME" <<'PY'
from pathlib import Path
import json
import sys

run = sys.argv[1]
base = Path("results") / run
rows = []

if not base.exists():
    print(f"run not found: {base}")
    raise SystemExit(1)

for d in sorted(base.glob("p*i*")):
    try:
        with (d / "_harness" / "verdict_val.json").open() as f:
            v = json.load(f)
        with (d / "instance.json").open() as f:
            i = json.load(f)
        with (d / "_harness" / "verdict_gen.json").open() as f:
            g = json.load(f)
        rows.append(
            (
                d.name,
                i.get("repo_language", "?"),
                i.get("repo", "?"),
                g.get("instance_id", "?"),
                bool(v.get("resolved")),
            )
        )
    except Exception:
        rows.append((d.name, "?", "?", "?", "MISSING_FILES"))

for r in rows:
    print(f"{r[0]} | lang={r[1]} | resolved={r[4]} | repo={r[2]} | instance_id={r[3]}")

ok = sum(1 for r in rows if r[4] is True)
print(f"\nresolved: {ok}/{len(rows)}")
PY
