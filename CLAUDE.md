# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

```bash
# Run the dev server (http://localhost:5000)
python run.py                      # env toggles: FLASK_DEBUG=1, FLASK_HOST=0.0.0.0

# Replace the Resources content in Supabase (content lives in this script)
python scripts/scrape_resources.py --dry-run   # preview
python scripts/scrape_resources.py             # full-replace upload
```

- The venv is `.venv/` (Windows: `.venv\Scripts\python.exe`). PyTorch is installed separately and only needed when `AI_MODE=real` (see README).
- There is no test suite or linter configured.
- **Database DDL cannot be run from code.** The backend talks to Supabase via PostgREST (supabase-py), so any schema change means editing `schema.sql` (keep it idempotent — `add column if not exists` pattern) and pasting the new block into the Supabase SQL editor manually. Scripts that need new columns should probe for them and abort cleanly before mutating data (see `upload()` in `scripts/scrape_resources.py`).
- Config comes only from `.env` at the project root, read through `app/config.py` (`Config`). Never scatter `os.getenv` elsewhere.

**Before touching admin features, read `CODING_GUIDE.md`** — it defines the user-side / admin-side split: admin work stays in `app/admin/`, `app/db/admin_repo.py`, `templates/admin/`, `static/js/admin/`, `static/css/admin.css` (+ guard/blueprint registration), and must not modify user-side routes, `repo.py`, the AI pipeline, or the published API shapes in `API.md`.

## Architecture

Flask app factory (`app/__init__.py:create_app`) + blueprints: `auth` (/auth), `chat` (/chat), `sessions` (/sessions), `resources` (/api/resources), `self_test` (/api/tests), `agreements` (/agreements), `admin`/`admin_api` (/admin + /admin/testing/multi-agent + /api/admin — role-guarded per request: `staff_required` allows staff+admin, `admin_required` allows only admin, who creates staff accounts by email via Supabase's auth admin API in `app/admin/service.py`; admin queries live in `app/db/admin_repo.py`, never in repo.py — except the id-scoped `get_profile`/`set_message_feedback` helpers admin routes may reuse; staff enter via the login page's "Login as staff" link → /admin/login; the first admin is promoted via SQL). The staff backoffice: dashboard views (overview, all-user emotion analysis, user→chat→transcript review with per-reply rating/feedback via the messages feedback columns, JSON export) plus the multi-agent test bench, whose chats are real sessions on the staff member's own account. Staff pages load `static/js/admin/review_helpers.js` (role guard + shared feedback/export helpers) before their page script. Pages are Jinja templates (`templates/base.html` → `app_base.html` → per-page; shared sidebar in `templates/partials/sidebar.html`, parameterized by `{% set active_page %}`) with vanilla JS in `app/static/js/` — `common.js` holds the `api()` fetch wrapper, auth/localStorage helpers, and `escapeHTML`, used by every page.

**Ownership is enforced in Python, not by the database.** The backend uses the Supabase *service* key, which bypasses RLS (the RLS policies in schema.sql are defense-in-depth only). Every user-scoped query in `app/db/repo.py` (the single data-access layer — all Supabase reads/writes live there) filters by `user_id`, and the route guards in `app/auth/decorators.py` do the checks: `login_required` validates the JWT into `g.user`; `session_required` additionally verifies the URL's `<session_id>` belongs to the caller (`g.session`). Error responses always go through `app/http_utils.json_error` so the frontend gets uniform `{error}` JSON.

**Multi-agent chat pipeline** (`app/chat/orchestrator.py`, one call per turn):
diagnostic agent (emotion + risk) → routing layer 2 (crisis escalation — returns a fixed crisis message and skips generation) → summarize agent (long-term memory; `RECENT_TURNS = 0` means the chatbot sees a summary only, never verbatim history) → prompt builder → chatbot agent. The turn is persisted to `messages` with emotion/escalation metadata, which feeds the per-session analysis page.

Two safety layers run regardless of AI mode: the lexical crisis regex in `app/agents/routing.py` (`crisis_keywords_present`) escalates even when the ML classifier misses, and the PHQ-9 self-harm item in the self-tests always attaches crisis contacts to the result.

**Stub/real AI duality:** with `AI_MODE=stub` (default) every agent runs a rule-based stub and boots instantly; with `real`, `app/ml/registry.py` loads local models (heavy imports happen inside loaders). Agents extend `BaseAgent` and route through `_with_fallback` — a model failing at load *or* inference time falls back to its stub, and the app keeps running. Voice (faster-whisper) is independent of `AI_MODE` and lazily loaded on first use.

**Agent prompts live in the DB** (`prompts` table, edited via the Supabase dashboard, ~15 s cache in `app/prompt_builder/loader.py`), with the bundled `.txt` files as seed + fallback.

**Content ownership split:**
- *Resources* (in-app guides/exercises with an Info tab, steps tab, and reference link) are owned by `scripts/scrape_resources.py` — it full-replaces the `resources` table; they are **not** seeded on boot.
- *Self-tests* (PSS-10 stress, Rosenberg self-esteem, PHQ-9 depression) live in `app/resources/self_test/`: `definitions.py` is seeded into the `test` table on boot; `routes.py` scores submissions **server-side** (each option carries its value, so reverse-scored items need no special casing) and records attempts in `test_created`.
- Boot seeding (`app/db/seed.py`, insert-only-when-table-empty): agreement, prompts, self-tests — not resources.

**Frontend conventions:** strict CSP (set in `create_app`) — no external scripts/frames; inline `onclick` handlers are why `'unsafe-inline'` is allowed, and all dynamic content must pass through `escapeHTML`. Card clicks pass array indexes, not interpolated ids. `api()` auto-redirects to /login on 401 **except** for `/auth/*` paths (a failed login is also a 401). The `sidebar-open` class on `<html>` drives the sidebar on both desktop and mobile; its no-flash default is set by an inline script in `app_base.html`'s head.
