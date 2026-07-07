/* ===========================================================================
   staff_login.js — the dedicated staff login page (/admin/login).
   Same Supabase login as the user page, but only accounts whose role is
   staff/admin get through; everyone else is told this isn't their entrance.
   =========================================================================== */

const STAFF_ROLES = ["staff", "admin"];

// Already signed in: staff go to the dashboard, everyone else to the app.
if (getToken()) {
  api("/auth/me").then((me) => {
    if (!me.error) {
      location.href = STAFF_ROLES.includes(me.role) ? "/admin" : "/chat";
    }
  });
}

function setAuthMsg(text, kind = "") {
  const el = $("authMsg");
  el.textContent = text;
  el.className = "auth-msg" + (kind ? " " + kind : "");
}

function setLoading(loading) {
  const btn = $("staffBtn");
  btn.disabled = loading;
  btn.innerHTML = loading
    ? '<span class="spinner"></span>Signing in…'
    : "Login";
}

async function submitStaffLogin() {
  const email = $("email").value.trim().toLowerCase();
  const password = $("password").value;
  if (!email || !password) {
    setAuthMsg("Please enter your email and password.", "error");
    return;
  }

  setAuthMsg("");
  setLoading(true);
  try {
    const r = await api("/auth/login", {
      method: "POST",
      body: JSON.stringify({ email, password }),
    });
    if (r.error) { setAuthMsg(r.error, "error"); return; }

    if (!STAFF_ROLES.includes(r.role)) {
      // Valid account, but not staff: don't sign them in here.
      setAuthMsg("This account doesn't have staff access. Use the user login instead.", "error");
      return;
    }

    setToken(r.token);
    localStorage.setItem("role", r.role);
    localStorage.removeItem("sessionID");
    location.href = "/admin";
  } finally {
    setLoading(false);
  }
}
