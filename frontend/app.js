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
const routes = { timetable: renderTimetable, data: renderData, rules: renderRules };
function route() { return location.hash.slice(1) in routes ? location.hash.slice(1) : "timetable"; }
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
