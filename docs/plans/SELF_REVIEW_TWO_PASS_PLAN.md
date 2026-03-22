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

## Validation Gates

1. 9 verdict files produced
2. no `nopatch`
3. no provider/model errors
4. compare against baseline `kimsia_glm47_nomem_v1` (`7/9`)
5. inspect `p02i01`, `p02i02` first

## Rollback

1. Set `SELF_REVIEW_ENABLED=0` (or remove self-review env vars)
2. Re-run baseline candidate
3. No harness code rollback required
