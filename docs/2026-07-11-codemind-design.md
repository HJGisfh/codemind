# CodeMind Design Spec

## Overview

CodeMind is an IDE-native AI coding agent — think Trae/Codex rather than Claude Code CLI.
It wraps a modular agent core (refactored from s20) with a web-based IDE frontend.
Uses DeepSeek via Anthropic-compatible API.

## Architecture

```
Browser (Monaco Editor + Chat + FileTree + Terminal)
    ↕ WebSocket + HTTP
FastAPI server (web/server.py)
    ↕ Python calls
codemind/ agent core (loop, tools, memory, hooks, ...)
    ↕ Anthropic SDK
DeepSeek API (api.deepseek.com/anthropic)
```

## Component Breakdown

### 1. Agent Core (codemind/)

Refactored from s20's 2123-line monolithic code.py into ~15 modules:

| Module | Lines (est.) | Responsibility |
|--------|-------------|----------------|
| loop.py | ~80 | while True agent loop |
| dispatch.py | ~60 | tool dispatch map |
| tools/bash.py | ~40 | bash execution |
| tools/file_ops.py | ~100 | read/write/edit/glob |
| tools/todo.py | ~80 | todo_write + nag |
| tools/task_crud.py | ~120 | task CRUD tools |
| tools/skill.py | ~30 | load_skill |
| tools/mcp.py | ~60 | MCP connect + dispatch |
| tools/cron.py | ~80 | cron tools |
| tools/team.py | ~120 | spawn/send/check |
| tools/worktree.py | ~100 | worktree tools |
| permission.py | ~60 | 3-gate permission |
| hooks.py | ~50 | hook registry |
| memory.py | ~120 | memory CRUD + LLM selection |
| compact.py | ~100 | 4-layer compaction |
| recovery.py | ~80 | error recovery |
| subagent.py | ~100 | subagent + teammate |
| background.py | ~80 | background tasks + cron daemon |
| prompt.py | ~50 | system prompt assembly |
| context.py | ~40 | context state object |
| cli.py | ~30 | CLI entry point |

### 2. Web IDE (web/)

| File | Responsibility |
|------|---------------|
| server.py | FastAPI app + WebSocket for streaming |
| static/index.html | IDE layout shell |
| static/js/chat.js | Chat panel with streaming messages |
| static/js/editor.js | Monaco Editor wrapper |
| static/js/filetree.js | File tree with click-to-open |
| static/js/terminal.js | Terminal output panel |
| static/js/app.js | Main controller, wires everything |

### 3. Project Config

- pyproject.toml: project metadata, dependencies, scripts
- .env.example: DeepSeek config template
- .gitignore: Python + node_modules patterns

## Key Design Decisions

1. **DeepSeek via Anthropic SDK**: DeepSeek's `/anthropic` endpoint is API-compatible — zero code changes to the agent core
2. **WebSocket streaming**: Agent responses stream token-by-token to the IDE chat panel
3. **Monaco Editor**: VS Code's editor engine, loaded from CDN (no npm build step needed)
4. **File tree reads actual disk**: Shows the workspace directory, click to open files into Monaco
5. **CLI preserved**: codemind/cli.py still works for terminal use

## Scope Boundaries

**In scope:**
- Modular agent core with all s20 features
- Web IDE with chat + editor + file tree + terminal
- DeepSeek API integration
- Basic README

**Out of scope (v2):**
- Multi-file refactoring in IDE
- Git diff view
- User auth / multi-user
- Docker deployment
- Tests (add skeleton only)
