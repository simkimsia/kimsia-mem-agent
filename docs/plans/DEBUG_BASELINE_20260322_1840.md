# DEBUG_BASELINE_20260322_1840

## Purpose

Re-run a clean no-memory baseline with `glm-4.7`, document exact commands, outcomes, and failure diagnostics.

## Source

This document is a structured rewrite of [debug_failed.md](debug_failed.md).

## Baseline Setup

### Candidate

```json
[
  {
    "run_name": "kimsia_glm47_nomem_v1",
    "agent_docker_image": "kimsia-mem-agent:latest",
    "llm_quota_total": 200,
    "llm_quota_instance": 2,
    "enable_memory": false,
    "timeout_s": 7200,
    "env": {
      "MODEL_NAME": "litellm_proxy/glm-4.7"
    }
  }
]
```

### Run Hygiene

1. Back up `candidates.json`
2. Archive old `results/`
3. Clean `workdir/*`
4. Remove stale `memcomp-` containers
5. Run `sudo -E "$(pwd)/.venv/bin/python" main.py`

## Baseline Result

### Summary

- Run: `kimsia_glm47_nomem_v1`
- Outcome: `7/9`

### Instance Outcomes

1. `p00i00` NodeBB (js): resolved
2. `p00i01` NodeBB (js): resolved
3. `p00i02` NodeBB (js): resolved
4. `p01i00` qutebrowser (python): resolved
5. `p01i01` qutebrowser (python): resolved
6. `p01i02` qutebrowser (python): resolved
7. `p02i00` element-web (js): resolved
8. `p02i01` element-web (js): failed
9. `p02i02` element-web (js): failed

Key takeaway: all Python instances passed (`3/3`).

## Failed Case Diagnostics

## p02i01

- Verdict: unresolved
- Failed tests: 28
- Pattern: failures centered on `RoomPreviewBar` behavior
- Patch touched unrelated files:
  - `src/SlashCommands.tsx`
  - `src/components/views/avatars/BaseAvatar.tsx`
  - `src/components/views/avatars/MemberAvatar.tsx`
  - `src/components/views/elements/AppPermission.tsx`
  - `src/components/views/elements/EventListSummary.tsx`
  - `src/components/views/messages/EncryptionEvent.tsx`
  - `src/settings/Settings.tsx`
- Signal: off-target edit drift (large collateral pass-to-pass regression)

## p02i02

- Verdict: unresolved
- Failed tests: 1
- Failing test:
  - `Sticky room and active index | active index is calculated with the last opened room in a space`
- Patch touched:
  - `src/components/viewmodels/roomlist/useStickyRoomList.tsx`
  - `src/stores/spaces/SpaceStore.ts`
- Signal: near-miss logic bug in the right subsystem (likely index/space-switch edge handling)

## Verification Commands Used

```bash
# narrow failed cases
run="kimsia_glm47_nomem_v1"
for p in p02i01 p02i02; do
  inst="results/$run/$p"
  jq '.resolved,.status,("all="+(.all_tests|length|tostring)),("passed="+(.passed_tests|length|tostring))' "$inst/_harness/verdict_val.json"
  rg '^diff --git ' "$inst/patch.diff" || true
done
```

## Decision from This Baseline

1. Keep `nomem` baseline as a stable control (`7/9`).
2. Do not pursue embedding-based memory for now.
3. Attempt a budget-capped self-review pass to reduce off-target drift and catch near-miss logic issues.
4. Detailed next plan: [SELF_REVIEW_TWO_PASS_PLAN.md](SELF_REVIEW_TWO_PASS_PLAN.md).
