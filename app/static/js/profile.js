// My Profile — view and edit your own details. Reads GET /auth/me and writes
// PATCH /auth/me; the server owns validation (email and role are not editable).
if (!requireAuth()) throw new Error("redirecting");

let loadedProfile = null;

function setMsg(text, kind = "") {
  const el = $("pfMsg");
  el.textContent = text;
  el.className = "auth-msg no-margin" + (kind ? " " + kind : "");
}

// Age is derived, never stored — show it next to the date so the user can see
// what the counsellor will see.
function showAge() {
  const age = ageFromDOB($("pfDob").value);
  $("pfAge").textContent = age === null ? "" : `(age ${age})`;
}

async function loadProfile() {
  const r = await api("/auth/me");
  if (r.error) { setMsg(r.error, "error"); return; }
  loadedProfile = r;
  $("pfEmail").value = r.email || "";
  $("pfName").value = r.name || "";
  $("pfPhone").value = r.phone || "";
  $("pfDob").value = r.dateOfBirth || "";
  $("pfGender").value = r.gender || "";
  showAge();
  $("pfJoined").textContent = r.joinedAt ? `Member since ${fmtDate(r.joinedAt)}` : "";
}

async function saveProfile() {
  const name = $("pfName").value.trim();
  const phone = $("pfPhone").value.trim();
  const dob = $("pfDob").value;
  const gender = $("pfGender").value;

  // Same courtesy checks as the register form; the server re-validates.
  if (!name) { setMsg("Your name is required.", "error"); return; }
  if (!/^\+?\d{7,15}$/.test(phone.replace(/[ \-().]/g, ""))) {
    setMsg("Please enter a valid phone number (e.g. +60123456789).", "error");
    return;
  }
  const minAge = minAgeFrom($("pfDob"));
  const age = ageFromDOB(dob);
  if (age === null) { setMsg("Please enter your date of birth.", "error"); return; }
  if (age < minAge) {
    setMsg(`You must be at least ${minAge} years old.`, "error");
    return;
  }
  if (!gender) { setMsg("Please select a gender.", "error"); return; }

  const btn = $("pfSave");
  btn.disabled = true;
  setMsg("Saving…");
  try {
    const r = await api("/auth/me", {
      method: "PATCH",
      body: JSON.stringify({ name, phone, gender, dateOfBirth: dob }),
    });
    if (r.error) { setMsg(r.error, "error"); return; }
    loadedProfile = r;
    setMsg("Saved.", "ok");
    setTimeout(() => setMsg(""), 3000);
  } finally {
    btn.disabled = false;
  }
}

document.addEventListener("DOMContentLoaded", loadProfile);
