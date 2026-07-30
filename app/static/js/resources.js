/* ===========================================================================
   resources.js — resources page. Uses helpers from common.js.
   Guides/exercises come from the `resources` table (uploaded by
   scripts/scrape_resources.py) and are read entirely in-app: a detail view
   with an Info tab, a steps tab, and a reference hyperlink at the bottom.
   =========================================================================== */

let allResources = [];
let tests = [];
let activeCategory = "All";

// State for the test being taken.
let activeTest = null;
let testAnswers = [];

const TESTS_CATEGORY = "Self-Tests";
const TEST_ICONS = {
  "stress-level-test": "🌡️",
  "self-esteem-test": "🪞",
  "depression-test": "🌦️",
  "suicide-risk-check": "💛",
};

/* Per-resource icon, with a category fallback for anything added later. */
const RESOURCE_ICONS = {
  "stopp-technique": "🛑",
  "478-breathing": "🌬️",
  "54321-grounding": "🖐️",
  "deep-breathing": "🧘",
  "understanding-stress": "🧠",
  "exam-stress-tips": "📝",
  "understanding-anger": "🔥",
  "anger-management-tips": "❄️",
  "breakup-coping": "💔",
  "suicide-risk-awareness": "💛",
};
const CATEGORY_META = {
  "Calm Down Exercises": { icon: "🧘", tint: "tint-calm" },
  "Stress":              { icon: "🧠", tint: "tint-stress" },
  "Anger":               { icon: "🔥", tint: "tint-anger" },
  "Relationships":       { icon: "💙", tint: "tint-love" },
  "Crisis Support":      { icon: "💛", tint: "tint-test" },
  "Self-Tests":          { icon: "📋", tint: "tint-test" },
};

function resourceIcon(rsc) {
  return RESOURCE_ICONS[rsc.slug] || (CATEGORY_META[rsc.category] || {}).icon || "📖";
}
function tintClass(rsc) {
  return (CATEGORY_META[rsc.category] || {}).tint || "tint-calm";
}

if (requireAuth()) initResources();

async function initResources() {
  const root = $("resourcesRoot");
  showPlaceholder(root, "Loading resources…");
  const [r, tr] = await Promise.all([api("/api/resources"), api("/api/tests")]);
  if (r.error) { showErrorPlaceholder(root, r.error); return; }
  allResources = r.resources || [];
  tests = tr.tests || []; // tests are optional: the page still works without them
  if (!allResources.length && !tests.length) {
    showPlaceholder(root, "No resources available yet.");
    return;
  }
  // Deep link from chat: /resources#test=<slug> jumps straight into that quiz
  // (used by the elevated-suicide-risk suggestion on chat replies).
  const m = location.hash.match(/^#test=([\w-]+)$/);
  if (m) {
    history.replaceState(null, "", location.pathname); // don't re-open on refresh
    const idx = tests.findIndex((t) => t.slug === m[1]);
    if (idx !== -1) { openTest(idx); return; }
  }
  renderList();
}

/* ---------- List view (category chips + card grid) ---------- */
function categories() {
  const seen = [];
  for (const rsc of allResources) {
    const c = rsc.category || "Other";
    if (!seen.includes(c)) seen.push(c);
  }
  if (tests.length) seen.push(TESTS_CATEGORY);
  return seen;
}

function renderList() {
  const chips = ["All", ...categories()].map((c, i) => {
    const icon = c === "All" ? "✨" : (CATEGORY_META[c] || {}).icon || "📖";
    return `
    <button class="chip ${c === activeCategory ? "active" : ""}"
            onclick="filterCategory(${i})">${icon} ${escapeHTML(c)}</button>`;
  }).join("");
  const shown = allResources.filter(
    (rsc) => activeCategory === "All" || (rsc.category || "Other") === activeCategory);
  const shownTests = (activeCategory === "All" || activeCategory === TESTS_CATEGORY)
    ? tests : [];
  $("resourcesRoot").innerHTML = `
    <h2>Self-Help Resources</h2>
    <div class="chip-row">${chips}</div>
    <div class="resource-grid">
      ${shown.map((rsc) => cardHTML(rsc, allResources.indexOf(rsc))).join("")}
      ${shownTests.map((t) => testCardHTML(t, tests.indexOf(t))).join("")}
    </div>`;
}

function filterCategory(i) {
  activeCategory = i === 0 ? "All" : categories()[i - 1];
  renderList();
}

function cardHTML(rsc, index) {
  return `
    <div class="resource-card" onclick="openCard(${index})">
      <div class="rc-body">
        <div class="rc-icon ${tintClass(rsc)}">${resourceIcon(rsc)}</div>
        <div class="rc-cat">${escapeHTML(rsc.category || "Resource")}</div>
        <h3>${escapeHTML(rsc.title)}</h3>
        <p>${escapeHTML(rsc.summary || "")}</p>
      </div>
    </div>`;
}

function testCardHTML(t, index) {
  return `
    <div class="resource-card" onclick="openTest(${index})">
      <div class="rc-body">
        <div class="rc-icon tint-test">${TEST_ICONS[t.slug] || "📋"}</div>
        <div class="rc-cat">${escapeHTML(TESTS_CATEGORY)}</div>
        <h3>${escapeHTML(t.title)}</h3>
        <p>${t.numQuestions} quick questions with your result at the end.</p>
      </div>
    </div>`;
}

// Cards pass an index (not interpolated ids/urls) so no escaping pitfalls.
function openCard(index) {
  const rsc = allResources[index];
  if (rsc) openResource(rsc.id);
}

/* ---------- Detail view ---------- */
async function openResource(id) {
  const root = $("resourcesRoot");
  showPlaceholder(root, "Loading…");
  const r = await api(`/api/resources/${id}`);
  if (r.error) { showErrorPlaceholder(root, r.error); return; }
  root.innerHTML = articleDetailHTML(r);
}

function backLinkHTML() {
  return '<div class="back-link" onclick="renderList()">← Back to resources</div>';
}

function articleDetailHTML(r) {
  const hero = r.image_url
    ? `<img class="detail-hero" src="${escapeHTML(r.image_url)}" alt="" />` : "";
  // Exercises read better as "How to do it"; guides keep "Steps to overcome it".
  const stepsLabel = (r.category || "").toLowerCase().includes("exercise")
    ? "How to do it" : "Steps to overcome it";
  const reference = r.external_url ? `
    <p class="reference">Reference:
      <a href="${escapeHTML(r.external_url)}" target="_blank" rel="noopener">
        ${escapeHTML(r.source || r.external_url)}</a>
    </p>` : "";
  return `
    <div class="resource-detail">
      ${backLinkHTML()}
      ${hero}
      <div class="rc-icon lg ${tintClass(r)}">${resourceIcon(r)}</div>
      <div class="detail-cat">${escapeHTML(r.category || "Resource")}</div>
      <h2>${escapeHTML(r.title)}</h2>
      <div class="detail-tabs">
        <button class="detail-tab active" data-tab="info" onclick="showTab('info')">Info</button>
        <button class="detail-tab" data-tab="steps" onclick="showTab('steps')">${stepsLabel}</button>
      </div>
      <div id="tab-info" class="tab-panel">
        ${escapeHTML(r.info || r.summary || "").replace(/\n/g, "<br>")}
      </div>
      <div id="tab-steps" class="tab-panel hidden">${stepsHTML(r.steps)}</div>
      ${reference}
    </div>`;
}

function stepsHTML(steps) {
  const items = (steps || []).map((s, i) => `
    <div class="step">
      <div class="step-num">${i + 1}</div>
      <div class="step-body">
        ${s.title ? `<h4>${escapeHTML(s.title)}</h4>` : ""}
        <p>${escapeHTML(s.content)}</p>
      </div>
    </div>`).join("");
  return items || placeholderHTML("No steps listed for this resource.");
}

function showTab(name) {
  document.querySelectorAll(".detail-tab").forEach((b) =>
    b.classList.toggle("active", b.dataset.tab === name));
  $("tab-info").classList.toggle("hidden", name !== "info");
  $("tab-steps").classList.toggle("hidden", name !== "steps");
}

/* ---------- Self-test flow (questions -> submit -> result) ---------- */
async function openTest(index) {
  const meta = tests[index];
  if (!meta) return;
  const root = $("resourcesRoot");
  showPlaceholder(root, "Loading…");
  const t = await api(`/api/tests/${meta.id}`);
  if (t.error) { showErrorPlaceholder(root, t.error); return; }
  activeTest = t;
  startTestForm();
}

function startTestForm() {
  testAnswers = new Array(activeTest.questions.length).fill(null);
  $("resourcesRoot").innerHTML = testFormHTML(activeTest);
  scrollContentTop();
}

function scrollContentTop() {
  const content = document.querySelector(".content");
  if (content) content.scrollTop = 0;
}

function testDisclaimerHTML(t) {
  return `
    <p class="reference">This screening is for information only — it is not a
      diagnosis. Reference:
      <a href="${escapeHTML(t.reference || "")}" target="_blank" rel="noopener">
        ${escapeHTML(t.source || t.reference || "")}</a>
    </p>`;
}

function testFormHTML(t) {
  const questions = t.questions.map((q, qi) => `
    <div class="q-block">
      <div class="q-text">${qi + 1}. ${escapeHTML(q.text)}</div>
      <div class="q-opts">
        ${q.options.map((o, oi) => `
          <button class="opt" onclick="pickAnswer(${qi}, ${oi}, this)">
            ${escapeHTML(o.label)}</button>`).join("")}
      </div>
    </div>`).join("");
  return `
    <div class="resource-detail">
      ${backLinkHTML()}
      <div class="rc-icon lg tint-test">${TEST_ICONS[t.slug] || "📋"}</div>
      <div class="detail-cat">${escapeHTML(TESTS_CATEGORY)}</div>
      <h2>${escapeHTML(t.title)}</h2>
      <p class="test-intro">${escapeHTML(t.description || "")}</p>
      ${questions}
      <div class="test-actions">
        <button id="submitTest" class="btn btn-primary" disabled onclick="submitTest()">
          See my result</button>
        <span id="answeredCount" class="muted">0 / ${t.questions.length} answered</span>
      </div>
      ${testDisclaimerHTML(t)}
    </div>`;
}

function pickAnswer(qi, oi, btn) {
  testAnswers[qi] = oi;
  btn.closest(".q-block").querySelectorAll(".opt")
    .forEach((b) => b.classList.remove("selected"));
  btn.classList.add("selected");
  const done = testAnswers.filter((a) => a !== null).length;
  $("answeredCount").textContent = `${done} / ${testAnswers.length} answered`;
  $("submitTest").disabled = done !== testAnswers.length;
}

async function submitTest() {
  const btn = $("submitTest");
  btn.disabled = true;
  btn.textContent = "Scoring…";
  const r = await api(`/api/tests/${activeTest.id}/submit`, {
    method: "POST",
    body: JSON.stringify({ answers: testAnswers }),
  });
  if (r.error) {
    btn.disabled = false;
    btn.textContent = "See my result";
    alert(r.error);
    return;
  }
  $("resourcesRoot").innerHTML = testResultHTML(activeTest, r);
  scrollContentTop();
}

function testResultHTML(t, r) {
  // Safety first: when the result carries a crisis alert (PHQ-9 item 9, or
  // always for the Suicide Risk Check), the counsellor/helpline block renders
  // ABOVE the score so it's the first thing the user sees.
  const alert = r.alert
    ? `<div class="test-alert">${escapeHTML(r.alert)}</div>` : "";
  return `
    <div class="resource-detail">
      ${backLinkHTML()}
      <div class="detail-cat">${escapeHTML(TESTS_CATEGORY)}</div>
      <h2>${escapeHTML(t.title)}</h2>
      <div class="test-result">
        ${alert}
        <div class="score-big">${r.score}<span class="score-max">/ ${r.max}</span></div>
        <div class="score-band">${escapeHTML(r.band)}</div>
        <p class="score-advice">${escapeHTML(r.advice || "")}</p>
      </div>
      <button class="btn btn-ghost" onclick="startTestForm()">Retake test</button>
      ${testDisclaimerHTML(t)}
    </div>`;
}
