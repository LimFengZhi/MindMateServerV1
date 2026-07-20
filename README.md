# MindMate — Multi-Agent Mental-Health Companion (Supabase edition)

A Flask app where users chat with a warm, non-clinical AI companion. Behind each
reply is a multi-agent pipeline: an emotion classifier, a crisis-escalation
router, a conversation summariser, and a chatbot. Around the chat it offers:

- **My Emotions** — per-session emotion analysis (dominant emotion, distribution, timeline)
- **Resources** — in-app self-help guides & calming exercises (content lives in
  the DB with a reference link to the original source; based on the TAR UMT
  Student Counselling Service collection)
- **Self-Tests** — PSS-10 stress, Rosenberg self-esteem, and PHQ-9 depression
  screens, scored server-side, with crisis contacts attached when needed
- **Staff site** — a separate `/admin` dashboard where staff see usage stats and
  admins create staff accounts by email

This edition stores everything in **Supabase** (Postgres + email-verified Auth).

---

## 1. One-time setup

### a. Create the database tables
Open your Supabase project → **SQL Editor** → **New query**, paste the entire
contents of [`schema.sql`](schema.sql), and **Run** it. This creates all tables,
row-level-security policies, and the trigger that auto-creates a profile for
each new user.

> ⚠️ `schema.sql` is a **full reset script**: every run **drops all app tables
> and deletes every user account** (Supabase Auth included), then recreates the
> schema from scratch. That is the intended workflow for schema changes — but
> never run it against data you want to keep.

### b. Turn on email verification + set the redirect URL
In Supabase → **Authentication → Sign In / Providers → Email**:
- Ensure **Confirm email** is **ON** (this is the default).

In **Authentication → URL Configuration**:
- Set **Site URL** to `http://localhost:5000` so the verification link returns
  users to the app's login page.

### c. Configure `.env`
Copy the template and fill in your Supabase values:
```bash
cp .env.example .env
```
The important ones:
```
SUPABASE_URL=...            # your project URL
SUPABASE_SECRET_KEY=...     # service (secret) key (server-side data access)
SUPABASE_ANON_KEY=          # optional: publishable key for the auth flow
SITE_URL=http://localhost:5000
SECRET_KEY=                 # blank = auto-generate; set a fixed value to persist
AI_MODE=stub               # "stub" (instant) or "real" (loads local models)
FLASK_DEBUG=0              # 1 enables the Werkzeug debugger — DEV ONLY (RCE risk)
FLASK_HOST=127.0.0.1      # 0.0.0.0 to expose on your LAN
```
> Security notes: the app runs with **debug off** and **bound to localhost** by
> default. The Supabase **secret key** bypasses RLS — keep `.env` out of version
> control (it's git-ignored). For anything beyond local dev, set a fixed
> `SECRET_KEY`, add `SUPABASE_ANON_KEY`, and serve behind gunicorn/waitress.

### d. Install dependencies
```bash
# CPU PyTorch (only needed when AI_MODE=real)
pip install torch --index-url https://download.pytorch.org/whl/cpu
pip install -r requirements.txt
```

### e. Upload the Resources content
The Resources page's guides/exercises are **owned by a script**, not seeded on
boot:
```bash
python scripts/scrape_resources.py --dry-run   # preview
python scripts/scrape_resources.py             # full-replace upload
```
Re-run it whenever you edit the content in that script. (It replaces the whole
`resources` table each time.)

---

## 2. Run it
```bash
python run.py
```
Open <http://localhost:5000>. On first boot the app **auto-seeds** the user
agreement, the agents' prompts, and the three self-tests (no action needed).

### First use
1. Go to **Register**, read the **User Agreement**, tick the box, and sign up.
2. Check your email and click the verification link.
3. Come back and **Log in**.

---

## 3. How the AI is wired (`AI_MODE`)

| Mode | Behaviour |
|------|-----------|
| `stub` (default) | Lightweight rule-based agents. Boots instantly, no model downloads. The full pipeline (diagnostic → routing → summarise → chatbot) still runs, and **crisis escalation still works** (lexical safety net). |
| `real` | Loads the local models in `models/` (Gemma2 chatbot, RoBERTa emotion classifier) and Qwen summariser. If any model fails to load, that component **falls back to its stub** automatically — the app keeps running. |

Voice (speech-to-text) uses **faster-whisper** and works in either mode once the
package is installed. Without it, the mic button reports "voice unavailable".

Check what's loaded at any time: <http://localhost:5000/health>.

---

## 4. Roles & the staff site (user / staff / admin)

Every user gets the `user` role automatically (via the `profiles` table).

- **staff** — the full backoffice at `/admin`:
  - **Live Counselling** (`/admin/live`) — supervision of **experiment mode**:
    users can start a chat in experiment mode, and every bot reply (crisis
    responses included) is held as a draft until a counsellor resolves it. The
    counsellor **takes charge of up to two users** (those needing attention are
    flagged and sorted first), picks one of each user's live sessions, watches
    the conversation live side by side, and **approves** the draft or **edits**
    it (the edit is delivered; the bot's draft is recorded as rejected). The counsellor can also
    rename the session as a case label. Meanwhile the user's chat shows "being
    reviewed by a counsellor…" and polls until delivery.
  - **Overview** — usage stats (users, sessions, messages, escalations, pending
    reviews, tests taken)
  - **Emotion Analysis** — emotion distribution + escalations across all users
  - **User Sessions** — pick a user → pick a chat → review the transcript with
    per-reply diagnostics; **rate each bot reply (1–5 ★), leave feedback**, and
    **export the session as JSON**
  - **Testing** — a multi-agent test bench (`/admin/testing/multi-agent`) that
    chats through the real pipeline on the staff member's own account, with the
    same rating/feedback controls and JSON export
- **admin** — everything staff can, plus **create/remove staff accounts by
  email** from the dashboard.

**Staff entrance:** the login page has a **"Login as staff →"** link that leads
to `/admin/login`. Non-staff accounts are rejected there.

**Bootstrap the first admin** (one-time, in the Supabase SQL editor):
```sql
update public.profiles set role = 'admin' where email = 'person@example.com';
```
After that, no SQL is needed — admins manage staff entirely from the dashboard.
Server-side guards (`staff_required` / `admin_required`) re-check the role on
every request, so demotions take effect immediately.

### Demo admin account
For trying out the staff site on the development database:

| | |
|---|---|
| **Email** | `admin@mindmate.com` |
| **Password** | `Admin123!` |

Log in via **"Login as staff →"** on the login page (or `/admin/login`).

> ⚠️ This is a **demo credential for local development only**. Anyone who reads
> this file can sign into that account, so change the password (Supabase →
> Authentication → Users) or delete the account before the app faces real
> users or real data.

> ♻️ Rerunning `schema.sql` **deletes this account** along with everything
> else. Recreate it afterwards: register any account in the app, promote it
> with the SQL at the bottom of `schema.sql`, or re-create this demo login
> from the admin dashboard of another admin account.

---

## 5. Project layout

The application code lives in the `app/` package. Setup files and the model
weights stay at the project root.

```
MultiAgent2/
├─ run.py                 dev entrypoint  (FLASK_DEBUG / FLASK_HOST aware)
├─ schema.sql             Supabase DB setup — run in the SQL editor (idempotent)
├─ requirements.txt       dependencies
├─ README.md  API.md  CLAUDE.md  CODING_GUIDE.md  .env  .gitignore
├─ scripts/
│  └─ scrape_resources.py owns the Resources content (full-replace upload)
├─ models/                ML model weights (loaded only when AI_MODE=real)
└─ app/                   the Flask application package
   ├─ __init__.py           app factory (create_app)
   ├─ config.py             env-driven configuration
   ├─ extensions.py         Supabase client + optional rate limiter
   ├─ http_utils.py         json_error helper (uniform error bodies)
   ├─ auth/                 Supabase email-verified auth + route guards
   ├─ db/                   repo.py (user queries) · admin_repo.py (admin queries)
   │                        · seed.py (boot seeding)
   ├─ ml/                   model registry (env-toggle + graceful fallback)
   ├─ agents/               diagnostic, routing, summarize, chatbot, voice
   ├─ prompt_builder/       system-prompt templates (DB-backed, file fallback)
   ├─ chat/                 multi-agent orchestrator + chat/voice routes
   ├─ sessions/             session CRUD + transcript + emotion analysis
   ├─ resources/            resources API + self_test/ (definitions, scoring)
   ├─ agreements/           active user-agreement API
   ├─ admin/                staff site: routes + account service
   ├─ templates/            Jinja: base.html → app_base.html → pages
   │                        · partials/sidebar.html · admin/ (staff pages)
   └─ static/               css/ (style.css + admin.css) · js/ (per page + admin/)
```

### Database tables
`profiles`, `agreements`, `agreement_acceptances`, `prompts`, `sessions`,
`messages`, `resources`, `resource_steps`, `test`, `test_created`.

### Editing the agents' prompts
The chatbot/summarizer system prompts live in the **`prompts`** table (seeded on
first boot from `app/prompt_builder/prompt/*.txt`). Edit them in the Supabase
dashboard (Table editor → `prompts` → edit the `content` of `composed` /
`summarise`); changes take effect within ~15 seconds, no restart needed. If the
table is empty or unreachable, the app falls back to the bundled `.txt` files.

### Message feedback (staff review)
The `messages` table's `rating` (1–5), `feedback` (text), `feedback_by`, and
`feedback_at` columns are written by the **staff site's review tools** (User
Sessions and the Testing bench): staff rate bot replies and leave feedback via
`POST /api/admin/messages/{id}/feedback`, and session exports include them —
a ready-made quality dataset for future fine-tuning.

> ⚠️ Re-running `schema.sql` **wipes the database and all user accounts**, then
> recreates the schema. After every reset: (1) `python run.py` re-seeds the
> agreement, prompts, and self-tests; (2) rerun
> `python scripts/scrape_resources.py` to restore the Resources content;
> (3) register your admin account again and re-promote it with the SQL at the
> bottom of `schema.sql` (the demo admin above is deleted too).

### Where to edit what
See [`CODING_GUIDE.md`](CODING_GUIDE.md) for the user-side / admin-side split —
which files admin work may touch and which are off-limits.
