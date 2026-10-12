# Execution control and reproducible evaluation

## Motivation and scope

The previous foreground loop could keep requesting tools indefinitely. The Web stop flag only changed the display and did not reach the worker. CodeMind now controls the foreground run at each model/tool boundary, reports a termination reason, and preserves tool-use/result pairing when remaining tools are skipped.

## Configuration

```python
from codemind.execution import RunControl
from codemind.loop import agent_loop

control = RunControl(max_model_calls=30, max_tool_calls=100,
                     max_seconds=300, repeat_limit=4)
result = agent_loop(messages, context, control=control)
# Another thread can call control.cancel().
print(result.reason, result.model_calls, result.tool_calls)
```

The CLI and Web entry points receive defaults automatically. Limits must be positive and finite; repeat_limit must be at least 3. Model-call counts include failed requests, explicit retry attempts, and foreground summarization. SDK automatic retries are disabled to avoid invisible extra attempts. The SDK request timeout is 30 seconds.

Tool-call counts measure admitted tool requests (including denied, failed and scheduling tools), not successful effects. The repeat signature includes tool name, canonicalized arguments and an SHA-256 digest of the output. Detection is conservative: only consecutive identical outcomes count. Changing output or a polling-exempt call resets the streak. The default exemptions are check_inbox, list_tasks and list_crons; application-specific status tools can be added through polling_tools. Cycles such as A/B/A/B and semantically equivalent but textually different failures are not detected.

## Stop semantics

Reasons: completed, cancelled, model_budget, tool_budget, time_budget, repeated_tool_result, response_limit, error.

- POST is not required by the existing client: GET /api/stop remains compatible and returns stopping or idle.
- Stopping means a cancellation request is pending. Stopped is emitted after the foreground worker exits.
- GET /api/status exposes running, stopping and last_run. WebSocket terminal messages include reason, model_calls, tool_calls and elapsed_seconds.
- The app remains single-workspace; simultaneous foreground submissions and workspace switching during execution are rejected.
- Cancellation is cooperative. A currently executing HTTP request, shell command or Hook may finish before stopping. The time budget prevents future work at checkpoints; it is not a hard wall-clock kill switch.
- Independent background jobs, cron runs and child-agent internals do not share this foreground budget and are not force-terminated. The counters are NOT whole-process token costs or a sandbox guarantee. A future lifecycle change is needed for transitive cancellation and budget propagation.
- Requests already issued may incur provider charges even if the user cancels. No promise of zero post-cancel billing is made.

## Offline evaluation

From the project root:

```bash
python -m pip install -e ".[dev]"
python -m pytest tests -q
python -m pytest tests/test_execution.py tests/test_web_execution.py -q --junitxml=reports/execution.xml
```

The test configuration uses a temporary runtime directory, dummy credentials, disabled dotenv loading and a loopback API endpoint. Model responses are simulated; no live API key is needed. Tests exercise the real loop, recovery code and FastAPI WebSocket/HTTP paths.

| Scenario | Required observation |
|---|---|
| Normal tool call then answer | completed; 2 model calls, 1 tool call |
| Model budget of 2 | model_budget; no third request |
| Tool budget of 1 with 2 requested tools | only one execution; both tool-use IDs have results |
| Repetition limit of 3 | warning before termination; 3 admitted tool calls |
| Changing results | normal completion rather than false-positive loop stop |
| Cancel during model request | no returned tool call is executed |
| Cancel between tools | second tool is skipped with matching error result |
| Cancel during retry backoff | retry wait is interrupted; no next request |
| Summary with model budget of 1 | summary consumes the allowance; no main request |
| Web stop | stop event reaches the worker; terminal reason is cancelled |
| Immediate Web completion | final answer still reaches the client |

These checks verify control behavior. They do not establish improvements in real coding success rate, latency, token consumption, or moderation accuracy. To measure those, fix a task set and model configuration, run controlled baseline/modified comparisons, and retain raw outcomes and costs. Do not invent improvement percentages from unit-test counts.

## Interview explanation

Explain the actual bug, the cooperative cancellation boundary, tool-result protocol preservation, and why polling must be distinguished from unproductive repetition. Long-term memory relevance selection remains unconnected and is not claimed as a completed end-to-end feature.
