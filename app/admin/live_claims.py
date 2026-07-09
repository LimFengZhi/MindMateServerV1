"""Who is 'in charge' of which user on the Live Counselling page.

In-memory registry (fine for the single-process dev server; with multiple
gunicorn workers this would need to move to a table). Claims are kept alive by
the claimer's ~4s poll heartbeat and expire ~15s after their browser stops
polling — so a closed tab releases the user automatically and no lock can go
stale.
"""
import time

CLAIM_TTL = 15  # seconds without a heartbeat before a claim is released

_claims = {}  # user_email -> {"staff_id", "staff_email", "ts"}


def _purge():
    now = time.time()
    for email in [e for e, c in _claims.items() if now - c["ts"] > CLAIM_TTL]:
        del _claims[email]


def claim_user(user_email, staff_id, staff_email):
    """Claim a user. Returns (True, None), or (False, other_staff_email) when
    another staff member already holds them."""
    _purge()
    existing = _claims.get(user_email)
    if existing and existing["staff_id"] != staff_id:
        return False, existing["staff_email"]
    _claims[user_email] = {"staff_id": staff_id, "staff_email": staff_email,
                           "ts": time.time()}
    return True, None


def release_user(user_email, staff_id):
    """Release a claim (only the holder can release it)."""
    existing = _claims.get(user_email)
    if existing and existing["staff_id"] == staff_id:
        del _claims[user_email]


def heartbeat(staff_id):
    """Keep this staff member's claims alive; called from their poll."""
    now = time.time()
    for c in _claims.values():
        if c["staff_id"] == staff_id:
            c["ts"] = now
    _purge()


def claims_by_email():
    """{user_email: staff_email} for every live claim."""
    _purge()
    return {email: c["staff_email"] for email, c in _claims.items()}
