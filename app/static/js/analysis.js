/* ===========================================================================
   analysis.js — per-session emotion analysis page. Uses helpers from common.js.
   Renders three blocks: stat cards, emotion distribution bars, message timeline.
   =========================================================================== */

if (requireAuth()) initAnalysis();

async function initAnalysis() {
  const r = await api("/sessions");
  const sessions = r.sessions || [];
  const sel = $("sessionSelect");
  if (!sessions.length) {
    sel.innerHTML = '<option value="">No sessions yet</option>';
    showPlaceholder($("analysisBody"),
      "Start chatting first, then come back to see your emotion analysis.");
    return;
  }
  sel.innerHTML = sessions
    .map((s) => `<option value="${s.sessionID}">${escapeHTML(s.title || "New chat")} — ${escapeHTML(fmtDate(s.createdAt))}</option>`)
    .join("");

  // Preselect the chat the user was last in, if it still exists.
  const active = getSessionID();
  const match = sessions.find((s) => s.sessionID === active);
  sel.value = match ? active : sessions[0].sessionID;
  loadAnalysis(sel.value);
}

async function loadAnalysis(sessionID) {
  if (!sessionID) return;
  const body = $("analysisBody");
  showPlaceholder(body, "Loading…");

  const r = await api(`/sessions/${sessionID}/analysis`);
  if (r.error) { showErrorPlaceholder(body, r.error); return; }

  const summary = r.summary || { total: 0, counts: {}, dominant: null, escalations: 0 };
  const messages = r.messages || [];

  if (!summary.total) {
    showPlaceholder(body, "No messages in this session yet.");
    return;
  }

  body.innerHTML = renderCards(summary) + renderDistribution(summary) + renderTimeline(messages);
}

function statCardHTML(label, value, valueClass = "") {
  return `
    <div class="stat-card">
      <div class="stat-label">${escapeHTML(label)}</div>
      <div class="stat-value${valueClass ? " " + valueClass : ""}">${value}</div>
    </div>`;
}

function renderCards(summary) {
  return `
    <div class="cards">
      ${statCardHTML("Messages", summary.total)}
      ${statCardHTML("Dominant emotion", escapeHTML(summary.dominant || "—"))}
      ${statCardHTML("Escalations", summary.escalations, summary.escalations ? "danger" : "")}
      ${statCardHTML("Distinct emotions", Object.keys(summary.counts || {}).length)}
    </div>`;
}

function renderDistribution(summary) {
  const entries = Object.entries(summary.counts || {}).sort((a, b) => b[1] - a[1]);
  const max = entries.length ? entries[0][1] : 1;
  const rows = entries.map(([emotion, count]) => {
    const pct = Math.round((count / max) * 100);
    return `
      <div class="bar-row">
        <div class="bar-label">${escapeHTML(emotion)}</div>
        <div class="bar-track"><div class="bar-fill" style="width:${pct}%"></div></div>
        <div class="bar-count">${count}</div>
      </div>`;
  }).join("");
  return `
    <div class="section-card">
      <h3>Emotion distribution</h3>
      ${rows}
    </div>`;
}

function renderTimeline(messages) {
  const items = messages.map((m) => {
    const when = fmtDate(m.created_at);
    const conf = (m.confidence != null) ? ` · ${Math.round(m.confidence * 100)}%` : "";
    const esc = m.escalated ? ' <span class="tag escalated">!</span>' : "";
    return `
      <div class="timeline-item">
        <div class="timeline-when">${escapeHTML(when)}</div>
        <div class="timeline-text" title="${escapeHTML(m.question)}">${escapeHTML(m.question)}</div>
        <span class="emotion-pill">${escapeHTML(m.emotion)}${conf}${esc}</span>
      </div>`;
  }).join("");
  return `
    <div class="section-card">
      <h3>Message timeline</h3>
      ${items}
    </div>`;
}
