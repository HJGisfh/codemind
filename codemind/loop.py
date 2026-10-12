"""Agent Loop — the heart of CodeMind.

while True:
    call LLM → check for tool_use → execute tools → append results → repeat

The loop doesn't change when features are added — hooks, permission,
compaction, and background tasks are all harness concerns that wrap
around this same core structure."""

from codemind.execution import RunControl, RunStopped, CURRENT_RUN

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
             state: RecoveryState, max_tokens: int, control=None):
    system = assemble_system_prompt(context)
    from codemind.context import client
    return with_retry(
        lambda: client.messages.create(
            model=state.current_model,
            system=system,
            messages=messages,
            tools=tools,
            max_tokens=max_tokens),
        state, control=control)


def agent_loop(messages: list, context: dict, control=None):
    """Run with bounded foreground model/tool calls and cooperative cancellation."""
    control = control or RunControl()
    token = CURRENT_RUN.set(control)
    try:
        _agent_loop(messages, context, control)
        control.check()
    except RunStopped:
        pass
    except Exception as exc:
        control.stop("error")
        messages.append({"role": "assistant", "content": [
            {"type": "text", "text": f"[Error] {type(exc).__name__}: {exc}"}]})
    finally:
        CURRENT_RUN.reset(token)
        if control.reason:
            messages.append({"role": "assistant", "content": [
                {"type": "text", "text": f"[Run stopped: {control.reason}] "
                 f"Model calls: {control.model_calls}; tool calls: {control.tool_calls}."}]})
        trigger_hooks("Stop", messages)
    return control.result()


def _agent_loop(messages, context, control):
    global rounds_since_todo
    from codemind.tools import assemble_tool_pool
    from codemind.tools.cron import consume_cron_queue

    state = RecoveryState()
    max_tokens = DEFAULT_MAX_TOKENS
    while True:
        control.check()
        for job in consume_cron_queue():
            messages.append({"role": "user", "content": f"[Scheduled] {job.prompt}"})
        notes = collect_background_results()
        if notes:
            messages.append({"role": "user", "content": [
                {"type": "text", "text": note} for note in notes]})
        if rounds_since_todo >= 3:
            messages.append({"role": "user", "content": "<reminder>Update your todos.</reminder>"})
            rounds_since_todo = 0
        prepare_context(messages, CONTEXT_LIMIT)
        control.check()
        context = update_context(context, messages)
        tools, handlers = assemble_tool_pool()
        try:
            response = call_llm(messages, context, tools, state, max_tokens, control=control)
        except RunStopped:
            raise
        except Exception as exc:
            control.check()
            if is_prompt_too_long_error(exc) and not state.has_attempted_reactive_compact:
                messages[:] = reactive_compact(messages)
                state.has_attempted_reactive_compact = True
                continue
            raise
        # A cancelled in-flight response must never start its requested tools.
        control.check()
        if response.stop_reason == "max_tokens":
            if not state.has_escalated:
                max_tokens = ESCALATED_MAX_TOKENS
                state.has_escalated = True
                continue
            # Do not append incomplete tool_use blocks from truncated responses.
            text = extract_text(response.content)
            if text:
                messages.append({"role": "assistant", "content": text})
            if state.recovery_count < MAX_RECOVERY_RETRIES:
                messages.append({"role": "user", "content": CONTINUATION_PROMPT})
                state.recovery_count += 1
                continue
            control.stop("response_limit")
            return
        max_tokens = DEFAULT_MAX_TOKENS
        state.has_escalated = False
        messages.append({"role": "assistant", "content": response.content})
        if not has_tool_use(response.content):
            return
        results = []
        warnings = []
        compact_requested = False
        for block in response.content:
            if block.type != "tool_use":
                continue
            try:
                control.before_tool()
                blocked = trigger_hooks("PreToolUse", block)
                control.check()
                if blocked:
                    output = str(blocked)
                elif block.name == "compact":
                    compact_requested = True
                    output = "Context compaction scheduled after this tool batch."
                elif should_run_background(block.name, block.input):
                    bg_id = start_background_task(block, handlers)
                    output = f"[Background task {bg_id} started] Result will arrive as a task_notification."
                else:
                    output = call_tool_handler(handlers.get(block.name), block.input, block.name)
                    trigger_hooks("PostToolUse", block, output)
                warning = control.observe_tool(block.name, block.input, output)
                if warning:
                    warnings.append(warning)
                rounds_since_todo = 0 if block.name == "todo_write" else rounds_since_todo + 1
                result = {"type": "tool_result", "tool_use_id": block.id, "content": str(output)}
            except RunStopped:
                result = {"type": "tool_result", "tool_use_id": block.id,
                          "content": f"Not executed: {control.reason}", "is_error": True}
            except Exception as exc:
                output = f"Error: {type(exc).__name__}: {exc}"
                warning = control.observe_tool(block.name, block.input, output)
                if warning:
                    warnings.append(warning)
                result = {"type": "tool_result", "tool_use_id": block.id,
                          "content": output, "is_error": True}
            results.append(result)
        # Always pair every tool_use with a result, including skipped calls.
        messages.append({"role": "user", "content": results})
        control.check()
        if warnings:
            messages.append({"role": "user", "content": "\n".join(warnings)})
        if compact_requested:
            messages[:] = compact_history(messages)


def print_turn_assistants(messages: list, turn_start: int):
    for msg in messages[turn_start:]:
        if msg.get("role") != "assistant":
            continue
        for block in msg.get("content", []):
            if isinstance(block, dict) and block.get("type") == "text":
                terminal_print(block["text"])
            elif getattr(block, "type", None) == "text":
                terminal_print(block.text)
