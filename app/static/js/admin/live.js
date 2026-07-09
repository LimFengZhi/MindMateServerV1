/* ===========================================================================
   live.js — Live Counselling page (/admin/live).
   Uses common.js + review_helpers.js (loaded before this file).

   Flow: the counsellor TAKES CHARGE of up to 2 users (left sidebar) → each
   connected user gets a panel where the counsellor picks one of that user's
   live experiment sessions → the conversation then updates automatically
   (shared ~4s poll): pending drafts show inline Approve / Send-edited
   controls, past reviews (by any staff member) are visible in the transcript,
   and the session can be renamed as a case label.

   Turn nodes are keyed by messageID and only replaced when their status
   changes, so an in-progress edit is never wiped by a refresh.
   =========================================================================== */

const MAX_CONNECTED = 2;
const LIVE_POLL_MS = 4000;

let liveSessions = [];  // every experiment session (from the API)
let liveClaims = {};    // user email -> staff email currently in charge
let liveUsers = [];     // grouped per user: {email, sessions, pending}
let slots = [];         // panels: {email, sessionID|null} — max 2, null = free
let myEmail = null;     // this staff member (to tell own claims apart)
let liveTimer = null;
let liveInFlight = false;

if (requireAuth()) initLive();

async function initLive() {
  const me = await requireStaff();
  if (!me) return;
  myEmail = me.email;
  await refreshLive();
  liveTimer = setInterval(refreshLive, LIVE_POLL_MS);
}

/* ===================== POLL LOOP ===================== */
async function refreshLive() {
  if (liveInFlight) return;
  liveInFlight = true;
  try {
    const r = await api("/api/admin/live-sessions"); // also heartbeats my claims
    if (r.error) { showErrorPlaceholder($("liveSessionList"), r.error); return; }
    liveSessions = r.sessions || [];
    liveClaims = r.claims || {};
    groupUsers();
    renderUserList();
    for (let i = 0; i < slots.length; i++) {
      if (!slots[i]) continue;
      if (slots[i].sessionID) await refreshTranscript(i);
      else renderSessionPicker(i);
    }
  } finally {
    liveInFlight = false;
  }
}

function groupUsers() {
  const map = new Map();
  for (const s of liveSessions) {
    if (!map.has(s.email)) map.set(s.email, { email: s.email, sessions: [], pending: 0 });
    const u = map.get(s.email);
    u.sessions.push(s);
    u.pending += s.pendingCount;
  }
  // Users needing attention first.
  liveUsers = [...map.values()].sort((a, b) => b.pending - a.pending);
}

/* ===================== SIDEBAR: take charge of users ===================== */
function renderUserList() {
  if (!liveUsers.length) {
    showPlaceholder($("liveSessionList"),
      "No users with experiment chats yet. They appear here when someone starts one.");
    return;
  }
  $("liveSessionList").innerHTML = liveUsers.map((u, i) => {
    const holder = liveClaims[u.email];
    const mine = slots.some((s) => s && s.email === u.email);
    const lockedByOther = holder && holder !== myEmail && !mine;
    return `
    <div class="session-item ${mine ? "active" : ""} ${lockedByOther ? "locked" : ""}"
         ${lockedByOther ? "" : `onclick="connectUserAt(${i})"`}>
      <div class="s-title">${u.pending
        ? `<span class="lv-pending-dot">${u.pending}</span> ` : ""}👤 ${escapeHTML(u.email)}</div>
      <div class="s-date">${lockedByOther
        ? `🔒 connected by ${escapeHTML(holder)}`
        : `${u.sessions.length} experiment chat${u.sessions.length === 1 ? "" : "s"}`}</div>
    </div>`;
  }).join("");
}

async function connectUserAt(index) {
  const u = liveUsers[index];
  if (!u) return;
  if (slots.some((s) => s && s.email === u.email)) return; // already in charge
  if (slots.filter(Boolean).length >= MAX_CONNECTED) {
    alert(`You can take charge of ${MAX_CONNECTED} users at a time — disconnect one first.`);
    return;
  }

  // Claim the user server-side first, so two staff can never hold the same one.
  const claim = await api("/api/admin/live-claim", {
    method: "POST",
    body: JSON.stringify({ email: u.email }),
  });
  if (claim.error) { // 409: another counsellor got there first
    alert(claim.error);
    refreshLive();
    return;
  }
  liveClaims[u.email] = myEmail;

  let idx = slots.findIndex((s) => !s);
  if (idx === -1) idx = slots.length;
  slots[idx] = { email: u.email, sessionID: null };

  const empty = document.querySelector(".lv-empty");
  if (empty) empty.remove();
  $("livePanels").insertAdjacentHTML("beforeend", panelShellHTML(idx));
  $(`lvuser-${idx}`).textContent = `👤 ${u.email}`;
  renderUserList();
  renderSessionPicker(idx);
}

function disconnectSlot(idx) {
  const slot = slots[idx];
  if (slot) {
    api("/api/admin/live-release", {
      method: "POST",
      body: JSON.stringify({ email: slot.email }),
    });
    delete liveClaims[slot.email];
  }
  slots[idx] = null;
  const panel = $(`lvpanel-${idx}`);
  if (panel) panel.remove();
  if (!slots.filter(Boolean).length) {
    slots = [];
    $("livePanels").innerHTML =
      '<p class="placeholder lv-empty">Select a user on the left to take charge.</p>';
  }
  renderUserList();
}

/* ===================== PANEL: pick a session, then watch it =============== */
function panelShellHTML(idx) {
  return `
    <div class="live-panel" id="lvpanel-${idx}">
      <div class="lv-head">
        <div class="lv-head-main">
          <div class="lv-user" id="lvuser-${idx}"></div>
          <strong class="lv-title hidden" id="lvtitle-${idx}"></strong>
        </div>
        <div class="rename-editor hidden" id="lvrenamebox-${idx}">
          <input id="lvrenameinput-${idx}" maxlength="80"
                 onkeydown="if(event.key==='Enter') saveLiveRename(${idx});
                            if(event.key==='Escape') cancelLiveRename(${idx});" />
          <button class="btn btn-primary" onclick="saveLiveRename(${idx})">Save</button>
          <button class="btn btn-ghost" onclick="cancelLiveRename(${idx})">Cancel</button>
        </div>
        <div class="lv-head-actions">
          <button class="btn hidden" id="lvback-${idx}"
                  onclick="backToSessions(${idx})">← Sessions</button>
          <button class="btn hidden" id="lvrenamebtn-${idx}"
                  onclick="openLiveRename(${idx})">Rename</button>
          <button class="btn btn-ghost" title="Disconnect from this user"
                  onclick="disconnectSlot(${idx})">✕</button>
        </div>
      </div>
      <div class="lv-body" id="lvbody-${idx}">
        <p class="placeholder">Loading…</p>
      </div>
    </div>`;
}

// Step 2 of the flow: choose which of this user's live sessions to supervise.
function renderSessionPicker(idx) {
  const slot = slots[idx];
  if (!slot) return;
  $(`lvtitle-${idx}`).classList.add("hidden");
  $(`lvback-${idx}`).classList.add("hidden");
  $(`lvrenamebtn-${idx}`).classList.add("hidden");
  $(`lvrenamebox-${idx}`).classList.add("hidden");

  const u = liveUsers.find((x) => x.email === slot.email);
  const body = $(`lvbody-${idx}`);
  if (!u || !u.sessions.length) {
    showPlaceholder(body, "This user has no experiment chats right now.");
    return;
  }
  body.innerHTML = `<div class="rq-label">Select their live session</div>` +
    u.sessions.map((s) => `
      <div class="sess-row" onclick="pickSession(${idx}, '${s.sessionID}')">
        <div class="sess-main">
          <div class="sess-title">${escapeHTML(s.title)}</div>
          <div class="sess-sub">${s.messageCount} messages
            · ${escapeHTML(fmtDate(s.createdAt))}</div>
        </div>
        ${s.pendingCount ? `<span class="lv-pending-dot">${s.pendingCount}</span>` : ""}
        <span class="sess-chev">›</span>
      </div>`).join("");
}

function pickSession(idx, sessionID) {
  const slot = slots[idx];
  if (!slot) return;
  slot.sessionID = sessionID;
  $(`lvback-${idx}`).classList.remove("hidden");
  $(`lvrenamebtn-${idx}`).classList.remove("hidden");
  showPlaceholder($(`lvbody-${idx}`), "Loading conversation…");
  refreshTranscript(idx);
}

function backToSessions(idx) {
  const slot = slots[idx];
  if (!slot) return;
  slot.sessionID = null;
  renderSessionPicker(idx);
}

/* ===================== LIVE TRANSCRIPT ===================== */
async function refreshTranscript(idx) {
  const slot = slots[idx];
  if (!slot || !slot.sessionID) return;
  const sid = slot.sessionID;
  const r = await api(`/api/admin/sessions/${sid}`);
  // Bail if the counsellor switched/disconnected while this request ran.
  if (slots[idx] !== slot || slot.sessionID !== sid) return;
  if (r.error) {
    showErrorPlaceholder($(`lvbody-${idx}`), r.error);
    return;
  }
  const title = $(`lvtitle-${idx}`);
  title.textContent = r.session.title;
  title.dataset.title = r.session.title;
  if ($(`lvrenamebox-${idx}`).classList.contains("hidden")) {
    title.classList.remove("hidden");
  }
  updatePanelBody(idx, r.messages || []);
}

// Incremental: append new turns, replace a turn's node only when its status
// changed. Never touches a card the counsellor is typing in.
function updatePanelBody(idx, messages) {
  const body = $(`lvbody-${idx}`);
  const ph = body.querySelector(":scope > .placeholder");
  if (!messages.length) {
    showPlaceholder(body, "No messages yet — waiting for the user…");
    return;
  }
  if (ph) ph.remove();
  let appended = false;
  for (const m of messages) {
    const node = $(`lvturn-${m.messageID}`);
    if (!node) {
      body.insertAdjacentHTML("beforeend", liveTurnHTML(idx, m));
      appended = true;
    } else if (node.dataset.status !== m.status) {
      node.outerHTML = liveTurnHTML(idx, m);
    }
  }
  if (appended) body.scrollTop = body.scrollHeight;
}

function liveTurnHTML(idx, m) {
  let replyPart;
  if (m.status === "pending") {
    const crisis = m.escalated
      ? '<div class="rq-crisis">⚠ CRISIS ESCALATION — please handle this first.</div>' : "";
    replyPart = `
      ${crisis}
      <div class="rq-draft">
        <div class="rq-label">Bot draft</div>
        ${escapeHTML(m.draft || "(empty draft)")}
      </div>
      <div class="rq-label">Your reply (edit to replace the draft)</div>
      <textarea id="lvedit-${m.messageID}" class="rq-textarea"
                rows="3">${escapeHTML(m.draft || "")}</textarea>
      <div class="rq-actions">
        <button class="btn btn-primary" id="lvapprove-${m.messageID}"
                onclick="liveResolve(${idx}, '${m.messageID}', 'approve')">Approve draft</button>
        <button class="btn" id="lvsend-${m.messageID}"
                onclick="liveResolve(${idx}, '${m.messageID}', 'edit')">Send edited reply</button>
      </div>`;
  } else {
    replyPart = `<div class="turn-a"><strong>Bot:</strong> ${escapeHTML(m.reply || "(no reply)")}</div>`;
    if (m.status === "rejected" && m.draft) {
      replyPart += `<div class="turn-rejected">Rejected bot draft: ${escapeHTML(m.draft)}</div>`;
    }
    if (m.status !== "delivered" && m.reviewedAt) {
      replyPart += `<div class="lv-reviewed">Reviewed ${escapeHTML(fmtDate(m.reviewedAt))}</div>`;
    }
  }
  return `
    <div class="turn lv-turn ${m.status === "pending" ? "rq-card" : ""}
                ${m.escalated && m.status === "pending" ? "rq-escalated" : ""}"
         id="lvturn-${m.messageID}" data-status="${escapeHTML(m.status)}">
      <div class="turn-q"><strong>User:</strong> ${escapeHTML(m.question)}</div>
      ${turnMetaHTML(m)}
      ${replyPart}
    </div>`;
}

async function liveResolve(idx, mid, action) {
  const body = { action };
  if (action === "edit") {
    const ta = $(`lvedit-${mid}`);
    const text = ta.value.trim();
    if (!text) { alert("The edited reply cannot be empty."); return; }
    if (text === ta.defaultValue.trim()) {
      body.action = "approve"; // unchanged text = approval, not a rejection
    } else {
      body.reply = text;
    }
  }
  const a = $(`lvapprove-${mid}`), s = $(`lvsend-${mid}`);
  if (a) a.disabled = true;
  if (s) s.disabled = true;

  const r = await api(`/api/admin/review/${mid}`, {
    method: "POST",
    body: JSON.stringify(body),
  });
  if (r.error) alert(r.error); // 409: already reviewed elsewhere — refresh shows it
  await refreshTranscript(idx);
}

/* ===================== RENAME (case label) ===================== */
function openLiveRename(idx) {
  $(`lvtitle-${idx}`).classList.add("hidden");
  $(`lvrenamebox-${idx}`).classList.remove("hidden");
  const input = $(`lvrenameinput-${idx}`);
  input.value = $(`lvtitle-${idx}`).dataset.title || "";
  input.focus();
  input.select();
}

function cancelLiveRename(idx) {
  $(`lvrenamebox-${idx}`).classList.add("hidden");
  $(`lvtitle-${idx}`).classList.remove("hidden");
}

async function saveLiveRename(idx) {
  const slot = slots[idx];
  if (!slot || !slot.sessionID) return;
  const title = $(`lvrenameinput-${idx}`).value.trim();
  if (!title) { cancelLiveRename(idx); return; }
  const r = await api(`/api/admin/sessions/${slot.sessionID}/rename`, {
    method: "POST",
    body: JSON.stringify({ title }),
  });
  if (r.error) { alert(r.error); return; }
  const el = $(`lvtitle-${idx}`);
  el.textContent = r.title;
  el.dataset.title = r.title;
  cancelLiveRename(idx);
  refreshLive();
}
