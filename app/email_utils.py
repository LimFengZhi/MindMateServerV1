"""Crisis-escalation email to the user (counselling contacts).

Fired from the graph's persist node whenever a turn escalates. Everything here
is fire-and-forget: the email is sent on a daemon thread and any failure is
logged, never raised — a broken SMTP setup must not break a chat turn.

Toggled by crisis_email.enabled in config.yaml (which also holds the subject,
body intro, and per-user cooldown); the SMTP credentials live in .env. The helpline list reuses the same crisis_message the chat shows, so
the two never drift apart. The cooldown registry is in-memory (like
live_claims): fine for the single-process dev server, resets on restart.
"""
import smtplib
import threading
import time
from email.message import EmailMessage

from app.config import Config

_last_sent = {}  # user_id -> time.monotonic() of the last email
_lock = threading.Lock()


def _smtp_ready():
    return bool(Config.SMTP_HOST and Config.MAIL_FROM)


def _cooldown_ok(user_id):
    """One email per user per cooldown window, so a crisis conversation with
    several escalated turns doesn't flood the inbox."""
    window = Config.CRISIS_EMAIL_COOLDOWN_MIN * 60
    with _lock:
        last = _last_sent.get(user_id)
        if last is not None and time.monotonic() - last < window:
            return False
        _last_sent[user_id] = time.monotonic()
        return True


def _compose(to_email):
    msg = EmailMessage()
    msg["Subject"] = Config.CRISIS_EMAIL_SUBJECT
    msg["From"] = Config.MAIL_FROM
    msg["To"] = to_email
    msg.set_content(
        f"{Config.CRISIS_EMAIL_INTRO}\n\n"
        f"{Config.CRISIS_MESSAGE}\n\n"
        "— MindMate\n"
        "This is an automated safety message from your MindMate companion."
    )
    return msg


def _send(to_email, user_id):
    try:
        msg = _compose(to_email)
        with smtplib.SMTP(Config.SMTP_HOST, Config.SMTP_PORT, timeout=20) as s:
            s.starttls()
            if Config.SMTP_USER:
                s.login(Config.SMTP_USER, Config.SMTP_PASSWORD)
            s.send_message(msg)
        print(f"[crisis-email] sent counselling info to {to_email}")
    except Exception as e:
        # Undo the cooldown stamp so the next escalation can retry.
        with _lock:
            _last_sent.pop(user_id, None)
        print(f"[crisis-email] FAILED for {to_email}: {type(e).__name__}: {e}")


def notify_crisis(user_id):
    """Send the counselling-information email for an escalated turn.

    No-op unless crisis_email.enabled (config.yaml) and SMTP (.env) are set.
    Never raises.
    """
    if not Config.CRISIS_EMAIL_ENABLED:
        return
    if not _smtp_ready():
        print("[crisis-email] enabled but SMTP_HOST/MAIL_FROM missing — skipped")
        return
    if not _cooldown_ok(user_id):
        return
    try:
        from app.extensions import get_sb
        res = (get_sb().table("profiles").select("email")
               .eq("id", user_id).limit(1).execute())
        to_email = (res.data or [{}])[0].get("email")
    except Exception as e:
        print(f"[crisis-email] could not look up user email: {e}")
        return
    if not to_email:
        return
    threading.Thread(target=_send, args=(to_email, user_id), daemon=True).start()
