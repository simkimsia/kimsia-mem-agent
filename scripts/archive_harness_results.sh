#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'EOF'
Archive all contents under harness/results into a timestamped run_archive folder.

Usage:
  archive_harness_results.sh --label "short note"
  archive_harness_results.sh --harness ~/projects/mem-comp-26/harness --label "before self-review run"

Options:
  --harness PATH   Harness directory (default: ~/projects/mem-comp-26/harness)
  --label TEXT     Required free-text label (commit-message style)
  --help           Show this help

Behavior:
  1) Best-effort fix ownership for results/workdir (uses sudo if needed).
  2) Moves everything inside results/ (including hidden entries) to:
       run_archive_<timestamp>_<slug>/results/
  3) Recreates an empty results/ directory.
  4) Writes archive metadata with the original label.
EOF
}

HARNESS_DIR="${HOME}/projects/mem-comp-26/harness"
LABEL=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --harness)
      [[ $# -ge 2 ]] || { echo "error: --harness requires a value" >&2; exit 2; }
      HARNESS_DIR="$2"
      shift 2
      ;;
    --label)
      [[ $# -ge 2 ]] || { echo "error: --label requires a value" >&2; exit 2; }
      LABEL="$2"
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

if [[ -z "${LABEL}" ]]; then
  echo "error: --label is required" >&2
  usage
  exit 2
fi

HARNESS_DIR="${HARNESS_DIR/#\~/$HOME}"
RESULTS_DIR="${HARNESS_DIR}/results"
WORKDIR_DIR="${HARNESS_DIR}/workdir"

if [[ ! -d "${HARNESS_DIR}" ]]; then
  echo "error: harness dir not found: ${HARNESS_DIR}" >&2
  exit 1
fi

mkdir -p "${RESULTS_DIR}"
mkdir -p "${WORKDIR_DIR}"

# Slug for folder naming (keep label text in metadata file).
SLUG="$(printf '%s' "${LABEL}" \
  | tr '[:upper:]' '[:lower:]' \
  | sed -E 's/[^a-z0-9]+/-/g; s/^-+//; s/-+$//; s/-+/-/g')"
[[ -n "${SLUG}" ]] || SLUG="note"
SLUG="${SLUG:0:50}"

TS="$(date +%Y%m%d_%H%M%S)"
ARCHIVE_DIR="${HARNESS_DIR}/run_archive_${TS}_${SLUG}"
ARCHIVE_RESULTS_DIR="${ARCHIVE_DIR}/results"

fix_ownership() {
  local target="$1"
  if [[ ! -e "${target}" ]]; then
    return 0
  fi
  if command -v sudo >/dev/null 2>&1; then
    # Best-effort ownership fix for root-owned previous runs.
    sudo chown -R "${USER}:$(id -gn)" "${target}" || true
  fi
}

fix_ownership "${RESULTS_DIR}"
fix_ownership "${WORKDIR_DIR}"

mkdir -p "${ARCHIVE_RESULTS_DIR}"

shopt -s dotglob nullglob
items=("${RESULTS_DIR}"/*)
shopt -u dotglob

if [[ ${#items[@]} -eq 0 ]]; then
  echo "nothing to archive: ${RESULTS_DIR} is empty"
else
  for item in "${items[@]}"; do
    if ! mv "${item}" "${ARCHIVE_RESULTS_DIR}/" 2>/dev/null; then
      if command -v sudo >/dev/null 2>&1; then
        sudo mv "${item}" "${ARCHIVE_RESULTS_DIR}/"
      else
        echo "error: failed to move ${item} and sudo is unavailable" >&2
        exit 1
      fi
    fi
  done
fi

mkdir -p "${RESULTS_DIR}"

# Normalize ownership on archive and fresh results after sudo fallback move.
fix_ownership "${ARCHIVE_DIR}"
fix_ownership "${RESULTS_DIR}"

cat > "${ARCHIVE_DIR}/ARCHIVE_META.txt" <<EOF
timestamp: ${TS}
label: ${LABEL}
user: ${USER}
host: $(hostname)
harness_dir: ${HARNESS_DIR}
archived_results_dir: ${ARCHIVE_RESULTS_DIR}
EOF

echo "archive complete"
echo "archive dir: ${ARCHIVE_DIR}"
echo "results now contains:"
ls -la "${RESULTS_DIR}"
