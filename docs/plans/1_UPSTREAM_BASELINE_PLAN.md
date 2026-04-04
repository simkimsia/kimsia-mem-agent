# 1_UPSTREAM_BASELINE_PLAN

## Goal

Establish a clean upstream control on the VPS that is as close as possible to the published SWE-bench Pro Kimi setup before making further changes to `kimsia-mem-agent`.

This plan exists because the current blocker is **interface fidelity**, not memory quality.

## Core Decision

Do **not** keep iterating inside `kimsia-mem-agent` for now.

Instead:

1. Keep `kimsia-mem-agent` as the experimental branch.
2. Create a separate clean upstream SWE-bench Pro baseline setup on the VPS.
3. Use upstream `SWE-agent` scaffold first.
4. Use local Docker evaluation first.
5. Only revisit memory or custom agent changes after upstream reproduction works on at least one known Kimi-solved instance.

## Why This Is The Right Move

The selected `element-web` instances are confirmed in `agent_runs` as solved by `Kimi - paper`.

That means:

1. The model is capable on these tasks.
2. The failure is likely in the surrounding interface, scaffold, prompting, tool flow, or execution environment.
3. Continuing to tweak memory or custom prompt layers before restoring the upstream control will hide the real issue.

## Working Assumption

Treat the published Kimi runs as closer to the upstream SWE-bench Pro scaffold than to the current custom `mini`-style SSH agent.

This assumption should guide the next phase unless direct VPS trajectory evidence proves otherwise.

## Proposed VPS Layout

Use separate directories with clear roles:

1. `SWE-bench_Pro-os/`
   - upstream reference repo
   - patch evaluation script
   - run scripts and Dockerfiles
2. `SWE-bench_Pro-os/SWE-agent/`
   - upstream scaffold for patch generation
3. `kimsia-mem-agent/`
   - custom experimental agent
   - no longer the primary reproduction path
4. `mem-comp-26/`
   - optional comparison harness
   - not the main route for reproducing published SWE-bench Pro Kimi results

## Execution Strategy

### Phase 1: Build The Clean Control

On the VPS:

1. Create a clean checkout of `SWE-bench_Pro-os`.
2. Set up the upstream `SWE-agent` path there.
3. Avoid modifying `kimsia-mem-agent` during this phase.

Success condition:

1. A single clean environment exists where the only moving pieces are upstream SWE-agent config, model endpoint, and the SWE-bench Pro task instance.

### Phase 2: Debug With Single Instances First

Use one or two of the confirmed Kimi-solved `element-web` instances first, not a batch.

Recommended starting rule:

1. Pick one lower-turn solved instance first.
2. Then pick one mid-turn solved instance.

Reason:

1. It is cheaper.
2. It is easier to inspect trajectories.
3. It avoids hiding failures inside batch orchestration noise.

## Candidate Target Instances

Good first-pass candidates from the known solved set:

1. `instance_element-hq__element-web-27139ca68eb075a4438c18fca184887002a4ffbc-vnan` (`23` turns)
2. `instance_element-hq__element-web-9bf77963ee5e036d54b2a3ca202fbf6378464a5e-vnan` (`25` turns)
3. `instance_element-hq__element-web-6961c256035bed0b7640a6e5907652c806968478-vnan` (`33` turns)

Avoid starting with the highest-turn cases.

## Evaluation Strategy

Start with local Docker evaluation, not Modal.

Use upstream SWE-bench Pro evaluation script with local Docker first because:

1. cost is lower
2. logs are easier to inspect
3. the current problem is baseline mismatch, not throughput
4. iteration speed is better for single-instance debugging

Only use Modal later if:

1. upstream local reproduction works on one or more target instances
2. larger-scale runs are needed
3. local infrastructure becomes the bottleneck

## What To Compare

Once a single upstream run is available, compare it against the current `kimsia-mem-agent` behavior on the same instance.

Inspect:

1. first prompt shape
2. tool or action interface
3. command sequencing
4. edit strategy
5. submission strategy
6. patch focus
7. number of turns before meaningful edit

The point is not to compare final scores first.
The point is to compare **behavioral interface** first.

## Explicit Non-Goals For This Phase

Do **not** do the following yet:

1. add memory
2. improve memory retrieval
3. add self-review layers
4. tune long custom prompt instructions
5. add more custom tools
6. change multiple systems at once

These are all downstream concerns.

## Decision Gate Before Returning To `kimsia-mem-agent`

Do not resume custom-agent iteration until at least one of these is true:

1. upstream SWE-agent reproduces one known Kimi-solved `element-web` instance
2. upstream SWE-agent also fails, and the failure clearly points to provider/config/environment mismatch instead of custom-agent mismatch

## If Upstream Reproduces

Then the next move is:

1. freeze the successful upstream config
2. treat it as the control
3. diff `kimsia-mem-agent` against that control
4. remove custom behaviors until the custom agent is behaviorally close to the control

Likely first removals:

1. memory injection
2. pattern memory prompt injection
3. custom retry and spend noise if they distort context or runtime
4. extra prompt instructions not present upstream

## If Upstream Fails Too

Then the problem likely shifts to:

1. provider mismatch
2. model alias mismatch
3. endpoint behavior
4. VPS environment mismatch
5. unpublished config/runtime details

In that case, stop changing agent logic and focus on environment and provider fidelity.

## Minimal Success Criteria

This phase is successful if all of the following are achieved:

1. a clean upstream control exists on the VPS
2. one known Kimi-solved `element-web` instance is run through upstream SWE-agent
3. the resulting trajectory and patch are captured
4. the result is evaluated with local Docker
5. a clear comparison can be made against `kimsia-mem-agent`

## Immediate Next Actions

1. Create the clean upstream baseline setup on the VPS.
2. Run one known solved `element-web` instance through upstream SWE-agent.
3. Evaluate with local Docker.
4. Save the trajectory, patch, and logs.
5. Only then decide whether the next step is:
   - upstream tuning
   - provider/environment debugging
   - or reducing `kimsia-mem-agent` toward the upstream control
