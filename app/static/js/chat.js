/* ===========================================================================
   chat.js — chat page. Uses helpers from common.js.
   Sections: init · sessions · messages · bubble builders · voice
   =========================================================================== */

// Soft centered welcome (ChatGPT-style empty state) for a fresh/empty chat.
// NOT a message: never persisted, never bubble-styled, and it disappears the
// moment the conversation starts (greetings go through the normal pipeline).
const WELCOME_HTML = `
  <div class="welcome-msg">
    <h2>What is on your mind?</h2>
    <p>Peer Counseling Support</p>
  </div>`;

let sessions = [];
let sessionID = null; // created lazily on the first message (fresh chat per login)

/* ---- Experiment mode (supervised live counselling) ----
   In an experiment chat the pipeline's reply is held for a counsellor to
   approve/edit; the user sees a "being reviewed…" bubble and this page polls
   /sessions/<id>/pending every few seconds until the reply is delivered. */
let experimentMode = false;             // toggle value, consumed at session creation
let currentMode = "multi";              // mode of the open session
let composerLocked = false;             // locked while a turn awaits review
const waitingBubbles = new Map();       // messageID -> waiting bubble element
let pollTimer = null;
let pollInFlight = false;
const POLL_MS = 3000;

if (requireAuth()) {
  // Establish the blank chat synchronously before the async session list loads,
  // so an early send can't be clobbered by the late /sessions response.
  startBlank();
  loadSessions();
}

function setExperimentMode(checked) {
  experimentMode = checked;
}

function updateModeUI() {
  // The toggle only matters before the chat exists; the badge marks the mode.
  $("modeToggle").classList.toggle("hidden", sessionID !== null);
  $("modeBadge").classList.toggle("hidden", currentMode !== "experiment");
}

function setComposerLocked(locked) {
  composerLocked = locked;
  $("message").disabled = locked;
  $("sendBtn").disabled = locked;
  $("voiceBtn").disabled = locked;
  $("message").placeholder = locked
    ? "Waiting for the counsellor to review the reply…"
    : "Type your message…";
}

/* ===================== SESSIONS ===================== */
async function loadSessions() {
  const r = await api("/sessions");
  const fetched = r.sessions || [];
  // Keep any locally-created session (e.g. a chat started before this response
  // arrived) at the top of the list.
  const have = new Set(fetched.map((s) => s.sessionID));
  const localOnly = sessions.filter((s) => !have.has(s.sessionID));
  sessions = [...localOnly, ...fetched];
  renderSessionList();
}

function startBlank() {
  sessionID = null;
  localStorage.removeItem("sessionID");
  currentMode = "multi";
  experimentMode = false;
  $("experimentChk").checked = false;
  stopPolling();
  waitingBubbles.clear();
  setComposerLocked(false);
  updateModeUI();
  renderSessionList();
  clearPanels();
  $("currentSessionTitle").textContent = "New chat";
}

async function createSession(title) {
  const r = await api("/sessions", {
    method: "POST",
    body: JSON.stringify({
      title: title || "New chat",
      mode: experimentMode ? "experiment" : "multi",
    }),
  });
  if (r.error) return false;
  sessionID = r.sessionID;
  setSessionID(sessionID);
  currentMode = r.mode || "multi";
  sessions.unshift({ sessionID: r.sessionID, title: r.title, mode: r.mode,
                     createdAt: r.createdAt });
  $("currentSessionTitle").textContent = r.title || "New chat";
  updateModeUI();
  renderSessionList();
  return true;
}

// Session being renamed inline. No window.prompt — browsers/extensions can
// block those dialogs, which made the Rename button look dead (same fix the
// admin test bench got earlier).
let renamingID = null;

function renderSessionList() {
  const list = $("sessionList");
  if (!sessions.length) {
    list.innerHTML = placeholderHTML("No chats yet.");
    return;
  }
  list.innerHTML = sessions.map((s) =>
    s.sessionID === renamingID ? renameRowHTML(s) : `
    <div class="session-item ${s.sessionID === sessionID ? "active" : ""}"
         onclick="openSession('${s.sessionID}', true)">
      <div class="s-title">${escapeHTML(s.title || "New chat")}</div>
      <div class="s-date">${escapeHTML(fmtDate(s.createdAt))}${s.mode === "experiment"
        ? ' · <span class="s-supervised">supervised</span>' : ""}</div>
      <div class="s-actions">
        <button onclick="event.stopPropagation(); startRename('${s.sessionID}')">Rename</button>
        <button onclick="event.stopPropagation(); deleteSession('${s.sessionID}')">Delete</button>
      </div>
    </div>`).join("");
  if (renamingID) {
    const input = $("renameInput");
    if (input) { input.focus(); input.select(); }
  }
}

function renameRowHTML(s) {
  return `
    <div class="session-item renaming" onclick="event.stopPropagation()">
      <input id="renameInput" class="rename-input" maxlength="80"
        value="${escapeHTML(s.title || "New chat")}"
        onkeydown="if(event.key==='Enter'){event.preventDefault(); saveRename('${s.sessionID}');}
                   else if(event.key==='Escape'){cancelRename();}" />
      <div class="s-actions">
        <button onclick="event.stopPropagation(); saveRename('${s.sessionID}')">Save</button>
        <button onclick="event.stopPropagation(); cancelRename()">Cancel</button>
      </div>
    </div>`;
}

async function newChat() {
  startBlank();
  if (isMobileViewport()) closeSidebar();
}

async function openSession(id, fromClick) {
  sessionID = id;
  setSessionID(id);
  stopPolling();
  waitingBubbles.clear();
  const s = sessions.find((x) => x.sessionID === id);
  currentMode = (s && s.mode) || "multi";
  $("currentSessionTitle").textContent = s ? (s.title || "New chat") : "Chat";
  updateModeUI();
  renderSessionList();
  clearPanels();
  const r = await api(`/sessions/${id}/messages`);
  if (sessionID !== id) return; // user already switched away
  const turns = (r && r.turns) || [];
  for (const t of turns) {
    appendUser(t.question);
    if (t.status === "pending") {
      $("chatPanel").appendChild(waitingBubble(t.messageID));
    } else if (t.reply) {
      $("chatPanel").appendChild(answerBubble(t.reply));
    }
  }
  // Resume supervision state: still-pending turns keep the composer locked
  // and restart the poll loop.
  if (waitingBubbles.size) {
    setComposerLocked(true);
    startPolling();
  } else {
    setComposerLocked(false);
  }
  scrollPanels();
  if (fromClick && isMobileViewport()) closeSidebar();
}

function startRename(id) {
  renamingID = id;
  renderSessionList();
}

function cancelRename() {
  renamingID = null;
  renderSessionList();
}

async function saveRename(id) {
  const input = $("renameInput");
  const trimmed = input ? input.value.trim() : "";
  if (!trimmed) { cancelRename(); return; }
  const r = await api(`/sessions/${id}`, { method: "PATCH", body: JSON.stringify({ title: trimmed }) });
  if (r.error) { alert(r.error); return; }
  const s = sessions.find((x) => x.sessionID === id);
  if (s) s.title = r.title;
  if (id === sessionID) $("currentSessionTitle").textContent = r.title;
  renamingID = null;
  renderSessionList();
}

async function deleteSession(id) {
  const s = sessions.find((x) => x.sessionID === id);
  if (!confirm(`Delete "${s ? s.title || "New chat" : "this chat"}"? This cannot be undone.`)) return;
  const r = await api(`/sessions/${id}`, { method: "DELETE" });
  if (r.error) { alert(r.error); return; }
  sessions = sessions.filter((x) => x.sessionID !== id);
  if (id === sessionID) startBlank();
  else renderSessionList();
}

// Auto-name a fresh chat after its first message.
async function maybeAutoTitle(firstMessage) {
  const s = sessions.find((x) => x.sessionID === sessionID);
  if (!s || (s.title && s.title !== "New chat")) return;
  await autoTitleFromMessage(sessionID, firstMessage, (title) => {
    s.title = title;
    $("currentSessionTitle").textContent = title;
    renderSessionList();
  });
}

/* ===================== MESSAGES ===================== */
// Guards against double-submits (Enter / Send while a reply is pending), which
// used to strand an empty loading bubble and could interleave replies. The
// guard is PER CHAT: a slow reply in one chat (possibly deleted meanwhile)
// must not silently swallow sends in every other chat.
const inFlight = new Set(); // session ids awaiting a reply (null = blank chat)

async function send() {
  if (composerLocked || inFlight.has(sessionID)) return; // typed text stays in the box
  const ta = $("message");
  const message = ta.value.trim();
  if (!message) return;

  let flightKey = sessionID; // null until the blank chat gets its session row
  inFlight.add(flightKey);
  $("sendBtn").disabled = true;
  try {
    if (!sessionID) {
      const ok = await createSession(message.slice(0, 40));
      if (!ok) { clearPanels(); appendError("Could not start a chat session."); return; }
      inFlight.delete(flightKey);
      flightKey = sessionID;
      inFlight.add(flightKey);
    }
    const sid = sessionID; // the chat this turn belongs to, even if the user leaves it

    ta.value = "";
    ta.style.height = "auto";

    appendUser(message);
    const load = appendLoading("thinking");

    const r = await api("/chat", {
      method: "POST",
      body: JSON.stringify({ sessionID: sid, message }),
    });

    if (r.error) {
      load.replaceWith(errorBubble(r.error)); // no-op if the user left this chat
      scrollPanels();
      return;
    }
    if (r.status === "pending") {
      // Experiment mode: the reply is with the counsellor. Wait + poll — but
      // only while the user is still looking at this chat (openSession rebuilds
      // the waiting state from the transcript if they come back later).
      if (sid === sessionID) {
        load.replaceWith(waitingBubble(r.messageID));
        scrollPanels();
        maybeAutoTitle(message);
        setComposerLocked(true);
        startPolling();
      }
      return;
    }
    load.replaceWith(answerBubble(r)); // no-op if the user left this chat
    scrollPanels();
    if (sid === sessionID) maybeAutoTitle(message);
  } finally {
    inFlight.delete(flightKey);
    $("sendBtn").disabled = composerLocked; // don't undo the review lock
  }
}

/* ---------- experiment-mode waiting + polling ---------- */
function waitingBubble(messageID) {
  const div = botBubble(
    `<span class="placeholder">Being reviewed by a counsellor<span class="dots"></span></span>`,
    "waiting-review");
  waitingBubbles.set(messageID, div);
  return div;
}

function startPolling() {
  if (!pollTimer) pollTimer = setInterval(pollPending, POLL_MS);
}

function stopPolling() {
  if (pollTimer) { clearInterval(pollTimer); pollTimer = null; }
  pollInFlight = false;
}

async function pollPending() {
  if (pollInFlight || !sessionID) return;
  pollInFlight = true;
  const sid = sessionID;
  try {
    const r = await api(`/sessions/${sid}/pending`);
    if (sid !== sessionID) return;         // user switched chats mid-request
    // On error (chat deleted elsewhere, transient 5xx, rate limit): stop AND
    // unlock, so the composer is never stranded in a permanently disabled
    // state. Reopening the chat rebuilds the lock from the transcript if the
    // turn is genuinely still pending. (401 already redirected by api().)
    if (r.error) { stopPolling(); setComposerLocked(false); return; }
    for (const m of r.messages || []) {
      if (m.status === "delivered" && waitingBubbles.has(m.messageID)) {
        waitingBubbles.get(m.messageID).replaceWith(answerBubble(m));
        waitingBubbles.delete(m.messageID);
        scrollPanels();
      }
    }
    if (!waitingBubbles.size) {
      stopPolling();
      setComposerLocked(false);
    }
  } finally {
    pollInFlight = false;
  }
}

/* auto-grow textarea */
document.addEventListener("input", (e) => {
  if (e.target && e.target.id === "message") {
    e.target.style.height = "auto";
    e.target.style.height = Math.min(e.target.scrollHeight, 140) + "px";
  }
});

/* ===================== BUBBLE BUILDERS ===================== */
function clearPanels() {
  $("chatPanel").innerHTML = WELCOME_HTML;
}

function clearPlaceholder() {
  // Only the panel's own empty state (placeholder text or the welcome
  // bubble) — never the "thinking…" span nested inside a loading bubble.
  const ph = $("chatPanel").querySelector(":scope > .placeholder, :scope > .welcome-msg");
  if (ph) ph.remove();
}

function scrollPanels() {
  $("chatPanel").scrollTop = $("chatPanel").scrollHeight;
}

// One bot-side bubble; every bot message (answer, error, loading) goes through here.
function botBubble(bubbleHTML, bubbleClass = "") {
  const div = document.createElement("div");
  div.className = "msg msg-bot";
  div.innerHTML = `<div class="bubble${bubbleClass ? " " + bubbleClass : ""}">${bubbleHTML}</div>`;
  return div;
}

function errorBubble(msg) {
  return botBubble(escapeHTML(msg), "text-danger");
}

function answerBubble(ans) {
  if (!ans) return botBubble("No response.");
  const meta = ans.escalated
    ? '<div class="meta"><span class="tag escalated">escalated</span></div>' : "";
  // Elevated suicide risk: the server attaches the Suicide Risk Check slug —
  // link straight to that quiz on the Resources page (auto-opened via #test=).
  const quiz = ans.suggestedTest
    ? `<a class="quiz-link" href="/resources#test=${escapeHTML(ans.suggestedTest)}">
         📋 Would you take a short 6-question check-in? It helps you see how
         you're doing and what support could help →</a>` : "";
  return botBubble(`${meta}<p class="answer-text">${escapeHTML(ans.reply)}</p>${quiz}`);
}

function appendUser(text) {
  clearPlaceholder();
  const div = document.createElement("div");
  div.className = "msg msg-user";
  div.innerHTML = `<div class="bubble">${escapeHTML(text)}</div>`;
  $("chatPanel").appendChild(div);
}

// Animated "thinking…" bubble; caller replaces it with the real answer.
function appendLoading(label) {
  const div = botBubble(
    `<span class="placeholder">${escapeHTML(label)}<span class="dots"></span></span>`);
  $("chatPanel").appendChild(div);
  scrollPanels();
  return div;
}

function appendError(msg) {
  $("chatPanel").appendChild(errorBubble(msg));
  scrollPanels();
}

/* ===================== VOICE ===================== */
const VOICE_MAX_MS = 30000; // auto-stop a recording after 30s

let mediaRecorder, chunks = [];
let recording = false;
let recStopTimer = null;

function setVoiceBtn(isRecording) {
  const btn = $("voiceBtn");
  btn.classList.toggle("recording", isRecording);
  btn.textContent = isRecording ? "⏹" : "🎤";
  btn.title = isRecording ? "Click to stop and send" : "Record voice";
}

async function startVoice() {
  if (recording && mediaRecorder && mediaRecorder.state !== "inactive") {
    mediaRecorder.stop();
    return;
  }

  if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
    voiceError(
      window.isSecureContext
        ? "Voice recording isn't supported in this browser."
        : "Microphone needs a secure page. Open the app via http://localhost:5000 or use HTTPS."
    );
    return;
  }

  try {
    const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
    mediaRecorder = new MediaRecorder(stream);
    chunks = [];
    mediaRecorder.ondataavailable = (e) => chunks.push(e.data);
    mediaRecorder.onstop = () => {
      stream.getTracks().forEach((t) => t.stop());
      recording = false;
      if (recStopTimer) { clearTimeout(recStopTimer); recStopTimer = null; }
      setVoiceBtn(false);
      sendVoice();
    };
    mediaRecorder.start();
    recording = true;
    setVoiceBtn(true);
    recStopTimer = setTimeout(() => {
      if (mediaRecorder && mediaRecorder.state !== "inactive") mediaRecorder.stop();
    }, VOICE_MAX_MS);
  } catch (err) {
    recording = false;
    setVoiceBtn(false);
    const msg = err && err.name === "NotAllowedError"
      ? "Microphone access was blocked. Allow mic permission and try again."
      : err && err.name === "NotFoundError"
        ? "No microphone found on this device."
        : "Could not access the microphone.";
    voiceError(msg);
  }
}

function voiceError(msg) {
  appendUser("🎤 (voice)");
  appendLoading("thinking").replaceWith(errorBubble(msg));
  scrollPanels();
}

async function sendVoice() {
  if (!chunks.length) return;

  if (!sessionID) {
    const ok = await createSession("New chat");
    if (!ok) { appendError("Could not start a chat session."); return; }
  }
  const sid = sessionID; // the chat this turn belongs to, even if the user leaves it

  const blob = new Blob(chunks, { type: "audio/webm" });
  const form = new FormData();
  form.append("sessionID", sid);
  form.append("audio", blob, "voice.webm");
  appendUser("🎤 (voice message)");
  const load = appendLoading("transcribing & replying");
  let r;
  try {
    // Multipart upload, so this bypasses the JSON api() helper.
    const res = await fetch(API + "/chat/voice", {
      method: "POST",
      headers: { Authorization: "Bearer " + getToken() },
      body: form,
    });
    r = await res.json();
  } catch {
    load.replaceWith(errorBubble("Voice upload failed."));
    return;
  }
  if (r.error) {
    load.replaceWith(errorBubble(r.error));
    return;
  }
  if (r.transcript) {
    const bubble = load.previousElementSibling?.querySelector(".bubble");
    if (bubble) bubble.textContent = r.transcript;
  }
  if (r.status === "pending") {
    // Experiment mode: the reply is with the counsellor. Wait + poll — only
    // while the user is still looking at this chat (see send()).
    if (sid === sessionID) {
      load.replaceWith(waitingBubble(r.messageID));
      scrollPanels();
      if (r.transcript) maybeAutoTitle(r.transcript);
      setComposerLocked(true);
      startPolling();
    }
    return;
  }
  load.replaceWith(answerBubble(r)); // no-op if the user left this chat
  scrollPanels();
  if (r.transcript && sid === sessionID) maybeAutoTitle(r.transcript);
}
