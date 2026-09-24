# -*- coding: utf-8 -*-
"""Sluzhba zhyvoyi rozshyfrovky: /api/live i /api/runs.

Odyn seans naraz - karta odna, i model' na nij dilyt' misce z gemma4.
Pidtverdzheni slova vykhodyat' potokom (SSE), shchob spozhyvach ne opytuvav.

    python scripts/live_service.py --port 8756
"""
import argparse, asyncio, json, os, sys, threading

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import audio_source as asrc
import live_core
import numpy as np
from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

app = FastAPI(title="live transcription")

# Типові програми зустрічей. Chrome тут - увесь браузер: вкладку від вкладки
# процесний loopback не відрізняє, бо їх зводить один audio service.
KNOWN = ["chrome.exe", "Zoom.exe", "ms-teams.exe", "Discord.exe", "msedge.exe"]

_session = None
_lock = threading.Lock()
_subs = []
_loop = None


def publish(kind, data):
    """Podiya vsim pidpysanym. Klychet'sya z potoku rozpiznavannya, tomu
    cherha napovnyuyetsya cherez petlyu asyncio, a ne napryamu."""
    if _loop is None:
        return
    msg = f"event: {kind}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"
    for q in list(_subs):
        _loop.call_soon_threadsafe(q.put_nowait, msg)


class StartBody(BaseModel):
    target: str = "chrome.exe"
    pid: int = 0
    model: str = "turbo"
    mic: bool = False           # мікрофон вимкнено, поки не заважає
    chunk: float = 1.0
    trim: float = 15.0
    max_sec: float = 30.0
    vad: bool = True
    prompt: bool = True
    seconds: float = 0.0


@app.on_event("startup")
async def _remember_loop():
    global _loop
    _loop = asyncio.get_running_loop()


@app.get("/api/targets")
def targets(name: str = ""):
    """Shcho mozhna slukhaty: korinni procesy vidomykh program."""
    names = [name] if name else KNOWN
    out = []
    for n in names:
        for pid, created in asrc.list_targets(n):
            out.append({"name": n, "pid": pid, "created": created})
    return {"targets": out}


@app.get("/api/live")
def live_state():
    if _session is None:
        return {"status": "idle"}
    return _session.state()


def _busy():
    return _session is not None and _session.status in ("loading", "running")


def _open_session(cfg):
    global _session
    _session = live_core.LiveSession(
        cfg,
        on_words=lambda ws: publish("words", ws),
        on_event=lambda k, v: publish("event", {"kind": k, "value": v}))
    return _session.start()


@app.post("/api/live/start")
def live_start(body: StartBody):
    with _lock:
        if _busy():
            raise HTTPException(409, "session already running")
        _open_session(live_core.Config(**body.model_dump()))
        return _session.state()


@app.websocket("/api/live/tab")
async def live_tab(ws: WebSocket, model: str = "turbo", mic: bool = False):
    """Seans vid rozshyrennya: pidkluchennya - pochatok, rozryv - kinets'.

    Rozshyrennya shle zvuk lyshe pislya "ready": pershyj seans vantazhyt'
    model' sekundamy, i zvuk, shcho nakopychyvsya b u soketi, pryjshov by
    pachkoyu - a z nym zayikhav by j spil'nyj nul' dlya mikrofona.
    """
    await ws.accept()
    sess = None
    if _lock.acquire(blocking=False):
        try:
            if not _busy():
                cfg = live_core.Config(source="tab", model=model, mic=mic)
                sess = await asyncio.to_thread(_open_session, cfg)
        finally:
            _lock.release()
    if sess is None:
        await ws.close(code=1013, reason="session already running")
        return
    await ws.send_text(json.dumps({"type": "ready", "id": sess.id, "mic": sess.mic_on}))
    try:
        while True:
            msg = await ws.receive()
            if msg["type"] == "websocket.disconnect":
                break
            if msg.get("bytes"):
                sess.src.feed(np.frombuffer(msg["bytes"], dtype=np.float32).copy())
            elif msg.get("text"):
                # Команди тим самим сокетом: {"type": "mic", "on": true}.
                cmd = json.loads(msg["text"])
                if cmd.get("type") == "mic":
                    on = await asyncio.to_thread(sess.set_mic, bool(cmd.get("on")))
                    await ws.send_text(json.dumps({"type": "mic", "on": on}))
    except WebSocketDisconnect:
        pass
    finally:
        if sess.status in ("running", "stopping"):
            await asyncio.to_thread(sess.stop)


@app.post("/api/live/stop")
def live_stop():
    global _session
    with _lock:
        if _session is None or _session.status not in ("loading", "running", "stopping"):
            raise HTTPException(409, "nothing to stop")
        return _session.stop()


class MicBody(BaseModel):
    on: bool


@app.post("/api/live/mic")
def live_mic(body: MicBody):
    if not _busy():
        raise HTTPException(409, "no running session")
    return {"mic": _session.set_mic(body.on)}


@app.get("/api/live/text")
def live_text():
    if _session is None:
        raise HTTPException(404, "no session")
    return {"id": _session.id, "text": _session.text(), "words": len(_session.words)}


@app.get("/api/live/stream")
async def live_stream():
    q = asyncio.Queue()
    _subs.append(q)

    async def gen():
        try:
            state = _session.state() if _session else {"status": "idle"}
            yield f"event: state\ndata: {json.dumps(state, ensure_ascii=False)}\n\n"
            while True:
                try:
                    yield await asyncio.wait_for(q.get(), timeout=15)
                except asyncio.TimeoutError:
                    yield ": keepalive\n\n"
        finally:
            _subs.remove(q)

    return StreamingResponse(gen(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@app.get("/api/runs")
def runs():
    return {"runs": live_core.list_runs()}


@app.get("/api/runs/{run_id}")
def run(run_id: str):
    d = live_core.read_run(run_id)
    if d is None:
        raise HTTPException(404, "no such run")
    return d


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8756)
    args = ap.parse_args()
    import uvicorn
    uvicorn.run(app, host=args.host, port=args.port, log_level="info")


if __name__ == "__main__":
    main()
