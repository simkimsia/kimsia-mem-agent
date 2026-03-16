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
        self.top_k = int(os.environ.get("MEMORY_TOP_K", "5"))
        self.score_weight = float(os.environ.get("MEMORY_SCORE_WEIGHT", "0.25"))
        self.max_items = int(os.environ.get("MEMORY_MAX_ITEMS", "200"))
        self.max_pattern_len = int(os.environ.get("MEMORY_MAX_PATTERN_LEN", "220"))
        self.last_retrieved_ids: list[str] = []
        self._warned_fallback = False
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
                return [float(x) for x in emb]
        except Exception:
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

    def _extract_patterns(self, messages: list[dict]) -> list[str]:
        items: list[str] = []
        seen = set()

        for message in messages:
            if message.get("role") != "assistant":
                continue
            content = message.get("content")
            if not isinstance(content, str):
                continue
            blocks = re.findall(r"```bash\s*(.*?)```", content, flags=re.DOTALL)
            for block in blocks:
                cmd = " ".join(block.strip().split())
                parts = re.split(r"\s*&&\s*|\s*\|\|\s*", cmd)
                for part in parts:
                    part = part.strip()
                    if len(part) < 8 or len(part) > self.max_pattern_len:
                        continue
                    if part.startswith("echo COMPLETE_TASK_AND_SUBMIT_FINAL_OUTPUT"):
                        continue
                    key = part.lower()
                    if key in seen:
                        continue
                    seen.add(key)
                    items.append(part)

        return items[:20]

    def _upsert_pattern(self, text: str, success: bool) -> None:
        now = time.time()
        for pattern in self.store["patterns"]:
            if pattern.get("text") == text:
                pattern["score"] = float(pattern.get("score", 0.0)) + (0.18 if success else 0.03)
                pattern["updated_at"] = now
                if success:
                    pattern["successes"] = int(pattern.get("successes", 0)) + 1
                else:
                    pattern["failures"] = int(pattern.get("failures", 0)) + 1
                return

        emb = self._embed(text)
        self.store["patterns"].append(
            {
                "id": hashlib.sha1(f"{text}|{now}".encode()).hexdigest()[:12],
                "text": text,
                "embedding": emb,
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

        query_emb = self._embed(task_text)
        scored: list[tuple[float, dict]] = []
        for pattern in patterns:
            emb = pattern.get("embedding")
            if not isinstance(emb, list) or not emb:
                continue
            sim = self._cosine(query_emb, emb)
            blended = sim + self.score_weight * float(pattern.get("score", 0.0))
            scored.append((blended, pattern))

        scored.sort(key=lambda x: x[0], reverse=True)
        selected = [p for _, p in scored[: self.top_k] if _ > 0.05]
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
            "Previous high-signal patterns from related tasks (use only if relevant):"
        ]
        for idx, pattern in enumerate(selected, start=1):
            lines.append(f"{idx}. {pattern.get('text', '')}")
        return "\n".join(lines)

    def learn_from_run(self, messages: list[dict], submitted: bool) -> None:
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
            self._upsert_pattern(text, success=submitted)

        self.store["patterns"].sort(
            key=lambda p: (float(p.get("score", 0.0)), float(p.get("updated_at", 0.0))),
            reverse=True,
        )
        self.store["patterns"] = self.store["patterns"][: self.max_items]
        self.save()
