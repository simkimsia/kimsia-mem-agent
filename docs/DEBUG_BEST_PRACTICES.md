# Debug Best Practices (Evidence First)

This is the default process for failed harness runs.  
Rule: **do not propose code changes until logs prove root cause**.

## 1) Triage by symptom

- `status = nopatch` on many/all instances:
  - Either agent crashed before submit, or patch was never written.
- `status = {'StatusCode': 0}` but unresolved:
  - Agent ran and submitted; this is quality/problem-solving, not infra.

## 2) Collect evidence for every failed instance first

Run in `~/projects/mem-comp-26/harness`:

```bash
run="YOUR_RUN_NAME"
for d in results/$run/p*/_harness; do
  p="${d%/_harness}"
  inst="$(basename "$p")"
  echo "===== $inst ====="

  echo "-- status/self-review --"
  rg -n "agent started!|done! status:|\\[self-review\\]" "$d/agent.log" | tail -n 40 || true

  echo "-- errors --"
  rg -n "Traceback|Exception|ModuleNotFoundError|BadRequestError|LLM Provider NOT provided|LimitsExceeded|timeout|error" "$d/agent.log" | tail -n 30 || true

  if [ -s "$p/patch.diff" ]; then
    echo "-- patch -- yes ($(wc -c < "$p/patch.diff") bytes)"
  else
    echo "-- patch -- NO"
  fi
  echo
done
```

## 3) If there is a Traceback, inspect one full traceback

```bash
run="YOUR_RUN_NAME"
sed -n '1,140p' "results/$run/p00i00/_harness/agent.log"
```

Do this before touching code.

## 4) Verify the Docker image content (avoid stale-image mistakes)

Even if repo code is fixed, harness uses image content. Confirm image has expected lines:

```bash
sudo docker run --rm --entrypoint /bin/sh kimsia-mem-agent:latest -lc \
'grep -n "done! status" -A3 /root/src/main.py; sed -n "1,30p" /root/src/agent.py'
```

If container code != local repo code, rebuild image and retry.

## 5) Decision tree (before any patch)

- No `agent started!` + import traceback:
  - startup/import/runtime compatibility bug.
- `agent started!` present, `done! status:` missing:
  - crash during run.
- `done! status:` present but no `patch.diff`:
  - patch-write gate bug (`status` handling / result handling).
- `patch.diff` exists and unresolved:
  - debugging patch quality, not harness plumbing.

## 6) Only then make a targeted fix

- Change only the component proven by logs.
- Rebuild image.
- Re-run 1-instance smoke test (if available) before full 9.

## 7) Report format to use with assistant

Always paste:

1. The triage output block (Step 2)
2. One full traceback (Step 3)
3. Container code verification output (Step 4)
4. Current `candidates.json`

This prevents guesswork and shortens turnaround.
