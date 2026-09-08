# kimsia-mem-agent

A software-engineering agent that carries a **pattern memory across task
instances**, built for the [MemComp-26](https://github.com/mem-comp/mem-comp-26)
competition and used as the treatment arm in an SMU MITB capstone study on
SWE-bench Pro.

The question it was built to answer: *does letting an agent remember what
worked on previous repository tasks make it better at the next one?*

**The measured answer was no.** On 100% of the instances in the target
repository, memory-ON resolved 21/56 (38%) against memory-OFF's 23/56 (41%).
A 23-instance pilot had shown memory *winning* by 13 points; the effect
reversed at full sample. The reversal is the finding — and it only surfaced
because the study ran every instance rather than a subset.

Raw run data, manifests and analysis scripts live in
[capstone-mem-artifacts](https://github.com/simkimsia/capstone-mem-artifacts).

## What it does

The agent is a subclass of [mini-swe-agent](https://github.com/SWE-agent/mini-swe-agent)'s
`DefaultAgent`, driving a one-command-per-step shell loop over SSH into a
containerized repository. Three mechanisms sit on top of that baseline, each
independently switchable so an arm can be isolated:

**1. Cross-instance pattern memory** (`src/pattern_memory.py`)
After each run, high-signal command patterns are extracted from the trajectory
and written to a persistent store, scored by whether the run submitted a patch
(+0.35) or not (-0.25). On the next task, patterns are retrieved by a blend of
embedding cosine similarity (0.55), normalized term overlap (0.45), and the
pattern's accumulated success score. Patterns with more failures than successes
are never retrieved. Survivors are injected into the prompt as prior art.

Embeddings come from an OpenAI-compatible endpoint, with a deterministic
hashed fallback so a dead embedding service
degrades instead of crashing — retrieval is then skipped entirely unless
`MEMORY_ALLOW_FALLBACK_RETRIEVAL` says otherwise, so a fallback can never
silently contaminate a memory arm.

**2. Self-review before submit** (`_run_self_review`)
Before the agent is allowed to finish, the candidate diff is measured against
the task text: which files changed, whether they overlap the paths and
identifiers the issue actually named, and whether the diff carries structural
risk signals. A critic pass reads that evidence and either accepts the patch or
returns concrete revision actions, which are fed back as another turn.

**3. Pre-submit verification gate** (`_vg_run_gate`)
Runs the repository's own typecheck/build and reads the result. The pass
criterion is *errors the patch introduced*, not a clean exit code — a repo that
was already failing does not get to veto a correct fix.

## Layout

| Path | What |
| :--- | :--- |
| `src/agent.py` | `MemoryAgent` — the loop, self-review, verification gate |
| `src/pattern_memory.py` | the memory store: extraction, scoring, retrieval |
| `src/env.py` | SSH execution environment |
| `src/main.py` | entrypoint; reads one instance, writes `patch.diff` |
| `src/config.yaml` | prompts, step/cost limits, model selection |
| `docs/plans/` | design notes per mechanism |
| `docs/runs/` | per-run debugging records |

## Running it

The image is self-contained; one container solves one instance.

```bash
docker build -t kimsia-mem-agent .
docker run --rm \
  -v /path/to/instance:/instance \
  -v /path/to/memory:/memory \
  kimsia-mem-agent \
  --instance-path /instance \
  --memory-path /memory \
  --llm-base-url "$LLM_BASE_URL" \
  --llm-api-key "$LLM_API_KEY" \
  --env-ssh "user:password@host"
```

`/instance` holds the `instance.json` (problem statement, requirements,
interface, repo language); the patch is written back there. `/memory` is the
store that persists across instances — mount the same directory across a batch
to get the memory arm, or a fresh one per instance for the control arm.

Model selection is via litellm, overridable with `MODEL_NAME`. The committed
defaults are GLM-4.7 and `nomic-embed-text-v1.5`; the study runs used Kimi K2
(`kimi-k2-instruct-0905`) with bge-m3 embeddings at 1024 dimensions.

## Configuration

Every mechanism is off-switchable, which is what makes an arm an arm.

| Arm switch | Effect |
| :--- | :--- |
| `SELF_REVIEW_ENABLED` | the pre-submit critic pass |
| `VERIFY_GATE_ENABLED` | the verification gate |
| `BEHAVIORAL_SELFTEST` | prompt-level self-test loop |
| *(memory)* | controlled by the mount: a shared `--memory-path` across a batch is the memory arm, a fresh one per instance is the control |

| Memory | Effect |
| :--- | :--- |
| `MEMORY_TOP_K` | patterns injected per task (default 3) |
| `MEMORY_MIN_SIM` / `MEMORY_MIN_OVERLAP` | retrieval thresholds; a pattern needs to clear one of the two |
| `MEMORY_SCORE_WEIGHT` | how much accumulated success outweighs similarity (default 0.25) |
| `MEMORY_MAX_ITEMS` / `MEMORY_MAX_PATTERN_LEN` | store size caps (default 200 items) |
| `MEMORY_EMBED_MODEL` | embedding model; committed default `litellm_proxy/nomic-embed-text-v1.5` |
| `MEMORY_ALLOW_FALLBACK_RETRIEVAL` | permit retrieval on hashed-embedding fallback |
| `MEMORY_VERIFICATION_AWARE` | bias memory toward verification-related patterns |

| Limits | Effect |
| :--- | :--- |
| `SELF_REVIEW_MAX_CHANGED_FILES` / `SELF_REVIEW_MAX_DIFF_LINES` | when a diff is too big to review |
| `SELF_REVIEW_MAX_EXTRA_STEPS` / `SELF_REVIEW_CRITIC_RETRIES` | budget for the review pass |
| `VERIFY_GATE_MAX_BOUNCES` / `VERIFY_GATE_TIMEOUT` | how many times the gate may send the agent back |
| `MODEL_QUERY_MAX_RETRIES`, `MODEL_QUERY_BACKOFF_*`, `MODEL_QUERY_MIN_INTERVAL_S` | rate-limit handling for the model endpoint |
| `PRINT_SPEND` | per-run cost reporting |

## Study parameters

| | |
| :--- | :--- |
| Dataset | SWE-bench Pro, `element-hq/element-web` — 56 instances, 100% of the repo |
| Canonical runs | 112 paired (56 instances × 2 memory arms) |
| All runs incl. pilots and baselines | 169 instance-runs, US$63.56 total LLM spend |
| Model / embeddings | Kimi K2 `kimi-k2-instruct-0905` / bge-m3, 1024-dim |
| Infrastructure | 8-core OVH VPS |

## Credit

The agent loop, prompt scaffolding and submission protocol are
[mini-swe-agent](https://github.com/SWE-agent/mini-swe-agent) by the SWE-agent
team. The pattern memory, self-review pass, verification gate and the
experimental design around them are mine.
