"""Shared state: all singletons and constants live here.

Every module imports from context to avoid circular dependencies.
The s20 teaching code used module-level globals; we keep them centralized
so the dependency graph stays a DAG."""

import os
import threading
from pathlib import Path

from anthropic import Anthropic
from dotenv import load_dotenv

load_dotenv(override=True)
if os.getenv("ANTHROPIC_BASE_URL"):
    os.environ.pop("ANTHROPIC_AUTH_TOKEN", None)

WORKDIR = Path.cwd()
client = Anthropic(base_url=os.getenv("ANTHROPIC_BASE_URL"))
MODEL = os.environ["MODEL_ID"]
PRIMARY_MODEL = MODEL
FALLBACK_MODEL = os.getenv("FALLBACK_MODEL_ID")

# ── directories ──
SKILLS_DIR = WORKDIR / "skills"
TASKS_DIR = WORKDIR / ".tasks"; TASKS_DIR.mkdir(exist_ok=True)
MEMORY_DIR = WORKDIR / ".memory"; MEMORY_DIR.mkdir(exist_ok=True)
MEMORY_INDEX = MEMORY_DIR / "MEMORY.md"
TRANSCRIPT_DIR = WORKDIR / ".transcripts"
TOOL_RESULTS_DIR = WORKDIR / ".task_outputs" / "tool-results"
MAILBOX_DIR = WORKDIR / ".mailboxes"; MAILBOX_DIR.mkdir(exist_ok=True)
WORKTREES_DIR = WORKDIR / ".worktrees"; WORKTREES_DIR.mkdir(exist_ok=True)
DURABLE_PATH = WORKDIR / ".scheduled_tasks.json"

# ── constants ──
DEFAULT_MAX_TOKENS = 8000
ESCALATED_MAX_TOKENS = 16000
MAX_RETRIES = 3
MAX_CONSECUTIVE_529 = 2
MAX_RECOVERY_RETRIES = 2
BASE_DELAY_MS = 500
CONTEXT_LIMIT = 50000
KEEP_RECENT_TOOL_RESULTS = 3
PERSIST_THRESHOLD = 30000
IDLE_POLL_INTERVAL = 5
IDLE_TIMEOUT = 60
CONTINUATION_PROMPT = "Continue from the previous response. Do not repeat completed work."
PROMPT = "\033[36mCodeMind >> \033[0m"
CLI_ACTIVE = False

# ── singleton state ──
CURRENT_TODOS: list[dict] = []
SKILL_REGISTRY: dict[str, dict] = {}
HOOKS: dict[str, list] = {
    "UserPromptSubmit": [], "PreToolUse": [],
    "PostToolUse": [], "Stop": [],
}
mcp_clients: dict[str, "MCPClient"] = {}
active_teammates: dict[str, bool] = {}

background_tasks: dict[str, dict] = {}
background_results: dict[str, str] = {}
background_lock = threading.Lock()
_bg_counter = 0

scheduled_jobs: dict[str, "CronJob"] = {}
cron_queue: list["CronJob"] = []
cron_lock = threading.Lock()
_last_fired: dict[str, str] = {}

agent_lock = threading.Lock()
rounds_since_todo = 0

# ── delayed imports to avoid circular deps ──
# Modules that depend on context import from here; when context needs objects
# defined in other modules (e.g. Task, MCPClient), we use string annotations
# or import inside the functions that need them.
