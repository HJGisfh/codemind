import pytest
import threading
import time
from fastapi.testclient import TestClient
from codemind.execution import RunResult


def test_stop_reaches_running_agent(monkeypatch):
    from web import server
    started = threading.Event()
    def waiting_agent(history, context, control=None):
        assert control is not None
        started.set()
        assert control.cancel_event.wait(3), "Stop did not reach worker"
        return RunResult("cancelled", 1, 0, 0.1)
    monkeypatch.setattr(server, "agent_loop", waiting_agent)
    with TestClient(server.app) as client:
        with client.websocket_connect("/ws") as ws:
            ws.send_json({"type":"chat","content":"test"})
            assert ws.receive_json()["status"] == "thinking"
            assert started.wait(2)
            stop = client.get("/api/stop").json()
            assert stop["status"] == "stopping"
            while True:
                msg=ws.receive_json()
                if msg.get("status")=="stopped": break
            assert msg["reason"]=="cancelled"
            assert client.get("/api/status").json()["running"] is False


def test_final_text_delivered_for_fast_run(monkeypatch):
    from web import server
    def quick(history, context, control=None):
        history.append({"role":"assistant","content":[{"type":"text","text":"finished immediately"}]})
        return RunResult("completed",1,0,0)
    monkeypatch.setattr(server,"agent_loop",quick)
    with TestClient(server.app) as client:
        with client.websocket_connect("/ws") as ws:
            ws.send_json({"type":"chat","content":"fast"})
            received=[]
            while True:
                msg=ws.receive_json();received.append(msg)
                if msg.get("status")=="done":break
            assert any(m.get("content")=="finished immediately" for m in received)


def test_running_workspace_change_rejected(monkeypatch):
    from web import server
    from codemind.execution import RunControl
    monkeypatch.setattr(server,"active_control",RunControl(),raising=False)
    with TestClient(server.app) as client:
        assert client.get("/api/open-folder",params={"path":"."}).status_code==409


def test_final_text_survives_compaction(monkeypatch):
    from web import server
    server.history[:]=[{"role":"user","content":"old"} for _ in range(10)]
    def compacted(history,context,control=None):
        history[:]=[{"role":"user","content":"summary"},{"role":"assistant","content":[{"type":"text","text":"answer after compact"}]}]
        return RunResult("completed",2,1,0)
    monkeypatch.setattr(server,"agent_loop",compacted)
    with TestClient(server.app) as client:
        with client.websocket_connect("/ws") as ws:
            ws.send_json({"type":"chat","content":"new"})
            received=[]
            while True:
                msg=ws.receive_json();received.append(msg)
                if msg.get("status")=="done":break
            assert any(m.get("content")=="answer after compact" for m in received)


def test_second_socket_cannot_mutate_active_run(monkeypatch):
    from web import server
    entered=threading.Event()
    def waiting(history,context,control=None):
        entered.set()
        assert control.cancel_event.wait(3)
        return RunResult("cancelled",0,0,0)
    monkeypatch.setattr(server,"agent_loop",waiting)
    with TestClient(server.app) as client:
        with client.websocket_connect("/ws") as first, client.websocket_connect("/ws") as second:
            first.send_json({"type":"chat","content":"first"})
            assert first.receive_json()["status"]=="thinking"
            assert entered.wait(1)
            before=list(server.history)
            second.send_json({"type":"chat","content":"second"})
            assert second.receive_json()["type"]=="error"
            second.send_json({"type":"clear"})
            assert second.receive_json()["type"]=="error"
            assert server.history==before
            client.get("/api/stop")
            while first.receive_json().get("status")!="stopped":pass


def test_idle_stop_does_not_cancel_next_run():
    from web import server
    with TestClient(server.app) as client:
        assert client.get("/api/stop").json()=={"status":"idle"}


@pytest.mark.parametrize("clear_after_completion", [False, True])
def test_final_delivery_owns_snapshot(monkeypatch, clear_after_completion):
    import asyncio
    from fastapi import WebSocketDisconnect
    from web import server
    server.history[:]=[{"role":"user","content":"old"} for _ in range(10)]
    finished=threading.Event()
    def compacted(history,context,control=None):
        history[:]=[{"role":"user","content":"summary"},{"role":"assistant","content":[{"type":"text","text":"owned answer"}]}]
        finished.set()
        return RunResult("completed",1,0,0)
    monkeypatch.setattr(server,"agent_loop",compacted)
    class Socket:
        def __init__(self):self.messages=[];self.received=False
        async def accept(self):pass
        async def receive_text(self):
            if self.received:raise WebSocketDisconnect()
            self.received=True
            return '{"type":"chat","content":"go"}'
        async def send_json(self,msg):
            self.messages.append(msg)
            if msg.get("status")=="thinking":
                # Force worker completion before WS initializes/reads delivery state.
                for _ in range(100):
                    if finished.is_set() and server.active_control is None:break
                    await asyncio.sleep(0.01)
                assert finished.is_set() and server.active_control is None
                if clear_after_completion:server.history.clear()
    socket=Socket()
    asyncio.run(server.websocket_chat(socket))
    assert any(m.get("content")=="owned answer" for m in socket.messages)
