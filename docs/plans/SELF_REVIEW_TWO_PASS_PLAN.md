# SELF_REVIEW_TWO_PASS_PLAN

## Goal

Add a budget-capped two-pass self-review loop using the same model (`litellm_proxy/glm-4.7`) to reduce off-target edits and catch near-miss logic issues.

## Scope

1. Change agent code only (`kimsia-mem-agent/src/agent.py` + optional config defaults).
2. Do not modify harness core logic.
3. Keep rollback trivial via env toggle.

## Two-Pass Design

## Pass A: Solve

Run normal agent loop and produce candidate patch.

## Risk Gate (cheap, local checks)

Trigger critic only if risk is detected:

1. `changed_files > SELF_REVIEW_MAX_CHANGED_FILES` (default 3)
2. `diff_lines > SELF_REVIEW_MAX_DIFF_LINES` (default 120)
3. `target_overlap == 0`

Target overlap heuristic:

1. Build general keyword tokens from task text:
   - length >= 4, stopword-filtered
   - keep identifier-like tokens (`camelCase`, `snake_case`, `PascalCase`, `_`, `-`)
2. Separately extract explicit path-like strings from task text using regex:
   - examples: `src/components/RoomPreviewBar.tsx`, `foo/bar/baz.py`
3. Compute overlap of changed files against both sets.
4. Explicit path matches are higher priority.

## Pass B: Critic (same GLM-4.7)

Input:

1. task summary
2. changed file list
3. compact diff summary

Diff truncation contract:

1. use `git diff -U0`
2. cap to first `12000` chars OR first `60` hunks
3. append `[DIFF_TRUNCATED]` marker when truncated

Critic output contract (strict JSON):

```json
{
  "risk_level": "low|medium|high",
  "off_target": true,
  "reasons": ["..."],
  "actions": ["..."]
}
```

Parser fallback:

1. if JSON parse fails or fields missing -> treat as low risk
2. skip revise and continue baseline submit path

## Optional Revise (max 1 cycle)

1. If critic reports medium/high risk or off-target:
   - append critic `actions` as a new user message
   - allow one additional revise cycle
2. then submit

## Budget and Limits

1. `SELF_REVIEW_MAX_EXTRA_STEPS` is the hard cap (default 2: critic + revise)
2. `SELF_REVIEW_MAX_EXTRA_COST` is best-effort only
3. If cost metrics unavailable, rely only on step cap
4. Important: `llm_quota_instance` is a **spend budget cap**, not a call-count cap

## Minimal Memory for Rules (No Embeddings)

Store optional static rules in `/mnt/memory/rules_memory.json`:

1. `repo`, `signal`, `rule_text`, `updated_at`
2. prepend top 1-3 matching rules at task start
3. no resolved-based counter updates in v1 (post-validation updater can be a later script)

## Observability

Log to `_harness/agent.log`:

1. `self_review.enabled`
2. risk metrics (`changed_files`, `diff_lines`, `target_overlap`, `should_review`)
3. critic raw JSON or parse-failed marker
4. `revise_applied`
5. `extra_steps_used`

## Candidate Example

```json
[
  {
    "run_name": "kimsia_glm47_nomem_selfreview_v1",
    "agent_docker_image": "kimsia-mem-agent:latest",
    "llm_quota_total": 200,
    "llm_quota_instance": 2,
    "enable_memory": false,
    "timeout_s": 7200,
    "env": {
      "MODEL_NAME": "litellm_proxy/glm-4.7",
      "SELF_REVIEW_ENABLED": "1",
      "SELF_REVIEW_MAX_EXTRA_STEPS": "2",
      "SELF_REVIEW_MAX_EXTRA_COST": "0.15",
      "SELF_REVIEW_MAX_CHANGED_FILES": "3",
      "SELF_REVIEW_MAX_DIFF_LINES": "120"
    }
  }
]
```

## How to Run

### Step 0: Use tmux session `memcomp`

```bash
tmux attach -t memcomp || tmux new -s memcomp
```

Run all following commands inside this tmux session so the eval keeps running if SSH disconnects.

### Step 1: Archive previous results

Before starting a new experiment, archive existing harness results so they don't mix with the new run.

```bash
cd ~/projects/kimsia-mem-agent
./scripts/archive_harness_results.sh \
  --harness ~/projects/mem-comp-26/harness \
  --label "selfreview v2 at 1/3 after improve risk gate"
```

See `scripts/archive_harness_results.md` for full usage details.

### Step 2: Back up and replace candidates.json

```bash
cd ~/projects/mem-comp-26/harness

# backup first (timestamped)
cp candidates.json "candidates.backup.$(date +%Y%m%d_%H%M%S).json"

# replace with self-review experiment candidate
cat > candidates.json <<'JSON'
[
  {
    "run_name": "kimsia_glm47_nomem_selfreview_v1",
    "agent_docker_image": "kimsia-mem-agent:latest",
    "llm_quota_total": 200,
    "llm_quota_instance": 2,
    "enable_memory": false,
    "timeout_s": 7200,
    "env": {
      "MODEL_NAME": "litellm_proxy/glm-4.7",
      "SELF_REVIEW_ENABLED": "1",
      "SELF_REVIEW_MAX_EXTRA_STEPS": "2",
      "SELF_REVIEW_MAX_EXTRA_COST": "0.15",
      "SELF_REVIEW_MAX_CHANGED_FILES": "3",
      "SELF_REVIEW_MAX_DIFF_LINES": "120"
    }
  }
]
JSON
```

### Step 3: Rebuild the Docker image on VPS

```bash
cd ~/projects/kimsia-mem-agent
docker build -t kimsia-mem-agent:latest .
```

### Step 4: Clean up stale harness containers (recommended)

```bash
cd ~/projects/mem-comp-26/harness
sudo docker ps -aq --filter "name=^/memcomp-" | xargs -r sudo docker rm -f
```

Why: old `memcomp-*` containers can cause name conflicts (HTTP 409) or stale run state.

### Step 5: Run the harness on VPS

```bash
cd ~/projects/mem-comp-26/harness
sudo -E "$(pwd)/.venv/bin/python" main.py | tee run_selfreview_v1_2failed_element-web.log
```

### Step 6: Check results

Inspect the log for `[self-review]` lines to see whether the risk gate triggered, what the critic said, and whether revise was applied. Then check verdict files against the validation gates below.

## Validation Gates

1. 9 verdict files produced
2. no `nopatch`
3. no provider/model errors
4. compare against baseline `kimsia_glm47_nomem_v1` (`7/9`)
5. inspect `p02i01`, `p02i02` first

## Rollback

1. Restore previous candidate config from your backup file:
   - `cp candidates.backup.<timestamp>.json candidates.json`
2. Or disable self-review in-place:
   - set `SELF_REVIEW_ENABLED=0` (or remove self-review env vars)
3. Re-run baseline candidate
4. No harness code rollback required

## How to Turn Off Self-Review

Three ways to disable, all equivalent:

1. **Don't set the env var** — `SELF_REVIEW_ENABLED` defaults to `0`, so the feature is off unless explicitly opted in.
2. **Set `SELF_REVIEW_ENABLED=0`** in the `env` block of `candidates.json`.
3. **Remove the self-review env vars entirely** from the candidate config — the agent falls back to baseline behavior.

## What Changed in `agent.py`

### Added (inert when disabled)

- **Imports** (top of file): `re`, `InterruptAgentFlow` — only used by self-review helpers.
- **Constants** (module level): `_STOPWORDS`, `_GENERIC_TOKENS`, regex patterns, critic prompt templates — never evaluated at runtime when disabled.
- **Config parsing** (`__init__`): reads `SELF_REVIEW_ENABLED`, `SELF_REVIEW_MAX_EXTRA_STEPS`, `SELF_REVIEW_MAX_CHANGED_FILES`, `SELF_REVIEW_MAX_DIFF_LINES` from env. Only side effect when disabled is reading env vars.
- **Helper methods** (`_sr_*`): `_sr_extract_general_keywords`, `_sr_extract_explicit_paths`, `_sr_compute_target_overlap`, `_sr_compute_risk_signals`, `_sr_truncate_diff`, `_sr_run_critic`, `_sr_run_revise`, `_sr_load_rules`, `_sr_log`, `_run_self_review` — none are called when `sr_enabled` is `False`.
- **Gate in `run()`**: a single `if self.sr_enabled and status == 'submitted'` check after `super().run(task)` returns.

### Not Changed

- `_compact_messages()` — untouched.
- `load_memory()` / `save_memory()` — untouched.
- `print_spend()` — untouched.
- `query()` — untouched.
- The `super().run(task)` call and `pattern_memory.learn_from_run()` — same position and logic.
- `config.yaml` — no changes.
- `main.py` — no changes.
- `env.py` — no changes.
- Harness code — no changes.
