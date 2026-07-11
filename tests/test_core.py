"""Tests for CodeMind agent core."""

import sys
from pathlib import Path

# Ensure codemind is importable when running tests directly
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def test_import_chain():
    """Verify all core modules import without error."""
    from codemind.context import WORKDIR, MODEL, DEFAULT_MAX_TOKENS
    assert MODEL is not None
    assert DEFAULT_MAX_TOKENS == 8000


def test_tool_registry():
    """Verify tool pool assembles correctly."""
    from codemind.tools import BUILTIN_TOOLS, BUILTIN_HANDLERS, assemble_tool_pool
    assert len(BUILTIN_TOOLS) == 27
    assert len(BUILTIN_HANDLERS) == 26  # compact handled in loop
    tools, handlers = assemble_tool_pool()
    assert len(tools) >= 27
    assert len(handlers) >= 26


def test_dispatch():
    """Verify text extraction and tool_use detection."""
    from codemind.dispatch import extract_text, has_tool_use

    # Mock content blocks
    class MockBlock:
        def __init__(self, block_type, text=""):
            self.type = block_type
            self.text = text

    text_blocks = [MockBlock("text", "hello"), MockBlock("text", "world")]
    assert extract_text(text_blocks) == "hello\nworld"

    mixed_blocks = [MockBlock("text", "hi"), MockBlock("tool_use")]
    assert has_tool_use(mixed_blocks) is True

    no_tool_blocks = [MockBlock("text", "just text")]
    assert has_tool_use(no_tool_blocks) is False


def test_safe_path():
    """Verify workspace boundary enforcement."""
    from codemind.tools.file_ops import safe_path

    p = safe_path("test.txt")
    assert p.is_relative_to(Path.cwd())

    try:
        safe_path("../outside.txt")
        assert False, "Should have raised ValueError"
    except ValueError:
        pass


def test_task_crud():
    """Verify task creation and lifecycle."""
    from codemind.tools.task_crud import (
        create_task, load_task, list_tasks,
        claim_task, complete_task, can_start,
    )

    task = create_task("test subject", "test description")
    assert task.subject == "test subject"
    assert task.status == "pending"

    loaded = load_task(task.id)
    assert loaded.subject == "test subject"

    result = claim_task(task.id)
    assert "Claimed" in result

    result = complete_task(task.id)
    assert "Completed" in result
