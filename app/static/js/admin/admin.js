/* ===========================================================================
   admin.js — the staff dashboard page. Uses common.js + review_helpers.js
   (loaded before this file).
   Views: Overview · Emotion Analysis · User Sessions (user -> chat -> review)
   · Testing (card picker -> opens its own page) · Staff (admin only).
   The page is only a shell: all data comes from guarded endpoints.
   =========================================================================== */
let chatbotDataCache = [];
let classifierDataCache = [];
let testChartInstance = null;
let testsCache = [];
let chatbotPage = 1;
let classifierPage = 1;
const DATASET_PAGE_SIZE = 100;
const VIEWS = ["overview", "emotions", "sessions", "testing", "staff", "resources_edit", "dataset", "test_analysis", "prompts", "agreements"];

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

  if (name === "resources_edit") { loadResourcesData(); return; }
  if (name === "dataset") { switchDatasetTab('chatbot'); return; }
  if (name === "test_analysis") { loadTestAnalytics(); }
  if (name === "prompts") { loadPromptsData(); }
  if (name === "agreements") { loadAgreementsData(); }
  if (name === "testing") {loadTestingData(); }

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

async function switchDatasetTab(targetTab) {
  const showChatbot = targetTab === 'chatbot';

  $('sub-view-chatbot').classList.toggle('hidden', !showChatbot);
  $('sub-view-classifier').classList.toggle('hidden', showChatbot);

  $('btn-sub-chatbot').classList.toggle('active', showChatbot);
  $('btn-sub-classifier').classList.toggle('active', !showChatbot);

  if (showChatbot) {
    loadChatbotDataset(chatbotPage);
  } else {
    loadClassifierDataset(classifierPage);
  }
}

/* --- CHATBOT DATASET --- */
async function loadChatbotDataset(page = 1) {
  chatbotPage = page;
  const container = $("sub-view-chatbot");
  container.innerHTML = `<h3>Chat Bot Dataset</h3><p class="placeholder">Loading page ${page}...</p>`;

  // Pass the requested page to the backend
  const res = await api(`/api/admin/dataset/chatbot?page=${page}`);
  if (res.error) {
    container.innerHTML = `<p class="auth-msg error">Error: ${escapeHTML(res.error)}</p>`;
    return;
  }

  let html = `
    <div style="display: flex; justify-content: space-between; align-items: flex-start; flex-wrap: wrap; gap: 10px;">
      <div>
        <h3>Chat Bot Training Data</h3>
        <p class="muted" style="margin-bottom: 16px;">Total rows: ${res.total}</p>
      </div>

      <div style="display: flex; align-items: center; gap: 12px; background: var(--bg-soft); padding: 4px 8px; border-radius: 99px; border: 1px solid var(--border-strong);">
        <button class="btn btn-ghost" style="padding: 4px 10px; font-size: 13px;" onclick="loadChatbotDataset(${page - 1})" ${page <= 1 ? 'disabled' : ''}>← Prev</button>
        <span class="muted" style="font-size: 13px;">Page ${page} of ${res.total_pages}</span>
        <button class="btn btn-ghost" style="padding: 4px 10px; font-size: 13px;" onclick="loadChatbotDataset(${page + 1})" ${page >= res.total_pages ? 'disabled' : ''}>Next →</button>
      </div>
    </div>
    <div class="sess-list">
  `;

  res.data.forEach(item => {
    html += `
      <div class="sess-row" style="cursor: default; background: var(--bg-soft); border-radius: 11px; flex-direction: column; align-items: flex-start; gap: 8px;">
        <div style="color: var(--muted); font-size: 12px; font-weight: bold; text-transform: uppercase;">Instruction</div>
        <div style="font-size: 14px; color: var(--blue); margin-bottom: 8px;">${escapeHTML(item.instruction || '')}</div>

        <div style="color: var(--muted); font-size: 12px; font-weight: bold; text-transform: uppercase;">User Input</div>
        <div style="font-size: 14px; font-style: italic; margin-bottom: 8px;">"${escapeHTML(item.input || '')}"</div>

        <div style="color: var(--muted); font-size: 12px; font-weight: bold; text-transform: uppercase;">Bot Output</div>
        <div style="font-size: 14px; color: var(--text); line-height: 1.5;">${escapeHTML(item.output || '')}</div>
      </div>
    `;
  });

  html += `</div>`;
  container.innerHTML = html;
}

/* --- CLASSIFIER DATASET --- */
async function loadClassifierDataset(page = 1) {
  classifierPage = page;
  const container = $("sub-view-classifier");
  container.innerHTML = `<h3>Classifier Dataset</h3><p class="placeholder">Loading page ${page}...</p>`;

  const res = await api(`/api/admin/dataset/classifier?page=${page}`);
  if (res.error) {
    container.innerHTML = `<p class="auth-msg error">Error: ${escapeHTML(res.error)}</p>`;
    return;
  }

  let html = `
    <div style="display: flex; justify-content: space-between; align-items: flex-start; flex-wrap: wrap; gap: 10px;">
      <div>
        <h3>Classifier Validation Samples</h3>
        <p class="muted" style="margin-bottom: 16px;">Total rows: ${res.total}</p>
      </div>

      <div style="display: flex; align-items: center; gap: 12px; background: var(--bg-soft); padding: 4px 8px; border-radius: 99px; border: 1px solid var(--border-strong);">
        <button class="btn btn-ghost" style="padding: 4px 10px; font-size: 13px;" onclick="loadClassifierDataset(${page - 1})" ${page <= 1 ? 'disabled' : ''}>← Prev</button>
        <span class="muted" style="font-size: 13px;">Page ${page} of ${res.total_pages}</span>
        <button class="btn btn-ghost" style="padding: 4px 10px; font-size: 13px;" onclick="loadClassifierDataset(${page + 1})" ${page >= res.total_pages ? 'disabled' : ''}>Next →</button>
      </div>
    </div>
    <div class="sess-list">
  `;

  res.data.forEach(item => {
    html += `
      <div class="sess-row" style="cursor: default; background: var(--bg-soft); border-radius: 11px;">
        <div class="sess-main">
          <div class="sess-title" style="font-style: italic; color: var(--text); font-size: 14.5px; line-height: 1.4;">
            "${escapeHTML(item.statement || '')}"
          </div>
          <div class="sess-sub" style="margin-top: 8px; display: flex; align-items: center; gap: 10px;">
            <span>Expected Classification:</span>
            <strong style="color: var(--blue);">${escapeHTML(item.status || '')}</strong>
            <span class="role-pill" style="background: var(--surface-3); font-size: 11px; padding: 2px 8px; font-weight: normal;">
              Row ID: ${item['Unnamed: 0'] ?? 'N/A'}
            </span>
          </div>
        </div>
      </div>
    `;
  });

  html += `</div>`;
  container.innerHTML = html;
}

/* ===================== RESOURCES DATASET EDITOR ===================== */
let resourcesCache = [];

async function loadResourcesData() {
  const container = $("resListGrid");
  if (!container) return;

  container.innerHTML = `<p class="placeholder">Fetching data safely from Supabase...</p>`;
  const r = await api("/api/admin/resources");

  if (r.error) {
    showErrorPlaceholder(container, r.error);
    return;
  }

  resourcesCache = r.resources || [];
  if (!resourcesCache.length) {
    showPlaceholder(container, "No resources currently found in the database.");
    return;
  }

  // Render records into rows inside the dataset view panel
  container.innerHTML = resourcesCache.map((res, i) => `
    <div class="sess-row" onclick="openResourceEditor(${i})">
      <div class="sess-main">
        <div class="sess-title" style="font-weight:600;">
          ${res.is_published ? '🟢' : '⚪'} ${escapeHTML(res.title)}
        </div>
        <div class="sess-sub">
          Category: <strong>${escapeHTML(res.category || 'Unassigned')}</strong> ·
          Type: <em>${escapeHTML(res.kind)}</em> ·
          Source: ${escapeHTML(res.source || 'In-house')}
        </div>
      </div>
      <span class="sess-chev">✏️ Edit</span>
    </div>
  `).join("");
}

function openNewResourceEditor() {
  $("edit-res-id").value = "new"; // Flag for creation
  $("edit-res-title").value = "";
  $("edit-res-category").value = "";
  $("edit-res-kind").value = "article";
  $("edit-res-source").value = "";
  $("edit-res-url").value = "";
  $("edit-res-summary").value = "";
  $("edit-res-info").value = "";
  $("edit-res-published").checked = true;

  $("editor-resource-title").textContent = "Create New Resource";
  $("btn-delete-res").classList.add("hidden"); // Can't delete what hasn't been saved!

  $("resourceFormMsg").textContent = "";
  $("res-list-container").classList.add("hidden");
  $("res-form-container").classList.remove("hidden");

  toggleFormFieldsByKind();
}

function openResourceEditor(index) {
  const res = resourcesCache[index];
  if (!res) return;

  $("edit-res-id").value = res.id;
  $("edit-res-title").value = res.title || "";
  $("edit-res-category").value = res.category || "";
  $("edit-res-kind").value = res.kind || "article";
  $("edit-res-source").value = res.source || "";
  $("edit-res-url").value = res.external_url || "";
  $("edit-res-summary").value = res.summary || "";
  $("edit-res-info").value = res.info || "";
  $("edit-res-published").checked = !!res.is_published;

  $("editor-resource-title").textContent = "Edit Resource";
  $("btn-delete-res").classList.remove("hidden"); // Show delete button

  $("resourceFormMsg").textContent = "";
  $("res-list-container").classList.add("hidden");
  $("res-form-container").classList.remove("hidden");

  toggleFormFieldsByKind();
}

function closeResourceEditor() {
  $("res-form-container").classList.add("hidden");
  $("res-list-container").classList.remove("hidden");
}

function toggleFormFieldsByKind() {
  const kind = $("edit-res-kind").value;
  // If it's a standard article, hide the external target URL, show the informational textarea body block
  const isArticle = kind === "article";
  $("field-external-url").classList.toggle("hidden", isArticle);
  $("field-inhouse-info").classList.toggle("hidden", !isArticle);
}

async function saveResourceChanges(event) {
  event.preventDefault();
  const id = $("edit-res-id").value;
  const isNew = id === "new";
  const msgEl = $("resourceFormMsg");

  msgEl.textContent = "Committing to Supabase...";
  msgEl.className = "auth-msg";

  const payload = {
    title: $("edit-res-title").value,
    category: $("edit-res-category").value,
    kind: $("edit-res-kind").value,
    source: $("edit-res-source").value,
    external_url: $("edit-res-url").value,
    summary: $("edit-res-summary").value,
    info: $("edit-res-info").value,
    is_published: $("edit-res-published").checked
  };

  // If new, POST to /resources. If existing, POST to /resources/{id}
  const endpoint = isNew ? "/api/admin/resources" : `/api/admin/resources/${id}`;

  const response = await api(endpoint, {
    method: "POST",
    body: JSON.stringify(payload)
  });

  if (response.error) {
    msgEl.textContent = "Error: " + response.error;
    msgEl.className = "auth-msg error";
  } else {
    msgEl.textContent = isNew ? "Created successfully!" : "Saved successfully!";
    msgEl.className = "auth-msg ok";

    setTimeout(() => {
      closeResourceEditor();
      loadResourcesData();
    }, 800);
  }
}

async function deleteCurrentResource() {
  const id = $("edit-res-id").value;
  if (id === "new") return;

  const confirmed = confirm("Are you sure you want to permanently delete this resource? This will remove it from the user catalog immediately.");
  if (!confirmed) return;

  const msgEl = $("resourceFormMsg");
  msgEl.textContent = "Deleting...";
  msgEl.className = "auth-msg";

  const res = await api(`/api/admin/resources/${id}`, { method: "DELETE" });

  if (res.error) {
    msgEl.textContent = "Error: " + res.error;
    msgEl.className = "auth-msg error";
  } else {
    msgEl.textContent = "Deleted successfully.";
    msgEl.className = "auth-msg ok";
    setTimeout(() => {
      closeResourceEditor();
      loadResourcesData();
    }, 800);
  }
}

/* ===================== SYSTEM PROMPTS EDITOR ===================== */
async function loadPromptsData() {
  const container = $("promptsList");
  container.innerHTML = `<p class="placeholder">Fetching prompts from Supabase...</p>`;

  const r = await api("/api/admin/prompts");
  if (r.error) { container.innerHTML = `<p class="auth-msg error">${escapeHTML(r.error)}</p>`; return; }

  if (!r.data || r.data.length === 0) {
    container.innerHTML = `<p class="placeholder">No system prompts found in the database.</p>`;
    return;
  }

  // Render each prompt as an editable block
  let html = `<div style="display: flex; flex-direction: column; gap: 20px;">`;
  r.data.forEach(prompt => {
    // Assuming the table has 'name' and 'content'
    const promptId = prompt.name || prompt.id;
    html += `
          <div style="background: var(--bg-soft); border: 1px solid var(--border-strong); border-radius: 11px; padding: 16px;">
            <h4 style="margin-top: 0; color: var(--blue); margin-bottom: 12px;">Prompt: ${escapeHTML(prompt.name)}</h4>
            <textarea id="prompt-content-${promptId}" class="dash-textarea" style="min-height: 200px; margin-bottom: 12px; font-family: monospace; font-size: 13px;">${escapeHTML(prompt.content)}</textarea>

            <div style="display: flex; justify-content: space-between; align-items: center;">
              <p id="prompt-msg-${promptId}" class="auth-msg" style="margin: 0;"></p>
              <div style="display: flex; gap: 10px;">
                <button class="btn btn-ghost" style="color: #ff6b6b;" onclick="deletePrompt('${promptId}')">🗑️ Delete</button>
                <button class="btn btn-primary" onclick="savePrompt('${promptId}')">💾 Save</button>
              </div>
            </div>
          </div>
        `;
  });
  html += `</div>`;
  container.innerHTML = html;
}

async function savePrompt(promptId) {
  const content = $(`prompt-content-${promptId}`).value;
  const msgEl = $(`prompt-msg-${promptId}`);

  msgEl.textContent = "Saving...";
  msgEl.className = "auth-msg";

  const res = await api(`/api/admin/prompts/${promptId}`, {
    method: "POST",
    body: JSON.stringify({ content })
  });

  if (res.error) {
    msgEl.textContent = "Error: " + res.error;
    msgEl.className = "auth-msg error";
  } else {
    msgEl.textContent = "Saved successfully! Takes ~15s to apply globally.";
    msgEl.className = "auth-msg ok";
    setTimeout(() => { msgEl.textContent = ""; }, 3000);
  }
}

function toggleNewPromptForm() {
  const form = $("new-prompt-container");
  const isHidden = form.classList.contains("hidden");

  if (isHidden) {
    form.classList.remove("hidden");
    $("new-prompt-name").value = "";
    $("new-prompt-content").value = "";
    $("new-prompt-msg").textContent = "";
    $("new-prompt-name").focus();
  } else {
    form.classList.add("hidden");
  }
}

async function submitNewPrompt() {
  const name = $("new-prompt-name").value;
  const content = $("new-prompt-content").value;
  const msgEl = $("new-prompt-msg");

  if (!name || !content) {
    msgEl.textContent = "Both Name and Content are required.";
    msgEl.className = "auth-msg error";
    return;
  }

  msgEl.textContent = "Creating...";
  msgEl.className = "auth-msg";

  const res = await api("/api/admin/prompts", {
    method: "POST",
    body: JSON.stringify({ name, content })
  });

  if (res.error) {
    msgEl.textContent = "Error: " + res.error;
    msgEl.className = "auth-msg error";
  } else {
    msgEl.textContent = "Created successfully!";
    msgEl.className = "auth-msg ok";

    // Hide form and refresh the prompt list smoothly
    setTimeout(() => {
      toggleNewPromptForm();
      loadPromptsData();
    }, 1000);
  }
}

async function deletePrompt(promptId) {
  // 1. Safety Check
  const confirmed = confirm(
    `WARNING: Are you sure you want to delete the '${promptId}' prompt?\n\nIf the AI pipeline relies on this specific prompt name, the system might break or fall back to default text files.`
  );
  if (!confirmed) return;

  const msgEl = $(`prompt-msg-${promptId}`);
  msgEl.textContent = "Deleting...";
  msgEl.className = "auth-msg";

  // 2. API Call
  const res = await api(`/api/admin/prompts/${promptId}`, {
    method: "DELETE"
  });

  if (res.error) {
    msgEl.textContent = "Error: " + res.error;
    msgEl.className = "auth-msg error";
  } else {
    // 3. Refresh the UI
    msgEl.textContent = "Deleted successfully.";
    msgEl.className = "auth-msg ok";
    setTimeout(() => {
      loadPromptsData();
    }, 800);
  }
}
/* ===================== AGREEMENTS EDITOR ===================== */
async function loadAgreementsData() {
  const container = $("agreementsList");
  container.innerHTML = `<p class="placeholder">Fetching agreements from Supabase...</p>`;

  const r = await api("/api/admin/agreements");
  if (r.error) { container.innerHTML = `<p class="auth-msg error">${escapeHTML(r.error)}</p>`; return; }

  if (!r.data || r.data.length === 0) {
    container.innerHTML = `<p class="placeholder">No agreements found in the database.</p>`;
    return;
  }

  let html = `<div style="display: flex; flex-direction: column; gap: 20px;">`;
  r.data.forEach(ag => {
    html += `
      <div style="background: var(--bg-soft); border: 1px solid var(--border-strong); border-radius: 11px; padding: 16px;">
        <h4 style="margin-top: 0; color: var(--blue); margin-bottom: 12px;">Agreement ID: ${escapeHTML(ag.id)}</h4>
        <textarea id="ag-content-${ag.id}" class="dash-textarea" style="min-height: 200px; margin-bottom: 12px;">${escapeHTML(ag.content)}</textarea>
        <div style="display: flex; justify-content: space-between; align-items: center;">
          <p id="ag-msg-${ag.id}" class="auth-msg" style="margin: 0;"></p>
          <button class="btn btn-primary" onclick="saveAgreement('${ag.id}')">💾 Save Agreement</button>
        </div>
      </div>
    `;
  });
  html += `</div>`;
  container.innerHTML = html;
}

async function saveAgreement(agId) {
  const content = $(`ag-content-${agId}`).value;
  const msgEl = $(`ag-msg-${agId}`);

  msgEl.textContent = "Saving...";
  msgEl.className = "auth-msg";

  const res = await api(`/api/admin/agreements/${agId}`, {
    method: "POST",
    body: JSON.stringify({ content })
  });

  if (res.error) {
    msgEl.textContent = "Error: " + res.error;
    msgEl.className = "auth-msg error";
  } else {
    msgEl.textContent = "Agreement updated successfully!";
    msgEl.className = "auth-msg ok";
    setTimeout(() => { msgEl.textContent = ""; }, 3000);
  }
}

async function loadTestingData() {
  const container = $("testListGrid");
  container.innerHTML = `<p class="placeholder">Fetching assessments...</p>`;

  const res = await api("/api/admin/tests");
  if (res.error) {
    container.innerHTML = `<p class="auth-msg error">${escapeHTML(res.error)}</p>`;
    return;
  }

  testsCache = res.data || [];
  if (testsCache.length === 0) {
    container.innerHTML = `<p class="placeholder">No assessments found. Create one above!</p>`;
    return;
  }

  let html = "";
  testsCache.forEach((test, idx) => {
    html += `
      <div class="sess-row" onclick="openTestEditor(${idx})" style="cursor: pointer; background: var(--bg-soft); border-radius: 11px;">
        <div class="sess-main">
          <div class="sess-title" style="color: var(--blue); font-weight: 600;">${escapeHTML(test.title || "Untitled")}</div>
          <div class="sess-sub" style="margin-top: 6px;">
            Category: <strong style="color:var(--text);">${escapeHTML(test.category || "General")}</strong>
          </div>
        </div>
        <button class="btn btn-ghost small">Edit →</button>
      </div>
    `;
  });

  container.innerHTML = html;
}

function openNewTestEditor() {
  $("edit-test-id").value = "new";
  $("edit-test-title").value = "";
  $("edit-test-description").value = "";
  $("edit-test-questions").value = "[\n  \n]";

  $("editor-test-title").textContent = "Create New Assessment";
  $("btn-delete-test").classList.add("hidden");
  $("testFormMsg").textContent = "";

  $("test-list-container").classList.add("hidden");
  $("test-form-container").classList.remove("hidden");
}

function openTestEditor(index) {
  const test = testsCache[index];
  if (!test) return;

  $("edit-test-id").value = test.id;
  $("edit-test-title").value = test.title || "";
  $("edit-test-description").value = test.description || "";

  // Format JSON beautifully if it's stored as an object, or just drop in the string
  let questionsVal = test.questions || "[]";
  if (typeof questionsVal !== "string") {
    questionsVal = JSON.stringify(questionsVal, null, 2);
  }
  $("edit-test-questions").value = questionsVal;

  $("editor-test-title").textContent = "Edit Assessment";
  $("btn-delete-test").classList.remove("hidden");
  $("testFormMsg").textContent = "";

  $("test-list-container").classList.add("hidden");
  $("test-form-container").classList.remove("hidden");
}

function closeTestEditor() {
  $("test-form-container").classList.add("hidden");
  $("test-list-container").classList.remove("hidden");
}

async function saveTestChanges(event) {
  event.preventDefault();
  const id = $("edit-test-id").value;
  const isNew = id === "new";
  const msgEl = $("testFormMsg");

  msgEl.textContent = "Committing to Supabase...";
  msgEl.className = "auth-msg";

  // Attempt to parse the questions to ensure valid JSON
  let parsedQuestions = [];
  try {
    parsedQuestions = JSON.parse($("edit-test-questions").value || "[]");
  } catch (e) {
    msgEl.textContent = "Error: Invalid JSON format in Questions field.";
    msgEl.className = "auth-msg error";
    return;
  }

  const payload = {
    title: $("edit-test-title").value,
    description: $("edit-test-description").value,
    questions: parsedQuestions
  };

  const endpoint = isNew ? "/api/admin/tests" : `/api/admin/tests/${id}`;

  const response = await api(endpoint, {
    method: "POST",
    body: JSON.stringify(payload)
  });

  if (response.error) {
    msgEl.textContent = "Error: " + response.error;
    msgEl.className = "auth-msg error";
  } else {
    msgEl.textContent = isNew ? "Created successfully!" : "Saved successfully!";
    msgEl.className = "auth-msg ok";

    setTimeout(() => {
      closeTestEditor();
      loadTestingData();
    }, 800);
  }
}

async function deleteCurrentTest() {
  const id = $("edit-test-id").value;
  if (id === "new") return;

  const confirmed = confirm("Are you sure you want to permanently delete this assessment?");
  if (!confirmed) return;

  const msgEl = $("testFormMsg");
  msgEl.textContent = "Deleting...";
  msgEl.className = "auth-msg";

  const res = await api(`/api/admin/tests/${id}`, { method: "DELETE" });

  if (res.error) {
    msgEl.textContent = "Error: " + res.error;
    msgEl.className = "auth-msg error";
  } else {
    msgEl.textContent = "Deleted successfully.";
    msgEl.className = "auth-msg ok";
    setTimeout(() => {
      closeTestEditor();
      loadTestingData();
    }, 800);
  }
}

/* ===================== TEST ANALYSIS MODULE ===================== */
async function loadTestAnalytics() {
  const container = $("test-analytics-container");
  container.innerHTML = `<p class="placeholder">Crunching assessment data...</p>`;

  // Reset global stat counters
  $("analysis-total-tests").textContent = "0";
  $("analysis-risk-band").textContent = "—";

  const res = await api("/api/admin/analytics/tests");
  if (res.error) {
    container.innerHTML = `<p class="auth-msg error">${escapeHTML(res.error)}</p>`;
    return;
  }

  const data = res.data || {};
  const testTitles = Object.keys(data);

  if (testTitles.length === 0) {
    container.innerHTML = `<p class="placeholder">No users have taken any assessments yet.</p>`;
    return;
  }

  // Variables for Global Stats
  let grandTotalTakes = 0;
  let globalBands = {};
  let html = "";

  testTitles.forEach(title => {
    const stats = data[title];

    // 1. Add to Global Stats
    grandTotalTakes += stats.total_takes;
    Object.entries(stats.bands).forEach(([bandName, count]) => {
      globalBands[bandName] = (globalBands[bandName] || 0) + count;
    });

    // 2. Build Specific Card HTML
    const sortedBands = Object.entries(stats.bands).sort((a, b) => b[1] - a[1]);
    let bandsHtml = "";

    sortedBands.forEach(([bandName, count]) => {
      const percentage = Math.round((count / stats.total_takes) * 100);
      bandsHtml += `
        <div style="display: flex; justify-content: space-between; align-items: center; margin-top: 8px; font-size: 13px;">
          <span style="color: var(--text);">${escapeHTML(bandName)}</span>
          <span style="color: var(--muted);">${count} users (${percentage}%)</span>
        </div>
        <div style="width: 100%; background: var(--surface-3); height: 6px; border-radius: 3px; margin-top: 4px; overflow: hidden;">
          <div style="width: ${percentage}%; background: var(--blue); height: 100%;"></div>
        </div>
      `;
    });

    html += `
      <div class="section-card" style="display: flex; flex-direction: column; justify-content: space-between;">
        <div>
          <h3 style="margin-top: 0; color: var(--blue); font-size: 16px;">${escapeHTML(title)}</h3>

          <div style="display: flex; gap: 15px; margin-bottom: 16px; border-bottom: 1px solid var(--border-strong); padding-bottom: 12px;">
            <div>
              <div style="font-size: 11px; text-transform: uppercase; color: var(--muted); font-weight: bold;">Total Takes</div>
              <div style="font-size: 20px; color: var(--text); font-weight: 600;">${stats.total_takes}</div>
            </div>
            <div>
              <div style="font-size: 11px; text-transform: uppercase; color: var(--muted); font-weight: bold;">Avg Score</div>
              <div style="font-size: 20px; color: var(--text); font-weight: 600;">${stats.avg_score}</div>
            </div>
          </div>

          <div style="font-size: 12px; text-transform: uppercase; color: var(--muted); font-weight: bold; margin-bottom: 8px;">Severity Distribution</div>
          ${bandsHtml}
        </div>
      </div>
    `;
  });

  // 3. Find the Dominant Global Band
  let dominantBand = "—";
  let maxBandCount = 0;
  Object.entries(globalBands).forEach(([bandName, count]) => {
    if (count > maxBandCount) {
      maxBandCount = count;
      dominantBand = bandName;
    }
  });

  // 4. Update the DOM
  $("analysis-total-tests").textContent = grandTotalTakes;
  $("analysis-risk-band").textContent = dominantBand;
  container.innerHTML = html;

  // 5. Draw the Chart.js Graph
  setTimeout(() => {
    const canvas = document.getElementById("testScoreChart");
    if (!canvas) {
      console.error("Chart Canvas not found in the DOM!");
      return;
    }

    const ctx = canvas.getContext("2d");

    // Destroy old chart instance if it exists
    if (testChartInstance) {
      testChartInstance.destroy();
    }

    const chartLabels = Object.keys(globalBands);
    const chartData = Object.values(globalBands);

    // If there is no data at all, don't try to draw an empty chart
    if (chartLabels.length === 0) return;

    testChartInstance = new Chart(ctx, {
      type: "bar",
      data: {
        labels: chartLabels,
        datasets: [{
          label: "Number of Users in Band",
          data: chartData,
          backgroundColor: "#4A90E2",
          borderRadius: 6,
        }]
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        plugins: { legend: { display: false } },
        scales: {
          y: {
            beginAtZero: true,
            ticks: { precision: 0 }
          }
        }
      }
    });
  }, 150); // 150 millisecond delay gives the UI time to unhide
}