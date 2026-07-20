/* ===========================================================================
   test_multi.js — the Multi-Agent System test bench (/admin/testing/
   multi-agent). Uses common.js + review_helpers.js (loaded before this file).

   Looks and behaves like the real chat: bubbles + composer, with a sidebar of
   this staff member's previous [TEST] sessions. Opening one loads its full
   history (via the staff review endpoint, so each reply carries diagnostics
   and any rating/feedback already given).
   =========================================================================== */

let mySessions = [];  // ALL of this staff member's sessions (tests + own chats)
let currentID = null;
let currentTitle = null;
let sending = false;

if (requireAuth()) initTestPage();

async function initTestPage() {
  const me = await requireStaff();
  if (!me) return;
  loadMySessions();
}

/* ================= CHAT HISTORY (sidebar: own chats) ================= */
async function loadMySessions() {
  const r = await api("/sessions"); // everything on this staff account
  if (r.error) { showErrorPlaceholder($("testSessionList"), r.error); return; }
  mySessions = r.sessions || [];
  renderTestSessionList();
}

function renderTestSessionList() {
  if (!mySessions.length) {
    showPlaceholder($("testSessionList"), "No chats yet.");
    return;
  }
  $("testSessionList").innerHTML = mySessions.map((s, i) => `
    <div class="session-item ${s.sessionID === currentID ? "active" : ""}"
         onclick="openTestSessionAt(${i})">
      <div class="s-title">${escapeHTML(s.title)}</div>
      <div class="s-date">${escapeHTML(fmtDate(s.createdAt))}</div>
    </div>`).join("");
}

function openTestSessionAt(index) {
  const s = mySessions[index];
  if (s) openTestSession(s.sessionID);
}

/* ===================== OPEN / CREATE A TEST CHAT ===================== */
async function openTestSession(id) {
  currentID = id;
  renderTestSessionList();
  const chat = $("testChat");
  showPlaceholder(chat, "Loading history…");

  // The staff review endpoint returns diagnostics + existing feedback per turn.
  const r = await api(`/api/admin/sessions/${id}`);
  if (r.error) { showErrorPlaceholder(chat, r.error); return; }

  setTestTitle(r.session.title);
  chat.innerHTML = r.messages.length
    ? "" : placeholderHTML("Send a message below to start testing.");
  for (const m of r.messages) {
    appendUserBubble(m.question);
    if (m.reply != null) appendBotBubble(m);
  }
  enableComposer(true);
  chat.scrollTop = chat.scrollHeight;
}

async function startTestChat() {
  const r = await api("/sessions", {
    method: "POST",
    body: JSON.stringify({ title: "New chat" }),
  });
  if (r.error) { alert(r.error); return; }
  mySessions.unshift({ sessionID: r.sessionID, title: r.title, createdAt: r.createdAt });
  currentID = r.sessionID;
  setTestTitle(r.title);
  renderTestSessionList();
  showPlaceholder($("testChat"), "Send a message below to start testing.");
  enableComposer(true);
}

function setTestTitle(title) {
  currentTitle = title;
  $("testSessionTitle").textContent = title;
  $("renameTestBtn").disabled = false;
  $("exportTestBtn").disabled = false;
}

function enableComposer(on) {
  $("testMessage").disabled = !on;
  $("testSendBtn").disabled = !on;
  if (on) $("testMessage").focus();
}

/* ===================== CHAT BUBBLES (like the real app) ===================== */
function clearChatPlaceholder() {
  const ph = $("testChat").querySelector(":scope > .placeholder");
  if (ph) ph.remove();
}

function appendUserBubble(text) {
  clearChatPlaceholder();
  $("testChat").insertAdjacentHTML("beforeend",
    `<div class="msg msg-user"><div class="bubble">${escapeHTML(text)}</div></div>`);
}

// One bot bubble: the reply, its diagnostics, and the rate/feedback controls.
function appendBotBubble(m) {
  clearChatPlaceholder();
  $("testChat").insertAdjacentHTML("beforeend", `
    <div class="msg msg-bot">
      <div class="bubble">
        <p class="answer-text">${escapeHTML(m.reply)}</p>
        ${turnMetaHTML(m)}
        ${feedbackControlsHTML(m)}
      </div>
    </div>`);
}

function appendLoadingBubble() {
  $("testChat").insertAdjacentHTML("beforeend",
    `<div class="msg msg-bot"><div class="bubble">
       <span class="placeholder">thinking<span class="dots"></span></span>
     </div></div>`);
  $("testChat").scrollTop = $("testChat").scrollHeight;
  return $("testChat").lastElementChild;
}

/* ===================== SEND / RENAME / EXPORT ===================== */
async function sendTestMessage() {
  if (sending) return;
  const ta = $("testMessage");
  const message = ta.value.trim();
  if (!message || !currentID) return;

  sending = true;
  $("testSendBtn").disabled = true;
  try {
    ta.value = "";
    appendUserBubble(message);
    const load = appendLoadingBubble();

    // Straight through the REAL user pipeline, on this staff account.
    const r = await api("/chat", {
      method: "POST",
      body: JSON.stringify({ sessionID: currentID, message }),
    });
    load.remove();

    if (r.error) {
      $("testChat").insertAdjacentHTML("beforeend",
        `<div class="msg msg-bot"><div class="bubble text-danger">${escapeHTML(r.error)}</div></div>`);
    } else {
      appendBotBubble({ messageID: r.messageID, reply: r.reply, emotion: r.emotion,
                        confidence: r.confidence, escalated: r.escalated,
                        rating: null, feedback: "" });
      maybeAutoTitle(message);
    }
    $("testChat").scrollTop = $("testChat").scrollHeight;
  } finally {
    sending = false;
    $("testSendBtn").disabled = false;
    ta.focus();
  }
}

/* Inline rename editor — no window.prompt (browsers/extensions can block those
   dialogs, which made the button look dead). */
function renameTestChat() {
  if (!currentID) return;
  $("renameMsg").textContent = "";
  $("testSessionTitle").classList.add("hidden");
  $("renameEditor").classList.remove("hidden");
  const input = $("renameInput");
  input.value = currentTitle || "";
  input.focus();
  input.select();
}

function cancelRename() {
  $("renameEditor").classList.add("hidden");
  $("testSessionTitle").classList.remove("hidden");
}

async function saveRename() {
  const trimmed = $("renameInput").value.trim();
  if (!trimmed) { cancelRename(); return; }

  const r = await api(`/sessions/${currentID}`, {
    method: "PATCH",
    body: JSON.stringify({ title: trimmed }),
  });
  if (r.error) { $("renameMsg").textContent = r.error; return; }

  applyTitle(r.title);
  cancelRename();
}

// Update the header + sidebar entry after a rename or auto-title.
function applyTitle(title) {
  setTestTitle(title);
  const s = mySessions.find((x) => x.sessionID === currentID);
  if (s) s.title = title;
  renderTestSessionList();
}

// Like the real chat: a fresh "New chat" is titled from its first message.
async function maybeAutoTitle(firstMessage) {
  if (currentTitle !== "New chat") return;
  await autoTitleFromMessage(currentID, firstMessage, applyTitle);
}

function exportTestChat() {
  if (currentID) exportSession(currentID);
}
