"""Cooperative limits for one foreground agent run (not an OS sandbox)."""
from dataclasses import dataclass
from contextvars import ContextVar
import hashlib
import json
import math
import threading
import time


CURRENT_RUN = ContextVar("codemind_run", default=None)


class RunStopped(Exception):
    pass


@dataclass(frozen=True)
class RunResult:
    reason: str
    model_calls: int
    tool_calls: int
    elapsed_seconds: float


class RunControl:
    def __init__(self, max_model_calls=30, max_tool_calls=100, max_seconds=300,
                 repeat_limit=4, polling_tools=("check_inbox", "list_tasks", "list_crons"),
                 clock=time.monotonic):
        for value in (max_model_calls, max_tool_calls, repeat_limit):
            if isinstance(value, bool) or not isinstance(value, int) or value < 1:
                raise ValueError("Call and repetition limits must be positive integers")
        if isinstance(max_seconds, bool) or not math.isfinite(max_seconds) or max_seconds <= 0:
            raise ValueError("Time limit must be finite and positive")
        if repeat_limit < 3:
            raise ValueError("repeat_limit must allow warning before stopping (>=3)")
        self.max_model_calls = max_model_calls
        self.max_tool_calls = max_tool_calls
        self.max_seconds = max_seconds
        self.repeat_limit = repeat_limit
        self.polling_tools = frozenset(polling_tools)
        self.clock = clock
        self.started = clock()
        self.cancel_event = threading.Event()
        self.reason = None
        self.model_calls = self.tool_calls = 0
        self._last_signature = None
        self._repeat_count = 0

    def cancel(self):
        self.cancel_event.set()

    def stop(self, reason):
        if self.reason is None:
            self.reason = reason

    def check(self):
        if self.cancel_event.is_set():
            self.stop("cancelled")
        if self.clock() - self.started >= self.max_seconds:
            self.stop("time_budget")
        if self.reason is not None:
            raise RunStopped(self.reason)

    def before_model(self):
        self.check()
        if self.model_calls >= self.max_model_calls:
            self.stop("model_budget")
            raise RunStopped(self.reason)
        self.model_calls += 1

    def before_tool(self):
        self.check()
        if self.tool_calls >= self.max_tool_calls:
            self.stop("tool_budget")
            raise RunStopped(self.reason)
        self.tool_calls += 1

    def wait(self, seconds):
        self.check()
        remaining = max(0, self.max_seconds - (self.clock() - self.started))
        self.cancel_event.wait(min(seconds, remaining))
        self.check()

    def observe_tool(self, name, args, output):
        if name in self.polling_tools:
            self._last_signature = None
            self._repeat_count = 0
            return None
        raw = json.dumps([name, args, str(output)], sort_keys=True, ensure_ascii=False, default=str)
        signature = hashlib.sha256(raw.encode("utf-8")).digest()
        self._repeat_count = self._repeat_count + 1 if signature == self._last_signature else 1
        self._last_signature = signature
        if self._repeat_count >= self.repeat_limit:
            self.stop("repeated_tool_result")
        if self._repeat_count == self.repeat_limit - 1:
            return "Repeated identical tool input and output. Change strategy; another identical result will stop this run."
        return None

    def result(self, default="completed"):
        return RunResult(self.reason or default, self.model_calls, self.tool_calls,
                         round(max(0, self.clock() - self.started), 3))
