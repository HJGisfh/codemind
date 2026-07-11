# CodeMind — IDE-Native AI Coding Agent

**An AI-powered coding agent with its own IDE.** Think Trae/Codex, not CLI.

Built from scratch in Python — agent loop, tool dispatch, permission pipeline, memory system, multi-agent teams, and a Monaco-based web IDE.

![Python](https://img.shields.io/badge/python-3.11+-blue)
![License](https://img.shields.io/badge/license-MIT-green)
![Status](https://img.shields.io/badge/status-active-brightgreen)

## Architecture

```
Browser (Monaco Editor + Chat + FileTree + Terminal)
    ↕ WebSocket + HTTP
FastAPI (web/server.py)
    ↕
CodeMind Agent Core (codemind/)
    ↕ Anthropic SDK
DeepSeek API (api.deepseek.com/anthropic)
```

### Agent Loop

```
User Input → Hooks → Compaction → System Prompt Assembly
    → LLM (DeepSeek) → Tool Use Check
    → Permission Gate → Execute Tools → PostToolUse Hooks
    → Append Results → Repeat
```

## Features

### Agent Core (27 tools)
- **File ops**: bash, read_file, write_file, edit_file, glob
- **Planning**: todo_write with auto-reminder, task graph with dependencies
- **Delegation**: subagent (context-isolated), spawn autonomous teammates
- **Memory**: persistent .memory/*.md storage, LLM-powered relevance selection
- **Skills**: on-demand skill loading, catalog in system prompt
- **Compaction**: 4-layer pipeline (budget → snip → micro → summarize)
- **Error Recovery**: 429 retry, 529 fallback, max_tokens escalation, prompt-too-long reactive compact
- **Background Tasks**: slow operations run on daemon threads
- **Cron Scheduler**: durable recurring jobs with 5-field cron
- **Worktree**: git worktree isolation per task
- **MCP**: late-bound external tools (mcp__server__tool naming)
- **Permission**: 3-gate pipeline (deny list → pattern match → workspace boundary)
- **Hooks**: UserPromptSubmit, PreToolUse, PostToolUse, Stop

### Web IDE
- **Monaco Editor**: VS Code's editor engine with syntax highlighting
- **Chat Panel**: WebSocket-based real-time agent conversation
- **File Tree**: browse workspace, click to open files in editor
- **Terminal Panel**: agent tool output logging

## Quick Start

### Prerequisites
- Python 3.11+
- DeepSeek API key ([platform.deepseek.com](https://platform.deepseek.com))

### Setup

```bash
git clone <your-repo-url> codemind
cd codemind

# Create virtual environment
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate

# Install dependencies
pip install -e .

# Configure API key
cp .env.example .env
# Edit .env with your DeepSeek API key
```

### CLI Mode

```bash
codemind
# or: python -m codemind.cli

CodeMind >> list Python files in this repo
CodeMind >> create a todo list for refactoring
CodeMind >> spawn alice as a code reviewer
```

### Web IDE

```bash
codemind-web
# or: python web/server.py

# Open http://localhost:8000
```

## Project Structure

```
codemind/
├── codemind/                  # Agent core package
│   ├── cli.py                 # CLI entry point
│   ├── loop.py                # Agent loop (while True → LLM → tools)
│   ├── dispatch.py            # Tool dispatch + text extraction
│   ├── context.py             # Shared state (WORKDIR, client, MODEL...)
│   ├── prompt.py              # System prompt assembly
│   ├── hooks.py               # Hook registry (register/trigger)
│   ├── permission.py          # 3-gate permission pipeline
│   ├── memory.py              # Memory storage + LLM relevance selection
│   ├── compact.py             # 4-layer context compaction
│   ├── recovery.py            # Error recovery (429/529/token/prompt)
│   ├── subagent.py            # Subagent + teammate + MessageBus
│   ├── background.py          # Background task dispatch
│   └── tools/                 # 27 built-in tools
│       ├── bash.py            # Shell execution
│       ├── file_ops.py        # read/write/edit/glob + safe_path
│       ├── todo.py            # Session task list
│       ├── task_crud.py       # Durable task graph
│       ├── skill.py           # Skill loading
│       ├── mcp.py             # MCP client + server registry
│       ├── cron.py            # Cron scheduler
│       └── worktree.py        # Git worktree isolation
├── web/                       # IDE frontend
│   ├── server.py              # FastAPI + WebSocket
│   └── static/
│       ├── index.html         # IDE shell
│       ├── css/style.css      # VS Code-like dark theme
│       └── js/app.js          # Monaco + Chat + FileTree controller
├── tests/                     # Test directory
├── pyproject.toml             # Project metadata
└── README.md
```

## Key Design Decisions

**Why not LangChain?** The agent loop is ~60 lines of Python. Adding a framework would hide the control flow that makes each component (hooks, permission, compaction) inspectable and testable in isolation.

**Why DeepSeek?** DeepSeek's Anthropic-compatible endpoint lets us use the same SDK while being cost-effective. Swap `ANTHROPIC_BASE_URL` and `MODEL_ID` to use any provider.

**Why Monaco + vanilla JS?** No React/Vue build step. Monaco loads from CDN. The frontend is ~300 lines of vanilla JS — enough for a working IDE, simple enough to understand in one reading.

**Why file-backed state?** Tasks, memory, cron jobs, and transcripts are all files on disk. No database. This means the agent's state is inspectable with any text editor and survives restarts without setup.

## License

MIT
