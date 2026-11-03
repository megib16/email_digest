import os
import subprocess

import requests


def mac_notification(title, message):
    # Notifications cap out at a few lines, so only the headline goes here.
    message = message.replace('"', "'")[:200]
    subprocess.run(
        ["osascript", "-e", f'display notification "{message}" with title "{title}"'],
        check=False,
    )


def telegram(text):
    """Optional: full digest to your phone. Skipped unless both env vars are set."""
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    chat_id = os.getenv("TELEGRAM_CHAT_ID")
    if not token or not chat_id:
        return
    requests.post(
        f"https://api.telegram.org/bot{token}/sendMessage",
        json={"chat_id": chat_id, "text": text[:4000]},
        timeout=15,
    ).raise_for_status()
