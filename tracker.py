"""Keeps track of open items between runs.

state["items"] maps a Gmail thread id to one of:
  reply_needed   - someone wrote to you and expects an answer
  awaiting_reply - you wrote to someone and are waiting on them
"""
import gmail_client

FOLLOW_UP_AFTER_DAYS = 3  # nudge about an unanswered email of yours after this long
REMIND_EVERY_HOURS = 20  # ...but at most about once a day
EXPIRE_AFTER_DAYS = 14  # stop tracking after this long


def refresh(service, state, now):
    """Drop items that resolved themselves: you replied, they replied, or it expired."""
    for tid, item in list(state["items"].items()):
        if now - item["since"] > EXPIRE_AFTER_DAYS * 86400:
            del state["items"][tid]
            continue
        msgs = gmail_client.thread_messages(service, tid)
        if msgs is None:
            del state["items"][tid]
            continue
        if item["kind"] == "reply_needed":
            resolved = any(m["from_me"] and m["ts"] > item["since"] for m in msgs)
        else:
            resolved = any(not m["from_me"] and m["ts"] > item["since"] for m in msgs)
        if resolved:
            del state["items"][tid]


def due_reminders(state, now):
    """(thread_id, item) pairs worth mentioning in this digest, oldest first."""
    due = []
    for tid, item in state["items"].items():
        if item["kind"] == "reply_needed":
            due.append((tid, item))
        elif (
            now - item["since"] >= FOLLOW_UP_AFTER_DAYS * 86400
            and now - item.get("last_reminded", 0) >= REMIND_EVERY_HOURS * 3600
        ):
            due.append((tid, item))
    return sorted(due, key=lambda pair: pair[1]["since"])


def ingest(state, analysis, incoming, sent):
    """Start tracking whatever this run's analysis says needs a reply or follow-up."""
    for r in analysis.get("received", []):
        # Only real emails from people: replies to LinkedIn and the like happen
        # elsewhere, so we could never see them and would nag forever.
        if r.get("action") != "reply" or r.get("kind") != "personal":
            continue
        email = _by_number(incoming, r.get("n"))
        if email and email["thread_id"] not in state["items"]:
            state["items"][email["thread_id"]] = {
                "kind": "reply_needed",
                "person": r.get("sender", email["from"]),
                "topic": r.get("topic", email["subject"]),
                "note": r.get("note", ""),
                "since": email["ts"],
            }
    for s in analysis.get("sent", []):
        if not s.get("expects_reply"):
            continue
        email = _by_number(sent, s.get("n"), offset=len(incoming))
        if email and email["thread_id"] not in state["items"]:
            state["items"][email["thread_id"]] = {
                "kind": "awaiting_reply",
                "person": s.get("recipient", email["to"]),
                "topic": s.get("topic", email["subject"]),
                "note": s.get("note", ""),
                "since": email["ts"],
            }


def mark_done(state, prefix):
    """Stop tracking the item whose thread id starts with `prefix`. Returns its topic."""
    matches = [tid for tid in state["items"] if tid.startswith(prefix)]
    if len(matches) != 1:
        return None
    return state["items"].pop(matches[0])["topic"]


def _by_number(emails, n, offset=0):
    """Emails are numbered 1..N in the prompt; sent mail continues after incoming."""
    try:
        return emails[int(n) - 1 - offset]
    except (TypeError, ValueError, IndexError):
        return None
