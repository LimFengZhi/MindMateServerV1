/* ===========================================================================
   chat.js — chat page. Uses helpers from common.js.
   Sections: init · sessions · messages · bubble builders · voice
   =========================================================================== */

const CHAT_PLACEHOLDER = "Ask something below to start the conversation.";

let sessions = [];
let sessionID = null; // created lazily on the first message (fresh chat per login)

if (requireAuth()) {
  // Establish the blank chat synchronously before the async session list loads,
  // so an early send can't be clobbered by the late /sessions response.
  startBlank();
  loadSessions();
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
  renderSessionList();
  clearPanels();
  $("currentSessionTitle").textContent = "New chat";
}

async function createSession(title) {
  const r = await api("/sessions", {
    method: "POST",
    body: JSON.stringify({ title: title || "New chat" }),
  });
  if (r.error) return false;
  sessionID = r.sessionID;
  setSessionID(sessionID);
  sessions.unshift({ sessionID: r.sessionID, title: r.title, createdAt: r.createdAt });
  $("currentSessionTitle").textContent = r.title || "New chat";
  renderSessionList();
  return true;
}

function renderSessionList() {
  const list = $("sessionList");
  if (!sessions.length) {
    list.innerHTML = placeholderHTML("No chats yet.");
    return;
  }
  list.innerHTML = sessions.map((s) => `
    <div class="session-item ${s.sessionID === sessionID ? "active" : ""}"
         onclick="openSession('${s.sessionID}', true)">
      <div class="s-title">${escapeHTML(s.title || "New chat")}</div>
      <div class="s-date">${escapeHTML(fmtDate(s.createdAt))}</div>
      <div class="s-actions">
        <button onclick="event.stopPropagation(); renamePrompt('${s.sessionID}')">Rename</button>
        <button onclick="event.stopPropagation(); deleteSession('${s.sessionID}')">Delete</button>
      </div>
    </div>`).join("");
}

async function newChat() {
  startBlank();
  if (isMobileViewport()) closeSidebar();
}

async function openSession(id, fromClick) {
  sessionID = id;
  setSessionID(id);
  const s = sessions.find((x) => x.sessionID === id);
  $("currentSessionTitle").textContent = s ? (s.title || "New chat") : "Chat";
  renderSessionList();
  clearPanels();
  const r = await api(`/sessions/${id}/messages`);
  const turns = (r && r.turns) || [];
  for (const t of turns) {
    appendUser(t.question);
    if (t.reply) $("chatPanel").appendChild(answerBubble(t.reply));
  }
  scrollPanels();
  if (fromClick && isMobileViewport()) closeSidebar();
}

async function renamePrompt(id) {
  const s = sessions.find((x) => x.sessionID === id);
  const title = prompt("Rename chat:", s ? s.title : "");
  if (title == null) return;
  const trimmed = title.trim();
  if (!trimmed) return;
  const r = await api(`/sessions/${id}`, { method: "PATCH", body: JSON.stringify({ title: trimmed }) });
  if (r.error) { alert(r.error); return; }
  if (s) s.title = r.title;
  if (id === sessionID) $("currentSessionTitle").textContent = r.title;
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
  const title = firstMessage.trim().slice(0, 40) || "New chat";
  const r = await api(`/sessions/${sessionID}`, {
    method: "PATCH",
    body: JSON.stringify({ title }),
  });
  if (r && !r.error) {
    s.title = r.title;
    $("currentSessionTitle").textContent = r.title;
    renderSessionList();
  }
}

/* ===================== MESSAGES ===================== */
// Guards against double-submits (Enter / Send while a reply is pending), which
// used to strand an empty loading bubble and could interleave replies.
let sending = false;

async function send() {
  if (sending) return; // a reply is pending; the typed text stays in the box
  const ta = $("message");
  const message = ta.value.trim();
  if (!message) return;

  sending = true;
  $("sendBtn").disabled = true;
  try {
    if (!sessionID) {
      const ok = await createSession(message.slice(0, 40));
      if (!ok) { clearPanels(); appendError("Could not start a chat session."); return; }
    }

    ta.value = "";
    ta.style.height = "auto";

    appendUser(message);
    const load = appendLoading("thinking");

    const r = await api("/chat", {
      method: "POST",
      body: JSON.stringify({ sessionID, message }),
    });

    if (r.error) {
      load.replaceWith(errorBubble(r.error));
      scrollPanels();
      return;
    }
    load.replaceWith(answerBubble(r));
    scrollPanels();
    maybeAutoTitle(message);
  } finally {
    sending = false;
    $("sendBtn").disabled = false;
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
  $("chatPanel").innerHTML = placeholderHTML(CHAT_PLACEHOLDER);
}

function clearPlaceholder() {
  // Only the panel's own placeholder — never the "thinking…" span nested
  // inside a pending loading bubble.
  const ph = $("chatPanel").querySelector(":scope > .placeholder");
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
  return botBubble(`${meta}<p class="answer-text">${escapeHTML(ans.reply)}</p>`);
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

  const blob = new Blob(chunks, { type: "audio/webm" });
  const form = new FormData();
  form.append("sessionID", sessionID);
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
  load.replaceWith(answerBubble(r));
  scrollPanels();
  if (r.transcript) maybeAutoTitle(r.transcript);
}
