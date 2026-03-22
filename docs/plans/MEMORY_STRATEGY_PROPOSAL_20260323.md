# MEMORY_STRATEGY_PROPOSAL_20260323

## Context

Goal: improve SWE-Bench Pro pass rate via memory, without hardcoding repo-specific logic into agent control flow.

This proposal consolidates guidance from recent analysis of `element-web` and `NodeBB` archive runs.

## Position

Do **not** hardcode repo behavior in `agent.py`.

Use **repo-scoped, confidence-weighted memory**:

1. Keep agent logic generic.
2. Store project-specific lessons as memory records.
3. Retrieve only relevant records for the current project/task.
4. Inject as conditional checks, not rigid instructions.

## Why This Is Better Than Hardcoding

Hardcoding:

1. Overfits to known repos/issues.
2. Risks regressions on unseen projects.
3. Does not scale across 200 benchmark instances.

Memory-based adaptation:

1. Preserves generic reasoning loop.
2. Lets project conventions emerge from evidence.
3. Improves over time with accumulated episodes.

## Key Concern: “Memory Helps Only After Eval”

True for post-episode memory on the current instance. Mitigation is a 3-layer strategy:

1. **Intra-instance memory (same task):**
   - During the run, capture failing-test signals and feed them into revise-before-submit checks.
2. **Inter-instance memory (same project sequence):**
   - After each evaluated instance, persist validated lessons for later instances in that project.
3. **Cross-run bootstrap memory:**
   - Seed memory DB from prior runs/devset so early instances are not memory-cold.

This aligns with Mem-Comp’s sequential-per-project setup, where N can help N+1...N+25.

## Concrete Changes (Recommended First Wave)

### 1) Retrieval Guardrails

Current risk: retrieval query is global vector search with no project filter.

Change:

1. Add project-aware retrieval filtering.
2. Optionally add recency and confidence weighting.
3. Keep top-k small and high precision.

Expected effect: lower cross-repo contamination.

### 2) Memory Quality Signals

Current risk: memories are stored without validation confidence.

Change:

1. Extend memory record metadata with:
   - `confidence`
   - `uses`
   - `successes`
   - `failures`
   - optional `tests_touched` / `failure_signature`
2. Update stats after each episode outcome.
3. Inject only above confidence threshold.

Expected effect: reduce noisy/one-off memories.

### 3) Failure-Fingerprint Extraction

Current extractor is trajectory-heuristic heavy.

Change:

1. Parse eval artifacts for structured failure signatures:
   - test name
   - expected vs received
   - target file/function hints
2. Convert repeated signatures into correction/pattern memories.

Expected effect: capture reusable debugging knowledge for similar failures.

### 4) Injection Format Upgrade

Current format is generic list text.

Change:

1. Inject memory as conditional operational checks:
   - “If touching X and seeing failure Y, verify Z before submit.”
2. Include short provenance (task + confidence).
3. Cap token footprint aggressively.

Expected effect: better actionability, less prompt clutter.

### 5) Two-Pass Integration (Optional but Valuable)

Current issue in observed failing element-web instance: self-review skipped because risk gate thresholds not crossed (`changed_files=2`, small diff), despite semantic risk.

Change:

1. Add semantic trigger to self-review gate:
   - if retrieved memory confidence high and changed files intersect memory targets, force critic pass.
2. Keep step budget cap.

Expected effect: self-review runs when it matters semantically, not only by diff size.

## What This Means for element-web Sticky-Room Failure

Do not hardcode a rule in agent flow for `element-web`.

Instead store a project-scoped correction memory like:

1. When editing `useStickyRoomList` / `SpaceStore` for space-switch behavior, validate active index against last-selected-room semantics (`RoomListViewModel` sticky-room test expectations).

This remains soft guidance and only activates when retrieval says it is relevant.

## Evaluation Plan

### A/B Setup

1. Baseline: current memory behavior.
2. Variant: project-filtered + confidence-weighted + failure-fingerprint extraction + improved injection.

### Metrics

1. Resolved count per project.
2. Precision of injected memories (manual audit sample).
3. % of instances where injected memory references touched files/tests.
4. Regression rate from irrelevant memory.
5. Cost/time overhead.

### Acceptance Gates

1. Improved resolved count on at least 2 projects (or no drop with lower variance).
2. Reduced noisy injections.
3. No increase in crash/nopatch incidents.

## Rollout Order

1. Project-scoped retrieval filter.
2. Confidence metadata + gating.
3. Failure-signature extraction from eval logs.
4. Injection template upgrade.
5. Optional semantic self-review trigger.

## Summary

Best path is not hardcoded repo behavior.  
Best path is stronger memory quality control + project-scoped retrieval + actionable injection, with explicit handling for the “post-eval memory timing” limitation via intra/inter-instance strategy.
