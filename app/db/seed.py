"""Idempotent seeding of the user agreement + agent prompts.

ensure_seed() runs on app startup. It only inserts when a table is empty, so it
is safe to call on every boot and safe to re-run. Edit the content here (or in
the Supabase dashboard) to change what users see.

Resources are NOT seeded here: they are imported from the TAR UMT counselling
self-help page by scripts/scrape_resources.py, which owns the resources table.
"""
from app.extensions import get_sb

AGREEMENT_VERSION = "1.0"
AGREEMENT_TITLE = "MindMate User Agreement"
AGREEMENT_CONTENT = """\
Welcome to MindMate. Please read this agreement carefully before creating an account.

1. NOT A MEDICAL SERVICE
MindMate is a peer-support companion powered by AI. It is NOT a therapist, doctor,
or crisis service, and it does not provide diagnosis, treatment, or medical advice.
Nothing here replaces care from a qualified professional.

2. IN A CRISIS
If you are in immediate danger or thinking about harming yourself, contact your
local emergency number or a crisis line right away:
  - Malaysia: Befrienders KL 03-7627 2929 (24 hours)
  - US: call or text 988 (Suicide & Crisis Lifeline)
  - UK & ROI: Samaritans 116 123

3. YOUR DATA
Your messages and emotion-analysis results are stored securely so you can revisit
your conversations. We do not sell your data. You may delete any conversation at
any time from within the app.

4. APPROPRIATE USE
Use MindMate respectfully and only for your own personal support. Do not use it to
harm yourself or others, and do not rely on it for emergencies.

5. NO GUARANTEE
AI responses can be wrong or incomplete. You are responsible for how you act on
anything the companion says.

By registering, you confirm that you are at least 16 years old, have read this
agreement, and accept these terms.
"""


def ensure_seed():
    """Insert the agreement + prompts + self-tests if their tables are empty.
    No-op otherwise."""
    sb = get_sb()
    _seed_agreement(sb)
    _seed_prompts(sb)
    _seed_tests(sb)


def _seed_tests(sb):
    """Seed the self-test instruments (stress / self-esteem / depression /
    suicide-risk). Unlike the other seeders this one TOPS UP: any test slug
    from definitions.py that is missing from the table is inserted, so a new
    instrument reaches existing databases without a reset. Existing rows are
    never touched (dashboard edits survive)."""
    from app.resources.self_test.definitions import TESTS
    existing = sb.table("test").select("slug").execute()
    have = {r["slug"] for r in (existing.data or [])}
    rows = [dict(t, sort_order=i) for i, t in enumerate(TESTS)
            if t["slug"] not in have]
    if rows:
        sb.table("test").insert(rows).execute()
        print(f"[seed] inserted {len(rows)} self-tests")


def _seed_prompts(sb):
    """Seed the agents' system prompts from the bundled .txt defaults so they
    can be edited in the dashboard afterwards. TOPS UP like the self-tests:
    any key missing from the table is inserted (existing rows untouched), so
    new prompts reach existing databases without a reset."""
    from app.agents.prompt_loader import bundled_prompt
    descriptions = {
        "composed": "Chatbot system prompt. Placeholders: {diagnostic_label}, {summarised_history}.",
        "summarise": "Summarize-agent instruction prompt.",
        "single": "Test Chat bench: single-agent baseline (composed rules WITHOUT the summary/memory parts).",
    }
    existing = sb.table("prompts").select("key").execute()
    have = {r["key"] for r in (existing.data or [])}
    rows = [{"key": key, "content": bundled_prompt(key),
             "description": desc}
            for key, desc in descriptions.items() if key not in have]
    if rows:
        sb.table("prompts").insert(rows).execute()
        print(f"[seed] inserted {len(rows)} agent prompts")


def _seed_agreement(sb):
    existing = sb.table("agreements").select("id").limit(1).execute()
    if existing.data:
        return
    sb.table("agreements").insert({
        "version": AGREEMENT_VERSION,
        "title": AGREEMENT_TITLE,
        "content": AGREEMENT_CONTENT,
        "is_active": True,
    }).execute()
    print("[seed] inserted user agreement v" + AGREEMENT_VERSION)
