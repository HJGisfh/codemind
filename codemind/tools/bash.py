"""Bash tool — shell command execution."""

import subprocess
from pathlib import Path

import codemind.context as ctx


def run_bash(command: str, cwd: Path = None,
             run_in_background: bool = False) -> str:
    """Execute a shell command. run_in_background is consumed by the dispatcher."""
    try:
        r = subprocess.run(command, shell=True, cwd=cwd or ctx.WORKDIR,
                           capture_output=True, text=True, timeout=120)
        out = (r.stdout + r.stderr).strip()
        return out[:50000] if out else "(no output)"
    except subprocess.TimeoutExpired:
        return "Error: Timeout (120s)"
