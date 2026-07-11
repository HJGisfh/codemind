"""CodeMind Web IDE — FastAPI backend.

Serves the Monaco-based IDE frontend and provides:
- WebSocket /ws for real-time agent chat
- REST /api/* for file operations
- Static file serving for the IDE UI"""

from __future__ import annotations

import json
import sys
import threading
from pathlib import Path

# Ensure codemind package is importable
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from codemind.context import (
    PROMPT, agent_lock, MODEL,
    CLI_ACTIVE, client,
)
import codemind.context as ctx
from codemind.hooks import trigger_hooks
from codemind.loop import agent_loop, update_context, print_turn_assistants, terminal_print
from codemind.permission import register_default_hooks
from codemind.tools.skill import scan_skills
from codemind.tools.cron import (
    load_durable_jobs, cron_scheduler_loop, consume_cron_queue,
)
from codemind.subagent import consume_lead_inbox
from codemind.tools.file_ops import safe_path, run_read, run_write, run_glob
from codemind.tools.bash import run_bash

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
import uvicorn

# ── App setup ──
app = FastAPI(title="CodeMind IDE", version="1.0.0")

# ── Startup ──
scan_skills()
register_default_hooks()
load_durable_jobs()
threading.Thread(target=cron_scheduler_loop, daemon=True).start()

# ── Shared agent state ──
history: list[dict] = []
context: dict = {}


def init_state():
    global context
    if not context:
        context = update_context({}, [])


# ── REST API ──

_stop_flag = False


@app.get("/api/stop")
async def api_stop():
    global _stop_flag
    _stop_flag = True
    return {"status": "stopped"}


@app.get("/api/status")
async def api_status():
    return {
        "model": MODEL,
        "workspace": str(ctx.WORKDIR),
        "message_count": len(history),
    }


@app.get("/api/browse-folder")
async def api_browse_folder():
    """Open native OS folder picker dialog via subprocess to avoid tkinter/async conflicts."""
    import subprocess, tempfile, os as _os
    try:
        # Run tkinter in a subprocess to isolate its event loop from uvicorn's async loop
        script = (
            "import tkinter.filedialog, tkinter, sys;"
            "root = tkinter.Tk();"
            "root.withdraw();"
            "root.attributes('-topmost', True);"
            "folder = tkinter.filedialog.askdirectory(title='Select Workspace Folder');"
            "root.destroy();"
            "print(folder if folder else '')"
        )
        proc = subprocess.run(
            [sys.executable, "-c", script],
            capture_output=True, text=True, timeout=120,
            cwd=str(ctx.WORKDIR), encoding="utf-8", errors="replace",
        )
        folder = proc.stdout.strip()
        if proc.stderr:
            print(f"  [browse-folder] tkinter stderr: {proc.stderr.strip()}")
        print(f"  [browse-folder] selected: {folder!r}")
        if folder and _os.path.isdir(folder):
            return await api_open_folder(folder)
        return {"cancelled": True}
    except subprocess.TimeoutExpired:
        return {"error": "Folder picker timed out"}
    except Exception as e:
        return {"error": str(e)}


@app.get("/api/open-folder")
async def api_open_folder(path: str = ""):
    """Switch workspace to a new directory."""
    global history, context

    if not path:
        return {"error": "No path provided"}

    new_path = Path(path).resolve()
    if not new_path.exists():
        return {"error": f"Path not found: {new_path}"}
    if not new_path.is_dir():
        return {"error": f"Not a directory: {new_path}"}

    ctx.WORKDIR = new_path
    # Refresh all WORKDIR-derived paths
    ctx.SKILLS_DIR = new_path / "skills"
    ctx.TASKS_DIR = new_path / ".tasks"; ctx.TASKS_DIR.mkdir(exist_ok=True)
    ctx.MEMORY_DIR = new_path / ".memory"; ctx.MEMORY_DIR.mkdir(exist_ok=True)
    ctx.MEMORY_INDEX = ctx.MEMORY_DIR / "MEMORY.md"
    ctx.TRANSCRIPT_DIR = new_path / ".transcripts"
    ctx.TOOL_RESULTS_DIR = new_path / ".task_outputs" / "tool-results"
    ctx.MAILBOX_DIR = new_path / ".mailboxes"; ctx.MAILBOX_DIR.mkdir(exist_ok=True)
    ctx.WORKTREES_DIR = new_path / ".worktrees"; ctx.WORKTREES_DIR.mkdir(exist_ok=True)
    ctx.DURABLE_PATH = new_path / ".scheduled_tasks.json"
    history.clear()
    context = update_context({}, [])
    print(f"  \033[33m[workspace] switched to {new_path}\033[0m")
    return {"status": "ok", "workspace": str(new_path)}


@app.get("/api/files")
async def api_list_files(path: str = ""):
    """List files in a directory relative to workspace."""
    try:
        print(f"  [api/files] WORKDIR={ctx.WORKDIR}, path={path!r}")
        dir_path = ctx.WORKDIR / path if path else ctx.WORKDIR
        if not dir_path.resolve().is_relative_to(ctx.WORKDIR.resolve()):
            raise HTTPException(403, f"Path escapes workspace: {dir_path} vs {ctx.WORKDIR}")
        entries = []
        for p in sorted(dir_path.iterdir()):
            entry = {
                "name": p.name,
                "path": str(p.relative_to(ctx.WORKDIR)).replace("\\", "/"),
                "is_dir": p.is_dir(),
            }
            if p.is_file():
                try:
                    entry["size"] = p.stat().st_size
                except Exception:
                    entry["size"] = 0
            entries.append(entry)
        return {"files": entries}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(500, str(e))


@app.get("/api/files/read")
async def api_read_file(path: str):
    """Read a file's contents."""
    try:
        content = run_read(path)
        return {"path": path, "content": content}
    except ValueError as e:
        raise HTTPException(403, str(e))
    except Exception as e:
        raise HTTPException(500, str(e))


@app.post("/api/files/write")
async def api_write_file(path: str, content: str):
    """Write content to a file."""
    try:
        result = run_write(path, content)
        return {"result": result}
    except ValueError as e:
        raise HTTPException(403, str(e))
    except Exception as e:
        raise HTTPException(500, str(e))


# ── WebSocket ──

@app.websocket("/ws")
async def websocket_chat(ws: WebSocket):
    global history, context
    await ws.accept()
    init_state()

    try:
        while True:
            data = await ws.receive_text()
            msg = json.loads(data)
            msg_type = msg.get("type", "message")

            if msg_type == "chat":
                query = msg.get("content", "")
                if not query.strip():
                    continue

                # Reset stop flag for new request
                global _stop_flag
                _stop_flag = False

                # Notify client we're processing
                await ws.send_json({"type": "status", "status": "thinking"})

                trigger_hooks("UserPromptSubmit", query)
                turn_start = len(history)
                history.append({"role": "user", "content": query})

                # Run agent loop in thread to not block WebSocket
                result_container = {"done": False}

                def run_agent():
                    with agent_lock:
                        agent_loop(history, context)
                        new_ctx = update_context(context, history)
                        context.clear()
                        context.update(new_ctx)
                    result_container["done"] = True

                thread = threading.Thread(target=run_agent, daemon=True)
                thread.start()

                # Poll for completion and send updates
                import time as _time
                last_text = ""
                while thread.is_alive():
                    _time.sleep(0.1)
                    if _stop_flag:
                        await ws.send_json({"type": "status", "status": "stopped"})
                        break
                    # Check for new assistant messages
                    for msg in history[turn_start:]:
                        if msg.get("role") != "assistant":
                            continue
                        content = msg.get("content", [])
                        if isinstance(content, list):
                            for block in content:
                                if getattr(block, "type", None) == "text":
                                    text = block.text
                                    if text != last_text:
                                        await ws.send_json({
                                            "type": "text",
                                            "content": text,
                                        })
                                        last_text = text

                thread.join()

                # Check inbox
                inbox = consume_lead_inbox(route_protocol=True)
                if inbox:
                    inbox_text = "\n".join(
                        f"From {m['from']}: {m['content'][:200]}" for m in inbox)
                    history.append({"role": "user", "content": f"[Inbox]\n{inbox_text}"})

                await ws.send_json({"type": "status", "status": "done"})

            elif msg_type == "clear":
                history.clear()
                context = update_context({}, [])
                await ws.send_json({"type": "status", "status": "cleared"})

    except WebSocketDisconnect:
        pass
    except Exception as e:
        try:
            await ws.send_json({"type": "error", "content": str(e)})
        except Exception:
            pass


# ── Static files ──

STATIC_DIR = Path(__file__).parent / "static"


@app.get("/")
async def serve_index():
    return FileResponse(STATIC_DIR / "index.html")


app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


def main():
    print(f"CodeMind IDE starting at http://localhost:8080")
    print(f"Workspace: {ctx.WORKDIR}")
    uvicorn.run(app, host="0.0.0.0", port=8080, log_level="info")


if __name__ == "__main__":
    main()
