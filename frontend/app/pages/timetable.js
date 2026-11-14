// Timetable (home): six cards on the gradient, then the schedule by all classes, one class or one teacher.
import { $, $$, t, esc, iso, state, api, allLessons, generate, isStale, lastGenerated, subjectName, subjectChip,
  pastel, abbr, dayName, dayShort, DAYS, PERIODS, options, msg, ICON, byId } from "../core.js";

// Remembered while the app is open: what the schedule shows.
const view = { mode: "all", grade: null, classId: null, subjectId: null, teacherId: null };

function heroCards() {
  const id = Session.current()?.school_id ?? "";
  const when = lastGenerated();
  const sameDay = when && new Date(when).toDateString() === new Date().toDateString();
  const updated = sameDay
    ? t("updated_today", { time: new Date(when).toLocaleTimeString(document.documentElement.lang, { hour: "2-digit", minute: "2-digit" }) })
    : t("updated_server");
  const hero = $("#hero");
  hero.className = "hero-cards home";
  hero.innerHTML = `
    <div class="card glass welcome"><i class="badge" aria-hidden="true"></i>
      <div><h1 class="hello">${esc(t("welcome"))}</h1><div class="school">${esc(t("school_name"))}</div>
      <div class="sub">${esc(t("school_id", { id }))}</div></div></div>
    <div class="card glass stat"><div class="stat-label">${esc(t("stat_classes"))}</div><div class="stat">${state.classes.length}</div></div>
    <div class="card glass stat"><div class="stat-label">${esc(t("stat_teachers"))}</div><div class="stat">${state.teachers.length}</div></div>
    <a class="card quick" href="#chat">${ICON.diamond}<span>${esc(t("quick"))}</span></a>
    <div class="card glass stat"><div class="stat-label">${esc(t("stat_periods"))}</div><div class="stat sm">35</div></div>
    <div class="card glass stat"><div class="stat-label">${esc(t("stat_updated"))}</div><div class="stat val">${esc(updated)}</div></div>`;
}

const statusMsg = () => !state.generated ? msg("warn", esc(t("st_none")))
  : isStale() ? msg("warn", esc(t("st_stale"))) : msg("ok", esc(t("st_ok")));

export async function render() {
  heroCards();
  const grades = [...new Set(state.classes.map((c) => c.grade))].sort();
  view.grade ??= grades[0] ?? 1;
  view.classId ??= state.classes.find((c) => c.grade === view.grade)?.id ?? null;
  view.subjectId ??= state.subjects[0]?.id ?? null;
  view.teacherId ??= state.teachers.find((x) => x.subject_id === view.subjectId)?.id ?? null;

  $("#page").innerHTML = `
    <section class="panel">
      <div class="row spread">
        <h2>${esc(t("sched_title"))}</h2>
        <div class="row"><span class="hint">${esc(t("sched_hint"))}</span>
          <button class="btn secondary" id="to-import">${ICON.upload}<span>${esc(t("import_upload"))}</span></button>
          <button class="btn" id="generate">${esc(state.generated ? t("regenerate") : t("generate"))}</button></div>
      </div>
      <div id="gen-status">${statusMsg()}</div>
      <div class="row controls">
        <label class="field">${esc(t("view_by"))}
          <select id="mode">${["all", "class", "teacher"].map((m) =>
            `<option value="${m}" ${view.mode === m ? "selected" : ""}>${esc(t(`view_${m}`))}</option>`).join("")}</select></label>
        <span id="who" class="row"></span>
      </div>
      <div id="grid" class="grid-box"></div>
      <div class="legend">${state.subjects.map((s) => subjectChip(s.id)).join("")}</div>
    </section>`;

  $("#generate").onclick = async (e) => {
    const b = e.currentTarget; b.disabled = true;
    $("#gen-status").innerHTML = msg("warn", esc(t("generating")));
    try {
      const r = await generate();
      $("#gen-status").innerHTML = msg("ok", esc(t("built", { n: r.lessons_count, s: r.seconds })));
      b.textContent = t("regenerate");
      heroCards(); await drawGrid();
    } catch (err) { $("#gen-status").innerHTML = msg("err", esc(err.message)); }
    finally { b.disabled = false; }
  };
  $("#to-import").onclick = () => { state.focus = "import"; location.hash = "rules"; };
  $("#mode").onchange = (e) => { view.mode = e.target.value; drawWho(); drawGrid(); };
  drawWho();
  await drawGrid();
}

function drawWho() {
  const box = $("#who");
  if (view.mode === "class") {
    const grades = [...new Set(state.classes.map((c) => c.grade))].sort();
    box.innerHTML = `
      <label class="field">${esc(t("pick_grade"))}<select id="grade">${grades.map((g) =>
        `<option value="${g}" ${g === view.grade ? "selected" : ""}>${esc(t("grade_n", { n: g }))}</option>`).join("")}</select></label>
      <label class="field">${esc(t("pick_class"))}<select id="klass">${options(state.classes.filter((c) => c.grade === view.grade), view.classId)}</select></label>`;
    $("#grade").onchange = (e) => {
      view.grade = Number(e.target.value);
      view.classId = state.classes.find((c) => c.grade === view.grade)?.id ?? null;
      drawWho(); drawGrid();
    };
    $("#klass").onchange = (e) => { view.classId = Number(e.target.value); drawGrid(); };
  } else if (view.mode === "teacher") {
    box.innerHTML = `
      <label class="field">${esc(t("pick_subject"))}<select id="subj">${options(state.subjects, view.subjectId, (s) => subjectName(s.id))}</select></label>
      <label class="field">${esc(t("pick_teacher"))}<select id="teacher">${options(state.teachers.filter((x) => x.subject_id === view.subjectId), view.teacherId)}</select></label>`;
    $("#subj").onchange = (e) => {
      view.subjectId = Number(e.target.value);
      view.teacherId = state.teachers.find((x) => x.subject_id === view.subjectId)?.id ?? null;
      drawWho(); drawGrid();
    };
    $("#teacher").onchange = (e) => { view.teacherId = Number(e.target.value); drawGrid(); };
  } else box.innerHTML = "";
}

// Open one class's or teacher's week from another screen.
export function openWeek(mode, id) {
  if (mode === "teacher") {
    const tch = byId(state.teachers, id);
    Object.assign(view, { mode, subjectId: tch?.subject_id ?? view.subjectId, teacherId: id });
  } else {
    const c = byId(state.classes, id);
    Object.assign(view, { mode: "class", grade: c?.grade ?? view.grade, classId: id });
  }
  location.hash = "timetable";
}

const empty = (title, sub) => `<div class="empty"><b>${esc(title)}</b>${esc(sub)}</div>`;
const cellTitle = (l) => `${subjectName(l.subject)} · ${l.teacher} · ${l.class} · ${dayName(l.day)} ${t("p_short", { n: l.period })}`;

export async function drawGrid() {
  const box = $("#grid");
  if (!box) return;
  box.innerHTML = `<div class="empty">${esc(t("loading"))}</div>`;
  try {
    if (view.mode === "all") return drawAll(box);
    const id = view.mode === "class" ? view.classId : view.teacherId;
    if (id == null) { box.innerHTML = empty(t("tt_empty_t"), ""); return; }
    const { lessons } = await api(`/timetable?${view.mode}_id=${id}`);
    drawWeek(box, lessons, id);
  } catch (e) { box.innerHTML = msg("err", esc(e.message)); }
}

async function drawAll(box) {
  const lessons = await allLessons();
  if (!lessons.length) { box.innerHTML = empty(t("tt_empty_t"), t("tt_empty_s")); return; }
  const at = new Map(lessons.map((l) => [`${l.class_id}-${l.day}-${l.period}`, l]));
  let html = `<div class="sg-corner">${esc(t("col_class"))}</div>` + DAYS.map((d) =>
    `<div class="sg-day"><div class="sg-dname">${esc(dayShort(d))}</div><div class="sg-ps">${PERIODS.map((p) => `<span>${p}</span>`).join("")}</div></div>`).join("");
  for (const c of state.classes) {
    html += `<button class="sg-class" data-class="${c.id}" title="${esc(t("class_n", { name: c.name }))}">${esc(c.name)}</button>`;
    html += DAYS.map((d) => `<div class="sg-cells">${PERIODS.map((p) => {
      const l = at.get(`${c.id}-${d}-${p}`);
      return l ? `<span style="background:${pastel(l.subject)}" title="${esc(cellTitle(l))}">${esc(abbr(l.subject))}</span>` : `<span class="free"></span>`;
    }).join("")}</div>`).join("");
  }
  box.innerHTML = `<div class="scroll"><div class="school-grid ${document.documentElement.lang === "ar" ? "ar" : ""}">${html}</div></div>`;
  box.querySelectorAll("[data-class]").forEach((b) => (b.onclick = () => {
    const c = byId(state.classes, Number(b.dataset.class));
    Object.assign(view, { mode: "class", grade: c.grade, classId: c.id });
    $("#mode").value = "class"; drawWho(); drawGrid();
  }));
}

function drawWeek(box, lessons, id) {
  if (!lessons.length) { box.innerHTML = empty(t("tt_empty_t"), t("tt_empty_s")); return; }
  const at = new Map(lessons.map((l) => [`${l.day}-${l.period}`, l]));
  const blocked = new Set(view.mode === "teacher"
    ? state.rules.filter((r) => r.kind === "teacher_unavailable" && r.params.teacher_id === id).map((r) => `${r.params.day}-${r.params.period}`)
    : []);
  let html = `<div></div>` + DAYS.map((d) => `<div class="dh">${esc(dayName(d))}</div>`).join("");
  for (const p of PERIODS) {
    html += `<div class="ph">${esc(t("p_short", { n: p }))}</div>`;
    for (const d of DAYS) {
      const l = at.get(`${d}-${p}`);
      if (l) {
        const sub = view.mode === "class" ? `<bdi>${esc(l.teacher)}</bdi>` : esc(t("class_n", { name: l.class }));
        html += `<div class="cell" style="background:${pastel(l.subject)}" title="${esc(cellTitle(l))}"><b>${esc(subjectName(l.subject))}</b><small>${sub}</small></div>`;
      } else if (blocked.has(`${d}-${p}`)) html += `<div class="cell blocked"><small>${esc(t("unavailable"))}</small></div>`;
      else html += `<div class="cell free"><small>${esc(t("free"))}</small></div>`;
    }
  }
  box.innerHTML = `<div class="grid">${html}</div>`;
}
