import os
import sys

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import app as app_module
import digest
import state as state_store

NOW = 1_000_000_000


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(state_store, "STATE_FILE", str(tmp_path / "state.json"))
    monkeypatch.setattr(digest, "HISTORY_DIR", str(tmp_path / "history"))
    state_store.save({
        "last_run": NOW,
        "items": {
            "t1": {"kind": "reply_needed", "person": "Noa", "topic": "the project", "note": "", "since": NOW - 100},
            "t2": {"kind": "awaiting_reply", "person": "Avi", "topic": "internship", "note": "", "since": NOW - 50},
        },
    })
    return TestClient(app_module.app)


def test_overview_lists_items_oldest_first(client):
    data = client.get("/api/overview").json()
    assert [i["id"] for i in data["items"]] == ["t1", "t2"]
    assert data["history"] == []


def test_done_removes_the_item(client):
    assert client.post("/api/items/t1/done").status_code == 200
    assert [i["id"] for i in client.get("/api/overview").json()["items"]] == ["t2"]
    assert client.post("/api/items/t1/done").status_code == 404


def test_history_hides_terminal_hints(client, tmp_path):
    os.makedirs(digest.HISTORY_DIR)
    with open(os.path.join(digest.HISTORY_DIR, "2026-10-30_1900_evening.txt"), "w") as f:
        f.write("STILL OPEN\n• You still need to reply to Noa.\n  (done with this? run: digest.py --done abc123)\n")
    entry = client.get("/api/overview").json()["history"][0]
    assert entry["mode"] == "evening" and entry["when"] == "2026-10-30_1900"
    assert "digest.py --done" not in entry["text"]
    assert "reply to Noa" in entry["text"]


def test_run_rejects_bad_mode_and_overlapping_runs(client):
    assert client.post("/api/run?mode=banana").status_code == 400
    app_module.run_lock.acquire()
    try:
        assert client.post("/api/run").status_code == 409
    finally:
        app_module.run_lock.release()


def test_history_prefers_structured_json(client):
    os.makedirs(digest.HISTORY_DIR)
    base = os.path.join(digest.HISTORY_DIR, "2026-10-30_1900_evening")
    open(base + ".txt", "w").write("plain text")
    open(base + ".json", "w").write('{"headline": "1 to reply to", "attention": [], "fyi": [], "reminders": [], "skipped": {"count": 0, "senders": []}}')
    entry = client.get("/api/overview").json()["history"][0]
    assert entry["digest"]["headline"] == "1 to reply to" and "text" not in entry
