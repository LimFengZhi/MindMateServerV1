/* ===========================================================================
   admin.js — the staff dashboard page. Uses common.js + review_helpers.js
   (loaded before this file).
   Views: Overview · Emotion Analysis · User Sessions (user -> chat -> review)
   · Testing (card picker -> opens its own page) · Staff (admin only).
   The page is only a shell: all data comes from guarded endpoints.
   =========================================================================== */

const VIEWS = ["overview", "emotions", "sessions", "testing", "staff"];

let currentView = "overview";
const loadedViews = new Set();

let sessionsCache = [];       // all sessions (for the sessions view)
let selectedUserEmail = null; // drill-down state
let staffCache = [];          // staff accounts (admin only)

if (requireAuth()) initAdmin();

async function initAdmin() {
  const me = await requireStaff();
  if (!me) return;
  if (me.role === "admin") $("nav-staff").classList.remove("hidden");
  loadView("overview");
}

/* ===================== VIEW SWITCHING ===================== */
function switchView(name) {
  currentView = name;
  for (const v of VIEWS) {
    $(`view-${v}`).classList.toggle("hidden", v !== name);
    const nav = $(`nav-${v}`);
    if (nav) nav.classList.toggle("active", v === name);
  }
  loadView(name);
}

// Sessions always refetch (review counts change); other views fetch once.
function loadView(name) {
  if (name === "sessions") { loadSessions(); return; }
  if (loadedViews.has(name)) return;
  loadedViews.add(name);
  if (name === "overview") loadStats();
  if (name === "emotions") loadEmotions();
  if (name === "staff") loadStaff();
}

/* ===================== OVERVIEW ===================== */
const STAT_LABELS = [
  ["users", "Registered users"],
  ["sessions", "Chat sessions"],
  ["messages", "Messages"],
  ["escalations", "Crisis escalations"],
  ["testsTaken", "Self-tests taken"],
  ["resources", "Resources"],
];

async function loadStats() {
  const stats = await api("/api/admin/stats");
  if (stats.error) { showErrorPlaceholder($("adminStats"), stats.error); return; }
  $("adminStats").innerHTML = `
    <div class="cards">
      ${STAT_LABELS.map(([key, label]) => `
        <div class="stat-card">
          <div class="stat-label">${escapeHTML(label)}</div>
          <div class="stat-value ${key === "escalations" && stats[key] ? "danger" : ""}">
            ${stats[key] ?? 0}</div>
        </div>`).join("")}
    </div>`;
}

/* ===================== EMOTION ANALYSIS (all users) ===================== */
async function loadEmotions() {
  const r = await api("/api/admin/emotions");
  if (r.error) { showErrorPlaceholder($("emotionBody"), r.error); return; }
  if (!r.total) { showPlaceholder($("emotionBody"), "No messages yet."); return; }

  const entries = Object.entries(r.counts || {}).sort((a, b) => b[1] - a[1]);
  const max = entries.length ? entries[0][1] : 1;
  const bars = entries.map(([emotion, count]) => `
    <div class="bar-row">
      <div class="bar-label">${escapeHTML(emotion)}</div>
      <div class="bar-track"><div class="bar-fill" style="width:${Math.round((count / max) * 100)}%"></div></div>
      <div class="bar-count">${count}</div>
    </div>`).join("");

  $("emotionBody").innerHTML = `
    <div class="cards">
      <div class="stat-card">
        <div class="stat-label">Messages analysed</div>
        <div class="stat-value">${r.total}</div>
      </div>
      <div class="stat-card">
        <div class="stat-label">Dominant emotion</div>
        <div class="stat-value">${escapeHTML(r.dominant || "—")}</div>
      </div>
      <div class="stat-card">
        <div class="stat-label">Escalations</div>
        <div class="stat-value ${r.escalations ? "danger" : ""}">${r.escalations}</div>
      </div>
    </div>
    <div class="section-card">
      <h3>Emotion distribution</h3>
      ${bars}
    </div>`;
}

/* ===================== USER SESSIONS (user -> chat -> review) ============= */
async function loadSessions() {
  const r = await api("/api/admin/sessions");
  if (r.error) { showErrorPlaceholder($("sessionsBody"), r.error); return; }
  sessionsCache = r.sessions || [];
  renderUsersList();
}

// Level 1: one row per user, aggregated from their sessions.
function renderUsersList() {
  selectedUserEmail = null;
  if (!sessionsCache.length) {
    showPlaceholder($("sessionsBody"), "No sessions yet.");
    return;
  }
  const users = [];
  for (const s of sessionsCache) {
    let u = users.find((x) => x.email === s.email);
    if (!u) { u = { email: s.email, sessions: 0, messages: 0, reviewed: 0 }; users.push(u); }
    u.sessions += 1;
    u.messages += s.messageCount;
    u.reviewed += s.reviewedCount;
  }
  $("sessionsBody").innerHTML = users.map((u, i) => `
    <div class="sess-row" onclick="openUser(${i})">
      <div class="sess-main">
        <div class="sess-title">👤 ${escapeHTML(u.email)}</div>
        <div class="sess-sub">${u.sessions} chats · ${u.messages} messages
          · ${u.reviewed} replies reviewed</div>
      </div>
      <span class="sess-chev">›</span>
    </div>`).join("");
  window._usersCache = users;
}

function openUser(index) {
  const u = (window._usersCache || [])[index];
  if (u) renderUserSessions(u.email);
}

// Level 2: that user's chats, with review progress on each.
function renderUserSessions(email) {
  selectedUserEmail = email;
  const mine = sessionsCache.filter((s) => s.email === email);
  const rows = mine.map((s) => `
    <div class="sess-row" onclick="openReview('${s.sessionID}')">
      <div class="sess-main">
        <div class="sess-title">${escapeHTML(s.title)}</div>
        <div class="sess-sub">${s.messageCount} messages
          · ${escapeHTML(fmtDate(s.createdAt))}</div>
      </div>
      <span class="sess-badge ${s.reviewedCount ? "done" : ""}">
        ${s.reviewedCount}/${s.messageCount} reviewed</span>
      <span class="sess-chev">›</span>
    </div>`).join("") || placeholderHTML("No chats for this user.");
  $("sessionsBody").innerHTML = `
    <div class="back-link" onclick="renderUsersList()">← All users</div>
    <div class="review-head"><div class="sess-title">👤 ${escapeHTML(email)}</div></div>
    ${rows}`;
}

// Level 3: the transcript, with rate/feedback controls per reply.
async function openReview(sessionID) {
  showPlaceholder($("sessionsBody"), "Loading transcript…");
  const r = await api(`/api/admin/sessions/${sessionID}`);
  if (r.error) { showErrorPlaceholder($("sessionsBody"), r.error); return; }

  const turns = (r.messages || []).map(reviewTurnHTML).join("")
    || placeholderHTML("No messages in this session.");
  $("sessionsBody").innerHTML = `
    <div class="back-link" onclick="renderUserSessions(selectedUserEmail)">
      ← Back to ${escapeHTML(r.session.email)}</div>
    <div class="review-head">
      <div>
        <div class="sess-title">${escapeHTML(r.session.title)}</div>
        <div class="sess-sub">${escapeHTML(r.session.email)}
          · ${escapeHTML(fmtDate(r.session.createdAt))}</div>
      </div>
      <button class="btn" onclick="exportSession('${r.session.sessionID}')">Export JSON</button>
    </div>
    ${turns}`;
}

function reviewTurnHTML(m) {
  return `
    <div class="turn">
      <div class="turn-q"><strong>User:</strong> ${escapeHTML(m.question)}</div>
      <div class="turn-a"><strong>Bot:</strong> ${escapeHTML(m.reply || "(no reply)")}</div>
      ${turnMetaHTML(m)}
      ${feedbackControlsHTML(m)}
    </div>`;
}

/* ===================== STAFF ACCOUNTS (admin only) ===================== */
async function loadStaff() {
  const r = await api("/api/admin/staff");
  if (r.error) { showErrorPlaceholder($("staffList"), r.error); return; }
  staffCache = r.staff || [];
  renderStaff();
}

function renderStaff() {
  if (!staffCache.length) {
    showPlaceholder($("staffList"), "No staff accounts yet.");
    return;
  }
  $("staffList").innerHTML = staffCache.map((p, i) => `
    <div class="staff-row">
      <div class="staff-email">${escapeHTML(p.email || "")}</div>
      <span class="role-pill">${escapeHTML(p.role)}</span>
      ${p.role === "staff"
        ? `<button class="btn btn-ghost" onclick="removeStaff(${i})">Remove</button>`
        : ""}
    </div>`).join("");
}

function setStaffMsg(text, kind = "") {
  const el = $("staffMsg");
  el.textContent = text;
  el.className = "auth-msg" + (kind ? " " + kind : "");
}

async function createStaff() {
  const email = $("staffEmail").value.trim().toLowerCase();
  const password = $("staffPassword").value;
  if (!email) { setStaffMsg("Please enter an email address.", "error"); return; }
  setStaffMsg("");

  const r = await api("/api/admin/staff", {
    method: "POST",
    body: JSON.stringify({ email, password }),
  });
  if (r.error) { setStaffMsg(r.error, "error"); return; }

  setStaffMsg(r.promoted
    ? "That email already had an account — it is now staff."
    : "Staff account created. Share the password with them so they can log in.",
    "ok");
  $("staffEmail").value = "";
  $("staffPassword").value = "";
  loadStaff();
}

async function removeStaff(index) {
  const p = staffCache[index];
  if (!p) return;
  if (!confirm(`Remove staff access for ${p.email}? They keep their normal account.`)) return;
  const r = await api(`/api/admin/staff/${p.id}`, { method: "DELETE" });
  if (r.error) { setStaffMsg(r.error, "error"); return; }
  setStaffMsg("Staff access removed.", "ok");
  loadStaff();
}
