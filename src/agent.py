import os
import re
import json
import time
import random
import requests
from minisweagent.agents.default import DefaultAgent, LimitsExceeded
try:
    from minisweagent.exceptions import InterruptAgentFlow
except Exception:
    try:
        from minisweagent.agents.default import InterruptAgentFlow
    except Exception:
        class InterruptAgentFlow(Exception):
            def __init__(self, *args, messages=None, **kwargs):
                super().__init__(*args)
                self.messages = list(messages or [])
from pattern_memory import PatternMemory

# ---------------------------------------------------------------------------
# Self-review constants
# ---------------------------------------------------------------------------
_STOPWORDS = frozenset({
    'this', 'that', 'with', 'from', 'should', 'have', 'been', 'will', 'when',
    'they', 'them', 'their', 'than', 'then', 'also', 'some', 'into', 'more',
    'what', 'were', 'does', 'like', 'only', 'just', 'very', 'your', 'about',
    'which', 'could', 'other', 'would', 'there', 'these', 'those', 'after',
    'before', 'being', 'using', 'because',
})
_GENERIC_TOKENS = frozenset({
    'file', 'test', 'make', 'each', 'data', 'code', 'line', 'type', 'name',
    'function', 'method', 'class', 'module', 'import', 'return', 'value',
    'error', 'print', 'string', 'number', 'list', 'dict', 'true', 'false',
    'none', 'added', 'removed', 'change', 'changes', 'update', 'updates',
})
_IDENTIFIER_RE = re.compile(r'[a-z]+[A-Z]|[A-Z][a-z]+[A-Z]|_|-')
_PATH_RE = re.compile(r'(?:^|[\s\'"`(])([a-zA-Z0-9_./-]+\.(?:ts|tsx|js|jsx|py|rb|go|rs|java|c|cpp|h|hpp|css|scss|html))\b')
_FULL_PATH_RE = re.compile(r'(?:^|[\s\'"`(])((?:[a-zA-Z0-9_.-]+/)+[a-zA-Z0-9_.-]+)\b')
_DIFF_HUNK_RE = re.compile(r'^@@\s', re.MULTILINE)
_WHITESPACE_RE = re.compile(r'\s+')
_SUBMISSION_EXCLUDE_PATTERNS = (
    'appendonly.aof*',
    '*.rdb',
    'dump.rdb',
    '__pycache__/',
    '.pytest_cache/',
    '.mypy_cache/',
    '.ruff_cache/',
    '.pyre/',
    '.tox/',
    '.nox/',
    '.venv/',
    'node_modules/',
    '.npm/',
    '.pnpm-store/',
    '.yarn/',
    '.parcel-cache/',
    '.next/',
    '.nuxt/',
    '.svelte-kit/',
    'coverage/',
    'htmlcov/',
    'dist/',
    'build/',
    'target/',
    '*.backup',
    '*.bak',
    '*.orig',
    '*.rej',
    '*.tmp',
    '*.temp',
    '*.swp',
    '*.swo',
    '*~',
    'backup_*',
    'temp_*',
    'tmp_*',
    'scratch_*',
    '*_SUMMARY.md',
    'CHANGES_SUMMARY.md',
    'IMPLEMENTATION_SUMMARY.md',
    'SOLUTION_SUMMARY.md',
    'test_implementation.py',
    'test_implementation.js',
    'test_fix.js',
    'verify_fix.js',
    'final_validation.py',
    'manual_test.sh',
    'manual_test_v2.sh',
    'requirements_check.sh',
)

_JUNK_FILE_RE = re.compile(
    r'(^|/)(?:'
    r'.*\.backup|.*\.bak|.*\.orig|.*\.rej|.*\.tmp|.*\.temp|'
    r'backup_.*|temp_.*|tmp_.*|scratch_.*|'
    r'.*_SUMMARY\.md|CHANGES_SUMMARY\.md|IMPLEMENTATION_SUMMARY\.md|SOLUTION_SUMMARY\.md|'
    r'test_fix\.js|verify_fix\.js|final_validation\.py|manual_test(?:_v2)?\.sh|requirements_check\.sh'
    r')$',
    re.IGNORECASE,
)
_STRUCTURAL_LINE_RE = re.compile(
    r'^(?:'
    r'(?:else\s+)?if\b|'
    r'return\b|'
    r'case\b|'
    r'switch\b|'
    r'(?:public|private|protected)\b|'
    r'(?:const|let|var)\b|'
    r'this\.|'
    r'super\.|'
    r'[A-Za-z_][A-Za-z0-9_.]*\s*[:=]'
    r')'
)

_CRITIC_SYSTEM = "You are a strict code-review critic. Respond with ONLY valid JSON, no markdown fences."
_CRITIC_USER = """\
Task summary (first 500 chars):
{task_summary}

Changed files:
{changed_files}

Observed risk signals:
{risk_signals}

Diff (-U0, possibly truncated):
{diff}

Question: Is this patch off-target or risky?
If yes, list exact corrective actions the developer should take.
Prioritize structural correctness over patch size.
Treat malformed code, duplicated branches or assignments, partial rewrites, and patches likely to wedge validation as strong negative signals.
Treat backup files, summary markdown, scratch scripts, and one-off validation/demo files as strong negative signals.
Do not penalize repo-native helper files when they are relevant and integrated cleanly.

Respond with ONLY this JSON schema:
{{"risk_level": "low|medium|high", "off_target": true/false, "reasons": ["..."], "actions": ["..."]}}"""

class MemoryAgent(DefaultAgent):
    def __init__(self, memory_path: str, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.memory_path = f'{memory_path}/memory.json'
        self.max_memory_messages = int(os.environ.get('MEMORY_MAX_MESSAGES', '30'))
        self.max_memory_chars = int(os.environ.get('MEMORY_MAX_CHARS', '1800'))
        self.memorized_messages = []
        model_kwargs = getattr(getattr(self.model, "config", None), "model_kwargs", {}) or {}
        self.pattern_memory = PatternMemory(
            memory_dir=memory_path,
            api_base=str(model_kwargs.get("api_base", "")),
            api_key=str(model_kwargs.get("api_key", "")),
        )
        self.pattern_prompt = ""
        self.load_memory()

        # Self-review config (all off by default — baseline unchanged)
        self.sr_enabled = os.environ.get('SELF_REVIEW_ENABLED', '0') == '1'
        self.sr_max_extra_steps = int(os.environ.get('SELF_REVIEW_MAX_EXTRA_STEPS', '2'))
        self.sr_max_changed_files = int(os.environ.get('SELF_REVIEW_MAX_CHANGED_FILES', '3'))
        self.sr_max_diff_lines = int(os.environ.get('SELF_REVIEW_MAX_DIFF_LINES', '120'))
        self.sr_extra_steps_used = 0
        self.query_max_retries = int(os.environ.get('MODEL_QUERY_MAX_RETRIES', '6'))
        self.query_backoff_base_s = float(os.environ.get('MODEL_QUERY_BACKOFF_BASE_S', '1.0'))
        self.query_backoff_max_s = float(os.environ.get('MODEL_QUERY_BACKOFF_MAX_S', '20.0'))
        self.query_backoff_jitter_s = float(os.environ.get('MODEL_QUERY_BACKOFF_JITTER_S', '0.35'))
        self.query_min_interval_s = float(os.environ.get('MODEL_QUERY_MIN_INTERVAL_S', '0.0'))
        self.print_spend_enabled = os.environ.get('PRINT_SPEND', '1') == '1'
        self._last_query_at = 0.0
        if self.sr_enabled:
            print(f'self-review enabled: max_extra_steps={self.sr_max_extra_steps}, '
                  f'max_changed_files={self.sr_max_changed_files}, max_diff_lines={self.sr_max_diff_lines}')

    def _compact_messages(self, messages: list[dict]) -> list[dict]:
        compacted = []
        for message in messages:
            role = message.get('role')
            content = message.get('content')
            if role not in {'user', 'assistant'}:
                continue
            if not isinstance(content, str):
                continue
            content = content.strip()
            if not content:
                continue
            compacted.append(
                {
                    'role': role,
                    'content': content[: self.max_memory_chars],
                    'timestamp': message.get('timestamp', time.time()),
                }
            )
        return compacted[-self.max_memory_messages :]

    def load_memory(self) -> None:
        if os.path.exists(self.memory_path):
            with open(self.memory_path, 'r') as f:
                remembered = self._compact_messages(json.load(f))
                self.memorized_messages = [
                    *remembered,
                    {
                        'role': 'user',
                        'content': '**A new task started. The project root path has been reset to a clean state for this task.**',
                        'timestamp': time.time(),
                    },
                ]
            print(f'loaded {len(self.memorized_messages)} memorized messages')

    def save_memory(self) -> None:
        serialized = self._compact_messages(self.messages[1:])
        print(f'saved {len(serialized)} messages to memory')
        with open(self.memory_path, 'w') as f:
            json.dump(serialized, f, indent=2)

    def print_spend(self) -> None:
        # NOTE: spend info is updated asynchronously in litellm, and can be stale for 2~30 seconds
        # see https://github.com/BerriAI/litellm/blob/d07c87860db91c7bbf5a051d1cf82857432bf856/litellm/proxy/utils.py#L3874

        u = self.model.config.model_kwargs['api_base']
        h = {'Authorization': f'Bearer {self.model.config.model_kwargs["api_key"]}'}

        try:
            info = requests.get(f'{u}/user/info', headers=h, timeout=2).json()
            user_spend = f'{info["user_info"]["spend"]:.4f} / {info["user_info"]["max_budget"]:.4f}'
        except Exception:
            user_spend = '???'

        try:
            info = requests.get(f'{u}/key/info', headers=h, timeout=2).json()
            key_spend = f'{info["info"]["spend"]:.4f} / {info["info"]["max_budget"]:.4f}'
        except Exception:
            key_spend = '???'

        print(f'spend so far: key {key_spend}, user {user_spend}')

    # ------------------------------------------------------------------
    # Self-review helpers
    # ------------------------------------------------------------------

    def _sr_extract_general_keywords(self, task: str) -> set[str]:
        """Step 1: extract high-signal identifier-like tokens from task text."""
        tokens = set()
        for word in re.findall(r'[A-Za-z0-9_.-]+', task.lower()):
            if len(word) < 4:
                continue
            if word in _STOPWORDS or word in _GENERIC_TOKENS:
                continue
            # keep identifier-like tokens (camelCase, snake_case, has _ or -)
            if _IDENTIFIER_RE.search(word):
                tokens.add(word)
            # also keep anything that looks domain-specific (not pure english)
            elif '_' in word or '-' in word:
                tokens.add(word)
            # keep PascalCase-ish tokens from original case
            elif any(c.isupper() for c in word[1:]):
                tokens.add(word)
        # also extract original-case identifiers
        for word in re.findall(r'[A-Za-z_][A-Za-z0-9_]+', task):
            if len(word) >= 4 and (_IDENTIFIER_RE.search(word) or '_' in word):
                tokens.add(word.lower())
        return tokens

    def _sr_extract_explicit_paths(self, task: str) -> set[str]:
        """Step 2: regex-extract full file/path strings from task text."""
        paths = set()
        for m in _PATH_RE.finditer(task):
            paths.add(m.group(1))
        for m in _FULL_PATH_RE.finditer(task):
            candidate = m.group(1)
            if '/' in candidate and not candidate.startswith('http'):
                paths.add(candidate)
        return paths

    def _submission_prepare_snapshot(self) -> None:
        """Stage a submission patch from the current working tree.

        The agent prompt only emits the submit marker. Patch generation happens
        here so we can consistently include valid new files while filtering
        common generated junk using repo-local Git excludes.
        """
        exclude_lines = '\n'.join(_SUBMISSION_EXCLUDE_PATTERNS)
        cmd = (
            "mkdir -p .git/info && "
            "cat <<'EOF' >> .git/info/exclude\n"
            f"{exclude_lines}\n"
            "EOF\n"
            "git reset >/dev/null 2>&1 && "
            "git add -A >/dev/null 2>&1"
        )
        self.env.execute(cmd)

    def _submission_collect_patch(self) -> str:
        """Return the staged patch using the normalized submission snapshot."""
        self._submission_prepare_snapshot()
        r = self.env.execute('git diff --cached')
        return r.get('output', '')

    def _sr_normalize_added_line(self, line: str) -> str:
        line = _WHITESPACE_RE.sub(' ', line.strip())
        return line.rstrip(',;')

    def _sr_detect_structural_risks(self, diff_text: str) -> list[str]:
        """Look for malformed diff patterns that often indicate shell-edit corruption."""
        reasons = []
        recent_added = []
        duplicate_structural_lines = set()
        blank_run = 0

        for raw_line in diff_text.splitlines():
            if raw_line.startswith('diff --git ') or raw_line.startswith('@@'):
                recent_added = []
                blank_run = 0
                continue

            if raw_line.startswith('+') and not raw_line.startswith('+++'):
                content = raw_line[1:]
                normalized = self._sr_normalize_added_line(content)
                if not normalized:
                    blank_run += 1
                    if blank_run >= 3:
                        reasons.append('runs of added blank lines suggest patch corruption')
                    continue

                blank_run = 0
                if _STRUCTURAL_LINE_RE.search(normalized):
                    if normalized in recent_added[-8:]:
                        duplicate_structural_lines.add(normalized)
                recent_added.append(normalized)
                if len(recent_added) > 12:
                    recent_added = recent_added[-12:]
                continue

            if not raw_line.startswith('-'):
                blank_run = 0

        if duplicate_structural_lines:
            sample = sorted(duplicate_structural_lines)[:3]
            reasons.append(f'duplicate added structural lines: {sample}')
        return reasons

    def _sr_compute_target_overlap(self, changed_files: list[str], keywords: set[str], explicit_paths: set[str]) -> float:
        """Step 3: compute overlap ratio."""
        if not changed_files:
            return 1.0  # nothing changed, no risk from overlap
        hits = 0
        for fpath in changed_files:
            fpath_lower = fpath.lower()
            # check explicit path match (higher priority)
            if any(ep in fpath or fpath.endswith(ep) for ep in explicit_paths):
                hits += 1
                continue
            # check keyword overlap with path components
            parts = set(re.findall(r'[A-Za-z0-9_]+', fpath_lower))
            if parts & keywords:
                hits += 1
        return hits / len(changed_files)

    def _sr_compute_risk_signals(self, task: str) -> dict:
        """Risk gate: gather signals via SSH, return metrics + should_review."""
        # Prefer staged diff (submit path uses git diff --cached), fallback to unstaged.
        r1 = self.env.execute('git diff --cached --name-only')
        changed_files = [f for f in r1.get('output', '').strip().split('\n') if f.strip()]
        diff_source = 'cached'
        if not changed_files:
            r1 = self.env.execute('git diff --name-only')
            changed_files = [f for f in r1.get('output', '').strip().split('\n') if f.strip()]
            diff_source = 'working'
        changed_count = len(changed_files)

        # Prefer staged numstat, fallback to unstaged.
        r2 = self.env.execute('git diff --cached --numstat')
        if not r2.get('output', '').strip():
            r2 = self.env.execute('git diff --numstat')
        diff_lines = 0
        for line in r2.get('output', '').strip().split('\n'):
            parts = line.split('\t')
            if len(parts) >= 2:
                try:
                    diff_lines += int(parts[0] if parts[0] != '-' else 0)
                    diff_lines += int(parts[1] if parts[1] != '-' else 0)
                except ValueError:
                    pass

        # keyword extraction
        keywords = self._sr_extract_general_keywords(task)
        explicit_paths = self._sr_extract_explicit_paths(task)
        target_overlap = self._sr_compute_target_overlap(changed_files, keywords, explicit_paths)
        diff_preview = self._submission_collect_patch()
        structural_reasons = self._sr_detect_structural_risks(diff_preview)

        # decide
        reasons = []
        if changed_count > self.sr_max_changed_files:
            reasons.append(f'changed_files={changed_count} > {self.sr_max_changed_files}')
        if diff_lines > self.sr_max_diff_lines:
            reasons.append(f'diff_lines={diff_lines} > {self.sr_max_diff_lines}')
        if target_overlap == 0 and changed_count > 0:
            reasons.append('zero target overlap')
        junk_files = [f for f in changed_files if _JUNK_FILE_RE.search(f)]
        if junk_files:
            reasons.append('junk files in patch')
        reasons.extend(structural_reasons)

        metrics = {
            'changed_files': changed_count,
            'changed_file_list': changed_files,
            'diff_source': diff_source,
            'diff_lines': diff_lines,
            'target_overlap': round(target_overlap, 3),
            'junk_file_list': junk_files,
            'structural_signal_list': structural_reasons,
            'should_review': len(reasons) > 0,
            'reasons': reasons,
        }
        return metrics

    def _sr_truncate_diff(self, diff_text: str, max_chars: int = 12000, max_hunks: int = 60) -> str:
        """Truncate diff to first max_chars or max_hunks, whichever comes first."""
        hunks = _DIFF_HUNK_RE.findall(diff_text)
        truncated = False
        result = diff_text

        if len(hunks) > max_hunks:
            # find position of the (max_hunks+1)-th hunk marker
            pos = 0
            count = 0
            for m in _DIFF_HUNK_RE.finditer(diff_text):
                count += 1
                if count > max_hunks:
                    pos = m.start()
                    break
            if pos > 0:
                result = diff_text[:pos]
                truncated = True

        if len(result) > max_chars:
            result = result[:max_chars]
            truncated = True

        if truncated:
            result += '\n[DIFF_TRUNCATED]'
        return result

    def _sr_run_critic(self, task: str, metrics: dict) -> dict:
        """Pass B: one LLM call to critique the diff. Returns parsed critic result."""
        self.sr_extra_steps_used += 1
        fallback = {'risk_level': 'low', 'off_target': False, 'reasons': [], 'actions': []}
        max_retries = int(os.environ.get('SELF_REVIEW_CRITIC_RETRIES', '2'))

        # collect diff (prefer staged to match submitted patch)
        r = self.env.execute('git diff --cached -U0')
        if not r.get('output', '').strip():
            r = self.env.execute('git diff -U0')
        raw_diff = r.get('output', '')
        diff = self._sr_truncate_diff(raw_diff)

        critic_messages = [
            {'role': 'system', 'content': _CRITIC_SYSTEM},
            {'role': 'user', 'content': _CRITIC_USER.format(
                task_summary=task[:500],
                changed_files='\n'.join(metrics.get('changed_file_list', [])),
                risk_signals='\n'.join(metrics.get('reasons', [])) or '(none)',
                diff=diff,
            )},
        ]

        for attempt in range(max_retries + 1):
            try:
                response = self.model.query(critic_messages)
                raw_content = response.get('content', '')
                print(f'[self-review] critic raw: {raw_content[:500]}')

                # try to extract JSON from response (may have markdown fences)
                json_match = re.search(r'\{[\s\S]*\}', raw_content)
                if not json_match:
                    print('[self-review] critic parse failed: no JSON found')
                    return fallback

                parsed = json.loads(json_match.group())
                return {
                    'risk_level': str(parsed.get('risk_level', 'low')),
                    'off_target': bool(parsed.get('off_target', False)),
                    'reasons': list(parsed.get('reasons', [])),
                    'actions': list(parsed.get('actions', [])),
                }
            except (json.JSONDecodeError, KeyError, TypeError) as e:
                print(f'[self-review] critic parse failed: {e}')
                return fallback
            except Exception as e:
                msg = str(e)
                retryable = ('429' in msg) or ('ratelimit' in msg.lower()) or ('busy' in msg.lower())
                if retryable and attempt < max_retries:
                    backoff_s = 2 ** attempt
                    print(f'[self-review] critic transient failure, retrying in {backoff_s}s: {e}')
                    time.sleep(backoff_s)
                    continue
                print(f'[self-review] critic query failed, skipping review: {e}')
                return fallback
        return fallback

    def _sr_run_revise(self, actions: list[str]) -> None:
        """Inject critic feedback and allow one revise cycle."""
        self.sr_extra_steps_used += 1

        # pop exit message(s) so agent can continue
        while self.messages and self.messages[-1].get('role') == 'exit':
            self.messages.pop()

        feedback = (
            "**Self-review critic found issues with your patch. Please fix before submitting.**\n\n"
            "Required actions:\n" +
            '\n'.join(f'- {a}' for a in actions) +
            "\n\nAfter fixing, submit again with:\n"
            "```bash\necho COMPLETE_TASK_AND_SUBMIT_FINAL_OUTPUT\n```"
        )
        self._sr_push_messages(
            {
                'role': 'user',
                'content': feedback,
                'timestamp': time.time(),
            }
        )

        # mini step loop — allow some iterations for format errors etc.
        for _ in range(15):
            try:
                self.step()
            except InterruptAgentFlow as e:
                self._sr_push_messages(*(e.messages or []))
            except Exception:
                break
            if self.messages[-1].get('role') == 'exit':
                break

    def _sr_push_messages(self, *messages) -> None:
        """Append one or more pre-formatted messages safely."""
        for msg in messages:
            if not isinstance(msg, dict):
                continue
            role = msg.get('role')
            if not role:
                continue
            payload = dict(msg)
            payload.pop('role', None)
            self.add_message(role, **payload)

    def _sr_load_rules(self, task: str) -> list[str]:
        """Load matching rules from rules_memory.json if it exists."""
        rules_path = '/mnt/memory/rules_memory.json'
        if not os.path.exists(rules_path):
            return []
        try:
            with open(rules_path, 'r') as f:
                rules = json.load(f)
            if not isinstance(rules, list):
                return []
            task_lower = task.lower()
            matching = []
            for rule in rules[:50]:  # bounded scan
                signal = str(rule.get('signal', '')).lower()
                if signal and signal in task_lower:
                    matching.append(str(rule.get('rule_text', '')))
            return matching[:3]
        except Exception:
            return []

    def _sr_log(self, **kwargs) -> None:
        """Log self-review metrics to stdout."""
        print(f'[self-review] {json.dumps(kwargs, default=str)}')

    def _run_self_review(self, task: str, status, result):
        """Orchestrate the self-review after Pass A. Returns (status, result), possibly revised."""
        self._sr_log(enabled=True, phase='start')
        self._submission_prepare_snapshot()

        # Risk gate
        metrics = self._sr_compute_risk_signals(task)
        self._sr_log(phase='risk_gate', **metrics)

        if not metrics['should_review']:
            self._sr_log(phase='skip', reason='risk gate not triggered')
            return status, result

        # Budget check
        if self.sr_extra_steps_used >= self.sr_max_extra_steps:
            self._sr_log(phase='skip', reason='extra step budget exhausted')
            return status, result

        # Pass B: critic
        critic = self._sr_run_critic(task, metrics)
        self._sr_log(phase='critic', **critic)

        needs_revise = critic['off_target'] or critic['risk_level'] in ('medium', 'high')
        if not needs_revise:
            self._sr_log(phase='done', revise_applied=False, extra_steps_used=self.sr_extra_steps_used)
            return status, result

        # Budget check for revise
        if self.sr_extra_steps_used >= self.sr_max_extra_steps:
            self._sr_log(phase='skip_revise', reason='extra step budget exhausted after critic')
            return status, result

        # Revise
        self._sr_log(phase='revise_start', actions=critic['actions'])
        self._sr_run_revise(critic['actions'])

        # extract new status/result from revised exit message
        last_extra = self.messages[-1].get('extra', {}) if self.messages else {}
        new_status = last_extra.get('exit_status', status)
        new_result = last_extra.get('submission', result)
        if str(new_status).strip().lower() == 'submitted':
            new_result = self._submission_collect_patch()

        self._sr_log(phase='done', revise_applied=True, extra_steps_used=self.sr_extra_steps_used,
                     new_status=str(new_status))
        return new_status, new_result

    # ------------------------------------------------------------------
    # Core overrides
    # ------------------------------------------------------------------

    def run(self, task: str):
        selected = self.pattern_memory.retrieve_for_task(task)
        self.pattern_prompt = self.pattern_memory.build_prompt_block(selected)
        if selected:
            print(f'retrieved {len(selected)} pattern memories')

        status, result = super().run(task)
        if str(status).strip().lower() == 'submitted':
            result = self._submission_collect_patch()

        # Self-review: only when enabled and agent submitted a patch
        if self.sr_enabled and str(status).strip().lower() == 'submitted':
            try:
                status, result = self._run_self_review(task, status, result)
            except Exception as e:
                self._sr_log(phase='error', error=str(e))

        submitted = str(status).strip().lower() == 'submitted'
        self.pattern_memory.learn_from_run(task, self.messages[1:], submitted=submitted)
        return status, result

    def _is_retryable_query_error(self, err: Exception) -> bool:
        msg = str(err).lower()
        retry_markers = (
            '429',
            'ratelimit',
            'rate limit',
            'throttl',
            'too many requests',
            'model busy',
            'retry later',
            'service unavailable',
            'temporarily unavailable',
            'timeout',
            'timed out',
            'connection reset',
            'connection aborted',
            'econnreset',
            '503',
            '502',
            '504',
        )
        return any(marker in msg for marker in retry_markers)

    def query(self) -> dict:
        """Query the model and return the response."""

        if 0 < self.config.step_limit <= self.model.n_calls or 0 < self.config.cost_limit <= self.model.cost:
            raise LimitsExceeded()

        if self.print_spend_enabled:
            self.print_spend()
        print(f'query llm: step {self.model.n_calls}')
        
        # insert memorized messages after the first message (system prompt)
        pattern_block = []
        if self.pattern_prompt:
            pattern_block.append(
                {
                    "role": "user",
                    "content": self.pattern_prompt,
                    "timestamp": time.time(),
                }
            )
        messages = [
            *self.messages[:1],
            *pattern_block,
            *self.memorized_messages,
            *self.messages[1:]
        ]

        if self.query_min_interval_s > 0 and self._last_query_at > 0:
            since_last = time.monotonic() - self._last_query_at
            if since_last < self.query_min_interval_s:
                sleep_s = self.query_min_interval_s - since_last
                print(f'query llm: pacing sleep {sleep_s:.2f}s')
                time.sleep(sleep_s)

        response = None
        for attempt in range(self.query_max_retries + 1):
            try:
                response = self.model.query(messages)
                self._last_query_at = time.monotonic()
                break
            except Exception as e:
                retryable = self._is_retryable_query_error(e)
                if not retryable or attempt >= self.query_max_retries:
                    raise
                backoff = min(self.query_backoff_max_s, self.query_backoff_base_s * (2 ** attempt))
                jitter = random.uniform(0, self.query_backoff_jitter_s)
                sleep_s = backoff + jitter
                print(
                    f'query llm: transient provider error (attempt {attempt + 1}/{self.query_max_retries + 1}), '
                    f'retrying in {sleep_s:.2f}s: {e}'
                )
                time.sleep(sleep_s)

        if response is None:
            raise RuntimeError('model query failed with no response')

        self.add_message('assistant', **response)
        return response
