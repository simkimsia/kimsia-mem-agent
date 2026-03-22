# quick_summary.sh

## What it does

Prints a compact per-instance summary for one harness run under `results/<run_name>/`.

For each `p*i*` instance folder, it shows:

1. instance folder name (for example `p02i02`)
2. repo language
3. resolved status (`True`/`False`)
4. repo name
5. instance id

At the end, it prints total resolved count (`resolved: X/Y`).

## Why use it

Use this as a fast first-pass triage before deep debugging:

1. confirms the run has expected instance folders
2. quickly shows pass/fail distribution
3. helps identify which instances to inspect next (`agent.log`, `patch.diff`, `verdict_val.json`)

## Script path

`kimsia-mem-agent/scripts/quick_summary.sh`

## Usage

### Interactive run selection

If you do not pass a run name, it lists runs from `results/` and lets you pick one.

```bash
cd ~/projects/kimsia-mem-agent
./scripts/quick_summary.sh --harness ~/projects/mem-comp-26/harness
```

### Explicit run name

```bash
cd ~/projects/kimsia-mem-agent
./scripts/quick_summary.sh kimsia_glm47_nomem_v1 --harness ~/projects/mem-comp-26/harness
```

### List runs only

```bash
cd ~/projects/kimsia-mem-agent
./scripts/quick_summary.sh --list --harness ~/projects/mem-comp-26/harness
```

## Defaults

If `--harness` is omitted, default harness path is:

`~/projects/mem-comp-26/harness`

## Notes

1. Missing files in an instance folder are reported as `MISSING_FILES`.
2. This script is read-only; it does not modify results.
3. Use `--help` for all options:

```bash
./scripts/quick_summary.sh --help
```
