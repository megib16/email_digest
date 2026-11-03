import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import gmail_client
import tracker

DAY = 86400
NOW = 1_000_000_000


def make_state(**items):
    return {"last_run": None, "items": items}


def item(kind, days_ago, **extra):
    return {"kind": kind, "person": "Noa", "topic": "the project", "note": "", "since": NOW - days_ago * DAY, **extra}


def fake_threads(monkeypatch, threads):
    """threads: {thread_id: [(from_me, days_ago), ...]}; a missing id behaves like a deleted thread."""
    def thread_messages(service, tid):
        if tid not in threads:
            return None
        return [{"from_me": me, "ts": NOW - d * DAY} for me, d in threads[tid]]
    monkeypatch.setattr(gmail_client, "thread_messages", thread_messages)


def test_reply_needed_resolves_when_you_reply(monkeypatch):
    fake_threads(monkeypatch, {"t1": [(False, 2), (True, 1)]})
    state = make_state(t1=item("reply_needed", 2))
    tracker.refresh(None, state, NOW)
    assert state["items"] == {}


def test_reply_needed_stays_open_without_your_reply(monkeypatch):
    fake_threads(monkeypatch, {"t1": [(False, 2)]})
    state = make_state(t1=item("reply_needed", 2))
    tracker.refresh(None, state, NOW)
    assert "t1" in state["items"]


def test_awaiting_resolves_when_they_answer(monkeypatch):
    fake_threads(monkeypatch, {"t1": [(True, 4), (False, 1)]})
    state = make_state(t1=item("awaiting_reply", 4))
    tracker.refresh(None, state, NOW)
    assert state["items"] == {}


def test_deleted_and_expired_items_are_dropped(monkeypatch):
    fake_threads(monkeypatch, {"old": [(False, 20)]})
    state = make_state(gone=item("reply_needed", 1), old=item("reply_needed", 20))
    tracker.refresh(None, state, NOW)
    assert state["items"] == {}


def test_awaiting_is_quiet_for_first_days_then_nudges_once_a_day():
    state = make_state(
        fresh=item("awaiting_reply", 1),
        stale=item("awaiting_reply", 4),
        nudged=item("awaiting_reply", 5, last_reminded=NOW - 3600),
    )
    due = [tid for tid, _ in tracker.due_reminders(state, NOW)]
    assert due == ["stale"]


def test_reply_needed_is_always_reminded():
    state = make_state(t1=item("reply_needed", 0, last_reminded=NOW - 60))
    assert [tid for tid, _ in tracker.due_reminders(state, NOW)] == ["t1"]


def test_ingest_tracks_replies_and_expected_answers_but_not_noise():
    incoming = [
        {"thread_id": "a", "ts": NOW, "from": "x", "subject": "s"},
        {"thread_id": "b", "ts": NOW, "from": "y", "subject": "s"},
    ]
    sent = [
        {"thread_id": "c", "ts": NOW, "to": "z", "subject": "s"},
        {"thread_id": "d", "ts": NOW, "to": "w", "subject": "s"},
    ]
    analysis = {
        "received": [
            {"n": 1, "kind": "personal", "action": "reply", "sender": "Prof", "topic": "exam"},
            {"n": 2, "kind": "important_automated", "action": "reply", "sender": "LinkedIn", "topic": "a message"},
        ],
        "sent": [
            {"n": 3, "expects_reply": True, "recipient": "Avi", "topic": "internship"},
            {"n": 4, "expects_reply": False, "recipient": "Bo", "topic": "thanks"},
        ],
    }
    state = make_state()
    tracker.ingest(state, analysis, incoming, sent)
    assert {t: i["kind"] for t, i in state["items"].items()} == {"a": "reply_needed", "c": "awaiting_reply"}


def test_ingest_does_not_reset_an_existing_item():
    incoming = [{"thread_id": "a", "ts": NOW, "from": "x", "subject": "s"}]
    analysis = {"received": [{"n": 1, "kind": "personal", "action": "reply"}], "sent": []}
    state = make_state(a=item("reply_needed", 5))
    tracker.ingest(state, analysis, incoming, [])
    assert state["items"]["a"]["since"] == NOW - 5 * DAY


def test_mark_done_needs_a_unique_prefix():
    state = make_state(abc111=item("reply_needed", 1), abc222=item("reply_needed", 1))
    assert tracker.mark_done(state, "abc") is None
    assert tracker.mark_done(state, "abc111") == "the project"
    assert list(state["items"]) == ["abc222"]
