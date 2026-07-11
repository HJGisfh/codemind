"""Hook registry: register and trigger extension points.

Events: UserPromptSubmit, PreToolUse, PostToolUse, Stop.
Hooks are deliberately outside tool handlers — the loop can add permission,
logging, and stop behavior without changing each individual tool."""

from codemind.context import HOOKS


def register_hook(event: str, callback):
    HOOKS[event].append(callback)


def trigger_hooks(event: str, *args):
    for callback in HOOKS[event]:
        result = callback(*args)
        if result is not None:
            return result
    return None
