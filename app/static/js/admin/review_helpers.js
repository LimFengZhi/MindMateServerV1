/* ===========================================================================
   review_helpers.js — shared by every staff page (dashboard, test benches).
   Role guard + the per-reply rating/feedback controls + JSON export.
   Load BEFORE the page's own script.
   =========================================================================== */

// Verifies the signed-in account is staff/admin; fills the topbar email.
// (STAFF_ROLES comes from common.js, loaded on every page.)
// Returns the /auth/me payload, or null (after redirecting) for non-staff.
async function requireStaff() {
  const me = await api("/auth/me");
  if (me.error) return null; // expired token -> api() already redirected
  if (!STAFF_ROLES.includes(me.role)) {
    location.href = "/chat";
    return null;
  }
  const el = $("adminEmail");
  if (el) el.textContent = me.email;
  return me;
}

/* ---------- diagnostic meta line for one turn ---------- */
function turnMetaHTML(m) {
  const conf = (m.confidence != null) ? ` · ${Math.round(m.confidence * 100)}%` : "";
  const esc = m.escalated ? ' <span class="tag escalated">escalated</span>' : "";
  return `<div class="turn-meta">
    <span class="emotion-pill">${escapeHTML(m.emotion || "Unknown")}${conf}</span>${esc}
  </div>`;
}

/* ---------- per-reply rating + feedback ---------- */
function reviewedStatusHTML(rating, feedback) {
  if (!rating && !feedback) {
    return '<span class="not-reviewed">Not reviewed yet</span>';
  }
  const stars = rating ? "★".repeat(rating) + "☆".repeat(5 - rating) : "";
  const text = feedback ? `“${escapeHTML(feedback)}”` : "";
  return `<span class="reviewed">Reviewed: ${stars}${stars && text ? " · " : ""}${text}</span>`;
}

function feedbackControlsHTML(m) {
  const mid = m.messageID;
  return `
    <div class="fb-given" id="fb-given-${mid}">${reviewedStatusHTML(m.rating, m.feedback)}</div>
    <div class="fb-row">
      <select id="fb-rating-${mid}">
        <option value="">rating</option>
        ${[1, 2, 3, 4, 5].map((n) => `
          <option value="${n}" ${m.rating === n ? "selected" : ""}>${n} ★</option>`).join("")}
      </select>
      <input id="fb-text-${mid}" placeholder="Feedback for this reply…"
             value="${escapeHTML(m.feedback || "")}" />
      <button class="btn" id="fb-save-${mid}" onclick="saveFeedback('${mid}')">Save</button>
    </div>`;
}

async function saveFeedback(mid) {
  const rating = $(`fb-rating-${mid}`).value;
  const feedback = $(`fb-text-${mid}`).value.trim();
  if (!rating && !feedback) return;

  const body = {};
  if (rating) body.rating = Number(rating);
  if (feedback) body.feedback = feedback;

  const btn = $(`fb-save-${mid}`);
  btn.disabled = true;
  const r = await api(`/api/admin/messages/${mid}/feedback`, {
    method: "POST",
    body: JSON.stringify(body),
  });
  btn.disabled = false;
  if (r.error) { alert(r.error); return; }
  $(`fb-given-${mid}`).innerHTML = reviewedStatusHTML(r.rating, r.feedback);
  btn.textContent = "Saved ✓";
  setTimeout(() => { btn.textContent = "Save"; }, 1600);
}

/* ---------- JSON export (needs the auth header, so fetch -> blob) ---------- */
async function exportSession(sessionID) {
  const res = await fetch(`/api/admin/sessions/${sessionID}/export`, {
    headers: { Authorization: "Bearer " + getToken() },
  });
  if (!res.ok) { alert(`Export failed (${res.status})`); return; }
  const url = URL.createObjectURL(await res.blob());
  const a = document.createElement("a");
  a.href = url;
  a.download = `session-${sessionID}.json`;
  a.click();
  URL.revokeObjectURL(url);
}
