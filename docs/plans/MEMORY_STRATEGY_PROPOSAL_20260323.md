# MEMORY_STRATEGY_PROPOSAL_20260323

## Context

Goal: improve SWE-Bench Pro pass rate via memory without hardcoding repo-specific behavior in agent control flow.

This version is feasibility-corrected to match harness constraints.

## Hard Constraints From Competition Interface

1. `--memory-path` is empty at project start.
2. Memory persists only between tasks in the same project.
3. Memory is not preserved across projects.
4. Agent process does not receive post-run evaluator verdicts during the solve loop.

Implications:

1. no cross-project bootstrap memory during official eval,
2. no runtime use of `verdict_val.json`/harness post-eval artifacts,
3. no true success/failure feedback loop from evaluator inside the agent.

## Corrected Value Chain

With project-local sequential execution, practical gains come from:

1. **Instance 1:** cold start (recon + robust solving discipline).
2. **Instance 2+:** reuse extracted memory from earlier instances in same project.

So extraction quality on early instances is disproportionately important.

## Position

Do not hardcode repo logic in `agent.py`.

Use project-local memory as data:

1. encode lessons as reusable records,
2. inject as conditional checks,
3. keep agent loop generic.

## What Is Actually Achievable

### 1) Intra-instance memory (same task, run-local)

Use signals from commands/tests run by the agent during the same solve loop:

1. parse failing test output from trajectory observations,
2. summarize as temporary failure fingerprints,
3. feed into revise/checklist prompt before final submit command.

This does not require persistence and works within one run.

### 2) Inter-instance memory (same project, persisted)

After each task:

1. extract memories from trajectory + test output observed by the agent,
2. store in `/mnt/memory`,
3. retrieve for next tasks in the same project.

## Retrieval Strategy (Adjusted)

Given harness already scopes memory per project directory, project filtering is effectively implicit.

First-wave retrieval should optimize precision over complexity:

1. vector retrieve top-k small (`k=3` default),
2. rerank by semantic similarity + specificity heuristic,
3. dedupe near-identical memories by normalized content/target.

Optional defensive project filter remains acceptable for local mixed-run tooling, but not required for harness correctness.

## Memory Quality Without Eval Outcome Feedback

Because evaluator outcomes are unavailable in-process, avoid claiming `success/failure` supervision from harness verdicts.

Use weak but available signals:

1. whether agent produced a patch vs crash/nopatch,
2. whether memory was injected,
3. whether injected memory target overlapped changed files/tests run,
4. whether agent's own rerun tests after edits improved (if present in trajectory).

These are proxies, not ground-truth correctness.

## Extraction Upgrade (Feasible Inputs Only)

Do not rely on post-run eval files.

Extract from:

1. agent trajectory observation messages (`<returncode>`, `<output>`),
2. test command output run during solving,
3. explicit assertion blocks (`Expected/Received`, failing test names, stack line hints).

Store failure fingerprint only when structured enough:

1. at least one stable test identifier, and
2. at least one concrete assertion/error snippet.

## Injection Format Upgrade (High ROI, Low Risk)

Current generic list should be replaced with actionable conditional checks.

Format target:

1. “If touching X and seeing Y, verify Z before submit.”

Token budget (explicit):

1. hard cap 350 tokens total,
2. max 4 memories,
3. max ~70 tokens each,
4. drop low-specificity/redundant entries first.

## Budget-Aware Extraction

Extraction has non-trivial cost overhead.

Policy:

1. if remaining budget below threshold, skip LLM extraction and use heuristic-only extraction,
2. always prefer solving budget over memory extraction budget.

## Memory Pruning / Noise Control

Need active pruning to avoid memory quality decay over 25 tasks.

Pruning policy:

1. remove stale low-specificity memories,
2. merge duplicates by normalized trigger/action,
3. cap memory count per project and evict lowest utility first.

## Two-Pass / Semantic Self-Review Trigger

Keep out of first-wave memory rollout.

Reason:

1. invasive control-flow coupling,
2. uncertain ROI compared with extraction+injection improvements,
3. can be revisited after memory quality improvements stabilize.

## Evaluation Plan (Revised)

### A/B

1. Baseline: current extraction + injection.
2. Variant: improved extraction from run-time test output + conditional injection + pruning + budget fallback.

### Primary metric

1. resolved count.

### Secondary metrics (quality)

1. Injection Precision@k (manual/sample audit),
2. Irrelevant Injection Rate,
3. Specificity score (penalize broad/generic memories),
4. memory growth vs retrieval quality trend,
5. runtime/cost overhead.

## Rollout Order

1. injection format upgrade,
2. extraction upgrade from run-time test output,
3. budget-aware extraction fallback,
4. pruning/eviction,
5. optional retrieval rerank refinements.

## Summary

Feasible path under competition constraints:

1. no cross-project bootstrap assumptions,
2. no reliance on post-eval artifacts,
3. prioritize extraction quality + injection actionability,
4. treat inter-instance memory (same project) as the main compounding advantage.
