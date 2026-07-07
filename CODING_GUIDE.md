# CODING_GUIDE — the User-side / Admin-side split

MindMate is one Flask app with two wings that share infrastructure but must
never bleed into each other:

- **User side** — everything a normal user touches: login/register, chat,
  emotion analysis, resources, self-tests. Its JSON API is a **published
  contract** ([API.md](API.md)) consumed by the web UI and the Flutter client.
- **Admin side** — the staff site at `/admin` (+ `/api/admin/*`): dashboards and
  staff-account management. Web-only, role-guarded, no external consumers.

The rule of thumb: **admin work adds files in the admin areas and registers
them; it does not modify user-side files.** This keeps the user API stable and
makes admin changes impossible to leak into user-facing behavior.

---

## 1. Where admin work MAY edit (the admin wing)

| Path | What goes here |
|---|---|
| `app/admin/routes.py` | Admin pages (`/admin/...`) and JSON API (`/api/admin/...`). **Every** API route carries `@staff_required` or `@admin_required`. |
| `app/admin/service.py` | Admin-side orchestration (e.g. creating staff accounts via Supabase's auth admin API). |
| `app/db/admin_repo.py` | **All** admin database queries. Never put them in `repo.py`, and never call `repo.py`'s user-scoped functions with another user's id. |
| `app/templates/admin/` | Admin Jinja pages (dashboard, staff login, test benches). Extend `base.html` directly (not `app_base.html` — that's the user shell with the user sidebar). |
| `app/static/js/admin/` | Admin page scripts. May use the shared helpers from `common.js` (`api()`, `escapeHTML`, `$`, placeholders). Staff-specific shared code (role guard, feedback controls, export) lives in `review_helpers.js` — load it before the page's own script. |
| `app/static/css/admin.css` | Admin-only styles, layered **on top of** `style.css`. New admin styles go here, not in `style.css`. |

### Shared files admin work may touch — but only in the marked way

| File | Allowed change | Nothing else |
|---|---|---|
| `app/__init__.py` | Add a blueprint registration line in `_register_blueprints`. | Don't alter CSP, error handlers, page routes. |
| `app/auth/decorators.py` | Add/adjust the role guards (`staff_required`, `admin_required`, `STAFF_ROLES`). | Don't touch `login_required` / `session_required` semantics. |
| `schema.sql` | **Append-only**, idempotent blocks (`create table if not exists`, `add column if not exists`, `drop policy if exists` + recreate). Every new table gets RLS + policies. | Never rewrite or reorder existing blocks. |
| `app/templates/base.html` | Add a new empty `{% block %}` if genuinely needed. | Don't change the head order (the sidebar no-flash script must run before first paint). |
| `app/templates/login.html` | The `auth-alt` staff-entrance link area only. | The register/agreement flow is user-side. |

---

## 2. Where admin work MUST NOT edit (the user wing)

| Path | Why it's off-limits |
|---|---|
| `app/auth/routes.py`, `app/sessions/`, `app/chat/routes.py`, `app/resources/routes.py`, `app/resources/self_test/routes.py`, `app/agreements/` | The public API contract in [API.md](API.md) — the Flutter client depends on these shapes and status codes. |
| `app/db/repo.py` | User-scoped data access. Every query filters by `user_id`; admin queries live in `admin_repo.py` so an admin feature can never accidentally widen a user query. (Sanctioned exceptions admin routes may call: the id-scoped helpers `get_profile` and `set_message_feedback` — never the `user_id`-filtered functions.) |
| `app/chat/orchestrator.py`, `app/agents/`, `app/ml/`, `app/prompt_builder/` | The AI pipeline and its safety layers (crisis regex, stub fallbacks). Admin edits prompts **through the `prompts` DB table**, which the loader picks up within ~15 s — that's the designed integration point; no code change needed. |
| `app/static/js/common.js`, `chat.js`, `login.js`*, `analysis.js`, `resources.js` | User UI. (*except the staff-entrance redirect note in §1.) |
| `app/static/css/style.css` | Shared base theme. Admin pages *consume* its classes (`.btn`, `.cards`, `.topbar`, `.auth-card`…); admin-specific rules go in `admin.css`. |
| `app/templates/app_base.html`, `partials/sidebar.html`, user page templates | The user shell. The user sidebar deliberately has **no admin link** — staff reach the site via `/admin/login` or the login-page link. |
| `app/config.py`, `app/extensions.py`, `app/http_utils.py` | Shared infrastructure — **reuse** (`Config`, `get_sb()`, `json_error`) as-is. If a change here seems necessary, it affects both wings: stop and review. |
| `scripts/scrape_resources.py` | Owns the `resources` table (full-replace). If an admin resources-CRUD UI is ever built, ownership must move there first — otherwise re-running the script wipes admin edits. |

---

## 3. Admin-side rules (apply to every admin feature)

1. **Guard every endpoint.** `@staff_required` (staff + admin) for read/dashboard
   features, `@admin_required` (admin only) for account management and anything
   destructive. The role is re-read from `profiles` on each request — hiding a
   button is never the access control.
2. **Pages are shells.** The `/admin` HTML renders for anyone; all data comes
   from guarded APIs. Client-side role checks only handle redirect UX.
3. **Privacy by default.** Dashboard endpoints return **aggregates** (counts,
   bands). The session-review tools expose transcripts to staff **by design**
   (counselling review + reply feedback) — but individual self-test answers
   stay private, and no endpoint returns more than its screen needs.
4. **Errors** always via `app/http_utils.json_error` → `{ "error": "…" }`.
5. **Roles:** `user` < `staff` < `admin`. Admins create/remove staff from the
   dashboard; the **first admin** is promoted by SQL (see README §4). Staff
   removal demotes to `user` — it never deletes the account.
6. **Escaping:** admin JS renders API data with `escapeHTML(...)` exactly like
   the user pages (the CSP allows inline handlers, so this is load-bearing).
7. **New tables** go into `schema.sql` as an idempotent block **with RLS
   policies**, and get a matching accessor in `admin_repo.py`.
8. **The test bench calls user-side endpoints on purpose.** Test chats are real
   sessions on the staff member's *own* account (`POST /sessions`, `POST /chat`
   with their own token), so the pipeline is exercised exactly as users
   experience it — don't replace that with a parallel admin chat endpoint.
   Only the review/export extras go through `/api/admin/*`.

## 4. User-side rules (the mirror image)

- User-side code never imports from `app/admin/` or `app/db/admin_repo.py`.
- Changing any user endpoint's request/response shape requires updating
  [API.md](API.md) in the same change (the Flutter client reads it).
- New user features follow the existing pattern: blueprint + `repo.py`
  functions filtered by `user_id` + guards from `auth/decorators.py`.

---

## 5. Quick reference — "I want to add an admin screen"

1. Query → `app/db/admin_repo.py` (aggregates only).
2. Endpoint → `app/admin/routes.py` under `/api/admin/...` with a role guard.
3. Page → `app/templates/admin/<name>.html` extending `base.html`.
4. Script → `app/static/js/admin/<name>.js`; styles → `admin.css`.
5. If a new page route is needed, add it in `admin_bp` (already registered).
6. Update [API.md](API.md)'s roles note only if the surface changes;
   user-side docs stay untouched.
