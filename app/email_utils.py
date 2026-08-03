"""Email sending.

Two layers:
    send_email(to, subject, body)  generic SMTP send — reusable by any feature.
    notify_crisis(user_id)         the crisis safety layer: emails the
                                   counselling info to a user after an
                                   escalated chat turn.

SMTP credentials live in .env; the crisis toggle, wording, and cooldown live
in config.yaml (crisis_email block). All sending is fire-and-forget on a
daemon thread and never raises — a broken email setup must not break a chat.
"""
import smtplib
import threading
import time
from email.message import EmailMessage

from app.config import Config

_last_sent = {}  # user_id -> monotonic time of their last crisis email
_lock = threading.Lock()


def send_email(to_email, subject, body):
    """Send one plain-text email in the background. Returns immediately."""
    if not (Config.SMTP_HOST and Config.MAIL_FROM):
        print("[email] SMTP_HOST/MAIL_FROM not configured — skipped")
        return

    def _send():
        try:
            msg = EmailMessage()
            msg["Subject"], msg["From"], msg["To"] = subject, Config.MAIL_FROM, to_email
            msg.set_content(body)
            with smtplib.SMTP(Config.SMTP_HOST, Config.SMTP_PORT, timeout=20) as s:
                s.starttls()
                if Config.SMTP_USER:
                    s.login(Config.SMTP_USER, Config.SMTP_PASSWORD)
                s.send_message(msg)
            print(f"[email] sent '{subject}' to {to_email}")
        except Exception as e:
            print(f"[email] FAILED for {to_email}: {type(e).__name__}: {e}")

    threading.Thread(target=_send, daemon=True).start()


def _cooldown_ok(user_id):
    """At most one crisis email per user per cooldown window."""
    window = Config.CRISIS_EMAIL_COOLDOWN_MIN * 60
    with _lock:
        last = _last_sent.get(user_id)
        if last is not None and time.monotonic() - last < window:
            return False
        _last_sent[user_id] = time.monotonic()
        return True


def _user_email(user_id):
    try:
        from app.extensions import get_sb
        res = (get_sb().table("profiles").select("email")
               .eq("id", user_id).limit(1).execute())
        return (res.data or [{}])[0].get("email")
    except Exception as e:
        print(f"[email] could not look up user email: {e}")
        return None


def notify_crisis(user_id):
    """Email the counselling information after an escalated turn. No-op when
    crisis_email.enabled is false or inside the cooldown. Never raises."""
    if not Config.CRISIS_EMAIL_ENABLED or not _cooldown_ok(user_id):
        return
    to_email = _user_email(user_id)
    if to_email:
        send_email(
            to_email,
            Config.CRISIS_EMAIL_SUBJECT,
            f"{Config.CRISIS_EMAIL_INTRO}\n\n"
            f"{Config.CRISIS_MESSAGE}\n\n"
            "— MindMate\n"
            "This is an automated safety message from your MindMate companion.",
        )
