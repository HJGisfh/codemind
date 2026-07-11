"""CLI entry point — the original terminal mode.

Run:  python -m codemind.cli
      codemind          (after pip install)"""

import threading
import time

from codemind.context import (
    WORKDIR, PROMPT, CLI_ACTIVE, agent_lock, client, MODEL,
)
from codemind.hooks import trigger_hooks
from codemind.loop import agent_loop, update_context, print_turn_assistants
from codemind.permission import register_default_hooks
from codemind.tools.skill import scan_skills
from codemind.tools.cron import (
    load_durable_jobs, cron_scheduler_loop, consume_cron_queue,
)
from codemind.subagent import consume_lead_inbox


def cron_autorun_loop(history: list, context: dict):
    while True:
        time.sleep(1)
        fired = consume_cron_queue()
        if not fired:
            continue
        with agent_lock:
            turn_start = len(history)
            for job in fired:
                history.append({"role": "user",
                                "content": f"[Scheduled] {job.prompt}"})
                print(f"  \033[35m[cron auto] {job.prompt[:60]}\033[0m")
            agent_loop(history, context)
            context = update_context(context, history)
            print_turn_assistants(history, turn_start)


def main():
    global CLI_ACTIVE
    CLI_ACTIVE = True

    # Startup
    scan_skills()
    register_default_hooks()
    load_durable_jobs()
    threading.Thread(target=cron_scheduler_loop, daemon=True).start()

    print("CodeMind — IDE-native AI coding agent")
    print(f"Workspace: {WORKDIR}")
    print("Enter a question, press Enter to send. Type q to quit.\n")

    history = []
    context = update_context({}, [])
    threading.Thread(target=cron_autorun_loop,
                     args=(history, context), daemon=True).start()

    while True:
        try:
            query = input(PROMPT)
        except (EOFError, KeyboardInterrupt):
            break
        if query.strip().lower() in ("q", "exit", ""):
            break
        trigger_hooks("UserPromptSubmit", query)
        turn_start = len(history)
        history.append({"role": "user", "content": query})
        with agent_lock:
            agent_loop(history, context)
            context = update_context(context, history)
            print_turn_assistants(history, turn_start)

        inbox = consume_lead_inbox(route_protocol=True)
        if inbox:
            def inbox_label(msg):
                req_id = msg.get("metadata", {}).get("request_id", "")
                suffix = f" req:{req_id}" if req_id else ""
                return f"{msg.get('type', 'message')}{suffix}"

            inbox_text = "\n".join(
                f"From {m['from']} [{inbox_label(m)}]: "
                f"{m['content'][:200]}" for m in inbox)
            history.append({"role": "user",
                            "content": f"[Inbox]\n{inbox_text}"})
        print()


if __name__ == "__main__":
    main()
