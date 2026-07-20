/* ===========================================================================
   admin.js — the staff dashboard page. Uses common.js + review_helpers.js
   (loaded before this file).
   Views: Overview · Emotion Analysis · User Sessions (user -> chat -> review)
   · Testing (assessment editor) · Staff (admin only) · Resources Editing
   · Dataset Management · Test Analysis · System Prompts · Agreements.
   (Live Counselling is its own page: /admin/live.)
   The page is only a shell: all data comes from guarded endpoints.
   =========================================================================== */

const VIEWS = ["overview", "emotions", "sessions", "testing", "staff",
               "resources_edit", "dataset", "test_analysis", "prompts", "agreements"];

let currentView = "overview";
const loadedViews = new Set();

let sessionsCache = [];       // all sessions (for the sessions view)
let selectedUserEmail = null; // drill-down state
let staffCache = [];          // staff accounts (admin only)
let resourcesCache = [];      // resources editor
let testsCache = [];          // assessments editor
let testChartInstance = null; // Chart.js instance (test analysis)

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
  if (name === "resources_edit") { loadResourcesData(); return; }
  if (name === "dataset") { switchDatasetTab("chatbot"); return; }
  if (name === "test_analysis") { loadTestAnalytics(); }
  if (name === "prompts") { loadPromptsData(); }
  if (name === "agreements") { loadAgreementsData(); }
  if (name === "testing") { loadTestingData(); }

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
      <textarea id="ag-content-${ag.id}" class="dash-textarea tall">${escapeHTML(ag.content)}</textarea>
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

// The short delay gives the view time to unhide before Chart.js measures it.
function drawBandChart(globalBands) {
  setTimeout(() => {
    const canvas = document.getElementById("testScoreChart");
    if (!canvas) return;
    if (testChartInstance) testChartInstance.destroy();

    const chartLabels = Object.keys(globalBands);
    if (!chartLabels.length) return;

    testChartInstance = new Chart(canvas.getContext("2d"), {
      type: "bar",
      data: {
        labels: chartLabels,
        datasets: [{
          label: "Number of Users in Band",
          data: Object.values(globalBands),
          backgroundColor: "#4A90E2",
          borderRadius: 6,
        }],
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        plugins: { legend: { display: false } },
        scales: { y: { beginAtZero: true, ticks: { precision: 0 } } },
      },
    });
  }, 150);
}
