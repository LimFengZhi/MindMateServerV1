/* ===========================================================================
   admin.js — the staff dashboard page. Uses common.js + review_helpers.js
   (loaded before this file).
   Views: Overview · Emotion Analysis · User Sessions (user -> chat -> review)
   · Testing (assessment editor) · Staff (admin only) · Resources Editing
   · Dataset Management · Test Analysis · System Prompts · Agreements.
   (Live Counselling is its own page: /admin/live.)
   The page is only a shell: all data comes from guarded endpoints.
   =========================================================================== */

const VIEWS = ["overview", "alerts", "testchat", "emotions", "sessions",
               "staff", "editing", "dataset", "test_analysis"];

let currentView = "overview";
const loadedViews = new Set();

let sessionsCache = [];       // all sessions (for the sessions view)
let selectedUserEmail = null; // drill-down state
let staffCache = [];          // staff accounts (admin only)
let resourcesCache = [];      // resources editor
let testsCache = [];          // assessments editor

if (requireAuth()) initAdmin();

async function initAdmin() {
  const me = await requireStaff();
  if (!me) return;
  if (me.role === "admin") $("nav-staff").classList.remove("hidden");
  loadView("overview");
}

/* ===================== SHARED HELPERS ===================== */
// Status line under a form/button ("auth-msg" styling; kind: "" | "ok" | "error").
function setMsg(el, text, kind = "") {
  el.textContent = text;
  el.className = "auth-msg" + (kind ? " " + kind : "");
}

function showApiError(container, err) {
  container.innerHTML = `<p class="auth-msg error">${escapeHTML(err)}</p>`;
}

// The save/delete pattern every editor uses: busy text -> request -> error or
// ok text, then (optionally) run a follow-up after `delay` ms.
async function submitAndRefresh(msgEl, busy, request, okText, after, delay = 800) {
  setMsg(msgEl, busy);
  const r = await request();
  if (r.error) { setMsg(msgEl, "Error: " + r.error, "error"); return; }
  setMsg(msgEl, okText, "ok");
  if (after) setTimeout(after, delay);
}

// List <-> editor swap used by the Resources and Testing views.
function toggleEditor(listId, formId, open) {
  $(listId).classList.toggle("hidden", open);
  $(formId).classList.toggle("hidden", !open);
}

/* ---- Collapsible sidebar (like the user app's) ---- */
function toggleAdminNav() {
  const collapsed = document.querySelector(".admin-wrap").classList.toggle("nav-collapsed");
  localStorage.setItem("adminNavCollapsed", collapsed ? "1" : "");
}
// Restore the saved state before first paint (script loads at end of body).
if (localStorage.getItem("adminNavCollapsed") === "1") {
  document.querySelector(".admin-wrap")?.classList.add("nav-collapsed");
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

// Sessions/resources/dataset/editors always refetch; overview/emotions/staff
// fetch once (loadedViews).
function loadView(name) {
  if (name === "sessions") { loadSessions(); return; }
  if (name === "editing") { switchEditTab(currentEditTab); return; }
  if (name === "dataset") { switchDatasetTab("chatbot"); return; }
  // Self-Tests hosts BOTH the analytics and the assessments editor (the
  // former separate "Testing" tab was merged into it).
  if (name === "test_analysis") { loadTestAnalytics(); loadTestingData(); }
  if (name === "testchat") { renderBenchModeChips(); renderBenchTurns(); loadBenchSessions(); return; }
  if (name === "overview") { loadStats(); loadActivity(); return; }
  if (name === "alerts") { loadAlerts(); return; }

  if (loadedViews.has(name)) return;
  loadedViews.add(name);
  if (name === "emotions") loadEmotions();
  if (name === "staff") loadStaff();
}

/* ---- Editing group: resources / prompts / agreements as sub-tabs ---- */
const EDIT_TABS = ["resources_edit", "prompts", "agreements"];
let currentEditTab = "resources_edit";

function switchEditTab(name) {
  currentEditTab = name;
  for (const t of EDIT_TABS) {
    $(`sub-view-${t}`).classList.toggle("hidden", t !== name);
    $(`etab-${t}`).classList.toggle("active", t === name);
  }
  if (name === "resources_edit") loadResourcesData();
  if (name === "prompts") loadPromptsData();
  if (name === "agreements") loadAgreementsData();
}

/* ===================== OVERVIEW ===================== */
const STAT_LABELS = [
  ["users", "Registered users"],
  ["sessions", "Chat sessions"],
  ["messages", "Messages"],
  ["escalations", "Crisis escalations"],
  ["pendingReviews", "Pending reviews"],
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

/* ---- Dashboard graphs: chatbot usage + escalations per day (14 days).
   Same-origin CSS bars only — the CSP forbids external chart libraries. ---- */
async function loadActivity() {
  const el = $("activityCharts");
  const r = await api("/api/admin/activity");
  if (r.error) { showErrorPlaceholder(el, r.error); return; }
  const days = r.days || [];
  if (!days.length) { showPlaceholder(el, "No chat activity yet."); return; }

  const chart = (title, key, fillClass) => {
    const max = Math.max(1, ...days.map((d) => d[key]));
    return `
      <div class="section-card">
        <h3 class="accent">${escapeHTML(title)}</h3>
        <div class="day-chart">
          ${days.map((d) => `
            <div class="day-col" title="${escapeHTML(d.date)}: ${d[key]}">
              <div class="day-count">${d[key] || ""}</div>
              <div class="day-bar-track">
                <div class="day-bar ${fillClass}" style="height:${Math.round((d[key] / max) * 100)}%"></div>
              </div>
              <div class="day-label">${escapeHTML(d.date.slice(5))}</div>
            </div>`).join("")}
        </div>
      </div>`;
  };

  el.innerHTML =
    chart("Chatbot Usage — messages per day", "messages", "fill-blue") +
    chart("Crisis Escalations per day", "escalations", "fill-red");
}

/* ===================== TEST CHAT (comparison bench) =====================
   Comparison runs live in bench SESSIONS (rename/delete like user chats).
   Each turn = one prompt answered by every variant; variants keep their own
   conversation history across the session's turns. Ratings/feedback save per
   variant to bench_result. "Normal - chat as a user" links to the test bench
   page (real sessions + messages feedback). */
const BENCH_HINTS = {
  single_vs_multi: "Same Gemma 2 weights AND the same prompt rules (the " +
    "'single' prompt = composed prompt without its summary/memory parts): " +
    "the model alone VS the full multi-agent pipeline (diagnosis, tone, " +
    "summary memory, guardrails).",
  models3: "The same message answered by all three fine-tuned study models " +
    "under an identical system prompt. First run lazy-loads Llama 3.2 and " +
    "Qwen3 - it can take a minute.",
};
let currentBenchMode = "single_vs_multi";
let benchSessions = [];
let benchSessionID = null;      // null = blank comparison (created on first run)
let benchTurns = [];            // rendered turns of the open session
let benchRenamingID = null;

function switchBenchMode(mode) {
  // Picking a mode starts a BLANK comparison in that mode (an open session's
  // mode is fixed - its runs must stay comparable).
  currentBenchMode = mode;
  benchSessionID = null;
  benchTurns = [];
  renderBenchModeChips();
  renderBenchSessionList();
  renderBenchTurns();
}

function renderBenchModeChips() {
  for (const m of Object.keys(BENCH_HINTS)) {
    $(`ttab-${m}`).classList.toggle("active", m === currentBenchMode);
  }
  $("benchModeHint").textContent = BENCH_HINTS[currentBenchMode];
}

function newBenchSession() {
  benchSessionID = null;
  benchTurns = [];
  renderBenchSessionList();
  renderBenchTurns();
  setMsg($("benchMsg"), "");
}

async function loadBenchSessions() {
  const el = $("benchSessionList");
  const r = await api("/api/admin/bench/sessions");
  if (r.error) { showApiError(el, r.error); return; }
  if (!r.available) {
    el.innerHTML = `<p class="placeholder">${escapeHTML(r.note || "Unavailable.")}</p>`;
    return;
  }
  benchSessions = r.sessions || [];
  renderBenchSessionList();
}

const BENCH_MODE_TAGS = { single_vs_multi: "single vs multi", models3: "3 models" };

function renderBenchSessionList() {
  const el = $("benchSessionList");
  if (!benchSessions.length) {
    el.innerHTML = `<p class="placeholder">No comparison chats yet.</p>`;
    return;
  }
  el.innerHTML = benchSessions.map((bs) =>
    bs.id === benchRenamingID ? `
    <div class="session-item renaming" onclick="event.stopPropagation()">
      <input id="benchRenameInput" class="rename-input" maxlength="80"
        value="${escapeHTML(bs.title)}"
        onkeydown="if(event.key==='Enter'){event.preventDefault(); saveBenchRename('${bs.id}');}
                   else if(event.key==='Escape'){cancelBenchRename();}" />
      <div class="s-actions">
        <button onclick="event.stopPropagation(); saveBenchRename('${bs.id}')">Save</button>
        <button onclick="event.stopPropagation(); cancelBenchRename()">Cancel</button>
      </div>
    </div>` : `
    <div class="session-item ${bs.id === benchSessionID ? "active" : ""}"
         onclick="openBenchSession('${bs.id}')">
      <div class="s-title">${escapeHTML(bs.title)}</div>
      <div class="s-date">${escapeHTML(fmtDate(bs.created_at))} -
        <span class="s-supervised">${escapeHTML(BENCH_MODE_TAGS[bs.mode] || bs.mode)}</span></div>
      <div class="s-actions">
        <button onclick="event.stopPropagation(); startBenchRename('${bs.id}')">Rename</button>
        <button onclick="event.stopPropagation(); deleteBenchSession('${bs.id}')">Delete</button>
      </div>
    </div>`).join("");
  if (benchRenamingID) {
    const input = $("benchRenameInput");
    if (input) { input.focus(); input.select(); }
  }
}

function startBenchRename(id) { benchRenamingID = id; renderBenchSessionList(); }
function cancelBenchRename() { benchRenamingID = null; renderBenchSessionList(); }

async function saveBenchRename(id) {
  const input = $("benchRenameInput");
  const title = input ? input.value.trim() : "";
  if (!title) { cancelBenchRename(); return; }
  const r = await api(`/api/admin/bench/sessions/${id}/rename`, {
    method: "POST", body: JSON.stringify({ title }),
  });
  if (r.error) { setMsg($("benchMsg"), r.error, "error"); return; }
  const bs = benchSessions.find((x) => x.id === id);
  if (bs) bs.title = r.title;
  benchRenamingID = null;
  renderBenchSessionList();
}

async function deleteBenchSession(id) {
  const bs = benchSessions.find((x) => x.id === id);
  if (!confirm(`Delete "${bs ? bs.title : "this comparison"}" and all its runs?`)) return;
  const r = await api(`/api/admin/bench/sessions/${id}`, { method: "DELETE" });
  if (r.error) { setMsg($("benchMsg"), r.error, "error"); return; }
  benchSessions = benchSessions.filter((x) => x.id !== id);
  if (id === benchSessionID) newBenchSession();
  else renderBenchSessionList();
}

async function openBenchSession(id) {
  const r = await api(`/api/admin/bench/sessions/${id}`);
  if (r.error) { setMsg($("benchMsg"), r.error, "error"); return; }
  benchSessionID = id;
  currentBenchMode = r.session.mode;
  benchTurns = r.turns || [];
  renderBenchModeChips();
  renderBenchSessionList();
  renderBenchTurns();
  setMsg($("benchMsg"), "");
}

function renderBenchTurns() {
  const el = $("benchTurns");
  if (!benchTurns.length) {
    el.innerHTML = `
      <div class="welcome-msg">
        <h2>${benchSessionID ? "No runs yet" : "New comparison"}</h2>
        <p>Type a message below - every variant answers it, side by side.</p>
      </div>`;
    return;
  }
  el.innerHTML = benchTurns.map((turn, ti) => `
    <div class="bench-turn">
      <div class="msg msg-user"><div class="bubble">${escapeHTML(turn.prompt)}</div></div>
      <div class="bench-grid">
        ${turn.results.map((res, vi) => benchCardHTML(res, ti, vi)).join("")}
      </div>
    </div>`).join("");
  el.scrollTop = el.scrollHeight;
}

function benchCardHTML(r, ti, vi) {
  const body = r.error
    ? `<p class="bench-error">! ${escapeHTML(r.error)}</p>`
    : `<p class="bench-reply">${escapeHTML(r.reply || "")}</p>`;
  const meta = r.latencyMs != null
    ? `<span class="bench-latency">${(r.latencyMs / 1000).toFixed(1)}s</span>` : "";
  const rated = r.rating || 0;
  const controls = (r.benchID && !r.error) ? `
      <div class="bench-stars" id="stars-t${ti}-v${vi}">
        ${[1, 2, 3, 4, 5].map((n) => `
          <button class="star-btn ${n <= rated ? "on" : ""}"
            onclick="rateBench(${ti}, ${vi}, ${n})">${n <= rated ? "\u2605" : "\u2606"}</button>`).join("")}
      </div>
      <textarea id="bench-fb-t${ti}-v${vi}" class="dash-textarea" style="min-height:48px;"
        placeholder="Feedback on this reply (optional)...">${escapeHTML(r.feedback || "")}</textarea>
      <div class="flex-between">
        <p id="bench-msg-t${ti}-v${vi}" class="auth-msg no-margin"></p>
        <button class="btn btn-ghost small" onclick="saveBenchFeedback(${ti}, ${vi})">Save</button>
      </div>` : "";
  return `
    <div class="bench-card">
      <div class="bench-head">
        <span class="bench-label">${escapeHTML(r.label || r.variant)}</span>${meta}
      </div>
      ${body}
      ${controls}
    </div>`;
}

function rateBench(ti, vi, n) {
  benchTurns[ti].results[vi]._rating = n;
  $(`stars-t${ti}-v${vi}`).querySelectorAll(".star-btn").forEach((b, idx) => {
    b.textContent = idx < n ? "\u2605" : "\u2606";
    b.classList.toggle("on", idx < n);
  });
}

async function saveBenchFeedback(ti, vi) {
  const r = benchTurns[ti].results[vi];
  const rating = r._rating || r.rating || null;
  const feedback = $(`bench-fb-t${ti}-v${vi}`).value.trim() || null;
  const msgEl = $(`bench-msg-t${ti}-v${vi}`);
  if (!rating && !feedback) { setMsg(msgEl, "Pick a rating or write feedback.", "error"); return; }
  setMsg(msgEl, "Saving...");
  const res = await api(`/api/admin/bench/${r.benchID}/feedback`, {
    method: "POST", body: JSON.stringify({ rating, feedback }),
  });
  if (res.error) { setMsg(msgEl, res.error, "error"); return; }
  r.rating = res.rating; r.feedback = res.feedback;
  setMsg(msgEl, "Saved", "ok");
}

async function runBench() {
  const message = $("benchMessage").value.trim();
  if (!message) { setMsg($("benchMsg"), "Type a test message first.", "error"); return; }
  const btn = $("benchRunBtn");
  btn.disabled = true;
  btn.textContent = currentBenchMode === "models3" ? "Running... (models may load)" : "Running...";
  setMsg($("benchMsg"), "");

  // Session created lazily on the first run - like the user chat. If the
  // bench tables are missing, fall back to a sessionless one-shot run.
  if (!benchSessionID) {
    const cs = await api("/api/admin/bench/sessions", {
      method: "POST", body: JSON.stringify({ mode: currentBenchMode }),
    });
    if (cs.sessionID) {
      benchSessionID = cs.sessionID;
      benchSessions.unshift({ id: cs.sessionID, title: cs.title,
                              mode: cs.mode, created_at: cs.createdAt });
      renderBenchSessionList();
    } else if (cs.error) {
      setMsg($("benchMsg"), cs.error, "error");
    }
  }

  const r = await api("/api/admin/bench/run", {
    method: "POST",
    body: JSON.stringify({ mode: currentBenchMode, message,
                           sessionID: benchSessionID }),
  });
  btn.disabled = false;
  btn.textContent = "\u25B6 Run";
  if (r.error) { setMsg($("benchMsg"), r.error, "error"); return; }

  benchTurns.push({ runID: r.runID, prompt: message, results: r.results || [] });
  renderBenchTurns();
  $("benchMessage").value = "";
  if (!r.persisted) setMsg($("benchMsg"), r.note || "Results not saved.", "error");
  if (r.title) {   // first turn auto-named the comparison chat
    const bs = benchSessions.find((x) => x.id === benchSessionID);
    if (bs) { bs.title = r.title; renderBenchSessionList(); }
  }
}

/* ===================== EMOTION ANALYSIS (all users) ===================== */
async function loadEmotions() {
  const r = await api("/api/admin/emotions");
  if (r.error) { showErrorPlaceholder($("emotionBody"), r.error); return; }
  if (!r.total) { showPlaceholder($("emotionBody"), "No messages yet."); return; }

  const bars = countBarsHTML(r.counts);

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

/* ===================== SUICIDE ALERT ===================== */
let currentAlertPeriod = "today";

function switchAlertPeriod(period) {
  currentAlertPeriod = period;
  for (const p of ["today", "week", "month"]) {
    $(`ptab-${p}`).classList.toggle("active", p === period);
  }
  loadAlerts();
}

async function loadAlerts() {
  const el = $("alertsBody");
  showPlaceholder(el, "Loading…");
  const r = await api(`/api/admin/alerts/suicide?period=${currentAlertPeriod}`);
  if (r.error) { showErrorPlaceholder(el, r.error); return; }

  const cards = `
    <div class="cards">
      <div class="stat-card">
        <div class="stat-label">Crisis escalations</div>
        <div class="stat-value ${r.totalEscalations ? "danger" : ""}">${r.totalEscalations}</div>
      </div>
      <div class="stat-card">
        <div class="stat-label">Users affected</div>
        <div class="stat-value">${r.usersAffected}</div>
      </div>
      <div class="stat-card">
        <div class="stat-label">Did the Suicide Risk Check</div>
        <div class="stat-value">${r.quizCompleted}/${r.usersAffected}</div>
      </div>
    </div>`;

  const rows = (r.users || []).map((u) => {
    const quiz = u.quizDone
      ? `<span class="reviewed">✓ done — ${escapeHTML(u.quizBand || "?")}
          (${u.quizScore ?? "?"})</span>`
      : '<span class="not-reviewed">✗ not taken</span>';
    return `
      <div class="sess-row">
        <div class="sess-main">
          <div class="sess-title">👤 ${escapeHTML(u.email)}</div>
          <div class="sess-sub">${u.phone ? "📞 " + escapeHTML(u.phone) + " · " : ""}
            last escalation ${escapeHTML(fmtDate(u.lastEscalation))}
            · quiz: ${quiz}</div>
        </div>
        <span class="sess-badge ${u.escalations ? "" : "done"}">
          ${u.escalations} escalation${u.escalations === 1 ? "" : "s"}</span>
      </div>`;
  }).join("") || placeholderHTML("No crisis escalations in this period. 🎉");

  el.innerHTML = cards + `
    <div class="section-card">
      <h3 class="accent">Users with escalations — highest first</h3>
      ${rows}
    </div>`;
}

/* ===================== USER SESSIONS (user info -> chat -> review) ======== */
let usersOverview = [];   // /api/admin/users — all users with info

async function loadSessions() {
  const [r, u] = await Promise.all([
    api("/api/admin/sessions"), api("/api/admin/users"),
  ]);
  if (r.error) { showErrorPlaceholder($("sessionsBody"), r.error); return; }
  sessionsCache = r.sessions || [];
  usersOverview = u.error ? [] : (u.users || []);
  renderUsersList();
}

// Level 1: one row per registered user, with their profile info, chats
// drill-down, and the session-analysis report generator.
function renderUsersList() {
  selectedUserEmail = null;
  if (!usersOverview.length) {
    showPlaceholder($("sessionsBody"), "No registered users yet.");
    return;
  }
  $("sessionsBody").innerHTML = usersOverview.map((u, i) => `
    <div class="sess-row">
      <div class="sess-main" onclick="openUser(${i})">
        <div class="sess-title">👤 ${escapeHTML(u.email)}
          ${u.role !== "user" ? `<span class="tag">${escapeHTML(u.role)}</span>` : ""}</div>
        <div class="sess-sub">${u.phone ? "📞 " + escapeHTML(u.phone) + " · " : ""}
          joined ${escapeHTML(fmtDate(u.joinedAt))}
          · ${u.sessions} chats · ${u.messages} messages
          ${u.escalations ? `· <span class="tag escalated">${u.escalations} escalations</span>` : ""}</div>
      </div>
      <button class="btn small" onclick="generateUserReport(${i}); event.stopPropagation();">
        📄 Report</button>
      <span class="sess-chev" onclick="openUser(${i})">›</span>
    </div>`).join("");
}

function openUser(index) {
  const u = usersOverview[index];
  if (u) renderUserSessions(u.email);
}

/* ---- Session-analysis report (generated ONLY on click; summarizer model +
   the 'session_analysis' DB prompt; PDF downloads the cached result) ---- */
async function generateUserReport(index) {
  const u = usersOverview[index];
  if (!u) return;
  showPlaceholder($("sessionsBody"),
    `Generating the session analysis for ${u.email}… (the summarizer model is writing)`);
  const r = await api(`/api/admin/users/${u.userID}/report`, { method: "POST" });
  if (r.error) { showErrorPlaceholder($("sessionsBody"), r.error); return; }
  renderUserReport(r.report);
}

function renderUserReport(rep) {
  const sessions = (rep.sessions || []).map((s) => {
    const emotions = Object.entries(s.emotions || {})
      .map(([k, v]) => `${escapeHTML(k)} ×${v}`).join(", ");
    return `
      <div class="sess-row">
        <div class="sess-main">
          <div class="sess-title">${escapeHTML(s.title)}</div>
          <div class="sess-sub">${escapeHTML(fmtDate(s.createdAt))}
            · ${s.messageCount} messages
            ${s.escalations ? `· <span class="tag escalated">${s.escalations} escalations</span>` : ""}
            ${emotions ? "· " + emotions : ""}</div>
        </div>
      </div>`;
  }).join("") || placeholderHTML("This user has no chat sessions yet.");

  $("sessionsBody").innerHTML = `
    <div class="back-link" onclick="renderUsersList()">← All users</div>
    <div class="review-head">
      <div>
        <div class="sess-title">📄 Session analysis — ${escapeHTML(rep.user.email)}</div>
        <div class="sess-sub">${rep.sessionCount} recent session(s)
          · generated ${escapeHTML(fmtDate(rep.generatedAt))}</div>
      </div>
      <button class="btn btn-primary" onclick="downloadUserReport('${rep.user.userID}')">
        ⬇ Download PDF</button>
    </div>
    <div class="section-card">
      <h3 class="accent">Analysis</h3>
      <p style="white-space: pre-wrap; margin: 0;">${escapeHTML(rep.analysis || "")}</p>
    </div>
    <div class="section-card">
      <h3 class="accent">Sessions covered</h3>
      ${sessions}
    </div>`;
}

// The PDF needs the auth header, so fetch -> blob (same as exportSession).
async function downloadUserReport(userID) {
  const res = await fetch(`/api/admin/users/${userID}/report.pdf`, {
    headers: { Authorization: "Bearer " + getToken() },
  });
  if (!res.ok) { alert(`Download failed (${res.status})`); return; }
  const url = URL.createObjectURL(await res.blob());
  const a = document.createElement("a");
  a.href = url;
  a.download = `mindmate_report_${userID}.pdf`;
  a.click();
  URL.revokeObjectURL(url);
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
  let replyLine;
  if (m.status === "pending") {
    replyLine = '<div class="turn-a"><em>(awaiting counsellor review)</em></div>';
  } else {
    replyLine = `<div class="turn-a"><strong>Bot:</strong> ${escapeHTML(m.reply || "(no reply)")}</div>`;
    if (m.status === "rejected" && m.draft) {
      replyLine += `<div class="turn-rejected">Rejected bot draft: ${escapeHTML(m.draft)}</div>`;
    }
  }
  return `
    <div class="turn">
      <div class="turn-q"><strong>User:</strong> ${escapeHTML(m.question)}</div>
      ${replyLine}
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
  setMsg($("staffMsg"), text, kind);
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

/* ===================== DATASET MANAGEMENT ===================== */
// Both datasets share the same page shell; only the heading and the way one
// row renders differ.
const DATASETS = {
  chatbot: {
    page: 1,
    loadingTitle: "Chat Bot Dataset",
    heading: "Chat Bot Training Data",
    rowHTML: (item) => `
      <div class="sess-row data-row stacked">
        <div class="data-label">Instruction</div>
        <div class="data-instruction">${escapeHTML(item.instruction || "")}</div>
        <div class="data-label">User Input</div>
        <div class="data-input">"${escapeHTML(item.input || "")}"</div>
        <div class="data-label">Bot Output</div>
        <div class="data-output">${escapeHTML(item.output || "")}</div>
      </div>`,
  },
  classifier: {
    page: 1,
    loadingTitle: "Classifier Dataset",
    heading: "Classifier Validation Samples",
    rowHTML: (item) => `
      <div class="sess-row data-row">
        <div class="sess-main">
          <div class="sess-title data-statement">"${escapeHTML(item.statement || "")}"</div>
          <div class="sess-sub data-status-line">
            <span>Expected Classification:</span>
            <strong>${escapeHTML(item.status || "")}</strong>
            <span class="role-pill data-rowid">Row ID: ${item["Unnamed: 0"] ?? "N/A"}</span>
          </div>
        </div>
      </div>`,
  },
};

function switchDatasetTab(targetTab) {
  const showChatbot = targetTab === "chatbot";
  $("sub-view-chatbot").classList.toggle("hidden", !showChatbot);
  $("sub-view-classifier").classList.toggle("hidden", showChatbot);
  $("btn-sub-chatbot").classList.toggle("active", showChatbot);
  $("btn-sub-classifier").classList.toggle("active", !showChatbot);
  loadDataset(targetTab, DATASETS[targetTab].page);
}

async function loadDataset(type, page = 1) {
  const cfg = DATASETS[type];
  cfg.page = page;
  const container = $(`sub-view-${type}`);
  container.innerHTML =
    `<h3>${cfg.loadingTitle}</h3><p class="placeholder">Loading page ${page}...</p>`;

  const res = await api(`/api/admin/dataset/${type}?page=${page}`);
  if (res.error) { showApiError(container, "Error: " + res.error); return; }

  container.innerHTML = `
    <div class="flex-between wrap-start">
      <div>
        <h3>${cfg.heading}</h3>
        <p class="muted data-total">Total rows: ${res.total}</p>
      </div>
      <div class="pager">
        <button class="btn btn-ghost" onclick="loadDataset('${type}', ${page - 1})"
                ${page <= 1 ? "disabled" : ""}>← Prev</button>
        <span>Page ${page} of ${res.total_pages}</span>
        <button class="btn btn-ghost" onclick="loadDataset('${type}', ${page + 1})"
                ${page >= res.total_pages ? "disabled" : ""}>Next →</button>
      </div>
    </div>
    <div class="sess-list">${res.data.map(cfg.rowHTML).join("")}</div>`;
}

/* ===================== RESOURCES EDITOR ===================== */
async function loadResourcesData() {
  const container = $("resListGrid");
  if (!container) return;

  container.innerHTML = `<p class="placeholder">Fetching data safely from Supabase...</p>`;
  const r = await api("/api/admin/resources");
  if (r.error) { showErrorPlaceholder(container, r.error); return; }

  resourcesCache = r.resources || [];
  if (!resourcesCache.length) {
    showPlaceholder(container, "No resources currently found in the database.");
    return;
  }
  container.innerHTML = resourcesCache.map((res, i) => `
    <div class="sess-row" onclick="openResourceEditor(${i})">
      <div class="sess-main">
        <div class="sess-title strong">
          ${res.is_published ? "🟢" : "⚪"} ${escapeHTML(res.title)}
        </div>
        <div class="sess-sub">
          Category: <strong>${escapeHTML(res.category || "Unassigned")}</strong> ·
          Type: <em>${escapeHTML(res.kind)}</em> ·
          Source: ${escapeHTML(res.source || "In-house")}
        </div>
      </div>
      <span class="sess-chev">✏️ Edit</span>
    </div>`).join("");
}

// One function fills the form for both "new" and "edit".
function fillResourceForm(res) {
  const isNew = !res;
  res = res || {};
  $("edit-res-id").value = isNew ? "new" : res.id;
  $("edit-res-title").value = res.title || "";
  $("edit-res-category").value = res.category || "";
  $("edit-res-kind").value = res.kind || "article";
  $("edit-res-source").value = res.source || "";
  $("edit-res-url").value = res.external_url || "";
  $("edit-res-summary").value = res.summary || "";
  $("edit-res-info").value = res.info || "";
  $("edit-res-published").checked = isNew ? true : !!res.is_published;

  $("editor-resource-title").textContent = isNew ? "Create New Resource" : "Edit Resource";
  $("btn-delete-res").classList.toggle("hidden", isNew);
  $("resourceFormMsg").textContent = "";
  toggleEditor("res-list-container", "res-form-container", true);
  toggleFormFieldsByKind();
}

function openNewResourceEditor() { fillResourceForm(null); }
function openResourceEditor(index) {
  if (resourcesCache[index]) fillResourceForm(resourcesCache[index]);
}
function closeResourceEditor() {
  toggleEditor("res-list-container", "res-form-container", false);
}

// Articles keep their body in-app; every other kind points at an external URL.
function toggleFormFieldsByKind() {
  const isArticle = $("edit-res-kind").value === "article";
  $("field-external-url").classList.toggle("hidden", isArticle);
  $("field-inhouse-info").classList.toggle("hidden", !isArticle);
}

async function saveResourceChanges(event) {
  event.preventDefault();
  const id = $("edit-res-id").value;
  const isNew = id === "new";
  const payload = {
    title: $("edit-res-title").value,
    category: $("edit-res-category").value,
    kind: $("edit-res-kind").value,
    source: $("edit-res-source").value,
    external_url: $("edit-res-url").value,
    summary: $("edit-res-summary").value,
    info: $("edit-res-info").value,
    is_published: $("edit-res-published").checked,
  };
  await submitAndRefresh(
    $("resourceFormMsg"),
    "Committing to Supabase...",
    () => api(isNew ? "/api/admin/resources" : `/api/admin/resources/${id}`, {
      method: "POST",
      body: JSON.stringify(payload),
    }),
    isNew ? "Created successfully!" : "Saved successfully!",
    () => { closeResourceEditor(); loadResourcesData(); },
  );
}

async function deleteCurrentResource() {
  const id = $("edit-res-id").value;
  if (id === "new") return;
  if (!confirm("Are you sure you want to permanently delete this resource? This will remove it from the user catalog immediately.")) return;
  await submitAndRefresh(
    $("resourceFormMsg"),
    "Deleting...",
    () => api(`/api/admin/resources/${id}`, { method: "DELETE" }),
    "Deleted successfully.",
    () => { closeResourceEditor(); loadResourcesData(); },
  );
}

/* ===================== SYSTEM PROMPTS EDITOR ===================== */
async function loadPromptsData() {
  const container = $("promptsList");
  container.innerHTML = `<p class="placeholder">Fetching prompts from Supabase...</p>`;

  const r = await api("/api/admin/prompts");
  if (r.error) { showApiError(container, r.error); return; }
  if (!r.data || r.data.length === 0) {
    container.innerHTML = `<p class="placeholder">No system prompts found in the database.</p>`;
    return;
  }
  container.innerHTML = `<div class="dash-stack">` + r.data.map((prompt) => {
    const promptId = prompt.key || prompt.id;
    return `
      <div class="dash-card">
        <h4>Prompt: ${escapeHTML(prompt.key)}</h4>
        <textarea id="prompt-content-${promptId}" class="dash-textarea code-area">${escapeHTML(prompt.content)}</textarea>
        <div class="flex-between">
          <p id="prompt-msg-${promptId}" class="auth-msg no-margin"></p>
          <div class="btn-row">
            <button class="btn btn-ghost danger-text" onclick="deletePrompt('${promptId}')">🗑️ Delete</button>
            <button class="btn btn-primary" onclick="savePrompt('${promptId}')">💾 Save</button>
          </div>
        </div>
      </div>`;
  }).join("") + `</div>`;
}

async function savePrompt(promptId) {
  const msgEl = $(`prompt-msg-${promptId}`);
  await submitAndRefresh(
    msgEl,
    "Saving...",
    () => api(`/api/admin/prompts/${promptId}`, {
      method: "POST",
      body: JSON.stringify({ content: $(`prompt-content-${promptId}`).value }),
    }),
    "Saved successfully! Takes ~15s to apply globally.",
    () => setMsg(msgEl, ""),
    3000,
  );
}

function toggleNewPromptForm() {
  const form = $("new-prompt-container");
  const opening = form.classList.contains("hidden");
  form.classList.toggle("hidden", !opening);
  if (opening) {
    $("new-prompt-name").value = "";
    $("new-prompt-content").value = "";
    $("new-prompt-msg").textContent = "";
    $("new-prompt-name").focus();
  }
}

async function submitNewPrompt() {
  const name = $("new-prompt-name").value;
  const content = $("new-prompt-content").value;
  const msgEl = $("new-prompt-msg");
  if (!name || !content) {
    setMsg(msgEl, "Both Name and Content are required.", "error");
    return;
  }
  await submitAndRefresh(
    msgEl,
    "Creating...",
    () => api("/api/admin/prompts", {
      method: "POST",
      body: JSON.stringify({ name, content }),
    }),
    "Created successfully!",
    () => { toggleNewPromptForm(); loadPromptsData(); },
    1000,
  );
}

async function deletePrompt(promptId) {
  if (!confirm(`WARNING: Are you sure you want to delete the '${promptId}' prompt?\n\nIf the AI pipeline relies on this specific prompt name, the system might break or fall back to default text files.`)) return;
  await submitAndRefresh(
    $(`prompt-msg-${promptId}`),
    "Deleting...",
    () => api(`/api/admin/prompts/${promptId}`, { method: "DELETE" }),
    "Deleted successfully.",
    () => loadPromptsData(),
  );
}

/* ===================== AGREEMENTS EDITOR ===================== */
async function loadAgreementsData() {
  const container = $("agreementsList");
  container.innerHTML = `<p class="placeholder">Fetching agreements from Supabase...</p>`;

  const r = await api("/api/admin/agreements");
  if (r.error) { showApiError(container, r.error); return; }
  if (!r.data || r.data.length === 0) {
    container.innerHTML = `<p class="placeholder">No agreements found in the database.</p>`;
    return;
  }
  container.innerHTML = `<div class="dash-stack">` + r.data.map((ag) => `
    <div class="dash-card">
      <h4>Agreement ID: ${escapeHTML(ag.id)}</h4>
      <textarea id="ag-content-${ag.id}" class="dash-textarea agreement-edit">${escapeHTML(ag.content)}</textarea>
      <div class="flex-between">
        <p id="ag-msg-${ag.id}" class="auth-msg no-margin"></p>
        <button class="btn btn-primary" onclick="saveAgreement('${ag.id}')">💾 Save Agreement</button>
      </div>
    </div>`).join("") + `</div>`;
}

async function saveAgreement(agId) {
  const msgEl = $(`ag-msg-${agId}`);
  await submitAndRefresh(
    msgEl,
    "Saving...",
    () => api(`/api/admin/agreements/${agId}`, {
      method: "POST",
      body: JSON.stringify({ content: $(`ag-content-${agId}`).value }),
    }),
    "Agreement updated successfully!",
    () => setMsg(msgEl, ""),
    3000,
  );
}

/* ===================== TESTING (assessment editor) ===================== */
async function loadTestingData() {
  const container = $("testListGrid");
  container.innerHTML = `<p class="placeholder">Fetching assessments...</p>`;

  const res = await api("/api/admin/tests");
  if (res.error) { showApiError(container, res.error); return; }

  testsCache = res.data || [];
  if (testsCache.length === 0) {
    container.innerHTML = `<p class="placeholder">No assessments found. Create one above!</p>`;
    return;
  }
  container.innerHTML = testsCache.map((test, idx) => `
    <div class="sess-row data-row pointer" onclick="openTestEditor(${idx})">
      <div class="sess-main">
        <div class="sess-title accent strong">${escapeHTML(test.title || "Untitled")}</div>
        <div class="sess-sub">
          Category: <strong class="text-plain">${escapeHTML(test.category || "General")}</strong>
        </div>
      </div>
      <button class="btn btn-ghost small">Edit →</button>
    </div>`).join("");
}

function fillTestForm(test) {
  const isNew = !test;
  test = test || {};
  $("edit-test-id").value = isNew ? "new" : test.id;
  $("edit-test-title").value = test.title || "";
  $("edit-test-description").value = test.description || "";

  let questionsVal = isNew ? "[\n  \n]" : (test.questions || "[]");
  if (typeof questionsVal !== "string") {
    questionsVal = JSON.stringify(questionsVal, null, 2);
  }
  $("edit-test-questions").value = questionsVal;

  $("editor-test-title").textContent = isNew ? "Create New Assessment" : "Edit Assessment";
  $("btn-delete-test").classList.toggle("hidden", isNew);
  $("testFormMsg").textContent = "";
  toggleEditor("test-list-container", "test-form-container", true);
}

function openNewTestEditor() { fillTestForm(null); }
function openTestEditor(index) {
  if (testsCache[index]) fillTestForm(testsCache[index]);
}
function closeTestEditor() {
  toggleEditor("test-list-container", "test-form-container", false);
}

async function saveTestChanges(event) {
  event.preventDefault();
  const id = $("edit-test-id").value;
  const isNew = id === "new";
  const msgEl = $("testFormMsg");

  let parsedQuestions;
  try {
    parsedQuestions = JSON.parse($("edit-test-questions").value || "[]");
  } catch (e) {
    setMsg(msgEl, "Error: Invalid JSON format in Questions field.", "error");
    return;
  }

  await submitAndRefresh(
    msgEl,
    "Committing to Supabase...",
    () => api(isNew ? "/api/admin/tests" : `/api/admin/tests/${id}`, {
      method: "POST",
      body: JSON.stringify({
        title: $("edit-test-title").value,
        description: $("edit-test-description").value,
        questions: parsedQuestions,
      }),
    }),
    isNew ? "Created successfully!" : "Saved successfully!",
    () => { closeTestEditor(); loadTestingData(); },
  );
}

async function deleteCurrentTest() {
  const id = $("edit-test-id").value;
  if (id === "new") return;
  if (!confirm("Are you sure you want to permanently delete this assessment?")) return;
  await submitAndRefresh(
    $("testFormMsg"),
    "Deleting...",
    () => api(`/api/admin/tests/${id}`, { method: "DELETE" }),
    "Deleted successfully.",
    () => { closeTestEditor(); loadTestingData(); },
  );
}

/* ===================== TEST ANALYSIS ===================== */
async function loadTestAnalytics() {
  const container = $("test-analytics-container");
  container.innerHTML = `<p class="placeholder">Crunching assessment data...</p>`;
  $("analysis-total-tests").textContent = "0";
  $("analysis-risk-band").textContent = "—";

  const res = await api("/api/admin/analytics/tests");
  if (res.error) { showApiError(container, res.error); return; }

  const data = res.data || {};
  const testTitles = Object.keys(data);
  if (testTitles.length === 0) {
    container.innerHTML = `<p class="placeholder">No users have taken any assessments yet.</p>`;
    return;
  }

  let grandTotalTakes = 0;
  const globalBands = {};

  container.innerHTML = testTitles.map((title) => {
    const stats = data[title];
    grandTotalTakes += stats.total_takes;
    for (const [bandName, count] of Object.entries(stats.bands)) {
      globalBands[bandName] = (globalBands[bandName] || 0) + count;
    }

    const bandsHtml = Object.entries(stats.bands)
      .sort((a, b) => b[1] - a[1])
      .map(([bandName, count]) => {
        const percentage = Math.round((count / stats.total_takes) * 100);
        return `
          <div class="band-row">
            <span>${escapeHTML(bandName)}</span>
            <span class="band-count">${count} users (${percentage}%)</span>
          </div>
          <div class="band-track"><div class="band-fill" style="width:${percentage}%"></div></div>`;
      }).join("");

    return `
      <div class="section-card">
        <h3 class="accent">${escapeHTML(title)}</h3>
        <div class="stat-mini-row">
          <div class="stat-mini">
            <div class="label">Total Takes</div>
            <div class="value">${stats.total_takes}</div>
          </div>
          <div class="stat-mini">
            <div class="label">Avg Score</div>
            <div class="value">${stats.avg_score}</div>
          </div>
        </div>
        <div class="data-label band-heading">Severity Distribution</div>
        ${bandsHtml}
        <button class="btn btn-ghost small logs-toggle"
                onclick="toggleAttemptLogs('${stats.test_id}', this)">
          📋 Individual Logs</button>
        <div id="logs-${stats.test_id}" class="attempt-logs hidden"></div>
      </div>`;
  }).join("");

  let dominantBand = "—";
  let maxBandCount = 0;
  for (const [bandName, count] of Object.entries(globalBands)) {
    if (count > maxBandCount) { maxBandCount = count; dominantBand = bandName; }
  }
  $("analysis-total-tests").textContent = grandTotalTakes;
  $("analysis-risk-band").textContent = dominantBand;

  drawBandChart(globalBands);
}

/* ---------- Individual attempt logs (per analytics card) ----------
   Click "Individual Logs" -> the card fetches that test's attempts and lists
   who took it and when; expanding an attempt shows the exact answer the user
   picked for EVERY question (labels resolved server-side). */
async function toggleAttemptLogs(testId, btn) {
  const panel = $(`logs-${testId}`);
  const nowHidden = panel.classList.toggle("hidden");
  btn.textContent = nowHidden ? "📋 Individual Logs" : "▾ Hide Individual Logs";
  if (nowHidden || panel.dataset.loaded) return;

  panel.innerHTML = `<p class="placeholder">Loading attempts...</p>`;
  const r = await api(`/api/admin/analytics/tests/${testId}/attempts`);
  if (r.error) { showApiError(panel, r.error); return; }
  panel.dataset.loaded = "1";

  const attempts = r.attempts || [];
  if (!attempts.length) {
    panel.innerHTML = `<p class="placeholder">No attempts recorded yet.</p>`;
    return;
  }
  attemptsCache[testId] = attempts;
  panel.innerHTML = attempts.map((a, i) => `
    <div class="attempt-row">
      <div class="attempt-head" onclick="toggleAttemptDetail('${testId}', ${i})">
        <div>
          <div class="attempt-user">${escapeHTML(a.email)}</div>
          <div class="attempt-date">${escapeHTML(fmtDate(a.createdAt))}</div>
        </div>
        <div class="attempt-result">
          <span class="attempt-band">${escapeHTML(a.band || "—")}</span>
          <span class="attempt-score">${a.score ?? "—"}</span>
          <span class="attempt-caret" id="caret-${testId}-${i}">▸</span>
        </div>
      </div>
      <div id="attempt-detail-${testId}-${i}" class="attempt-detail hidden"></div>
    </div>`).join("");
}

const attemptsCache = {}; // testId -> attempts (for detail expansion)

function toggleAttemptDetail(testId, i) {
  const detail = $(`attempt-detail-${testId}-${i}`);
  const open = !detail.classList.toggle("hidden");
  $(`caret-${testId}-${i}`).textContent = open ? "▾" : "▸";
  if (!open || detail.dataset.loaded) return;
  detail.dataset.loaded = "1";
  const a = (attemptsCache[testId] || [])[i];
  detail.innerHTML = (a.picks || []).map((p, qi) => `
    <div class="pick-row">
      <div class="pick-q">${qi + 1}. ${escapeHTML(p.question)}</div>
      <div class="pick-a">${escapeHTML(p.answer)}${p.value != null
        ? ` <span class="pick-val">(+${p.value})</span>` : ""}</div>
    </div>`).join("") || `<p class="placeholder">No answers stored.</p>`;
}

// All-tests risk-band distribution, drawn with the shared bar rows
// (no external chart library — the CSP allows same-origin scripts only).
function drawBandChart(globalBands) {
  const el = $("testScoreChart");
  if (!el) return;
  el.innerHTML = Object.keys(globalBands).length
    ? countBarsHTML(globalBands)
    : '<p class="placeholder">No attempts yet.</p>';
}
