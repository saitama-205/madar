// Madar frontend — plain JS, no build step. Talks to the FastAPI backend under /api (see CONTRACT.md).

const DAYS = ["Sunday", "Monday", "Tuesday", "Wednesday", "Thursday"];
const PERIODS = [1, 2, 3, 4, 5, 6, 7];
const PASTEL = {
  "Islamic Education": "#c9d6ff", Arabic: "#bfe9dc", English: "#ffd9c2", Math: "#d9c9ff", Science: "#c2eefa",
  "Social Studies": "#ffe7a8", Computer: "#bcd0f5", PE: "#ffc9d4", Art: "#e4f5b8", Music: "#e9c9f2",
};
const RULE_KINDS = {
  subject_not_in_period: "Subject never in a period",
  teacher_unavailable: "Teacher unavailable",
  pin_lesson: "Pin a lesson",
};

const state = {
  subjects: [], classes: [], teachers: [], rules: [],
  generated: null,            // true / false once checked
  stale: readStale(),         // data changed since the last Generate
  view: { mode: "class", id: null },
  ruleKind: "subject_not_in_period",
  teacherSubject: "",
  chat: [],                   // scheduler conversation: {role, content, proposals?, steps?}
};

// ---------- helpers ----------
async function api(path, options = {}) {
  const res = await fetch("/api" + path, {
    ...options,
    headers: options.body ? { "Content-Type": "application/json" } : undefined,
    body: options.body ? JSON.stringify(options.body) : undefined,
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data.message || `Request failed (${res.status})`);
  return data;
}
const $ = (sel, root = document) => root.querySelector(sel);
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);
const byId = (list, id) => list.find((x) => x.id === id);
const subjectName = (id) => byId(state.subjects, id)?.name ?? `Subject ${id}`;
const teacherName = (id) => byId(state.teachers, id)?.name ?? `Teacher ${id}`;
const className = (id) => byId(state.classes, id)?.name ?? `Class ${id}`;
const pastel = (name) => PASTEL[name] ?? "#e5f1ff";
const subjectChip = (id) => `<span class="chip" style="background:${pastel(subjectName(id))}">${esc(subjectName(id))}</span>`;
const iso = (s) => `\u2068${s}\u2069`; // keeps Arabic names from scrambling English text where <bdi> cannot be used
// Direction of a whole message from its own words, ignoring isolated names (an English reply may start with an Arabic name).
const textDir = (s) => {
  const t = String(s ?? "").replace(/\u2068[^\u2069]*\u2069/g, "");
  return (t.match(/[\u0600-\u06FF]/g) || []).length > (t.match(/[A-Za-z]/g) || []).length ? "rtl" : "ltr";
};
const options = (list, selected, label = (x) => iso(x.name)) =>
  list.map((x) => `<option value="${x.id}" ${x.id === selected ? "selected" : ""}>${esc(label(x))}</option>`).join("");

function readStale() { try { return localStorage.getItem("madar.stale") === "1"; } catch { return false; } }
function setStale(v) { state.stale = v; try { localStorage.setItem("madar.stale", v ? "1" : "0"); } catch {} }

let toastTimer;
function toast(text, isError = false) {
  const el = $("#toast");
  el.textContent = text;
  el.className = "toast show" + (isError ? " err" : "");
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => (el.className = "toast"), 3500);
}

async function busy(button, work) {
  button.disabled = true;
  try { await work(); } catch (e) { toast(e.message, true); } finally { button.disabled = false; }
}

// ---------- data ----------
async function loadAll() {
  [state.subjects, state.classes, state.teachers, state.rules] = await Promise.all(
    ["/subjects", "/classes", "/teachers", "/rules"].map((p) => api(p)));
  if (state.view.id == null || !byId(state.view.mode === "class" ? state.classes : state.teachers, state.view.id)) {
    state.view = { mode: "class", id: state.classes[0]?.id ?? null };
  }
  if (state.classes[0]) {
    const { lessons } = await api(`/timetable?class_id=${state.classes[0].id}`);
    state.generated = lessons.length > 0;
  } else state.generated = false;
}

// ---------- routing ----------
const routes = { timetable: renderTimetable, data: renderData, rules: renderRules, scheduler: renderScheduler };
function route() {
  const h = location.hash.slice(1) === "assistant" ? "scheduler" : location.hash.slice(1);   // old #assistant links
  return h in routes ? h : "timetable";
}
async function render() {
  const r = route();
  document.querySelectorAll(".tabs a").forEach((a) => a.classList.toggle("active", a.dataset.route === r));
  await routes[r]();
}
window.addEventListener("hashchange", render);

function heading(eyebrow, title, sentence) {
  const hero = $("#hero");
  hero.className = "hero-cards single";
  hero.innerHTML = `<div class="card glass"><div class="eyebrow">${eyebrow}</div><h1 class="title">${title}</h1><p class="help">${sentence}</p></div>`;
}

// ---------- timetable page ----------
function statusMessage() {
  if (!state.generated) return `<div class="msg warn">No timetable yet. Press Generate to build one.</div>`;
  if (state.stale) return `<div class="msg warn">Data or rules changed since the last run. Generate again to update the timetable.</div>`;
  return `<div class="msg ok">Timetable is up to date and keeps every rule.</div>`;
}

async function renderTimetable() {
  const hero = $("#hero");
  hero.className = "hero-cards";
  hero.innerHTML = `
    <div class="card glass wide">
      <div class="eyebrow">Amr bin Al-Aas Elementary</div>
      <h1 class="title">School timetable</h1>
      <div class="row"><button class="btn" id="generate">Generate</button></div>
      <div id="gen-status">${statusMessage()}</div>
    </div>
    <div class="card glass"><div class="stat-label">Classes</div><div class="stat">${state.classes.length}</div></div>
    <div class="card glass"><div class="stat-label">Teachers</div><div class="stat">${state.teachers.length}</div></div>
    <div class="card glass"><div class="stat-label">Rules</div><div class="stat">${state.rules.length}</div></div>`;

  $("#generate").onclick = (e) => busy(e.currentTarget, async () => {
    $("#gen-status").innerHTML = `<div class="msg warn">Building the timetable…</div>`;
    try {
      const r = await api("/timetable/generate", { method: "POST" });
      state.generated = true; setStale(false);
      $("#gen-status").innerHTML = `<div class="msg ok">Built ${r.lessons_count} lessons in ${r.seconds} s. Every rule is kept.</div>`;
      drawGrid();
    } catch (err) {
      $("#gen-status").innerHTML = `<div class="msg err">${esc(err.message)}</div>`;
    }
  });

  const { mode, id } = state.view;
  $("#page").innerHTML = `
    <section class="panel">
      <div class="row spread">
        <h2>Week view</h2>
        <div class="row">
          <div class="seg" role="tablist">
            <button data-mode="class" class="${mode === "class" ? "on" : ""}">Class</button>
            <button data-mode="teacher" class="${mode === "teacher" ? "on" : ""}">Teacher</button>
          </div>
          <select id="pick" aria-label="Choose ${mode}">
            ${mode === "class" ? options(state.classes, id)
              : options(state.teachers, id, (t) => `${iso(t.name)} · ${subjectName(t.subject_id)}`)}
          </select>
        </div>
      </div>
      <div id="grid"></div>
      <div class="legend">${state.subjects.map((s) => subjectChip(s.id)).join("")}</div>
    </section>`;

  document.querySelectorAll(".seg button").forEach((b) => (b.onclick = () => {
    const m = b.dataset.mode;
    state.view = { mode: m, id: (m === "class" ? state.classes : state.teachers)[0]?.id ?? null };
    renderTimetable();
  }));
  $("#pick").onchange = (e) => { state.view.id = Number(e.target.value); drawGrid(); };
  drawGrid();
}

async function drawGrid() {
  const box = $("#grid");
  if (!box) return;
  const { mode, id } = state.view;
  if (id == null) { box.innerHTML = `<div class="empty"><b>Nothing to show</b>Add a ${mode} first.</div>`; return; }
  let lessons;
  try { ({ lessons } = await api(`/timetable?${mode}_id=${id}`)); }
  catch (e) { box.innerHTML = `<div class="empty"><b>Could not load the timetable</b>${esc(e.message)}</div>`; return; }
  if (!lessons.length) {
    box.innerHTML = `<div class="empty"><b>No lessons yet</b>Press Generate to build the timetable.</div>`;
    return;
  }
  const at = new Map(lessons.map((l) => [`${l.day}-${l.period}`, l]));
  const blocked = new Set(mode === "teacher"
    ? state.rules.filter((r) => r.kind === "teacher_unavailable" && r.params.teacher_id === id)
        .map((r) => `${r.params.day}-${r.params.period}`)
    : []);

  let html = `<div></div>` + DAYS.map((d) => `<div class="dh">${d.slice(0, 3)}</div>`).join("");
  for (const p of PERIODS) {
    html += `<div class="ph">P${p}</div>`;
    for (let d = 0; d < 5; d++) {
      const l = at.get(`${d}-${p}`);
      if (l) {
        const sub = mode === "class" ? `<bdi>${esc(l.teacher)}</bdi>` : `Class ${esc(l.class)}`;
        html += `<div class="cell" style="background:${pastel(l.subject)}" title="${esc(l.subject)} · ${esc(l.teacher)} · ${esc(l.class)}"><b>${esc(l.subject)}</b><small>${sub}</small></div>`;
      } else if (blocked.has(`${d}-${p}`)) {
        html += `<div class="cell blocked"><small>Unavailable</small></div>`;
      } else {
        html += `<div class="cell free"><small>Free</small></div>`;
      }
    }
  }
  box.innerHTML = `<div class="grid">${html}</div>`;
}

// ---------- data page ----------
function renderData() {
  heading("School data", "Classes and teachers",
    "Add a class or a teacher here, then go back to the timetable and press Generate.");
  const grades = [1, 2, 3, 4, 5];
  const subjectFilter = state.teacherSubject;
  const teachers = state.teachers.filter((t) => !subjectFilter || t.subject_id === Number(subjectFilter));

  $("#page").innerHTML = `
    <section class="panel">
      <h2>Classes</h2>
      <p class="help">A new class gets the next free section number and has no teachers yet.</p>
      ${grades.map((g) => `
        <div class="grade-row">
          <strong>Grade ${g}</strong>
          ${state.classes.filter((c) => c.grade === g).map((c) => `<span class="chip">${esc(c.name)}</span>`).join("")}
          <button class="btn mini secondary" data-add-grade="${g}">+ Add section</button>
        </div>`).join("")}
    </section>

    <div class="two">
      <section class="panel">
        <h2>Add a teacher</h2>
        <p class="help">For each class you tick, this teacher takes over the subject from whoever teaches it now.</p>
        <div class="row">
          <label class="field">Name <input type="text" id="t-name" maxlength="100" placeholder="e.g. Sara K."></label>
          <label class="field">Subject <select id="t-subject">${options(state.subjects, null)}</select></label>
        </div>
        ${grades.map((g) => `
          <div class="grade-row"><strong>Grade ${g}</strong>
            ${state.classes.filter((c) => c.grade === g).map((c) =>
              `<label class="check"><input type="checkbox" value="${c.id}" class="t-class"> ${esc(c.name)}</label>`).join("")}
          </div>`).join("")}
        <div id="t-preview"></div>
        <div class="row" style="margin-top:14px"><button class="btn" id="t-save">Save teacher</button></div>
      </section>

      <section class="panel">
        <div class="row spread">
          <h2>Teachers (${teachers.length})</h2>
          <select id="t-filter" aria-label="Filter by subject">
            <option value="">All subjects</option>${options(state.subjects, Number(subjectFilter))}
          </select>
        </div>
        <table class="list">
          <thead><tr><th>Name</th><th>Subject</th><th>Classes</th><th></th></tr></thead>
          <tbody>${teachers.map((t) => `
            <tr>
              <td><bdi>${esc(t.name)}</bdi></td>
              <td>${subjectChip(t.subject_id)}</td>
              <td>${t.class_ids.map(className).map(esc).join(", ") || `<span style="color:var(--muted)">None</span>`}</td>
              <td><button class="btn mini secondary" data-view-teacher="${t.id}">Week</button></td>
            </tr>`).join("")}</tbody>
        </table>
      </section>
    </div>

    <section class="panel">
      <h2>Start over</h2>
      <p class="help">Wipes everything added since the start (classes, teachers, rules and the timetable) and reloads the original school data.</p>
      <button class="btn danger" id="reset">Reset school data</button>
    </section>`;

  document.querySelectorAll("[data-add-grade]").forEach((b) => (b.onclick = () => busy(b, async () => {
    const c = await api("/classes", { method: "POST", body: { grade: Number(b.dataset.addGrade) } });
    setStale(true); toast(`Class ${c.name} added. It needs teachers before Generate will work.`);
    await loadAll(); renderData();
  })));

  const preview = () => {
    const subject = Number($("#t-subject").value);
    const ids = [...document.querySelectorAll(".t-class:checked")].map((i) => Number(i.value));
    const takeovers = ids.map((cid) => {
      const old = state.teachers.find((t) => t.subject_id === subject && t.class_ids.includes(cid));
      return old ? `${className(cid)} from ${iso(old.name)}` : null;
    }).filter(Boolean);
    $("#t-preview").innerHTML = !ids.length
      ? `<div class="msg warn">No classes ticked: the teacher is saved but has no lessons.</div>`
      : takeovers.length
        ? `<div class="msg warn">Takes over ${esc(subjectName(subject))} in ${esc(takeovers.join("; "))}</div>`
        : `<div class="msg ok">Teaches ${esc(subjectName(subject))} in ${ids.length} class${ids.length > 1 ? "es" : ""}.</div>`;
  };
  $("#t-subject").onchange = preview;
  document.querySelectorAll(".t-class").forEach((i) => (i.onchange = preview));
  preview();

  $("#t-save").onclick = (e) => busy(e.currentTarget, async () => {
    const body = {
      name: $("#t-name").value,
      subject_id: Number($("#t-subject").value),
      class_ids: [...document.querySelectorAll(".t-class:checked")].map((i) => Number(i.value)),
    };
    const t = await api("/teachers", { method: "POST", body });
    setStale(true); toast(`${t.name} saved.`);
    await loadAll(); renderData();
  });

  $("#t-filter").onchange = (e) => { state.teacherSubject = e.target.value; renderData(); };
  document.querySelectorAll("[data-view-teacher]").forEach((b) => (b.onclick = () => {
    state.view = { mode: "teacher", id: Number(b.dataset.viewTeacher) };
    location.hash = "timetable";
  }));

  $("#reset").onclick = (e) => {
    if (!confirm("Reset all school data? Everything added, the rules and the timetable will be lost.")) return;
    busy(e.currentTarget, async () => {
      await api("/reset", { method: "POST" });
      setStale(false); toast("Original school data restored.");
      await loadAll(); renderData();
    });
  };
}

// ---------- rules page ----------
function describeRule(kind, p) {
  if (kind === "subject_not_in_period") return `${subjectName(p.subject_id)} is never in period ${p.period}`;
  if (kind === "teacher_unavailable") return `${teacherName(p.teacher_id)} is unavailable on ${DAYS[p.day]}, period ${p.period}`;
  if (kind === "pin_lesson") return `Class ${className(p.class_id)} always has ${subjectName(p.subject_id)} on ${DAYS[p.day]}, period ${p.period}`;
  return kind;
}

function ruleFields(kind) {
  const day = `<label class="field">Day <select data-p="day">${DAYS.map((d, i) => `<option value="${i}">${d}</option>`).join("")}</select></label>`;
  const period = `<label class="field">Period <select data-p="period">${PERIODS.map((p) => `<option>${p}</option>`).join("")}</select></label>`;
  const subject = `<label class="field">Subject <select data-p="subject_id">${options(state.subjects, null)}</select></label>`;
  if (kind === "subject_not_in_period") return subject + period;
  if (kind === "teacher_unavailable")
    return `<label class="field">Teacher <select data-p="teacher_id">${options(state.teachers, null, (t) => `${iso(t.name)} · ${subjectName(t.subject_id)}`)}</select></label>` + day + period;
  return `<label class="field">Class <select data-p="class_id">${options(state.classes, null)}</select></label>` + subject + day + period;
}

function renderRules() {
  heading("Rules", "Rules the solver keeps",
    "A saved rule is used the next time you press Generate. The current timetable does not change until then.");
  const kind = state.ruleKind;

  // Group teacher-unavailable rules by teacher so 80 rows stay readable.
  const byTeacher = new Map();
  const others = [];
  for (const r of state.rules) {
    if (r.kind === "teacher_unavailable") {
      if (!byTeacher.has(r.params.teacher_id)) byTeacher.set(r.params.teacher_id, []);
      byTeacher.get(r.params.teacher_id).push(r);
    } else others.push(r);
  }

  $("#page").innerHTML = `
    <section class="panel">
      <h2>Add a rule</h2>
      <p class="help">Pick a kind, fill it in, check the preview, then save.</p>
      <div class="seg">${Object.entries(RULE_KINDS).map(([k, label]) =>
        `<button data-kind="${k}" class="${k === kind ? "on" : ""}">${label}</button>`).join("")}</div>
      <div class="row" style="margin-top:14px" id="r-fields">${ruleFields(kind)}</div>
      <label class="field" style="margin-top:12px">Note (optional) <input type="text" id="r-note" maxlength="500" placeholder="Why this rule exists"></label>
      <div id="r-preview"></div>
      <div class="row" style="margin-top:14px"><button class="btn" id="r-save">Save rule</button></div>
    </section>

    <section class="panel">
      <h2>Saved rules (${state.rules.length})</h2>
      ${others.length ? `
        <table class="list"><tbody>${others.map((r) => `
          <tr><td><b>${esc(describeRule(r.kind, r.params))}</b>${r.source_text ? `<div class="help" style="margin:0">${esc(r.source_text)}</div>` : ""}</td>
              <td style="text-align:end"><button class="btn mini danger" data-del="${r.id}">Delete</button></td></tr>`).join("")}
        </tbody></table>` : ""}
      ${byTeacher.size ? `
        <h3 style="margin-top:20px;font-size:.9em;letter-spacing:.16em;color:var(--soft)">Teacher availability</h3>
        <table class="list"><tbody>${[...byTeacher].map(([tid, rules]) => `
          <tr><td style="width:30%"><bdi><b>${esc(teacherName(tid))}</b></bdi><div class="help" style="margin:0">${esc(rules[0].source_text ?? "")}</div></td>
              <td><div class="row" style="gap:6px">${rules.map((r) =>
                `<span class="chip">${DAYS[r.params.day].slice(0, 3)} P${r.params.period}<button data-del="${r.id}" aria-label="Delete rule">×</button></span>`).join("")}</div></td></tr>`).join("")}
        </tbody></table>` : ""}
      ${!state.rules.length ? `<div class="empty"><b>No rules yet</b>Add one above.</div>` : ""}
    </section>`;

  const readParams = () => Object.fromEntries([...document.querySelectorAll("[data-p]")].map((s) => [s.dataset.p, Number(s.value)]));
  const preview = () => { $("#r-preview").innerHTML = `<div class="msg ok">Preview: ${esc(describeRule(state.ruleKind, readParams()))}.</div>`; };
  document.querySelectorAll("[data-p]").forEach((s) => (s.onchange = preview));
  preview();

  document.querySelectorAll("[data-kind]").forEach((b) => (b.onclick = () => { state.ruleKind = b.dataset.kind; renderRules(); }));
  $("#r-save").onclick = (e) => busy(e.currentTarget, async () => {
    await api("/rules", { method: "POST", body: { kind: state.ruleKind, params: readParams(), source_text: $("#r-note").value } });
    setStale(true); toast("Rule saved. Generate again to apply it.");
    state.rules = await api("/rules"); renderRules();
  });
  document.querySelectorAll("[data-del]").forEach((b) => (b.onclick = () => busy(b, async () => {
    await api(`/rules/${b.dataset.del}`, { method: "DELETE" });
    setStale(true); toast("Rule deleted.");
    state.rules = await api("/rules"); renderRules();
  })));
}

// ---------- scheduler page (the AI agent) ----------
// POST /api/agent returns a reply, the steps it took and proposals. Nothing is saved until the admin approves
// a proposal; approving sends proposal.request to the existing endpoint (POST /api/rules or POST /api/teachers).
const EXAMPLES = [
  "A teacher has left the school. Who teaches her classes, and what should I change?",
  "PE should never be in period 7.",
  "Class 2/3 has no teacher on Monday, period 3. Who can cover?",
  "Who is free on Tuesday, period 5?",
  "المعلمة لا تستطيع التدريس يوم الأحد في الحصة الأولى",
];

// ---------- teacher name suggestions (scheduler input) ----------
// Each teacher has the stored Arabic name ("فاطمة ج.") and an English spelling (name_en: "Fatima J.", from
// database/teacher_names_en.json). Arabic typing completes the Arabic name, Latin typing the English one.
// Other spellings ("fatma", "aysha") still find the teacher by sound: both sides are reduced
// to a consonant skeleton: Latin letters map to one sound class, each Arabic letter to the classes it can be written as
// (ق can be q, k or g). Vowels, and و/ي inside a word, are skipped on both sides, so "fatma" and "fatima" both give F T M.
const AR_SOUNDS = {
  "ب": "B", "ت": "T", "ث": "TH T S", "ج": "J G", "ح": "H", "خ": "KH K H", "د": "D", "ذ": "DH D Z", "ر": "R", "ز": "Z",
  "س": "S", "ش": "SH", "ص": "S", "ض": "D DH", "ط": "T", "ظ": "Z DH", "غ": "G", "ف": "F", "ق": "Q K G", "ك": "K",
  "ل": "L", "م": "M", "ن": "N", "ه": "H",
};
const AR_VOWELS = new Set([..."اأإآءئؤعىة"]);
const LATIN_VOWELS = new Set([..."aeiou"]);
const NAME_STOP = new Set(("ms mrs miss mr teacher teachers the and has have had left leaving who whom can cover covers covering is are was " +
  "on in at of for from to her his she he it this that with will would class classes period periods day days today tomorrow " +
  "absent absence sick free never not no new replace replaces replacing take takes taking sunday monday tuesday wednesday " +
  "thursday arabic english math science social computer music art pe islamic please what which when lesson lessons rule " +
  "المعلمة المعلمات معلمة الأستاذة أستاذة غائبة غائبه يوم الحصة حصة فصل الفصل في من على لا").split(" "));

function arabicSkeleton(word) {
  const out = [];
  [...word].forEach((ch, i) => {
    if (ch === "و" || ch === "ي") { if (i === 0) out.push(ch === "و" ? ["W"] : ["Y"]); return; }  // consonant only at the start
    if (AR_SOUNDS[ch]) out.push(AR_SOUNDS[ch].split(" "));
  });
  return out;
}
function latinSkeleton(word) {
  const w = word.toLowerCase().replace(/[^a-z]/g, "").replace(/(.)\1+/g, "$1");
  const out = [];
  for (let i = 0; i < w.length; i++) {
    const two = w.slice(i, i + 2);
    if (["sh", "kh", "gh", "th", "dh", "ph"].includes(two)) { out.push({ sh: "SH", kh: "KH", gh: "G", th: "TH", dh: "DH", ph: "F" }[two]); i++; continue; }
    const c = w[i];
    if (LATIN_VOWELS.has(c)) continue;
    if ((c === "w" || c === "y") && i > 0) continue;               // like و/ي inside a word
    out.push({ c: "K", v: "F", p: "B", x: "KS" }[c] || c.toUpperCase());
  }
  return out;
}
const normArabic = (t) => String(t).replace(/[ً-ٰٟـ]/g, "").replace(/[أإآا]/g, "ا").replace(/ة/g, "ه").replace(/ى/g, "ي");
const firstName = (name) => String(name).split(/\s+/)[0];
const withoutAl = (w) => (w.startsWith("ال") && w.length > 3 ? w.slice(2) : w);

/** Teachers whose first name could start with `typed` (Latin or Arabic), best matches first. */
function suggestTeachers(typed, max = 6) {
  const q = typed.trim();
  if (q.length < 2) return [];
  const common = NAME_STOP.has(q.toLowerCase()) || NAME_STOP.has(q);   // "no", "has": only an exact English name start counts
  const arabic = /[؀-ۿ]/.test(q);
  const scored = [];
  for (const t of state.teachers) {
    const first = firstName(t.name);
    let score = 0;
    if (arabic) {
      if (common) continue;
      const nq = normArabic(q), nn = normArabic(t.name);
      if (nn.startsWith(nq)) score = 3; else if (normArabic(withoutAl(first)).startsWith(nq)) score = 2;
    } else {
      if (t.name_en && t.name_en.toLowerCase().startsWith(q.toLowerCase())) { scored.push({ t, score: 5 }); continue; }
      if (common) continue;
      const qs = latinSkeleton(q);
      const vowelStart = LATIN_VOWELS.has(q[0].toLowerCase());
      for (const form of new Set([first, withoutAl(first)])) {
        if (vowelStart !== AR_VOWELS.has(form[0])) continue;      // "aisha" ↔ عايشة, "huda" ↔ هدى
        const as = arabicSkeleton(form);
        if (qs.length > as.length) continue;
        if (qs.every((cls, i) => as[i].includes(cls))) score = Math.max(score, qs.length ? 1 + qs.length / as.length : 0.5);
      }
    }
    if (score > 0) scored.push({ t, score });
  }
  const label = (t) => (arabic ? t.name : t.name_en || t.name);
  return scored.sort((a, b) => b.score - a.score || label(a.t).localeCompare(label(b.t), arabic ? "ar" : "en")).slice(0, max).map((x) => x.t);
}

/** Inline suggestion inside an <input>: the rest of the name appears in grey after the caret.
    Tab (or → at the end) accepts, ↓/↑ show the other matches, Esc hides it. Enter still sends. */
function attachNameSuggestions(input, hint) {
  const wrap = document.createElement("div");
  wrap.className = "ghost-wrap";
  input.replaceWith(wrap);
  wrap.append(input);
  const ghost = document.createElement("div");
  ghost.className = "ghost";
  ghost.setAttribute("aria-hidden", "true");
  wrap.append(ghost);
  const defaultHint = hint.textContent;
  hint.setAttribute("aria-live", "polite");
  let items = [], idx = 0, word = null, dismissed = null;

  const firstStrongDir = (t) => { const m = String(t).match(/[A-Za-z؀-ۿ]/); return m && /[؀-ۿ]/.test(m[0]) ? "rtl" : "ltr"; };
  const currentWord = () => {
    const v = input.value, pos = input.selectionStart ?? v.length;
    if (pos !== v.length || input.selectionEnd !== pos) return null;      // only while typing at the end
    const m = v.match(/[A-Za-z؀-ۿ]+$/);
    return m ? { text: m[0], start: v.length - m[0].length } : null;
  };
  // English typed -> the English name; Arabic typed -> the Arabic name. When that name starts with what was typed, only the
  // rest is shown (Fa|tima J., فا|طمة ج.); otherwise (another spelling) the word is underlined and the whole name follows.
  const target = (t) => (/[\u0600-\u06FF]/.test(word.text) ? t.name : t.name_en || t.name);
  const continues = (t) => target(t).toLowerCase().startsWith(word.text.toLowerCase());
  const clear = () => {
    items = []; word = null; ghost.innerHTML = "";
    hint.textContent = defaultHint;
  };
  const render = () => {
    const t = items[idx];
    const cs = getComputedStyle(input);
    for (const k of ["fontFamily", "fontSize", "fontWeight", "letterSpacing", "lineHeight", "paddingLeft", "paddingRight", "paddingTop", "paddingBottom"]) ghost.style[k] = cs[k];
    ghost.dir = firstStrongDir(input.value);
    const v = input.value;
    ghost.innerHTML = continues(t)
      ? `<span class="typed">${esc(v)}</span><bdi class="tail">${esc(target(t).slice(word.text.length))}</bdi><span class="key">Tab</span>`
      : `<span class="typed">${esc(v.slice(0, word.start))}</span><span class="typed swap">${esc(word.text)}</span>` +
        `<span class="gap"><bdi class="tail">${esc(target(t))}</bdi></span><span class="key">Tab</span>`;
    ghost.scrollLeft = input.scrollLeft;
    // The line under the box repeats the suggestion with buttons, for touch screens (no Tab key) and narrow boxes.
    const other = target(t) === t.name ? t.name_en : t.name;          // show the other spelling too
    hint.innerHTML = `<button type="button" class="chip pick" data-act="use">Use <bdi>${esc(target(t))}</bdi></button>` +
      (items.length > 1 ? ` <button type="button" class="chip pick" data-act="next">Next (${idx + 1} of ${items.length})</button>` : "") +
      ` <span>${other && other !== target(t) ? `<bdi>${esc(other)}</bdi> · ` : ""}${esc(subjectName(t.subject_id))} · ${continues(t) ? "Tab" : `Tab replaces “${esc(word.text)}”`} · ↓ ↑ other matches · Esc hides</span>`;
  };
  const update = () => {
    word = currentWord();
    if (!word || word.text === dismissed) return clear();
    dismissed = null;
    items = suggestTeachers(word.text);
    idx = 0;
    if (!items.length) return clear();
    render();
  };
  const accept = () => {
    const t = items[idx];
    input.value = input.value.slice(0, word.start) + target(t) + " ";
    input.setSelectionRange(input.value.length, input.value.length);
    clear();
  };
  input.addEventListener("input", update);
  input.addEventListener("click", update);
  input.addEventListener("focus", update);
  input.addEventListener("scroll", () => (ghost.scrollLeft = input.scrollLeft));
  input.addEventListener("blur", () => { ghost.innerHTML = ""; });
  input.addEventListener("keydown", (e) => {
    if (!items.length || !word) return;
    const forward = ghost.dir === "rtl" ? "ArrowLeft" : "ArrowRight";
    if ((e.key === "Tab" && !e.shiftKey) || e.key === forward) { e.preventDefault(); accept(); }
    else if (e.key === "ArrowDown" || e.key === "ArrowUp") {
      e.preventDefault();
      idx = (idx + (e.key === "ArrowDown" ? 1 : -1) + items.length) % items.length;
      render();
    } else if (e.key === "Escape") { e.preventDefault(); dismissed = word.text; clear(); }
  });
  hint.addEventListener("mousedown", (e) => {                    // mousedown: keep the focus in the box
    const b = e.target.closest("[data-act]");
    if (!b || !items.length) return;
    e.preventDefault();
    if (b.dataset.act === "use") accept(); else { idx = (idx + 1) % items.length; render(); }
    input.focus();
  });
  input.addEventListener("keyup", (e) => { if (["Home", "End", "ArrowLeft", "ArrowRight"].includes(e.key)) update(); });
}

function renderScheduler() {
  heading("Scheduler", "Ask for a change",
    "Describe what happened, in English or Arabic. The scheduler looks things up and prepares changes. Nothing is saved until you approve it.");
  $("#page").innerHTML = `
    <section class="panel scheduler">
      <div class="chat-log" id="chat-log" aria-live="polite"></div>
      <form class="chat-form" id="chat-form">
        <label class="sr-only" for="chat-input">Your request</label>
        <input type="text" id="chat-input" dir="auto" maxlength="1000" autocomplete="off"
               placeholder="For example: Ms Noura left the school, Huda will take her classes">
        <button class="btn" id="chat-send">Send</button>
      </form>
      <p class="help" id="chat-hint" style="margin:-4px 0 0">Start typing a teacher's name, in English or Arabic: a suggestion appears in the box. Tab accepts it.</p>
      ${state.chat.length ? "" : `<div class="row examples">${EXAMPLES.map((x) =>
        `<button type="button" class="check" data-example="${esc(x)}" dir="auto">${esc(x)}</button>`).join("")}</div>`}
    </section>`;
  drawChat();
  document.querySelectorAll("[data-example]").forEach((b) => (b.onclick = () => { $("#chat-input").value = b.dataset.example; $("#chat-input").focus(); }));
  $("#chat-form").onsubmit = (e) => { e.preventDefault(); sendToScheduler(); };
  attachNameSuggestions($("#chat-input"), $("#chat-hint"));
  $("#chat-input").focus();
}

function drawChat() {
  const log = $("#chat-log");
  if (!log) return;
  if (!state.chat.length) {
    log.innerHTML = `<div class="empty"><b>No messages yet</b>Try one of the examples below, or write your own request.</div>`;
    return;
  }
  log.innerHTML = state.chat.map((m, i) => {
    if (m.role === "user") return `<div class="bubble me" dir="${textDir(m.content)}">${esc(m.content)}</div>`;
    if (m.pending) return `<div class="bubble ai thinking">Working on it…</div>`;
    if (m.error) return `<div class="msg err">${esc(m.error)}</div>`;
    const steps = m.steps?.length ? `<details class="steps"><summary>How I worked it out (${m.steps.length} steps)</summary>
        <ol>${m.steps.map((s) => `<li>${esc(iso(s.summary))}</li>`).join("")}</ol></details>` : "";
    const cards = (m.proposals || []).map((p, j) => proposalCard(p, i, j)).join("");
    return `<div class="bubble ai"><p dir="${textDir(m.content)}">${esc(m.content)}</p>${steps}${cards}</div>`;
  }).join("");
  log.querySelectorAll("[data-approve]").forEach((b) => (b.onclick = () => decide(b, true)));
  log.querySelectorAll("[data-reject]").forEach((b) => (b.onclick = () => decide(b, false)));
  log.scrollTop = log.scrollHeight;
}

function proposalCard(p, i, j) {
  const status = {
    applied: `<div class="msg ok">Approved and saved. Press Generate on the Timetable tab to apply it.</div>`,
    rejected: `<div class="help">Rejected. Nothing was changed.</div>`,
    failed: `<div class="msg err">${esc(p.error || "Could not save this change.")}</div>`,
  }[p.status] || `<div class="row"><button class="btn mini" data-approve="${i}:${j}">Approve</button>
      <button class="btn mini secondary" data-reject="${i}:${j}">Reject</button></div>`;
  return `<div class="proposal ${p.status || ""}">
    <div class="row spread"><span class="chip">${esc(p.id)} · ${p.type === "teacher" ? "New teacher" : "Rule"}</span></div>
    <p dir="${textDir(p.description)}"><b>${esc(p.description)}</b></p>
    ${p.impact?.length ? `<ul class="impact">${p.impact.map((x) => `<li class="${x.level === "error" ? "bad" : ""}">${esc(iso(x.text))}</li>`).join("")}</ul>` : ""}
    ${status}</div>`;
}

async function decide(button, approve) {
  const [i, j] = button.dataset[approve ? "approve" : "reject"].split(":").map(Number);
  const p = state.chat[i].proposals[j];
  if (!approve) { p.status = "rejected"; drawChat(); return; }
  button.disabled = true;
  try {
    const { method, path, body } = p.request;
    await api(path.replace(/^\/api/, ""), { method, body });   // the same endpoint the Rules/Data pages use
    p.status = "applied";
    setStale(true);
    [state.teachers, state.rules] = await Promise.all([api("/teachers"), api("/rules")]);
    toast("Saved. Generate again to update the timetable.");
  } catch (e) {
    p.status = "failed"; p.error = e.message;
  }
  drawChat();
}

async function sendToScheduler() {
  const input = $("#chat-input");
  const text = input.value.trim();
  if (!text) return;
  const history = state.chat.filter((m) => !m.pending && !m.error).slice(-6).map((m) => ({ role: m.role, content: m.content }));
  state.chat.push({ role: "user", content: text });
  const answer = { role: "assistant", pending: true };
  state.chat.push(answer);
  input.value = "";
  input.dispatchEvent(new Event("input"));                        // clears any name suggestion
  $("#chat-send").disabled = true;
  document.querySelector(".examples")?.remove();
  drawChat();
  try {
    const r = await api("/agent", { method: "POST", body: { message: text, language: Session.lang(), history } });
    Object.assign(answer, { pending: false, content: r.reply, proposals: r.proposals, steps: r.steps });
  } catch (e) {
    const hint = /OPENROUTER_API_KEY/.test(e.message)
      ? " Add OPENROUTER_API_KEY to the .env file in the project folder, then restart the backend." : "";
    Object.assign(answer, { pending: false, error: e.message + hint });
  }
  if ($("#chat-send")) $("#chat-send").disabled = false;
  drawChat();
}

// ---------- session ----------
$("#signout").addEventListener("click", () => { Session.signOut(); location.href = "../"; });

// ---------- start ----------
(async () => {
  try { await loadAll(); await render(); }
  catch (e) {
    heading("Madar", "Cannot reach the server", "Start the backend (cd backend, then uvicorn main:app --reload) and reload this page.");
    $("#page").innerHTML = `<div class="msg err">${esc(e.message)}</div>`;
  }
})();
