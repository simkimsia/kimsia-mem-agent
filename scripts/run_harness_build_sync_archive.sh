#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'EOF'
Build agent image, run harness, sync agent_runs to Turso, then archive results.

Usage:
  run_harness_build_sync_archive.sh --description "selfreview sync test for nodebb"

Options:
  --description TEXT     Required. Used as archive label and source for run_name slug.
  --harness PATH         Harness dir (default: ~/projects/mem-comp-26/harness)
  --mem-agent PATH       kimsia-mem-agent dir (default: script parent dir)
  --candidate-index N    Candidate index in candidates.json to update (default: 0)
  --help                 Show this help

Behavior:
  1) Build docker image: kimsia-mem-agent:latest
  2) Backup candidates.json and set candidates[N].run_name from description slug
  3) Run harness main.py
  4) Sync run rows into Turso via sync_agent_runs_to_turso.py
  5) Archive harness/results with archive_harness_results.sh --label <description>

Notes:
  - run_name format: <slug>_<YYYYMMDD_HHMMSS> (max 64 chars total).
  - archive label/folder text still comes from --description (human-readable).
  - .env in harness dir must contain TURSO_DATABASE_URL and TURSO_AUTH_TOKEN.
EOF
}

DESCRIPTION=""
HARNESS_DIR="${HOME}/projects/mem-comp-26/harness"
MEM_AGENT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CANDIDATE_INDEX="0"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --description)
      [[ $# -ge 2 ]] || { echo "error: --description requires a value" >&2; exit 2; }
      DESCRIPTION="$2"
      shift 2
      ;;
    --harness)
      [[ $# -ge 2 ]] || { echo "error: --harness requires a value" >&2; exit 2; }
      HARNESS_DIR="$2"
      shift 2
      ;;
    --mem-agent)
      [[ $# -ge 2 ]] || { echo "error: --mem-agent requires a value" >&2; exit 2; }
      MEM_AGENT_DIR="$2"
      shift 2
      ;;
    --candidate-index)
      [[ $# -ge 2 ]] || { echo "error: --candidate-index requires a value" >&2; exit 2; }
      CANDIDATE_INDEX="$2"
      shift 2
      ;;
    --help|-h)
      usage
      exit 0
      ;;
    *)
      echo "error: unknown argument: $1" >&2
      usage
      exit 2
      ;;
  esac
done

if [[ -z "${DESCRIPTION}" ]]; then
  echo "error: --description is required" >&2
  usage
  exit 2
fi

HARNESS_DIR="${HARNESS_DIR/#\~/$HOME}"
MEM_AGENT_DIR="${MEM_AGENT_DIR/#\~/$HOME}"

if [[ ! -d "${HARNESS_DIR}" ]]; then
  echo "error: harness dir not found: ${HARNESS_DIR}" >&2
  exit 1
fi
if [[ ! -d "${MEM_AGENT_DIR}" ]]; then
  echo "error: mem-agent dir not found: ${MEM_AGENT_DIR}" >&2
  exit 1
fi

ARCHIVE_SCRIPT="${MEM_AGENT_DIR}/scripts/archive_harness_results.sh"
if [[ ! -x "${ARCHIVE_SCRIPT}" ]]; then
  echo "error: archive script not found/executable: ${ARCHIVE_SCRIPT}" >&2
  exit 1
fi

if ! [[ "${CANDIDATE_INDEX}" =~ ^[0-9]+$ ]]; then
  echo "error: --candidate-index must be an integer >= 0" >&2
  exit 2
fi

RUN_SLUG="$(
  printf '%s' "${DESCRIPTION}" \
    | tr '[:upper:]' '[:lower:]' \
    | sed -E 's/[^a-z0-9]+/_/g; s/^_+//; s/_+$//; s/_+/_/g' \
    | cut -c1-48
)"
[[ -n "${RUN_SLUG}" ]] || RUN_SLUG="run"
RUN_TS="$(date +%Y%m%d_%H%M%S)"
RUN_NAME="${RUN_SLUG}_${RUN_TS}"

echo "description: ${DESCRIPTION}"
echo "run_slug: ${RUN_SLUG}"
echo "run_name: ${RUN_NAME}"
echo "harness_dir: ${HARNESS_DIR}"
echo "mem_agent_dir: ${MEM_AGENT_DIR}"
echo "candidate_index: ${CANDIDATE_INDEX}"

echo "== Step 1/6: docker build =="
cd "${MEM_AGENT_DIR}"
docker build -t kimsia-mem-agent:latest .

echo "== Step 2/6: set run_name in candidates.json =="
cd "${HARNESS_DIR}"
cp candidates.json "candidates.backup.$(date +%Y%m%d_%H%M%S).json"

python3 - <<PY
import json
from pathlib import Path

path = Path("candidates.json")
idx = int("${CANDIDATE_INDEX}")
run_name = "${RUN_NAME}"

data = json.loads(path.read_text())
if not isinstance(data, list):
    raise SystemExit("candidates.json must be a JSON list")
if idx >= len(data):
    raise SystemExit(f"candidate index {idx} out of range (len={len(data)})")
if not isinstance(data[idx], dict):
    raise SystemExit(f"candidate at index {idx} is not an object")

old = data[idx].get("run_name")
data[idx]["run_name"] = run_name
path.write_text(json.dumps(data, indent=2) + "\\n")
print(f"updated candidates[{idx}].run_name: {old!r} -> {run_name!r}")
PY

echo "== Step 3/6: clean stale memcomp containers =="
cd "${HARNESS_DIR}"
sudo docker ps -aq --filter "name=^/memcomp-" | xargs -r sudo docker rm -f

echo "== Step 4/6: run harness main.py =="
set -a
source .env
set +a

PYTHON_BIN=""
if [[ -x "${HARNESS_DIR}/.venv/bin/python" ]]; then
  PYTHON_BIN="${HARNESS_DIR}/.venv/bin/python"
else
  PYTHON_BIN="$(command -v python3)"
fi

RUN_LOG="run_${RUN_NAME}.log"
sudo -E "${PYTHON_BIN}" main.py | tee "${RUN_LOG}"

echo "== Step 5/6: sync agent_runs to Turso =="
if ! "${PYTHON_BIN}" -c "import libsql" >/dev/null 2>&1; then
  "${PYTHON_BIN}" -m pip install -r requirements.txt
fi

"${PYTHON_BIN}" sync_agent_runs_to_turso.py \
  --results-dir results \
  --run-name "${RUN_NAME}"

echo "== Step 6/6: archive results =="
cd "${MEM_AGENT_DIR}"
"${ARCHIVE_SCRIPT}" \
  --harness "${HARNESS_DIR}" \
  --label "${DESCRIPTION}"

echo "done"
echo "run_name: ${RUN_NAME}"
echo "log: ${HARNESS_DIR}/${RUN_LOG}"
