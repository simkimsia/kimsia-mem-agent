import os
import json
import time
import requests
from minisweagent.agents.default import DefaultAgent, LimitsExceeded
from pattern_memory import PatternMemory

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

    def run(self, task: str):
        selected = self.pattern_memory.retrieve_for_task(task)
        self.pattern_prompt = self.pattern_memory.build_prompt_block(selected)
        if selected:
            print(f'retrieved {len(selected)} pattern memories')

        status, result = super().run(task)

        submitted = str(status).strip().lower() == 'submitted'
        self.pattern_memory.learn_from_run(task, self.messages[1:], submitted=submitted)
        return status, result

    def query(self) -> dict:
        """Query the model and return the response."""

        if 0 < self.config.step_limit <= self.model.n_calls or 0 < self.config.cost_limit <= self.model.cost:
            raise LimitsExceeded()
        
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

        response = self.model.query(messages)
        self.add_message('assistant', **response)
        return response
