# MAKE_AGENT_GREAT_AGAIN

## Objective

Document what was tried, what worked, what failed, and why the next iteration is a budget-capped self-review strategy.

## Historical Audit

## Phase A: Initial Baselines and Setup Issues

1. Baseline runs executed with GLM through LiteLLM proxy.
2. Early failures included model/provider formatting issues and container reuse collisions.
3. Once stabilized, baseline behavior around `6/9` was observed.

## Phase B: Memory Experiments

1. Memory attempt with invalid provider formatting caused `nopatch`/runtime failures.
2. Memory attempt with simple memory reached baseline-level performance (`~6/9`).
3. Nomic/embedding attempt regressed performance and showed embedding fallback behavior.

Conclusion: embedding-dependent memory was unstable in this environment and did not improve resolve rate.

## Phase C: Clean No-Memory Re-baseline

1. A fresh no-memory run was executed with strict run hygiene.
2. Result improved to `7/9`.
3. All Python instances passed; remaining failures were both in `element-web` JS cases.

Detailed debug record: [DEBUG_BASELINE_20260322_1840.md](DEBUG_BASELINE_20260322_1840.md)

## Failure Pattern Diagnosis

## p02i01

- Off-target drift: patch touched multiple unrelated files.
- Regression pattern: many `RoomPreviewBar`-related failures with no direct patch focus in that area.

## p02i02

- Near miss: only one sticky-room active-index test failed.
- Suggests targeted logic correction is possible.

## Why This Leads to Self-Review Two-Pass

Given the observed failures:

1. A lightweight risk gate can catch off-target broad edits before submit.
2. A short critic pass can flag likely regressions without changing model/provider.
3. One bounded revise pass can fix near-miss logic issues.
4. Strict caps are needed to preserve contest budget and stability.

Implementation plan: [SELF_REVIEW_TWO_PASS_PLAN.md](SELF_REVIEW_TWO_PASS_PLAN.md)

## What Worked vs Didn’t

## Worked

1. Clean run hygiene (archive results, clear workdir, remove stale containers)
2. No-memory baseline as a stable control
3. Focused failure triage using `verdict_val.json` + patch file lists

## Didn’t Work

1. Embedding-based memory dependency in this proxy environment
2. Broad unbounded edits in difficult JS cases
3. Assuming memory alone would improve resolve rate

## Operating Principle Going Forward

1. Keep a stable baseline (`nomem`) as rollback.
2. Add improvements only with explicit gates and observability.
3. Prefer deterministic, bounded behavior over aggressive unbounded agent exploration.
