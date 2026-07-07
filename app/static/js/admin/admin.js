/* ===========================================================================
   admin.js — staff dashboard. Uses helpers from common.js.
   The page is only a shell: all data comes from the guarded /api/admin
   endpoints (server-side checks). Roles: staff see the overview; admins also
   get the staff-accounts section (create staff logins by email).
   =========================================================================== */

const STAFF_ROLES = ["staff", "admin"];

let staffCache = [];

if (requireAuth()) initAdmin();

async function initAdmin() {
  const me = await api("/auth/me");
  if (me.error) return; // expired token -> api() already redirected to /login
  if (!STAFF_ROLES.includes(me.role)) {
    location.href = "/chat";
    return;
  }
  $("adminEmail").textContent = me.email;

  loadStats();
  if (me.role === "admin") {
    $("staffSection").classList.remove("hidden");
    loadStaff();
  }
}

/* ---------- Overview stats ---------- */
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

/* ---------- Staff accounts (admin only) ---------- */
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
