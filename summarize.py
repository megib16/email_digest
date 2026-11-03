import json

import anthropic

MODEL = "claude-haiku-5-5"

SYSTEM = """You triage one person's email. You get emails they RECEIVED and emails they SENT, numbered in one sequence.
Return ONLY a JSON object, no other text:

{"received": [{"n": 1, "kind": "personal", "sender": "...", "topic": "...", "summary": "...", "action": "reply", "note": "..."}],
 "sent": [{"n": 5, "recipient": "...", "topic": "...", "expects_reply": true, "note": "..."}]}

Rules for received emails (include every one exactly once):
- kind "personal": a real person wrote to them (teacher, colleague, recruiter, friend, ...), even if short.
- kind "important_automated": automated but with substance: deadlines, exam or class dates, bills, appointments, security alerts, application status updates, deliveries needing action.
- kind "noise": newsletters, promotions, social media, generic notifications, receipts with nothing to do.
- sender: a readable name, never the raw address. For "personal" it is the person who wrote (e.g. "Prof. Cohen"). For "important_automated" and "noise" it is ALWAYS the service or organization that sent the email (e.g. "LinkedIn", "Electric Co"), never a person named inside it, even when the email relays a person's message.
- topic: a short phrase that completes "<sender> sent an email regarding ___", e.g. "the date of the midterm exam".
- summary, for "personal": one or two sentences starting with "The email", saying concretely what it says: dates, amounts, questions asked, requests.
- summary, for "important_automated": ONE sentence stating what happened, naming the real actor, e.g. "Chirag Vijay sent you two new messages on LinkedIn." or "Your October bill of $84.20 is due Nov 5." The service is the sender, so never say the person "sent an email". Do not mention links, or what the email lacks or contains.
- summary for "noise": empty string.
- action: "reply" only if an answer is expected or sensible (a question, request, invitation, recruiter outreach, a message from a person). "act" for a non-reply task such as paying, submitting or confirming something. Otherwise "none".
- note: only when action is "reply" or "act", and only if it adds something the summary does not already say (a deadline, what to answer, where to do it). One short sentence, never a restatement of the summary. Otherwise empty string.

Rules for sent emails (include every one exactly once):
- expects_reply is true only if the email asks something or waits on an answer. False for thank-yous and confirmations.
- recipient: a readable name. note: what to follow up about.

Write summaries and notes addressed to the person: say "you" (e.g. "The email asks you to confirm by Friday"), never "the user" or "the student".
Use only what the emails say. Do not invent dates, names or details."""


def _render_input(incoming, sent):
    blocks = []
    for i, e in enumerate(incoming, 1):
        status = "unread" if e["unread"] else "read"
        blocks.append(f"[{i}] RECEIVED ({status})\nFrom: {e['from']}\nSubject: {e['subject']}\n{e['body']}")
    for i, e in enumerate(sent, len(incoming) + 1):
        blocks.append(f"[{i}] SENT\nTo: {e['to']}\nSubject: {e['subject']}\n{e['body']}")
    return "\n\n---\n\n".join(blocks)


def _parse_json(text):
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end == -1:
        raise ValueError("no JSON object in model reply")
    return json.loads(text[start : end + 1])


def analyze(incoming, sent):
    """Classify and summarize emails. Returns {"received": [...], "sent": [...]}."""
    if not incoming and not sent:
        return {"received": [], "sent": []}

    client = anthropic.Anthropic()  # reads ANTHROPIC_API_KEY from the environment
    last_error = None
    for _ in range(2):  # the model occasionally returns malformed JSON; one retry is enough
        resp = client.messages.create(
            model=MODEL,
            max_tokens=6000,
            system=SYSTEM,
            messages=[{"role": "user", "content": _render_input(incoming, sent)}],
        )
        # The reply can start with a thinking block, so keep only the text blocks.
        text = "".join(b.text for b in resp.content if b.type == "text")
        try:
            return _parse_json(text)
        except ValueError as e:  # JSONDecodeError is a ValueError
            last_error = e
    raise RuntimeError(f"Could not parse the model's reply: {last_error}")
