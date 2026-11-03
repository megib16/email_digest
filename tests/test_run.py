import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import digest
import gmail_client
import state as state_store

NOTIFIED = []


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setattr(state_store, "STATE_FILE", str(tmp_path / "state.json"))
    monkeypatch.setattr(digest, "HISTORY_DIR", str(tmp_path / "history"))
    monkeypatch.setattr(digest, "HERE", str(tmp_path))
    monkeypatch.setattr(digest, "load_dotenv", lambda *a, **k: None)
    monkeypatch.setattr(gmail_client, "get_service", lambda: object())
    monkeypatch.setattr(gmail_client, "fetch_sent", lambda service, since: [])
    NOTIFIED.clear()
    monkeypatch.setattr(digest, "mac_notification", lambda *a: NOTIFIED.append(a))
    monkeypatch.setattr(digest, "telegram", lambda text: NOTIFIED.append(text))
    return tmp_path


def history_files(env):
    d = env / "history"
    return sorted(os.listdir(d)) if d.exists() else []


def test_manual_check_with_nothing_new_records_nothing_and_stays_quiet(env, monkeypatch):
    monkeypatch.setattr(gmail_client, "fetch_incoming", lambda service, since: [])
    result = digest.run_digest("morning", notify=False, skip_empty=True)
    assert result["recorded"] is False
    assert history_files(env) == [] and NOTIFIED == []
    assert state_store.load()["last_run"] is not None  # the check itself is remembered


def test_scheduled_run_with_nothing_new_still_records_and_notifies(env, monkeypatch):
    monkeypatch.setattr(gmail_client, "fetch_incoming", lambda service, since: [])
    result = digest.run_digest("morning")
    assert result["recorded"] is True
    assert len(history_files(env)) == 2 and NOTIFIED  # .txt and .json


def test_manual_check_with_new_mail_records_without_notifying(env, monkeypatch):
    email = {"thread_id": "t1", "ts": 1, "from": "x", "to": "", "subject": "s", "unread": True, "body": "b"}
    monkeypatch.setattr(gmail_client, "fetch_incoming", lambda service, since: [email])
    monkeypatch.setattr(digest, "analyze", lambda inc, sent: {
        "received": [{"n": 1, "kind": "personal", "sender": "Dana", "topic": "exam", "summary": "The email...",
                      "action": "reply", "note": ""}], "sent": []})
    result = digest.run_digest("morning", notify=False, skip_empty=True)
    assert result["recorded"] is True
    assert len(history_files(env)) == 2 and NOTIFIED == []
    assert "t1" in state_store.load()["items"]


def test_update_mode_covers_everything_since_the_last_run(env, monkeypatch):
    seen = {}
    monkeypatch.setattr(gmail_client, "fetch_incoming", lambda service, since: seen.setdefault("since", since) and [])
    state_store.save({"last_run": 1_700_000_000, "items": {}})
    monkeypatch.setattr(digest.time, "time", lambda: 1_700_000_000 + 3 * 3600)
    result = digest.run_digest("update", skip_empty=True)
    assert seen["since"] == 1_700_000_000
    assert result["headline"] == "No new emails." and result["recorded"] is False
