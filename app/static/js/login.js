// Login / register page. Email-verified auth via Supabase. The register tab
// shows the User Agreement (fetched from the DB) and requires acceptance.
if (getToken()) location.href = "/chat";

let authMode = "login"; // "login" | "register"
let activeAgreement = null;

function switchTab(mode) {
  authMode = mode;
  $("tabLogin").classList.toggle("active", mode === "login");
  $("tabRegister").classList.toggle("active", mode === "register");
  $("authBtn").textContent = mode === "login" ? "Login" : "Create account";
  $("registerExtras").classList.toggle("hidden", mode !== "register");
  // The "min 6 characters" hint is only relevant when creating an account.
  $("password").placeholder = mode === "register"
    ? "Create a password (min 6 characters)" : "Password";
  $("password").setAttribute(
    "autocomplete", mode === "register" ? "new-password" : "current-password");
  setAuthMsg("");
  updateBtnState();
  if (mode === "register" && !activeAgreement) loadAgreement();
}

async function loadAgreement() {
  const r = await api("/agreements/active");
  const body = $("agreementBody");
  if (r.error) {
    body.textContent = "Could not load the agreement. You can still continue.";
    return;
  }
  activeAgreement = r;
  $("agreementTitle").textContent = `${r.title} (v${r.version})`;
  body.textContent = r.content;
  $("agreeCheckLabel").innerHTML =
    `I have read and accept the ${escapeHTML(r.title)} (v${escapeHTML(r.version)}).`;
}

function updateBtnState() {
  if ($("authBtn").classList.contains("loading")) return; // don't override mid-request
  if (authMode !== "register") { $("authBtn").disabled = false; return; }
  $("authBtn").disabled = !$("agreeChk").checked;
}

// Spinner + disabled while a request is in flight; restores the right label after.
function setLoading(loading, text) {
  const btn = $("authBtn");
  if (loading) {
    btn.disabled = true;
    btn.classList.add("loading");
    btn.innerHTML = `<span class="spinner"></span>${escapeHTML(text || "Please wait…")}`;
  } else {
    btn.classList.remove("loading");
    btn.textContent = authMode === "login" ? "Login" : "Create account";
    updateBtnState();
  }
}

async function submitAuth() {
  const email = $("email").value.trim().toLowerCase();
  const password = $("password").value;

  // Email is always required.
  if (!email) { setAuthMsg("Please enter your email address.", "error"); return; }

  if (authMode === "register") {
    // The 6-character minimum applies only when creating an account.
    if (password.length < 6) {
      setAuthMsg("Password must be at least 6 characters.", "error");
      return;
    }
    // 7-15 digits once spaces/dashes are stripped (server re-validates).
    const phoneDigits = $("phone").value.replace(/[ \-().]/g, "");
    if (!/^\+?\d{7,15}$/.test(phoneDigits)) {
      setAuthMsg("Please enter a valid phone number (e.g. +60123456789).", "error");
      return;
    }
    if (!$("agreeChk").checked) {
      setAuthMsg("Please accept the User Agreement to register.", "error");
      return;
    }
  } else if (!password) {
    // Login: any password is accepted as input; the server decides if it's right.
    setAuthMsg("Please enter your password.", "error");
    return;
  }

  setAuthMsg("");
  setLoading(true, authMode === "register" ? "Creating account…" : "Signing in…");

  try {
    if (authMode === "register") {
      const r = await api("/auth/register", {
        method: "POST",
        body: JSON.stringify({ email, password, agree: true,
                               phone: $("phone").value.trim() }),
      });
      if (r.error) { setAuthMsg(r.error, "error"); return; }

      if (r.needsVerification) {
        setAuthMsg(r.message || "Check your email to verify your account, then log in.", "ok");
        switchTab("login");
        return;
      }
      // Email confirmation disabled on the project -> token returned, go straight in.
      setToken(r.token);
      localStorage.removeItem("sessionID");
      location.href = "/chat";
      return;
    }

    // Login
    const r = await api("/auth/login", {
      method: "POST",
      body: JSON.stringify({ email, password }),
    });
    if (r.error) { setAuthMsg(r.error, "error"); return; }

    setToken(r.token);
    if (r.role) localStorage.setItem("role", r.role);
    localStorage.removeItem("sessionID"); // start a fresh, blank chat
    // This form is the user entrance; staff have their own at /admin/login.
    location.href = "/chat";
  } finally {
    setLoading(false);
  }
}

document.addEventListener("DOMContentLoaded", () => {
  $("agreeChk").addEventListener("change", updateBtnState);
});
