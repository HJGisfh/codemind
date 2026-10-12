import importlib.util
from copy import deepcopy
from types import SimpleNamespace as NS
import pytest


def test_execution_control_available():
    assert importlib.util.find_spec("codemind.execution") is not None, "Agent needs bounded, cancellable execution"


def make_control(**kwargs):
    from codemind.execution import RunControl
    return RunControl(**kwargs)


def setup_loop(monkeypatch, responses, handler=lambda **kw: "unchanged"):
    import codemind.loop as loop
    import codemind.tools as tools
    import codemind.context as ctx
    calls = []
    iterator = iter(responses)
    def create(**kw):
        calls.append(deepcopy(kw))
        value = next(iterator)
        if callable(value):
            return value()
        return value
    monkeypatch.setattr(ctx.client.messages, "create", create)
    monkeypatch.setattr(loop, "prepare_context", lambda *a: None)
    monkeypatch.setattr(loop, "update_context", lambda *a: {})
    monkeypatch.setattr(loop, "should_run_background", lambda *a: False)
    monkeypatch.setattr(loop, "trigger_hooks", lambda *a: None)
    monkeypatch.setattr(tools, "assemble_tool_pool", lambda: ([], {"read_file": handler}))
    return loop, calls


def response(*blocks):
    return NS(content=list(blocks), stop_reason="tool_use" if blocks and blocks[0].type == "tool_use" else "end_turn")


def tool(n=0):
    return NS(type="tool_use", name="read_file", input={"path": "a.txt"}, id=f"t{n}")


def test_normal_completion(monkeypatch):
    loop, calls = setup_loop(monkeypatch, [response(tool()), response(NS(type="text",text="done"))])
    result = loop.agent_loop([], {}, control=make_control())
    assert result.reason == "completed"
    assert (result.model_calls, result.tool_calls) == (2, 1)


def test_model_budget(monkeypatch):
    loop, calls = setup_loop(monkeypatch, [response(tool())]*5)
    result = loop.agent_loop([], {}, control=make_control(max_model_calls=2))
    assert result.reason == "model_budget"
    assert len(calls) == 2


def test_tool_budget_preserves_protocol(monkeypatch):
    executed=[]
    loop, calls=setup_loop(monkeypatch,[response(tool(1),tool(2))],lambda **kw: executed.append(kw) or "ok")
    history=[]
    result=loop.agent_loop(history,{},control=make_control(max_tool_calls=1))
    assert result.reason == "tool_budget"
    assert len(executed)==1
    results=[b for m in history if isinstance(m.get("content"),list) for b in m["content"] if isinstance(b,dict) and b.get("type")=="tool_result"]
    assert {b["tool_use_id"] for b in results}=={"t1","t2"}


def test_cancel_during_model_prevents_tools(monkeypatch):
    c=make_control(); executed=[]
    def cancel_response():
        c.cancel(); return response(tool())
    loop,calls=setup_loop(monkeypatch,[cancel_response],lambda **kw: executed.append(kw))
    result=loop.agent_loop([],{},control=c)
    assert result.reason=="cancelled" and executed==[]


def test_repetition_warns_then_stops(monkeypatch):
    loop,calls=setup_loop(monkeypatch,[response(tool(i)) for i in range(8)])
    history=[]
    result=loop.agent_loop(history,{},control=make_control(repeat_limit=3))
    assert result.reason=="repeated_tool_result"
    assert result.tool_calls==3
    assert "repeated" in str(calls[2]["messages"]).lower()


def test_polling_exemption_and_changing_results():
    c=make_control(repeat_limit=3)
    for i in range(6):
        assert c.observe_tool("check_inbox",{},"empty") is None
        assert c.observe_tool("read_file",{},str(i)) is None
    assert c.reason is None


def test_deadline():
    now=[0.0]
    c=make_control(max_seconds=1,clock=lambda:now[0])
    now[0]=2
    from codemind.execution import RunStopped
    with pytest.raises(RunStopped): c.check()
    assert c.reason=="time_budget"


def test_retry_counts_against_budget():
    from codemind.recovery import with_retry, RecoveryState
    from codemind.execution import RunStopped
    c=make_control(max_model_calls=1)
    calls=[]
    def fail():
        calls.append(1); raise RuntimeError("429")
    c.wait=lambda seconds:c.check()
    with pytest.raises(RunStopped): with_retry(fail,RecoveryState(),control=c)
    assert len(calls)==1 and c.reason=="model_budget"


def test_cancel_interrupts_backoff():
    from codemind.recovery import with_retry, RecoveryState
    from codemind.execution import RunStopped
    c=make_control()
    def fail():
        c.cancel(); raise RuntimeError("429")
    with pytest.raises(RunStopped): with_retry(fail,RecoveryState(),control=c)
    assert c.reason=="cancelled"


def test_summary_calls_share_run_budget(monkeypatch):
    import codemind.compact as compact
    loop,calls=setup_loop(monkeypatch,[response(NS(type="text",text="summary")),response(NS(type="text",text="done"))])
    monkeypatch.setattr(loop,"prepare_context",lambda *a:compact.summarize_history(a[0]))
    result=loop.agent_loop([],{},control=make_control(max_model_calls=1))
    assert result.reason=="model_budget"
    assert len(calls)==1


def test_changed_results_do_not_trigger_loop_detection(monkeypatch):
    outputs=iter(["one","two","three","four"])
    loop,calls=setup_loop(monkeypatch,[response(tool(i)) for i in range(4)]+[response(NS(type="text",text="done"))],lambda **kw:next(outputs))
    assert loop.agent_loop([],{},control=make_control(repeat_limit=3)).reason=="completed"


def test_cancel_between_tools_preserves_results(monkeypatch):
    c=make_control(); executed=[]
    def first(**kw):
        executed.append(1);c.cancel();return "first finished"
    loop,calls=setup_loop(monkeypatch,[response(tool(1),tool(2))],first)
    history=[]
    result=loop.agent_loop(history,{},control=c)
    assert result.reason=="cancelled" and len(executed)==1
    assert history[-2]["content"][1]["is_error"] is True


def test_invalid_limits():
    for kwargs in ({"max_model_calls":0},{"max_tool_calls":True},{"max_seconds":float("inf")},{"repeat_limit":2}):
        with pytest.raises(ValueError):make_control(**kwargs)
