/* ===========================================================================
   common.js — helpers shared by every page.
   Sections: auth storage · API wrapper · DOM/HTML helpers · sidebar · dates
   =========================================================================== */

const API = ""; // same-origin

/* ---------- Auth storage ----------
   The Supabase access token + active session id are kept in localStorage so
   auth survives navigation between pages. */
function getToken() { return localStorage.getItem("token"); }
function setToken(t) { localStorage.setItem("token", t); }
function getSessionID() { return localStorage.getItem("sessionID"); }
function setSessionID(id) { localStorage.setItem("sessionID", id); }
function clearAuth() {
  localStorage.removeItem("token");
  localStorage.removeItem("sessionID");
  localStorage.removeItem("role");
}

// Redirect to /login if not authenticated. Call at the top of protected pages.
function requireAuth() {
  if (!getToken()) {
    location.href = "/login";
    return false;
  }
  return true;
}

async function logout() {
  await api("/auth/logout", { method: "POST" }).catch(() => {});
  clearAuth();
  location.href = "/login";
}

/* ---------- API wrapper ----------
   JSON fetch with the auth header attached. Always resolves to an object;
   failures come back as { error } so callers never need try/catch. */
async function api(path, opts = {}) {
  const token = getToken();
  opts.headers = Object.assign(
    { "Content-Type": "application/json" },
    token ? { Authorization: "Bearer " + token } : {},
    opts.headers || {}
  );
  let res;
  try {
    res = await fetch(API + path, opts);
  } catch (e) {
    return { error: "Cannot reach server. Is it running?" };
  }
  // A 401 from a protected endpoint means the token expired -> back to login.
  // But on /auth/* endpoints 401 means bad credentials: fall through so the
  // server's message is shown instead of reloading the page (which erased it).
  if (res.status === 401 && !path.startsWith("/auth/")) {
    clearAuth();
    location.href = "/login";
    return { error: "Session expired. Please log in again." };
  }
  try {
    return await res.json();
  } catch {
    return { error: "Server error (" + res.status + ")" };
  }
}

/* ---------- DOM / HTML helpers ---------- */
const $ = (id) => document.getElementById(id);

function escapeHTML(s) {
  return String(s ?? "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#39;");
}

// Placeholder / status paragraphs used by every page.
function placeholderHTML(text, extraClass = "") {
  return `<p class="placeholder${extraClass ? " " + extraClass : ""}">${escapeHTML(text)}</p>`;
}
function showPlaceholder(container, text) {
  container.innerHTML = placeholderHTML(text);
}
function showErrorPlaceholder(container, msg) {
  container.innerHTML = placeholderHTML(msg, "text-danger");
}

/* ---------- Sidebar (shared across chat / analysis / resources) ----------
   The `sidebar-open` class on <html> drives both states: on desktop it slides
   the sidebar in/out of the layout, on mobile it opens an off-canvas drawer
   with a scrim. The default (open on desktop, closed on mobile) is set by a
   tiny inline script in app_base.html's <head> to avoid a flash on load. */
function toggleSidebar() {
  document.documentElement.classList.toggle("sidebar-open");
}
function closeSidebar() {
  document.documentElement.classList.remove("sidebar-open");
}
function isMobileViewport() {
  return window.matchMedia("(max-width: 900px)").matches;
}
// Escape closes the drawer on mobile.
document.addEventListener("keydown", (e) => {
  if (e.key === "Escape" && isMobileViewport()) closeSidebar();
});

/* ---------- Dates ---------- */
// "2026-06-27T10:31:00+00:00" -> "2026-06-27 10:31"
function fmtDate(iso) {
  if (!iso) return "";
  const d = new Date(iso);
  if (isNaN(d)) return String(iso);
  const pad = (n) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ` +
         `${pad(d.getHours())}:${pad(d.getMinutes())}`;
}

/* ---------- Shared page helpers ---------- */
// Roles allowed into the staff site (mirrors staff_required on the server).
const STAFF_ROLES = ["staff", "admin"];

// Status line under the auth forms (login + staff login pages).
function setAuthMsg(text, kind = "") {
  const el = $("authMsg");
  el.textContent = text;
  el.className = "auth-msg" + (kind ? " " + kind : "");
}

// Auto-name a fresh "New chat" from its first message (chat + test bench).
async function autoTitleFromMessage(sessionID, firstMessage, onApplied) {
  const title = firstMessage.trim().slice(0, 40) || "New chat";
  const r = await api(`/sessions/${sessionID}`, {
    method: "PATCH",
    body: JSON.stringify({ title }),
  });
  if (r && !r.error) onApplied(r.title);
}

// Sorted horizontal bar rows for a {label: count} map, largest first
// (emotion distributions, risk-band distribution).
function countBarsHTML(counts) {
  const entries = Object.entries(counts || {}).sort((a, b) => b[1] - a[1]);
  const max = entries.length ? entries[0][1] : 1;
  return entries.map(([label, count]) => `
    <div class="bar-row">
      <div class="bar-label">${escapeHTML(label)}</div>
      <div class="bar-track"><div class="bar-fill" style="width:${Math.round((count / max) * 100)}%"></div></div>
      <div class="bar-count">${count}</div>
    </div>`).join("");
}
