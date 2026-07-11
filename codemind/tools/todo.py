"""Todo tool — lightweight in-session planning.

todo_write gives the agent a planning capability separate from execution.
A nag reminder fires after 3 rounds without a todo update."""

import ast
import json

from codemind.context import CURRENT_TODOS


def _normalize_todos(todos):
    if isinstance(todos, str):
        try:
            todos = json.loads(todos)
        except json.JSONDecodeError:
            try:
                todos = ast.literal_eval(todos)
            except (SyntaxError, ValueError):
                return None, "Error: todos must be a list or JSON array string"
    if not isinstance(todos, list):
        return None, "Error: todos must be a list"
    for i, todo in enumerate(todos):
        if not isinstance(todo, dict):
            return None, f"Error: todos[{i}] must be an object"
        if "content" not in todo or "status" not in todo:
            return None, f"Error: todos[{i}] missing 'content' or 'status'"
        if todo["status"] not in ("pending", "in_progress", "completed"):
            return None, f"Error: todos[{i}] has invalid status '{todo['status']}'"
    return todos, None


def run_todo_write(todos: list) -> str:
    global CURRENT_TODOS
    from codemind.context import CURRENT_TODOS as ct
    todos, error = _normalize_todos(todos)
    if error:
        return error
    ct.clear()
    ct.extend(todos)
    print(f"  \033[33m[todo] updated {len(ct)} item(s)\033[0m")
    return f"Updated {len(ct)} todos"
