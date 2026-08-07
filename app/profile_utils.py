"""Profile field rules shared by the user side, the admin side and the report.

Age is never stored — a stored integer silently goes stale (a 19-year-old is
still 19 in the database three years later). date_of_birth is the column;
age_from_dob() derives the number wherever one is shown, so every surface
agrees and none of them can drift.

No DB and no Flask (only Config, which is itself dependency-free), so anything
may import this.
"""
from datetime import date, datetime

from app.config import Config

# The gender values profiles.gender is constrained to in schema.sql. Keys are
# what is stored; values are what the UI shows.
GENDERS = {
    "female": "Female",
    "male": "Male",
    "other": "Other",
    "prefer_not_to_say": "Prefer not to say",
}

# Accepted age range — tuned in config.yaml's `profile` block, not here.
MIN_AGE = Config.PROFILE_MIN_AGE
MAX_AGE = Config.PROFILE_MAX_AGE


def parse_dob(value):
    """An ISO 'YYYY-MM-DD' string (or a date) -> date, or None if unparseable.
    Accepts what <input type="date"> posts."""
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    if isinstance(value, datetime):
        return value.date()
    try:
        return datetime.strptime((value or "").strip(), "%Y-%m-%d").date()
    except (ValueError, TypeError):
        return None


def age_from_dob(value, today=None):
    """Whole years as of today, or None when the date is missing/unparseable.
    The month/day comparison handles a birthday that hasn't happened yet."""
    dob = parse_dob(value)
    if dob is None:
        return None
    today = today or date.today()
    return today.year - dob.year - ((today.month, today.day) < (dob.month, dob.day))


def dob_error(value):
    """None when the date of birth is acceptable, else a user-facing reason."""
    dob = parse_dob(value)
    if dob is None:
        return "A valid date of birth is required (YYYY-MM-DD)."
    age = age_from_dob(dob)
    if age is None or age < 0 or age > MAX_AGE:
        return "That date of birth doesn't look right."
    if age < MIN_AGE:
        return f"You must be at least {MIN_AGE} years old to register."
    return None


def gender_label(value):
    """Stored value -> display label, falling back to the raw value."""
    return GENDERS.get(value, value or "—")
