import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import digest

NOW = 1_000_000_000


def test_empty_morning_says_nothing_to_show():
    headline, text = digest.render("morning", {"received": [], "sent": []}, [], NOW)
    assert headline == "Nothing to show, enjoy your day ☀️"


def test_only_noise_counts_as_nothing_but_mentions_skipped():
    analysis = {"received": [{"kind": "noise", "sender": "LinkedIn", "action": "none"}], "sent": []}
    headline, text = digest.render("morning", analysis, [], NOW)
    assert headline.startswith("Nothing to show")
    assert "Skipped 1 automated email (LinkedIn)" in text


def test_reply_email_uses_requested_wording():
    analysis = {
        "received": [{
            "kind": "personal", "sender": "Prof. Cohen", "topic": "the midterm date",
            "summary": "The email says the exam is Nov 12.", "action": "reply", "note": "Confirm by Friday.",
        }],
        "sent": [],
    }
    headline, text = digest.render("evening", analysis, [], NOW)
    assert "Prof. Cohen sent an email regarding the midterm date." in text
    assert "The email says the exam is Nov 12." in text
    assert "1 to reply to" in headline


def test_automated_emails_name_the_service_and_group_by_sender():
    auto = lambda s: {"kind": "important_automated", "sender": "LinkedIn", "summary": s, "action": "reply", "note": ""}
    analysis = {"received": [auto("Chirag sent you two new messages."), auto("Dana accepted your invite.")], "sent": []}
    _, text = digest.render("evening", analysis, [], NOW)
    assert "sent an email regarding" not in text
    assert "• LinkedIn (2 emails)" in text
    assert "  - Chirag sent you two new messages." in text


def test_reminders_show_in_morning_even_without_new_mail():
    reminder = ("abcdef123456", {"kind": "reply_needed", "person": "Noa", "topic": "the project", "note": "", "since": NOW - 2 * 86400})
    headline, text = digest.render("morning", {"received": [], "sent": []}, [reminder], NOW)
    assert "You still need to reply to Noa about the project (received 2 days ago)" in text
    assert "--done abcdef" in text


def test_structure_groups_automated_and_keeps_people_separate():
    r = lambda kind, sender, summary="s": {"kind": kind, "sender": sender, "topic": "t", "summary": summary, "action": "none", "note": ""}
    analysis = {"received": [r("personal", "Dana"), r("important_automated", "LinkedIn", "a"),
                             r("important_automated", "LinkedIn", "b"), r("noise", "Kiwi.com")], "sent": []}
    s = digest.build_structure("evening", "h", analysis, [], NOW)
    assert [e["type"] for e in s["fyi"]] == ["personal", "automated"]
    assert [i["summary"] for i in s["fyi"][1]["items"]] == ["a", "b"]
    assert s["skipped"] == {"count": 1, "senders": ["Kiwi.com"]}
