"""Local dashboard for the email digest.  Run: .venv/bin/uvicorn app:app --port 8765"""
import glob
import json
import os
import re
import threading

from fastapi import FastAPI, HTTPException
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import FileResponse

import digest
import state as state_store

HERE = os.path.dirname(os.path.abspath(__file__))

app = FastAPI(title="Email digest")
run_lock = threading.Lock()

# The dashboard has Done buttons, so the terminal hint under each reminder is just noise here.
_CLI_HINT = re.compile(r"^\s*\(done with this\? run: .*\)\s*$", re.MULTILINE)


def _clean(text):
    return _CLI_HINT.sub("", text).replace("\n\n\n", "\n\n").strip()


def _history(limit=15):
    paths = sorted(glob.glob(os.path.join(digest.HISTORY_DIR, "*.txt")), reverse=True)[:limit]
    out = []
    for path in paths:
        base = path[: -len(".txt")]
        when, mode = os.path.basename(base).rsplit("_", 1)  # e.g. 2026-10-30_1900 / evening
        entry = {"when": when, "mode": mode}
        try:
            with open(base + ".json") as f:
                entry["digest"] = json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            # Digests saved before structured history existed: show them as plain text.
            with open(path) as f:
                entry["text"] = _clean(f.read())
        out.append(entry)
    return out


@app.get("/")
def index():
    return FileResponse(os.path.join(HERE, "static", "index.html"))


@app.get("/api/overview")
def overview():
    state = state_store.load()
    items = [{"id": tid, **item} for tid, item in state["items"].items()]
    items.sort(key=lambda i: i["since"])
    return {"last_run": state.get("last_run"), "items": items, "history": _history()}


@app.post("/api/items/{thread_id}/done")
def mark_done(thread_id: str):
    state = state_store.load()
    if state["items"].pop(thread_id, None) is None:
        raise HTTPException(404, "No such open item")
    state_store.save(state)
    return {"ok": True}


@app.post("/api/run")
async def run_now(mode: str = "update"):
    if mode not in ("update", "morning", "evening"):
        raise HTTPException(400, "mode must be update, morning or evening")
    if not run_lock.acquire(blocking=False):
        raise HTTPException(409, "A run is already in progress")
    try:
        result = await run_in_threadpool(lambda: digest.run_digest(mode, notify=False, skip_empty=True))
    except Exception as e:
        raise HTTPException(500, f"{type(e).__name__}: {e}")
    finally:
        run_lock.release()
    result["text"] = _clean(result["text"])
    return result
