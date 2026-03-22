# archive_harness_results.sh

## What it does
Archives everything inside `harness/results/` into a timestamped folder so `main.py` validation does not re-include old runs.

It also:
1. Recreates an empty `results/` directory.
2. Stores your note/label in `ARCHIVE_META.txt`.
3. Tries to fix `results/` and `workdir/` ownership (uses `sudo` if needed).

## Script path
`kimsia-mem-agent/scripts/archive_harness_results.sh`

## Basic usage
```bash
cd ~/projects/kimsia-mem-agent
./scripts/archive_harness_results.sh \
  --harness ~/projects/mem-comp-26/harness \
  --label "baseline nomem v1 before two-pass self-review"
```

## Minimal usage (default harness path)
Default harness path is `~/projects/mem-comp-26/harness`.

```bash
cd ~/projects/kimsia-mem-agent
./scripts/archive_harness_results.sh --label "before new experiment"
```

## Output location
Archive folder is created under harness:

`~/projects/mem-comp-26/harness/run_archive_<timestamp>_<slug>/`

Archived results go to:

`.../run_archive_<timestamp>_<slug>/results/`

Metadata file:

`.../run_archive_<timestamp>_<slug>/ARCHIVE_META.txt`

## After archiving
Run your harness as usual:

```bash
cd ~/projects/mem-comp-26/harness
sudo -E "$(pwd)/.venv/bin/python" main.py | tee run_new.log
```

## Notes
1. `--label` is required (commit-message style free text).
2. If `results/` is already empty, script exits cleanly and still prints status.
3. Use `--help` to see options:

```bash
./scripts/archive_harness_results.sh --help
```
