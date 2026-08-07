# MindMate — Multi-Agent Mental-Health Companion

A Flask app where users chat with a warm, non-clinical AI companion. Behind each
reply is a multi-agent pipeline: an emotion classifier, a crisis-escalation
router, a conversation summariser, and a fine-tuned chatbot. Data and auth live
in Supabase (Postgres + email-verified accounts).

- **Chat** — text or voice, with hybrid conversation memory and layered crisis
  safeguards
- **My Emotions** — per-session emotion analysis (dominant emotion,
  distribution, timeline)
- **Resources** — in-app self-help guides & calming exercises (based on the
  TAR UMT Student Counselling Service collection)
- **Self-Tests** — PSS-10, Rosenberg self-esteem, PHQ-9, and a Suicide Risk
  Check (adapted from the SWSPHN screening tool), scored server-side with
  crisis contacts attached when needed
- **Staff site** — `/admin` backoffice: live counselling supervision,
  dashboards, transcript review, model test bench

The fine-tuning research pipeline behind the chatbot lives in its own repo:
[counseling_chatbot_fine_tuning_pipeline](https://github.com/LimFengZhi/counseling_chatbot_fine_tuning_pipeline)
(cloned into `fine_tuning_chatbot/` — see its README). The tuned weights are on
[Hugging Face](https://huggingface.co/Fz0212).

---

## 1. Supabase setup (once per project)

1. **Create the tables:** Supabase → **SQL Editor** → paste all of
   [`schema.sql`](schema.sql) → Run.
2. **Auth:** in **Authentication → Sign In / Providers → Email**, keep
   **Confirm email** ON. In **Authentication → URL Configuration**, set
   **Site URL** to where the app runs (`http://localhost:5000` for local dev,
   your public URL for a deployment).

> ⚠️ `schema.sql` is a **full reset script**: every run drops all app tables
> **and deletes every auth account**, then recreates the schema. Never run it
> against data you want to keep. The post-reset checklist is in §6.

---

## 2. Run locally (development)

```bash
cp .env.example .env        # fill in SUPABASE_URL + SUPABASE_SECRET_KEY (min.)
pip install torch --index-url https://download.pytorch.org/whl/cpu   # AI_MODE=real only
pip install -r requirements.txt
python scripts/scrape_resources.py    # one-time: upload the Resources content
python run.py
```

Open <http://localhost:5000>. First boot auto-seeds the user agreement, the
agents' prompts, and the self-tests.

Key `.env` values (full template: [`.env.example`](.env.example)):

```
SUPABASE_URL=...            # project URL
SUPABASE_SECRET_KEY=...     # service key — bypasses RLS, keep out of git
SUPABASE_ANON_KEY=          # optional: least-privilege key for the auth flow
SITE_URL=http://localhost:5000
AI_MODE=stub                # "stub" (instant, rule-based) or "real" (local models)
```

Model weights are not in git. Fetch them from Hugging Face into `models/`:

```bash
python scripts/download_models.py          # ~9.5 GB; idempotent, resumable
```

**Optional — crisis email:** set `crisis_email.enabled: true` in `config.yaml`
and fill the SMTP values in `.env` (Gmail needs an App Password). Every crisis
escalation then emails the counselling info to the user, max once per hour.

---

## 3. Deploy with Docker (GPU host)

The repo ships a complete container setup: one gunicorn worker, weights in a
volume, secrets never in the image.

**Host prerequisites (once):** NVIDIA driver, Docker + compose plugin,
[nvidia-container-toolkit](https://docs.nvidia.com/datacenter/cloud-native/container-toolkit/latest/install-guide.html)
(`sudo nvidia-ctk runtime configure && sudo systemctl restart docker`).

```bash
git clone https://github.com/LimFengZhi/MindMateServerV1.git
cd MindMateServerV1
cp .env.example .env        # fill in the real secrets; set SITE_URL to the public URL
docker compose up --build -d
docker compose logs -f      # watch the first boot
```

First boot downloads the weights from Hugging Face into the `models` volume
(~9.5 GB: the three study chat models + the int8 ONNX classifier, auto-detected
and loaded through `optimum-onnxruntime`); the summariser and whisper caches
land in the same volume. Later boots are instant.

- **Verify:** `curl http://localhost:5000/health` →
  `{"models": {"chatbot": true, "classifier": true, ...}}`
- **Update:** `git pull && docker compose up --build -d` (weights persist)
- **Supabase side:** set the project's Auth **Site URL** to the deployment's
  public URL (same value as `SITE_URL` in `.env`)
- **HTTPS:** put a reverse proxy or a Cloudflare tunnel in front — don't expose
  the bare port to the internet

**Why one worker?** The rate limiter, live-counselling claims, crisis-email
cooldown and report cache are all in process memory — a second worker would get
its own copies (and its own multi-GB model load). The compose file and
`docker/entrypoint.sh` already enforce this; scaling out means moving that state
to shared storage first.

---

## 4. AI modes (`AI_MODE`)

| Mode | Behaviour |
|------|-----------|
| `stub` (default) | Rule-based agents, instant boot, no downloads. The full pipeline still runs and **crisis escalation still works** (lexical safety net). |
| `real` | Loads the local models from `models/`. Any model that fails to load **falls back to its stub** — the app keeps running. |

Voice (faster-whisper) works in either mode and is loaded at startup, so the
first voice message doesn't stall (`WHISPER_MODEL=tiny` in `.env` speeds up
boot). Check what's loaded: <http://localhost:5000/health>.

---

## 5. Roles & the staff site

Every registered account gets the `user` role. Staff enter via the login page's
**"Login as staff →"** link (`/admin/login`).

- **staff** — the `/admin` backoffice:
  - **Live Counselling** — supervises **experiment mode** chats: every bot
    reply is held as a draft until a counsellor approves or edits it (the user
    sees "being reviewed…" until delivery). A counsellor takes charge of up to
    two users at a time.
  - **Dashboard / Suicide Alert / Emotion Analysis** — usage stats, 14-day
    charts, crisis escalations for today/week/month with quiz-uptake per user
  - **User Sessions** — every user with profile info and chat counts →
    transcript review with per-reply ratings & feedback, JSON export, and a
    generated **session-analysis report** (viewable + PDF download)
  - **Editing** — CRUD for Resources, the agents' **Prompts** (live in ~15 s,
    no restart), Agreements and Self-Tests, plus test analytics
  - **Test Chat** — chat through the real pipeline, compare **single vs
    multi-agent**, or run the same message through all **three study models**;
    every reply ratable, stored in bench sessions
- **admin** — everything above, plus creating/removing staff accounts by email.

**Bootstrap the first admin** (once, in the Supabase SQL editor):

```sql
update public.profiles set role = 'admin' where email = 'person@example.com';
```

After that, staff management happens entirely in the dashboard. Role guards
re-check on every request, so demotions apply immediately.

**Demo admin (local development only):** `admin@mindmate.com` / `Admin123!` —
anyone reading this file can use it, so change or delete it before facing real
users. A schema reset deletes it too.

---

## 6. Resetting the database

Running `schema.sql` again wipes everything (§1 warning). Afterwards, in order:

1. Restart the app — it re-seeds the agreement, prompts, and self-tests.
2. `python scripts/scrape_resources.py` — restore the Resources content.
   (⚠️ this also overwrites any edits made in the admin Resources editor)
3. Register a fresh account, then promote it to admin with the SQL in §5.

---

## 7. Project layout

```
MindMateServerV1/
├─ run.py                 dev entrypoint
├─ schema.sql             Supabase DB setup (full reset — run in the SQL editor)
├─ requirements.txt       dependencies
├─ README.md  API.md  CLAUDE.md  CODING_GUIDE.md
├─ config.yaml            committed app tuning (generation, memory, thresholds)
├─ Dockerfile / docker-compose.yml / docker/entrypoint.sh   container deployment
├─ scripts/
│  ├─ download_models.py  fetch the model weights from Hugging Face
│  └─ scrape_resources.py owns the Resources content (full-replace upload)
├─ models/                weights (gitignored; volume-mounted in Docker)
├─ fine_tuning_chatbot/   SEPARATE repo cloned here (research pipeline)
└─ app/
   ├─ __init__.py           app factory (create_app)
   ├─ config.py             the single reader of .env + config.yaml
   ├─ extensions.py         Supabase client + rate limiter
   ├─ auth/                 email-verified auth + route guards
   ├─ db/                   repo.py (user queries) · admin_repo.py (admin) · seed.py
   ├─ agents/               the pipeline: LangChain chains + LangGraph graph,
   │                        guards, stubs, registry, DB-backed prompts
   ├─ chat/ sessions/ resources/ agreements/   user-facing APIs
   ├─ admin/                staff site routes + account service
   └─ templates/ static/    Jinja pages + vanilla JS/CSS
```

**Database tables:** `profiles`, `agreements`, `agreement_acceptances`,
`prompts`, `sessions`, `messages`, `resources`, `resource_steps`, `test`,
`test_created`, `bench_session`, `bench_result`.

**Editing the agents' prompts:** use the admin dashboard's **Editing → Prompts**
tab — changes apply within ~15 s, no restart. If the `prompts` table is empty or
unreachable, the app falls back to the bundled `app/agents/prompt/*.txt` files.

**Where to edit what:** see [`CODING_GUIDE.md`](CODING_GUIDE.md) for the
user-side / admin-side split.
