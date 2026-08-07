# MindMate API Reference (for the Flutter client)

Base backend: Flask (`python run.py`), default port **5000**. All request/response
bodies are **JSON** (except voice upload, which is `multipart/form-data`).

---

## 1. Connecting from Flutter

The API runs on your PC at `http://localhost:5000`. "localhost" means different
things depending on where the Flutter app runs:

| Where Flutter runs | Base URL to use |
|---|---|
| Android **emulator** | `http://10.0.2.2:5000` |
| iOS **simulator** | `http://localhost:5000` |
| **Physical phone** (same Wi‑Fi) | `http://<your-PC-LAN-IP>:5000` (e.g. `http://192.168.1.20:5000`) — and start the server with `FLASK_HOST=0.0.0.0` |
| Flutter **Web** | `http://localhost:5000` **but** the backend must send CORS headers (see §7) |

```dart
const String kBaseUrl = String.fromEnvironment('API_BASE',
    defaultValue: 'http://10.0.2.2:5000'); // Android emulator default
```

---

## 2. Authentication model

- Auth is **Supabase email‑verified**. After registering, the user must click the
  email link before they can log in.
- **Login returns a JWT `token`.** Send it on every protected request:
  ```
  Authorization: Bearer <token>
  ```
- The token **expires** (~1 hour). A `refreshToken` is also returned, but the
  backend has **no refresh endpoint** — on a `401`, send the user back to log in
  again (or refresh directly against Supabase if you add its SDK).
- Store the token securely (`flutter_secure_storage`), not in plain prefs.

**Which endpoints need the token?** Everything **except**:
`GET /agreements/active`, `GET /health`, and the register/login calls.

---

## 3. Conventions

- Request header (JSON endpoints): `Content-Type: application/json`
- **Errors** always look like: `{ "error": "human-readable message" }` with a
  matching HTTP status (400/401/403/404/413/415/422/429/503).
- `sessionID`, `messageID`, resource `id` are **UUID strings**.
- Timestamps (`createdAt`, `created_at`) are ISO‑8601 UTC strings.

---

## 4. Endpoint summary ("which → which")

| # | Method & path | Auth | Purpose |
|---|---|:---:|---|
| 1 | `GET /agreements/active` | – | Fetch the User Agreement to show on the register screen |
| 2 | `POST /auth/register` | – | Create account (sends verification email) |
| 3 | `POST /auth/login` | – | Log in → get `token` |
| 4 | `POST /auth/logout` | ✔ | Log out (client just discards the token) |
| 5 | `GET /auth/me` | ✔ | Current user `{id,email,role,phone}` |
| 6 | `GET /sessions` | ✔ | List the user's chats (sidebar) |
| 7 | `POST /sessions` | ✔ | Create a new chat |
| 8 | `PATCH /sessions/{id}` | ✔ | Rename a chat |
| 9 | `DELETE /sessions/{id}` | ✔ | Delete a chat |
| 10 | `GET /sessions/{id}/messages` | ✔ | Load a chat's full transcript |
| 11 | `GET /sessions/{id}/analysis` | ✔ | Emotion analysis for a chat |
| 11b | `GET /sessions/{id}/pending` | ✔ | Experiment mode: poll for counsellor-reviewed replies |
| 12 | `POST /chat` | ✔ | Send a text message → get the bot reply (or `pending` in experiment mode) |
| 13 | `POST /chat/voice` | ✔ | Send a voice recording → transcript + reply |
| 14 | `GET /api/resources` | ✔ | List self‑help guides & exercises |
| 15 | `GET /api/resources/{id}` | ✔ | One guide: info text + steps + reference link |
| 16 | `GET /api/tests` | ✔ | List the self‑tests (stress / self‑esteem / depression / suicide‑risk) |
| 17 | `GET /api/tests/{id}` | ✔ | One test's questions + options |
| 18 | `POST /api/tests/{id}/submit` | ✔ | Submit answers → score, band, advice (stored server‑side) |
| 19 | `GET /health` | – | Server status / which AI models are loaded |

### Typical screen → API flow
- **Register screen:** `GET /agreements/active` (show agreement) → `POST /auth/register` (email + password + **phone** + agree).
- **Login screen:** `POST /auth/login` → store `token`.
- **Chat list (sidebar):** `GET /sessions`.
- **Open a chat:** `GET /sessions/{id}/messages`.
- **Send a message:** if no session yet → `POST /sessions` first, then `POST /chat`.
- **Emotions tab:** `GET /sessions` (to pick one) → `GET /sessions/{id}/analysis`.
- **Resources tab:** `GET /api/resources` + `GET /api/tests` (both shown as cards) →
  tap a guide → `GET /api/resources/{id}`; tap a test → `GET /api/tests/{id}` →
  answer everything → `POST /api/tests/{id}/submit` → show score/band/advice.

---

## 5. Endpoint details

### 1) GET `/agreements/active` — public
Response `200`:
```json
{ "id": "uuid", "version": "1.0", "title": "MindMate User Agreement", "content": "…full text…" }
```
`404 { "error": "no active agreement" }` if none seeded.

### 2) POST `/auth/register` — public  · rate‑limited 10/min
Request:
```json
{ "email": "you@example.com", "password": "min 6 chars",
  "name": "Ada Lovelace", "phone": "+60123456789",
  "dateOfBirth": "1998-04-23", "gender": "female", "agree": true }
```
Every field above is **required** and stored in the user's profile:
- `name` — 1–60 characters.
- `phone` — optional leading `+`, then 7–15 digits (spaces/dashes/parentheses are stripped server-side).
- `dateOfBirth` — ISO `YYYY-MM-DD`; the user must be at least `profile.min_age` (config.yaml, default **13**). Age is *derived* from this on read and never stored, so it can't go stale.
- `gender` — one of `female` · `male` · `other` · `prefer_not_to_say`.
Response `201` (email verification on — the normal case):
```json
{ "needsVerification": true, "message": "Account created! Check your email…" }
```
Response `201` (if email confirmation is disabled on Supabase):
```json
{ "needsVerification": false, "token": "jwt…", "refreshToken": "…", "message": "Account created!" }
```
Errors: `400 {error}` (invalid email / password < 6 / missing name / invalid phone /
invalid or under-13 date of birth / invalid gender / `agree` not true),
`429 {error}` (Supabase email rate limit).

### 3) POST `/auth/login` — public · rate‑limited 10/min
Request: `{ "email": "…", "password": "…" }`
Response `200`:
```json
{ "token": "jwt…", "refreshToken": "…", "user": { "id": "uuid", "email": "…" }, "role": "user" }
```
Errors: `401 { "error": "Invalid email or password." }`,
`403 { "error": "Please verify your email first…" }`.

### 4) POST `/auth/logout` — auth
Response `200`: `{ "ok": true }` (just drop the token client‑side).

### 5) GET `/auth/me` — auth
Response `200`:
```json
{ "id": "uuid", "email": "…", "role": "user", "name": "Ada Lovelace",
  "phone": "+60123456789", "dateOfBirth": "1998-04-23", "gender": "female",
  "age": 28, "joinedAt": "2026-06-27T09:54:09Z" }
```
`age` is computed from `dateOfBirth` on every read — it is not a stored column.
Any profile field is `null` for accounts created outside the registration form
(e.g. staff accounts made through the Supabase admin API).

### 5b) PATCH `/auth/me` — auth
Edit your own profile. Send only the fields you want to change; omitted fields are
left alone. `email` and `role` are **not** editable here (role must never be
self-assignable).
Request: `{ "name": "…", "phone": "…", "dateOfBirth": "1998-04-23", "gender": "male" }`
Response `200`: the same shape as `GET /auth/me`.
Errors: `400 {error}` (a sent field fails the same validation as registration, or
nothing to update), `500 {error}` (save failed).

### 6) GET `/sessions` — auth
Response `200`:
```json
{ "sessions": [ { "sessionID": "uuid", "title": "Hi today…", "mode": "multi", "createdAt": "2026-06-27T09:54:09Z" } ] }
```
(newest first) · `mode` is `"multi"` (normal) or `"experiment"` (supervised — see §11b/§12).

### 7) POST `/sessions` — auth
Request (optional): `{ "title": "New chat", "mode": "multi" }`
- `mode`: `"multi"` (default, instant bot replies) or `"experiment"` — every reply
  in the chat is reviewed live by a counsellor before the user sees it.
Response `201`: `{ "sessionID": "uuid", "title": "New chat", "mode": "multi", "createdAt": "…" }`
Errors: `400` (invalid mode).

### 8) PATCH `/sessions/{id}` — auth
Request: `{ "title": "New name" }` (1–80 chars)
Response `200`: `{ "ok": true, "title": "New name" }`
Errors: `400` (missing/too long), `403 {error:"invalid session"}`.

### 9) DELETE `/sessions/{id}` — auth
Response `200`: `{ "ok": true }` · `403` if not yours.

### 10) GET `/sessions/{id}/messages` — auth
Response `200`:
```json
{
  "turns": [
    {
      "messageID": "uuid",
      "question": "Hi today I feel stress",
      "status": "delivered",
      "reply": { "reply": "That sounds like a lot…", "escalated": false },
      "created_at": "2026-06-27T09:54:10Z"
    }
  ]
}
```
`status` is `"delivered"` or `"pending"` (experiment mode: the reply is still with
the counsellor — `reply` is `null`; show a waiting indicator and poll §11b).
When a turn was flagged as elevated suicide risk, its `reply` object also carries
`"suggestedTest": "suicide-risk-check"` (see §12) — render the same quiz link.
`403` if not yours.

### 11) GET `/sessions/{id}/analysis` — auth
Response `200`:
```json
{
  "title": "Hi today I feel stress",
  "messages": [
    { "question": "…", "emotion": "Stress", "confidence": 0.55, "escalated": false, "created_at": "…" }
  ],
  "summary": {
    "total": 6,
    "counts": { "Stress": 3, "Depression": 2, "Normal": 1 },
    "dominant": "Stress",
    "escalations": 0
  }
}
```

### 11b) GET `/sessions/{id}/pending` — auth · rate‑limited 40/min
Experiment mode only: poll this (~every 3 s) while any turn is awaiting review.
Response `200`:
```json
{ "messages": [
  { "messageID": "uuid", "status": "pending" },
  { "messageID": "uuid", "status": "delivered",
    "reply": "…counsellor-approved reply…", "emotion": "Stress",
    "confidence": 0.55, "escalated": false }
] }
```
Swap each waiting indicator for its reply when its entry turns `"delivered"`;
stop polling when nothing is `"pending"`. (The API never reveals whether the
counsellor approved the bot's draft or replaced it.) Delivered entries carry
`"suggestedTest"` exactly like §12 when the turn was flagged as elevated risk.

### 12) POST `/chat` — auth · rate‑limited 20/min
Request: `{ "sessionID": "uuid", "message": "text (≤2000 chars)" }`
Response `200` (normal `multi` session):
```json
{ "messageID": "uuid", "reply": "…bot reply…", "emotion": "Stress", "confidence": 0.55, "escalated": false }
```
Response `200` (**experiment session** — the reply is held for counsellor review;
show a waiting indicator and poll §11b):
```json
{ "messageID": "uuid", "status": "pending" }
```
`escalated:true` means a crisis response was returned instead of a normal reply.

**Elevated suicide risk:** when the turn escalated, the payload additionally
carries:
```json
{ "suggestedTest": "suicide-risk-check" }
```
Render it as a link into the Suicide Risk Check quiz —
`/resources#test=suicide-risk-check` in the web app (the Resources page
auto-opens that quiz from the hash). After submitting, the result shows the
counsellor/helpline block **first**, then the score (§18).
Errors: `400` (missing fields / message too long), `403` (invalid session),
`404` (chat deleted while the reply was generating).

### 13) POST `/chat/voice` — auth · rate‑limited 10/min · `multipart/form-data`
Form fields: `sessionID` (text), `audio` (file: wav/webm/mpeg/ogg, ≤10 MB).
Response `200`:
```json
{ "messageID": "uuid", "reply": "…", "emotion": "…", "confidence": 0.5, "escalated": false, "transcript": "the transcribed text" }
```
May also carry `"suggestedTest"` under the same rules as §12.
Errors: `400`, `403`, `413` (too large), `415` (unsupported type),
`422` (couldn't transcribe), `503` (voice not available on server).

### 14) GET `/api/resources` — auth
Guides & exercises whose content lives **in the app** (written into the DB by
`scripts/scrape_resources.py`); `external_url`/`source` are only the reference
citation shown at the bottom of the detail view.
Response `200`:
```json
{ "resources": [
  { "id": "uuid", "slug": "understanding-stress", "title": "Understanding Stress",
    "category": "Stress", "summary": "short blurb", "kind": "article",
    "external_url": "https://www.mind.org.uk/…", "source": "Mind UK",
    "image_url": null, "sort_order": 4 }
] }
```
Categories: `Calm Down Exercises`, `Stress`, `Anger`, `Relationships`,
`Crisis Support`.

### 15) GET `/api/resources/{id|slug}` — auth
Response `200`:
```json
{
  "id": "uuid", "slug": "understanding-stress", "title": "Understanding Stress",
  "category": "Stress", "summary": "…", "kind": "article",
  "info": "…full Info-tab text…",
  "external_url": "https://www.mind.org.uk/…", "source": "Mind UK",
  "image_url": null, "is_published": true, "sort_order": 4, "created_at": "…",
  "steps": [ { "step_order": 0, "title": "Know your signs", "content": "…" } ]
}
```
`404 { "error": "resource not found" }`. Accepts either the UUID `id` or the `slug`.
Show `info` as one tab and `steps` as the other ("How to do it" for the
Calm Down Exercises category, "Steps to overcome it" otherwise), with
`source` hyperlinked to `external_url` as the reference underneath.

### 16) GET `/api/tests` — auth
The self‑tests: Stress Level Test (PSS‑10), Self‑Esteem Test (Rosenberg),
Depression Test (PHQ‑9), Suicide Risk Check (adapted from the SWSPHN Clinical
Suicide Risk Screening Tool — 6 questions, bands Low / Medium / High /
Emergency; an "immediate or next‑24‑hours plan" answer always lands in
Emergency).
Response `200`:
```json
{ "tests": [
  { "id": "uuid", "slug": "depression-test", "title": "Depression Test",
    "description": "The PHQ-9 — …", "source": "Mental Health America",
    "reference": "https://screening.mhanational.org/screening-tools/depression/",
    "numQuestions": 9 }
] }
```

### 17) GET `/api/tests/{id|slug}` — auth
Response `200` (scoring bands stay server‑side):
```json
{
  "id": "uuid", "slug": "depression-test", "title": "Depression Test",
  "description": "…", "source": "…", "reference": "https://…",
  "questions": [
    { "text": "Little interest or pleasure in doing things",
      "options": [ { "label": "Not at all", "value": 0 },
                   { "label": "Several days", "value": 1 },
                   { "label": "More than half the days", "value": 2 },
                   { "label": "Nearly every day", "value": 3 } ] }
  ]
}
```
`404 { "error": "test not found" }`.

### 18) POST `/api/tests/{id}/submit` — auth
Request — one chosen **option index** per question, in order:
```json
{ "answers": [0, 2, 1, 0, 3, 1, 0, 2, 0] }
```
Response `200` (the attempt is stored server‑side in `test_created`):
```json
{
  "score": 9, "max": 27, "band": "Mild depression",
  "advice": "Your answers suggest mild symptoms. …",
  "alert": null
}
```
`alert` is a crisis‑contacts message (non‑null) when the depression test's
self‑harm question is answered above "Not at all", and **always** for the
Suicide Risk Check. Show it prominently and **before** the score/band —
helplines come first.
Errors: `400` (missing/invalid answers), `404` (unknown test).
Screens should display the standard disclaimer: results are a screening, not a
diagnosis.

### 19) GET `/health` — public
```json
{ "status": "ok", "ai_mode": "real",
  "models": { "chatbot": true, "classifier": true, "summarizer": true, "voice": false } }
```

---

## 6. Minimal Flutter client (Dart)

Uses the `http` package.

```dart
import 'dart:convert';
import 'package:http/http.dart' as http;

class ApiClient {
  ApiClient(this.baseUrl);
  final String baseUrl;
  String? token; // set after login

  Map<String, String> get _headers => {
        'Content-Type': 'application/json',
        if (token != null) 'Authorization': 'Bearer $token',
      };

  Future<Map<String, dynamic>> _post(String path, Map body) async {
    final r = await http.post(Uri.parse('$baseUrl$path'),
        headers: _headers, body: jsonEncode(body));
    final data = jsonDecode(r.body) as Map<String, dynamic>;
    if (r.statusCode == 401) throw Exception('Session expired — log in again');
    if (data['error'] != null) throw Exception(data['error']);
    return data;
  }

  Future<Map<String, dynamic>> _get(String path) async {
    final r = await http.get(Uri.parse('$baseUrl$path'), headers: _headers);
    final data = jsonDecode(r.body) as Map<String, dynamic>;
    if (r.statusCode == 401) throw Exception('Session expired — log in again');
    if (data['error'] != null) throw Exception(data['error']);
    return data;
  }

  // --- auth ---
  Future<Map<String, dynamic>> agreement() => _get('/agreements/active');
  Future<Map<String, dynamic>> register(String email, String pw) =>
      _post('/auth/register', {'email': email, 'password': pw, 'agree': true});
  Future<void> login(String email, String pw) async {
    final d = await _post('/auth/login', {'email': email, 'password': pw});
    token = d['token'] as String; // store securely
  }

  // --- sessions & chat ---
  Future<List> sessions() async => (await _get('/sessions'))['sessions'] as List;
  Future<Map<String, dynamic>> newSession([String title = 'New chat']) =>
      _post('/sessions', {'title': title});
  Future<List> messages(String id) async =>
      (await _get('/sessions/$id/messages'))['turns'] as List;
  Future<Map<String, dynamic>> sendMessage(String sessionId, String text) =>
      _post('/chat', {'sessionID': sessionId, 'message': text});

  // --- resources ---
  Future<List> resources() async =>
      (await _get('/api/resources'))['resources'] as List;
  Future<Map<String, dynamic>> resource(String idOrSlug) =>
      _get('/api/resources/$idOrSlug');

  // --- self-tests ---
  Future<List> tests() async => (await _get('/api/tests'))['tests'] as List;
  Future<Map<String, dynamic>> test(String idOrSlug) =>
      _get('/api/tests/$idOrSlug');
  Future<Map<String, dynamic>> submitTest(String id, List<int> answers) =>
      _post('/api/tests/$id/submit', {'answers': answers});
}
```

### Voice upload (multipart)
```dart
Future<Map<String, dynamic>> sendVoice(String sessionId, List<int> audioBytes) async {
  final req = http.MultipartRequest('POST', Uri.parse('$baseUrl/chat/voice'))
    ..headers['Authorization'] = 'Bearer $token'
    ..fields['sessionID'] = sessionId
    ..files.add(http.MultipartFile.fromBytes('audio', audioBytes,
        filename: 'voice.m4a')); // wav/webm/mpeg/ogg also accepted
  final res = await http.Response.fromStream(await req.send());
  return jsonDecode(res.body) as Map<String, dynamic>;
}
```

---

## 7. Important notes

- **Flutter mobile (Android/iOS): no CORS issue** — CORS is a browser rule, so
  native apps call the API directly.
- **Flutter Web: CORS applies.** The backend currently sets **no** CORS headers,
  so a web build will be blocked by the browser. If you need Flutter Web, add
  `flask-cors` on the server and allow your web origin. (Ask me and I'll wire it.)
- **Android cleartext HTTP:** `http://` (not https) is blocked by default on
  Android. For local dev add `android:usesCleartextTraffic="true"` (or a
  network‑security‑config) in `AndroidManifest.xml`.
- **Email verification:** after `register` with `needsVerification:true`, tell the
  user to check their inbox; they can only `login` after confirming.
- **Rate limits:** `login`/`register` 10/min, `chat` 20/min, `voice` 10/min —
  handle `429` gracefully.
- **Roles:** `role` is `"user"`, `"staff"`, or `"admin"`. Staff/admin accounts
  get the web admin site at `/admin` — a **web-only** surface; the Flutter
  client only needs `role` to know the user type. Its API (all under
  `/api/admin/*`, staff-guarded): `stats`, `emotions`, `sessions`,
  `sessions/{id}`, `sessions/{id}/export` (JSON download),
  `messages/{id}/feedback` (staff rating 1–5 + feedback on a bot reply),
  `alerts/suicide?period=today|week|month` (escalation counts + affected users
  ranked highest-first, each with whether they completed the Suicide Risk Check
  quiz in that window), `users` (all registered users with profile info +
  chat aggregates), `users/{id}/report` (POST — generates the session-analysis
  report over the user's recent chats with the summarizer model; rate-limited
  6/min) + `users/{id}/report.pdf` (GET — downloads the last generated report;
  404 until a report was generated), `live-sessions` + `sessions/{id}/rename`
  + `review/{messageID}` (experiment-mode live counselling: connect to a
  user's chat, approve/edit pending drafts — an edit records the draft as
  rejected), and the admin-only `staff` account management. **Admins create
  staff accounts by email** on the dashboard. Only the first admin is made via
  SQL: `update public.profiles set role = 'admin' where email = '…';`
- **Crisis email:** when a turn escalates, the server can email the counselling
  information to the user's registered address (toggle `crisis_email.enabled`
  in `config.yaml`; SMTP credentials in `.env`). At most one
  email per user per cooldown window (default 60 min). No API surface — it is
  a server-side side effect of §12's `escalated:true`.
