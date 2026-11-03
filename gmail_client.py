import base64
import os

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

# Read-only: this script can never send, delete or modify mail.
SCOPES = ["https://www.googleapis.com/auth/gmail.readonly"]
HERE = os.path.dirname(os.path.abspath(__file__))
CREDENTIALS_FILE = os.path.join(HERE, "credentials.json")
TOKEN_FILE = os.path.join(HERE, "token.json")


def get_service():
    creds = None
    if os.path.exists(TOKEN_FILE):
        creds = Credentials.from_authorized_user_file(TOKEN_FILE, SCOPES)
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            # First run only: opens a browser for you to approve access.
            flow = InstalledAppFlow.from_client_secrets_file(CREDENTIALS_FILE, SCOPES)
            creds = flow.run_local_server(port=0)
        with open(TOKEN_FILE, "w") as f:
            f.write(creds.to_json())
    return build("gmail", "v1", credentials=creds)


def _body_text(payload):
    """Walk the MIME tree and return the first text/plain part, decoded."""
    if payload.get("mimeType") == "text/plain" and payload.get("body", {}).get("data"):
        return base64.urlsafe_b64decode(payload["body"]["data"]).decode("utf-8", "replace")
    for part in payload.get("parts", []):
        text = _body_text(part)
        if text:
            return text
    return ""


def _parse(msg, max_chars):
    headers = {h["name"].lower(): h["value"] for h in msg["payload"]["headers"]}
    return {
        "id": msg["id"],
        "thread_id": msg["threadId"],
        "ts": int(msg["internalDate"]) // 1000,
        "from": headers.get("from", ""),
        "to": headers.get("to", ""),
        "subject": headers.get("subject", "(no subject)"),
        "unread": "UNREAD" in msg.get("labelIds", []),
        "body": (_body_text(msg["payload"]) or msg.get("snippet", ""))[:max_chars],
    }


def _fetch(service, query, max_emails, max_chars):
    resp = service.users().messages().list(userId="me", q=query, maxResults=max_emails).execute()
    emails = []
    for ref in resp.get("messages", []):
        msg = service.users().messages().get(userId="me", id=ref["id"], format="full").execute()
        emails.append(_parse(msg, max_chars))
    return sorted(emails, key=lambda e: e["ts"])


def fetch_incoming(service, since_ts, max_emails=60):
    """Inbox mail received after `since_ts` (unix seconds), oldest first."""
    return _fetch(service, f"in:inbox -from:me after:{since_ts}", max_emails, 1500)


def fetch_sent(service, since_ts, max_emails=30):
    """Mail you sent after `since_ts`, oldest first."""
    return _fetch(service, f"in:sent after:{since_ts}", max_emails, 800)


def thread_messages(service, thread_id):
    """Who wrote each message in a thread and when. None if the thread is gone."""
    try:
        thread = service.users().threads().get(
            userId="me", id=thread_id, format="metadata", metadataHeaders=["From"]
        ).execute()
    except HttpError as e:
        if e.resp.status == 404:
            return None
        raise
    return [
        {"from_me": "SENT" in m.get("labelIds", []), "ts": int(m["internalDate"]) // 1000}
        for m in thread["messages"]
    ]
