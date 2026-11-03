import warnings

# Old-Python deprecation notices from the Google libraries would otherwise land in the log every 2 minutes.
warnings.filterwarnings("ignore")

import argparse
import json
import os
import re
import subprocess
import time
from datetime import datetime

from dotenv import load_dotenv

import gmail_client
import state as state_store
import tracker
from notify import mac_notification, telegram
from summarize import analyze

HERE = os.path.dirname(os.path.abspath(__file__))
HISTORY_DIR = os.path.join(HERE, "history")

EMPTY = {
    "morning": "Nothing to show, enjoy your day ☀️",
    "evening": "Nothing important in your inbox today.",
    "update": "No new emails.",
}

TITLES = {
    "morning": "☀️ Good morning — while you were away",
    "evening": "🌙 Today's emails",
    "update": "📬 New since your last check",
}


def _ago(ts, now):
    days = int((now - ts) // 86400)
    if days <= 0:
        return "today"
    return "yesterday" if days == 1 else f"{days} days ago"


def _group(items):
    """Real emails from people stay separate. Automated ones are grouped by sender."""
    out, groups = [], {}
    for r in items:
        if r["kind"] == "personal":
            out.append({"type": "personal", "sender": r["sender"], "topic": r["topic"],
                        "summary": r.get("summary", ""), "note": r.get("note", ""), "action": r.get("action")})
        elif r["sender"] not in groups:
            groups[r["sender"]] = {"type": "automated", "sender": r["sender"], "items": []}
            out.append(groups[r["sender"]])
        if r["kind"] != "personal":
            groups[r["sender"]]["items"].append(
                {"summary": r.get("summary", ""), "note": r.get("note", ""), "action": r.get("action")}
            )
    return out


def _blocks(items):
    blocks = []
    for e in _group(items):
        if e["type"] == "personal":
            lines = [f"• {e['sender']} sent an email regarding {e['topic']}."]
            if e["summary"]:
                lines.append(f"  {e['summary']}")
            if e["note"]:
                lines.append(f"  → {e['note']}")
        else:
            note = lambda i: f" → {i['note']}" if i["note"] else ""
            if len(e["items"]) == 1:
                lines = [f"• {e['sender']}: {e['items'][0]['summary']}{note(e['items'][0])}"]
            else:
                lines = [f"• {e['sender']} ({len(e['items'])} emails)"]
                lines += [f"  - {i['summary']}{note(i)}" for i in e["items"]]
        blocks.append("\n".join(lines))
    return "\n\n".join(blocks)


def build_structure(mode, headline, analysis, reminders, now):
    """The same digest as render(), as data, so the dashboard can lay it out properly."""
    received = analysis.get("received", [])
    attention = [r for r in received if r["kind"] != "noise" and r.get("action") in ("reply", "act")]
    fyi = [r for r in received if r["kind"] != "noise" and r.get("action") not in ("reply", "act")]
    noise = [r for r in received if r["kind"] == "noise"]
    return {
        "mode": mode,
        "headline": headline,
        "attention": _group(attention),
        "fyi": _group(fyi),
        "reminders": [
            {"kind": i["kind"], "person": i["person"], "topic": i["topic"], "note": i.get("note", ""),
             "ago": _ago(i["since"], now)}
            for _, i in reminders
        ],
        "skipped": {"count": len(noise), "senders": sorted({r["sender"] for r in noise})},
    }


def _reminder_block(tid, item, now):
    if item["kind"] == "reply_needed":
        text = f"• You still need to reply to {item['person']} about {item['topic']} (received {_ago(item['since'], now)})."
    else:
        text = (
            f"• No reply yet from {item['person']} about {item['topic']} "
            f"(you wrote {_ago(item['since'], now)}). Consider following up."
        )
    if item.get("note"):
        text += f"\n  {item['note']}"
    return text + f"\n  (done with this? run: digest.py --done {tid[:6]})"


def render(mode, analysis, reminders, now):
    """Returns (headline, full_text)."""
    received = analysis.get("received", [])
    attention = [r for r in received if r["kind"] != "noise" and r.get("action") in ("reply", "act")]
    fyi = [r for r in received if r["kind"] != "noise" and r.get("action") not in ("reply", "act")]
    noise = [r for r in received if r["kind"] == "noise"]

    sections = []
    if attention:
        sections.append("NEEDS YOUR ATTENTION\n" + _blocks(attention))
    if fyi:
        sections.append("FOR YOUR INFO\n" + _blocks(fyi))
    if reminders:
        sections.append("STILL OPEN\n" + "\n\n".join(_reminder_block(t, i, now) for t, i in reminders))

    skipped = ""
    if noise:
        names = sorted({r["sender"] for r in noise})
        shown = ", ".join(names[:5]) + ("…" if len(names) > 5 else "")
        skipped = f"Skipped {len(noise)} automated email{'s' if len(noise) != 1 else ''} ({shown})."

    title = f"{TITLES[mode]} ({datetime.now():%a %d %b})"

    if not sections:
        headline = EMPTY[mode]
        return headline, "\n\n".join(filter(None, [headline, skipped]))

    counts = []
    to_reply = len([r for r in attention if r["action"] == "reply"]) + len(
        [1 for _, i in reminders if i["kind"] == "reply_needed"]
    )
    if to_reply:
        counts.append(f"{to_reply} to reply to")
    follow_ups = len([1 for _, i in reminders if i["kind"] == "awaiting_reply"])
    if follow_ups:
        counts.append(f"{follow_ups} to follow up")
    other = len(attention) - len([r for r in attention if r["action"] == "reply"])
    if other:
        counts.append(f"{other} to do")
    if fyi:
        counts.append(f"{len(fyi)} FYI")
    headline = ", ".join(counts)

    return headline, "\n\n".join(filter(None, [title, *sections, skipped]))


def _idle_seconds():
    """Seconds since the last key press or mouse movement (0 if it can't be read)."""
    out = subprocess.run(["ioreg", "-c", "IOHIDSystem"], capture_output=True, text=True).stdout
    match = re.search(r'"HIDIdleTime" = (\d+)', out)
    return int(match.group(1)) / 1e9 if match else 0


def run_digest(mode="auto", dry_run=False, notify=True, skip_empty=False):
    """Fetch mail, analyze it, notify and update tracking.

    mode "update" looks at everything since the last run (like "morning", but not
    labelled as such). skip_empty=True records nothing when there is no new mail, so an
    empty check can't push the last real digest down the history list. The dashboard's
    "Check now" uses notify=False, skip_empty=True; the when-active check uses notify=True,
    skip_empty=True; scheduled runs use the defaults.
    Returns {"mode", "headline", "text", "recorded"}.
    """
    load_dotenv(os.path.join(HERE, ".env"))
    state = state_store.load()

    if mode == "auto":
        mode = "morning" if datetime.now().hour < 12 else "evening"
    now = int(time.time())
    if mode == "evening":
        # The whole day, so the evening digest stands on its own.
        since = int(datetime.now().replace(hour=0, minute=0, second=0, microsecond=0).timestamp())
    else:
        # Everything since the last run (normally last evening), capped at 3 days.
        since = max(state.get("last_run") or now - 14 * 3600, now - 72 * 3600)

    service = gmail_client.get_service()
    tracker.refresh(service, state, now)
    reminders = tracker.due_reminders(state, now)

    incoming = gmail_client.fetch_incoming(service, since)
    sent = gmail_client.fetch_sent(service, since)
    # Don't remind about a thread that is also showing up as new mail right now.
    new_threads = {e["thread_id"] for e in incoming}
    reminders = [(t, i) for t, i in reminders if t not in new_threads]

    analysis = analyze(incoming, sent)
    tracker.ingest(state, analysis, incoming, sent)
    headline, text = render(mode, analysis, reminders, now)

    result = {"mode": mode, "headline": headline, "text": text, "recorded": False}
    if dry_run:
        return result

    structure = build_structure(mode, headline, analysis, reminders, now)
    if skip_empty and not structure["attention"] and not structure["fyi"]:
        state["last_run"] = now
        state_store.save(state)  # tracking may have changed (replies noticed)
        return result

    stamp = datetime.now()
    os.makedirs(HISTORY_DIR, exist_ok=True)
    base = os.path.join(HISTORY_DIR, f"{stamp:%Y-%m-%d_%H%M}_{mode}")
    with open(base + ".txt", "w") as f:
        f.write(text)
    with open(base + ".json", "w") as f:
        json.dump(structure, f, indent=1)
    with open(os.path.join(HERE, "latest_digest.txt"), "w") as f:
        f.write(f"{stamp:%Y-%m-%d %H:%M}\n\n{text}")

    for tid, _ in reminders:
        state["items"][tid]["last_reminded"] = now
    state["last_run"] = now
    state_store.save(state)
    if notify:
        mac_notification("Email digest", headline)
        telegram(text)
    result["recorded"] = True
    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=["auto", "morning", "evening", "update"], default="auto")
    parser.add_argument("--print-only", action="store_true", help="dry run: no notifications, nothing saved")
    parser.add_argument("--done", metavar="ID", help="stop tracking an item (id shown in the digest)")
    parser.add_argument(
        "--if-stale", type=float, metavar="HOURS",
        help="login mode: skip if a digest ran within HOURS, and retry while the network comes up",
    )
    parser.add_argument(
        "--when-active", type=float, metavar="HOURS",
        help="run only if you are at the Mac and no digest ran within HOURS (for the 2-minute launchd check)",
    )
    args = parser.parse_args()

    if args.done:
        state = state_store.load()
        topic = tracker.mark_done(state, args.done)
        if topic:
            state_store.save(state)
            print(f"Done: {topic}")
        else:
            print(f"No single open item starts with '{args.done}'.")
        return

    if args.when_active is not None:
        last_run = state_store.load().get("last_run")
        if (last_run and time.time() - last_run < args.when_active * 3600) or _idle_seconds() > 120:
            return  # nothing to do; stay silent because this runs every 2 minutes
        try:
            run_digest("update", skip_empty=True)
        except Exception as e:
            print(f"{datetime.now():%H:%M} when-active check failed: {type(e).__name__}: {e}")
        return

    if args.if_stale is not None:
        last_run = state_store.load().get("last_run")
        if last_run and time.time() - last_run < args.if_stale * 3600:
            print("A digest ran recently, skipping.")
            return
        # Right after login the Wi-Fi often isn't up yet, so try a few times.
        for attempt in range(1, 6):
            try:
                print(run_digest(args.mode)["text"])
                return
            except Exception as e:
                print(f"Attempt {attempt} failed: {type(e).__name__}: {e}")
                if attempt == 5:
                    raise
                time.sleep(30)

    print(run_digest(args.mode, dry_run=args.print_only)["text"])


if __name__ == "__main__":
    main()
