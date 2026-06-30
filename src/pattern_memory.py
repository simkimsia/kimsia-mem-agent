import hashlib
import json
import math
import os
import re
import time
from typing import Any

import requests


class PatternMemory:
    def __init__(self, memory_dir: str, api_base: str, api_key: str):
        self.path = f"{memory_dir}/pattern_memory.json"
        self.api_base = (api_base or "").rstrip("/")
        self.api_key = api_key or ""
        self.embedding_model = os.environ.get(
            "MEMORY_EMBED_MODEL", "litellm_proxy/nomic-embed-text-v1.5"
        )
        self.top_k = int(os.environ.get("MEMORY_TOP_K", "3"))
        self.score_weight = float(os.environ.get("MEMORY_SCORE_WEIGHT", "0.25"))
        self.max_items = int(os.environ.get("MEMORY_MAX_ITEMS", "200"))
        self.max_pattern_len = int(os.environ.get("MEMORY_MAX_PATTERN_LEN", "220"))
        self.min_sim = float(os.environ.get("MEMORY_MIN_SIM", "0.20"))
        self.min_overlap = float(os.environ.get("MEMORY_MIN_OVERLAP", "0.08"))
        self.allow_fallback_retrieval = (
            os.environ.get("MEMORY_ALLOW_FALLBACK_RETRIEVAL", "0").strip() == "1"
        )
        self.verification_aware = (
            os.environ.get("MEMORY_VERIFICATION_AWARE", "0").strip() == "1"
        )
        self.last_retrieved_ids: list[str] = []
        self._warned_fallback = False
        self._embedding_ok = True
        self.store: dict[str, Any] = {"version": 1, "patterns": []}
        self._load()

    def _load(self) -> None:
        if not os.path.exists(self.path):
            return
        try:
            with open(self.path, "r") as f:
                data = json.load(f)
                if isinstance(data, dict) and isinstance(data.get("patterns"), list):
                    self.store = data
        except Exception:
            # Keep empty memory on any parse/read failure.
            self.store = {"version": 1, "patterns": []}

    def save(self) -> None:
        with open(self.path, "w") as f:
            json.dump(self.store, f, indent=2)

    def _hash_embedding(self, text: str, dim: int = 128) -> list[float]:
        vec = [0.0] * dim
        for token in re.findall(r"[A-Za-z0-9_./:-]+", text.lower()):
            h = int(hashlib.sha256(token.encode()).hexdigest()[:8], 16)
            idx = h % dim
            vec[idx] += 1.0
        norm = math.sqrt(sum(v * v for v in vec))
        if norm > 0:
            vec = [v / norm for v in vec]
        return vec

    def _embed(self, text: str) -> list[float]:
        if not self.api_base or not self.api_key:
            self._embedding_ok = False
            return self._hash_embedding(text)
        try:
            resp = requests.post(
                f"{self.api_base}/embeddings",
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
                },
                json={"model": self.embedding_model, "input": [text]},
                timeout=20,
            )
            resp.raise_for_status()
            payload = resp.json()
            emb = (payload.get("data") or [{}])[0].get("embedding")
            if isinstance(emb, list) and emb:
                self._embedding_ok = True
                return [float(x) for x in emb]
        except Exception:
            self._embedding_ok = False
            if not self._warned_fallback:
                print(
                    f"embedding fallback active (model={self.embedding_model}); using hashed embeddings"
                )
                self._warned_fallback = True
        return self._hash_embedding(text)

    def _cosine(self, a: list[float], b: list[float]) -> float:
        if not a or not b or len(a) != len(b):
            return 0.0
        dot = sum(x * y for x, y in zip(a, b))
        na = math.sqrt(sum(x * x for x in a))
        nb = math.sqrt(sum(y * y for y in b))
        if na == 0 or nb == 0:
            return 0.0
        return dot / (na * nb)

    def _normalize_terms(self, text: str) -> list[str]:
        stop = {
            "the",
            "and",
            "for",
            "with",
            "that",
            "this",
            "from",
            "into",
            "your",
            "have",
            "will",
            "when",
            "then",
            "task",
            "project",
            "repo",
            "code",
            "file",
            "files",
            "test",
            "tests",
            "issue",
            "fix",
            "bug",
        }
        terms = re.findall(r"[a-z0-9_./:-]{3,}", text.lower())
        return [t for t in terms if t not in stop][:80]

    def _task_signature(self, task_text: str) -> str:
        terms = self._normalize_terms(task_text)
        if not terms:
            return "generic"
        basis = " ".join(sorted(set(terms))[:30])
        return hashlib.sha1(basis.encode()).hexdigest()[:12]

    def _term_overlap(self, query_terms: list[str], task_terms: list[str]) -> float:
        if not query_terms or not task_terms:
            return 0.0
        qa = set(query_terms)
        tb = set(task_terms)
        if not qa or not tb:
            return 0.0
        inter = len(qa.intersection(tb))
        union = len(qa.union(tb))
        return inter / union if union else 0.0

    def _extract_patterns(self, messages: list[dict]) -> list[str]:
        items: list[str] = []
        seen = set()
        allowed_prefixes = (
            "grep ",
            "rg ",
            "find ",
            "ls ",
            "cat ",
            "sed -n ",
            "nl -ba ",
            "wc -l ",
            "git diff",
            "git status",
        )
        # FIX arm: verification cmds = the agent checking its own edit compiles/typechecks/tests.
        verification_prefixes = (
            "tsc",
            "npx tsc",
            "yarn tsc",
            "yarn lint:types",
            "yarn check-types",
            "yarn typecheck",
            "yarn test",
            "npm test",
            "npm run test",
            "jest",
            "npx jest",
            "python -m py_compile",
            "python -m pytest",
            "pytest",
            "go build",
            "go test",
            "go vet",
        )
        banned_substrings = (
            "cat <<",
            "cat >",
            "cat >>",
            "sed -i",
            "git add",
            "echo complete_task_and_submit_final_output",
            "apply_patch",
            "python3 <<",
            "node --check",
            "yarn ",
            "npm ",
        )
        if self.verification_aware:
            # stop banning verify cmds; keep a NARROW ban so we still skip dependency installs
            banned_substrings = tuple(
                b
                for b in banned_substrings
                if b not in ("node --check", "yarn ", "npm ")
            ) + ("yarn add", "yarn install", "npm install", "npm i ", "npm ci")
            allow = allowed_prefixes + verification_prefixes
        else:
            allow = allowed_prefixes

        for message in messages:
            if message.get("role") != "assistant":
                continue
            content = message.get("content")
            if not isinstance(content, str):
                continue
            blocks = re.findall(r"```bash\s*(.*?)```", content, flags=re.DOTALL)
            for block in blocks:
                cmd = " ".join(block.strip().split())
                parts = re.split(r"\s*&&\s*|\s*\|\|\s*|\s*;\s*", cmd)
                for part in parts:
                    part = part.strip()
                    if len(part) < 8 or len(part) > self.max_pattern_len:
                        continue
                    lowered = part.lower()
                    if any(token in lowered for token in banned_substrings):
                        continue
                    if not lowered.startswith(allow):
                        continue
                    key = lowered
                    if key in seen:
                        continue
                    seen.add(key)
                    items.append(part)

        return items[:20]

    def _upsert_pattern(self, text: str, task_text: str, success: bool) -> None:
        now = time.time()
        task_sig = self._task_signature(task_text)
        task_terms = self._normalize_terms(task_text)
        task_emb = self._embed(task_text)
        for pattern in self.store["patterns"]:
            if pattern.get("text") == text and pattern.get("task_signature") == task_sig:
                pattern["score"] = float(pattern.get("score", 0.0)) + (0.18 if success else 0.03)
                pattern["updated_at"] = now
                pattern["task_terms"] = task_terms
                pattern["task_embedding"] = task_emb
                if success:
                    pattern["successes"] = int(pattern.get("successes", 0)) + 1
                else:
                    pattern["failures"] = int(pattern.get("failures", 0)) + 1
                return

        self.store["patterns"].append(
            {
                "id": hashlib.sha1(f"{text}|{task_sig}".encode()).hexdigest()[:12],
                "text": text,
                "task_signature": task_sig,
                "task_terms": task_terms,
                "task_embedding": task_emb,
                "score": 0.5 if success else 0.08,
                "uses": 0,
                "successes": 1 if success else 0,
                "failures": 0 if success else 1,
                "created_at": now,
                "updated_at": now,
            }
        )

    def retrieve_for_task(self, task_text: str) -> list[dict]:
        patterns = self.store.get("patterns", [])
        if not patterns:
            self.last_retrieved_ids = []
            return []

        query_terms = self._normalize_terms(task_text)
        query_emb = self._embed(task_text)
        if not self.allow_fallback_retrieval and not self._embedding_ok:
            self.last_retrieved_ids = []
            return []

        scored: list[tuple[float, dict]] = []
        for pattern in patterns:
            emb = pattern.get("task_embedding")
            if not isinstance(emb, list) or not emb:
                continue
            sim = self._cosine(query_emb, emb)
            overlap = self._term_overlap(
                query_terms, pattern.get("task_terms", []) if isinstance(pattern.get("task_terms"), list) else []
            )
            score = float(pattern.get("score", 0.0))
            successes = int(pattern.get("successes", 0))
            failures = int(pattern.get("failures", 0))
            if successes <= failures:
                continue
            if sim < self.min_sim and overlap < self.min_overlap:
                continue

            blended = (0.55 * sim) + (0.45 * overlap) + (self.score_weight * score)
            scored.append((blended, pattern))

        scored.sort(key=lambda x: x[0], reverse=True)
        selected = [p for score, p in scored[: self.top_k] if score > 0.05]
        self.last_retrieved_ids = [str(p.get("id")) for p in selected]

        now = time.time()
        for pattern in patterns:
            if str(pattern.get("id")) in self.last_retrieved_ids:
                pattern["uses"] = int(pattern.get("uses", 0)) + 1
                pattern["updated_at"] = now

        self.save()
        return selected

    def build_prompt_block(self, selected: list[dict]) -> str:
        if not selected:
            return ""
        lines = [
            "Previous high-signal command patterns from similar tasks (reuse only if clearly relevant):"
        ]
        for idx, pattern in enumerate(selected, start=1):
            lines.append(f"{idx}. {pattern.get('text', '')}")
        return "\n".join(lines)

    def learn_from_run(self, task_text: str, messages: list[dict], submitted: bool) -> None:
        now = time.time()
        delta = 0.35 if submitted else -0.25

        for pattern in self.store["patterns"]:
            if str(pattern.get("id")) in self.last_retrieved_ids:
                pattern["score"] = max(-2.0, float(pattern.get("score", 0.0)) + delta)
                pattern["updated_at"] = now
                if submitted:
                    pattern["successes"] = int(pattern.get("successes", 0)) + 1
                else:
                    pattern["failures"] = int(pattern.get("failures", 0)) + 1

        for text in self._extract_patterns(messages):
            self._upsert_pattern(text, task_text=task_text, success=submitted)

        self.store["patterns"].sort(
            key=lambda p: (float(p.get("score", 0.0)), float(p.get("updated_at", 0.0))),
            reverse=True,
        )
        self.store["patterns"] = self.store["patterns"][: self.max_items]
        self.save()
