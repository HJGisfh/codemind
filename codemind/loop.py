"""Agent Loop — the heart of CodeMind.

while True:
    call LLM → check for tool_use → execute tools → append results → repeat

The loop doesn't change when features are added — hooks, permission,
compaction, and background tasks are all harness concerns that wrap
around this same core structure."""

import threading
import time

import codemind.context as ctx
from codemind.context import (
    DEFAULT_MAX_TOKENS, ESCALATED_MAX_TOKENS,
    MAX_RECOVERY_RETRIES, CONTEXT_LIMIT, CONTINUATION_PROMPT,
    CLI_ACTIVE, mcp_clients, active_teammates,
    agent_lock, rounds_since_todo,
)
from codemind.dispatch import has_tool_use, call_tool_handler, extract_text
from codemind.hooks import trigger_hooks
from codemind.prompt import assemble_system_prompt
from codemind.recovery import RecoveryState, with_retry, is_prompt_too_long_error
from codemind.compact import (
    prepare_context, compact_history, reactive_compact,
)
from codemind.background import (
    should_run_background, start_background_task, collect_background_results,
)

try:
    import readline
    readline.parse_and_bind('set bind-tty-special-chars off')
    READLINE_AVAILABLE = True
except ImportError:
    READLINE_AVAILABLE = False


def terminal_print(text: str):
    """Thread-safe print that preserves the CLI input line."""
    if threading.current_thread() is threading.main_thread() or not CLI_ACTIVE:
        print(text)
        return
    line = ""
    if READLINE_AVAILABLE:
        try:
            line = readline.get_line_buffer()
        except Exception:
            line = ""
    from codemind.context import PROMPT
    print(f"\r\033[K{text}")
    print(PROMPT + line, end="", flush=True)


def update_context(context: dict, messages: list) -> dict:
    memories = ""
    memory_index = ctx.WORKDIR / ".memory" / "MEMORY.md"
    if memory_index.exists():
        memories = memory_index.read_text(encoding="utf-8")[:2000]
    return {
        "memories": memories,
        "connected_mcp": list(mcp_clients.keys()),
        "active_teammates": list(active_teammates.keys()),
    }


def call_llm(messages: list, context: dict, tools: list,
             state: RecoveryState, max_tokens: int):
    system = assemble_system_prompt(context)
    from codemind.context import client
    return with_retry(
        lambda: client.messages.create(
            model=state.current_model,
            system=system,
            messages=messages,
            tools=tools,
            max_tokens=max_tokens),
        state)


def agent_loop(messages: list, context: dict):
    global rounds_since_todo
    from codemind.tools import assemble_tool_pool
    from codemind.tools.cron import consume_cron_queue

    tools, handlers = assemble_tool_pool()
    state = RecoveryState()
    max_tokens = DEFAULT_MAX_TOKENS

    while True:
        # ── Inject scheduled work ──
        fired = consume_cron_queue()
        for job in fired:
            messages.append({"role": "user",
                             "content": f"[Scheduled] {job.prompt}"})
            print(f"  \033[35m[cron inject] {job.prompt[:60]}\033[0m")

        # ── Inject background notifications ──
        notes = collect_background_results()
        if notes:
            messages.append({"role": "user", "content": [
                {"type": "text", "text": note} for note in notes]})

        # ── Todo nag ──
        if rounds_since_todo >= 3:
            messages.append({"role": "user",
                             "content": "<reminder>Update your todos.</reminder>"})
            rounds_since_todo = 0

        # ── Compaction ──
        prepare_context(messages, CONTEXT_LIMIT)
        context = update_context(context, messages)
        tools, handlers = assemble_tool_pool()

        # ── LLM call with recovery ──
        try:
            response = call_llm(messages, context, tools, state, max_tokens)
        except Exception as e:
            if is_prompt_too_long_error(e) and not state.has_attempted_reactive_compact:
                messages[:] = reactive_compact(messages)
                state.has_attempted_reactive_compact = True
                continue
            messages.append({"role": "assistant", "content": [
                {"type": "text", "text": f"[Error] {type(e).__name__}: {e}"}]})
            return

        # ── Max tokens handling ──
        if response.stop_reason == "max_tokens":
            if not state.has_escalated:
                max_tokens = ESCALATED_MAX_TOKENS
                state.has_escalated = True
                print(f"  \033[33m[max_tokens] retry with {max_tokens}\033[0m")
                continue
            messages.append({"role": "assistant", "content": response.content})
            if state.recovery_count < MAX_RECOVERY_RETRIES:
                messages.append({"role": "user", "content": CONTINUATION_PROMPT})
                state.recovery_count += 1
                continue
            return

        max_tokens = DEFAULT_MAX_TOKENS
        state.has_escalated = False
        messages.append({"role": "assistant", "content": response.content})

        # ── Stop if no tool_use ──
        if not has_tool_use(response.content):
            trigger_hooks("Stop", messages)
            return

        # ── Execute tools ──
        results = []
        compacted_now = False
        for block in response.content:
            if block.type != "tool_use":
                continue
            print(f"\033[36m> {block.name}\033[0m")

            # compact tool: model-initiated summarization
            if block.name == "compact":
                messages[:] = compact_history(messages)
                messages.append({"role": "user",
                                 "content": "[Compacted. Continue with summarized context.]"})
                compacted_now = True
                break

            # Permission gate
            blocked = trigger_hooks("PreToolUse", block)
            if blocked:
                results.append({"type": "tool_result",
                                "tool_use_id": block.id,
                                "content": str(blocked)})
                continue

            # Background dispatch for slow operations
            if should_run_background(block.name, block.input):
                bg_id = start_background_task(block, handlers)
                output = (f"[Background task {bg_id} started] "
                          "Result will arrive as a task_notification.")
                results.append({"type": "tool_result",
                                "tool_use_id": block.id,
                                "content": output})
                continue

            # Execute
            handler = handlers.get(block.name)
            output = call_tool_handler(handler, block.input, block.name)
            trigger_hooks("PostToolUse", block, output)
            print(str(output)[:300])

            if block.name == "todo_write":
                rounds_since_todo = 0
            else:
                rounds_since_todo += 1

            results.append({"type": "tool_result",
                            "tool_use_id": block.id, "content": output})

        if compacted_now:
            continue

        messages.append({"role": "user", "content": results})


def print_turn_assistants(messages: list, turn_start: int):
    for msg in messages[turn_start:]:
        if msg.get("role") != "assistant":
            continue
        for block in msg.get("content", []):
            if getattr(block, "type", None) == "text":
                terminal_print(block.text)
