// Rules & data: data check, Excel import, classes, subject hours, teachers, add a teacher, rules.
// The server rebuilds the timetable after every change, so there is no Regenerate button here.
import { $, $$, t, esc, iso, api, ApiFail, missingRoute, state, loadBase, updating,
  subjectName, subjectChip, className, teacherName, dayName, DAYS, PERIODS, options, msg, busy,
  confirmBox, heading, ruleText, ICON, lang, warnList, teacherPicker } from "../core.js";
import { openWeek } from "./timetable.js";

const ui = { search: "", page: 0, kind: "subject_not_in_period", parsed: null, imported: null };
const PAGE = 10;

export async function render() {
  heading(t("head_rules_e"), t("head_rules_t"), t("head_rules_s"));
  $("#page").innerHTML = `
    <div id="check">${dataCheck()}</div>
    <section class="panel" id="import-panel">${importPanel()}</section>
    <section class="panel">${classesPanel()}</section>
    <section class="panel" id="hours"><h2>${esc(t("hours_t"))}</h2><p class="help">${esc(t("hours_d"))}</p><div class="empty">${esc(t("loading"))}</div></section>
    <section class="panel" id="teachers"></section>
    <section class="panel">${addTeacherPanel()}</section>
    <section class="panel" id="rules-panel">${rulesPanel()}</section>`;
  wireImport(); wireClasses(); drawTeachers(); wireAddTeacher(); wireRules();
  drawHours();
  if (state.focus === "import") { state.focus = null; $("#import-panel").scrollIntoView({ block: "start" }); }
}

// ---------- data check: every class needs a teacher for every subject its grade is taught ----------
function dataCheck() {
  const taught = {};                                   // grade -> subjects someone teaches in that grade
  for (const tch of state.teachers) for (const cid of tch.class_ids) {
    const g = state.classes.find((c) => c.id === cid)?.grade;
    if (g != null) (taught[g] ??= new Set()).add(tch.subject_id);
  }
  const problems = [];
  for (const c of state.classes) {
    const need = [...(taught[c.grade] ?? new Set(state.subjects.map((s) => s.id)))];
    const missing = need.filter((sid) => !state.teachers.some((x) => x.subject_id === sid && x.class_ids.includes(c.id)));
    if (missing.length) problems.push(t("issue_missing", { klass: c.name, subjects: missing.map(subjectName).join(", ") }));
  }
  return problems.length
    ? msg("warn", `<div><b>${esc(t("issues_title"))}</b><ul class="bul">${problems.map((p) => `<li>${esc(p)}</li>`).join("")}</ul></div>`)
    : msg("ok", esc(t("rules_ok")));
}

// ---------- Excel import (contract: GET /api/import/template, POST /api/import, POST /api/import/confirm) ----------
function importPanel() {
  const p = ui.imported;
  return `
    <div class="row spread"><h2>${esc(t("import_t"))}</h2>
      <div class="row">
        <button class="btn secondary" id="tpl" type="button">${ICON.download}<span>${esc(t("import_template"))}</span></button>
        <label class="btn" id="upload-btn">${ICON.upload}<span>${esc(t("import_upload"))}</span>
          <input type="file" id="xlsx" accept=".xlsx,application/vnd.openxmlformats-officedocument.spreadsheetml.sheet" hidden></label>
      </div></div>
    <p class="help">${esc(t("import_d"))}</p>
    <div id="import-out">${p ? importPreview(p) : ""}</div>`;
}
function importPreview(p) {
  const classes = new Set(p.rows.map((r) => r.class)), teachers = new Set(p.rows.filter((r) => r.teacher).map((r) => `${r.subject}|${r.teacher}`));
  return `
    <div class="preview">
      <h3>${esc(t("import_preview_t", { file: p.file }))}</h3>
      <p class="help">${esc(t("import_counts", { classes: classes.size, teachers: teachers.size, hours: p.rows.length }))}</p>
      ${p.warnings?.length ? msg("warn", `<div><b>${esc(t("import_warn"))}</b><ul class="bul">${p.warnings.map((w) => `<li>${esc(w)}</li>`).join("")}</ul></div>`) : ""}
      <div class="scroll"><table class="list"><thead><tr><th>${esc(t("f_class"))}</th><th>${esc(t("col_subject"))}</th><th>${esc(t("col_name"))}</th><th>${esc(t("hours_total"))}</th></tr></thead>
        <tbody>${p.rows.slice(0, 10).map((r) => `<tr><td>${esc(r.class)}</td><td>${esc(r.subject)}</td><td><bdi>${esc(r.teacher || "—")}</bdi></td><td>${r.hours_per_week}</td></tr>`).join("")}</tbody></table></div>
      ${p.rows.length > 10 ? `<p class="help">+ ${p.rows.length - 10}</p>` : ""}
      <div class="row"><button class="btn danger-fill" id="import-confirm">${esc(t("import_confirm"))}</button>
        <button class="btn secondary" id="import-cancel">${esc(t("cancel"))}</button></div>
    </div>`;
}
function wireImport() {
  const out = () => $("#import-out");
  $("#tpl").onclick = (e) => busy(e.currentTarget, async () => {
    const res = await fetch("/api/import/template");
    if (!res.ok) { out().innerHTML = msg("warn", esc(t("import_na"))); return; }
    const url = URL.createObjectURL(await res.blob());
    Object.assign(document.createElement("a"), { href: url, download: "madar_template.xlsx" }).click();
    setTimeout(() => URL.revokeObjectURL(url), 2000);
  });
  $("#xlsx").onchange = async (e) => {
    const file = e.target.files[0];
    e.target.value = "";
    if (!file) return;
    out().innerHTML = msg("warn", esc(t("import_reading")));
    const form = new FormData(); form.append("file", file);
    try {
      ui.imported = { ...(await api("/import", { method: "POST", body: form })), file: file.name };
      out().innerHTML = importPreview(ui.imported);
      wirePreview();
    } catch (err) {
      out().innerHTML = msg(missingRoute(err) ? "warn" : "err", esc(missingRoute(err) ? t("import_na") : err.message));
    }
  };
  if (ui.imported) wirePreview();
}
function wirePreview() {
  $("#import-cancel").onclick = () => { ui.imported = null; $("#import-out").innerHTML = ""; };
  $("#import-confirm").onclick = async (e) => {
    const btn = e.currentTarget;                       // the event forgets its button once we await the dialog
    if (!(await confirmBox(t("import_confirm_q"), t("import_confirm"), true))) return;
    await busy(btn, async () => {
      const r = await updating(() => api("/import/confirm", { method: "POST", body: { rows: ui.imported.rows } }));
      ui.imported = null;
      await loadBase();
      await render();
      if (r.warnings?.length) $("#import-out").innerHTML = msg("warn", warnList(r.warnings));
    });
  };
}

// ---------- classes ----------
function classesPanel() {
  const grades = [1, 2, 3, 4, 5];
  return `
    <h2>${esc(t("classes_t"))}</h2>
    <p class="help">${esc(t("classes_now", { n: state.classes.length }))}</p>
    <div class="chips">${state.classes.map((c) => `<span class="chip">${esc(c.name)}</span>`).join("")}</div>
    <div class="row" style="margin-top:14px">
      <label class="field">${esc(t("add_section"))}<select id="new-grade">${grades.map((g) => `<option value="${g}">${esc(t("grade_n", { n: g }))}</option>`).join("")}</select></label>
      <button class="btn" id="add-class">${esc(t("add_class"))}</button>
    </div>
    <p class="help">${esc(t("add_class_hint"))}</p><div id="class-out"></div>`;
}
function wireClasses() {
  $("#add-class").onclick = async (e) => {
    const btn = e.currentTarget; btn.disabled = true;
    $("#class-out").innerHTML = msg("warn", esc(t("adding_class")));
    let out;
    try {
      const c = await updating(() => api("/classes", { method: "POST", body: { grade: Number($("#new-grade").value) } }));
      const w = [...(c.warnings || []), ...(c.violations || [])];
      out = msg(w.length ? "warn" : "ok", `<div><b>${esc(t("msg_class_ready", { klass: c.name, n: c.generation?.lessons_count ?? "" }))}</b>${warnList(w)}</div>`);
    } catch (err) { out = msg("err", esc(err.message)); }   // the class is kept even when the rebuild fails
    btn.disabled = false;
    await loadBase(); await render();
    $("#class-out").innerHTML = out;
  };
}

// ---------- subject hours per grade, counted from the timetable ----------
async function drawHours() {
  const box = $("#hours");
  const lessons = await allLessons().catch(() => []);
  const body = box.querySelector(".empty");
  if (!lessons.length) { body.textContent = t("hours_none"); return; }
  const grades = [...new Set(state.classes.map((c) => c.grade))].sort();
  const rows = grades.map((g) => {
    const cls = state.classes.find((c) => c.grade === g && lessons.some((l) => l.class_id === c.id));
    const counts = {};
    if (cls) for (const l of lessons) if (l.class_id === cls.id) counts[l.subject_id] = (counts[l.subject_id] || 0) + 1;
    return { g, counts };
  });
  body.outerHTML = `<div class="scroll"><table class="list hours"><thead><tr><th></th>${state.subjects.map((s) => `<th>${subjectChip(s.id)}</th>`).join("")}<th>${esc(t("hours_total"))}</th></tr></thead>
    <tbody>${rows.map(({ g, counts }) => `<tr><th>${esc(t("grade_n", { n: g }))}</th>${state.subjects.map((s) => `<td>${counts[s.id] ?? 0}</td>`).join("")}
      <td class="total">${Object.values(counts).reduce((a, b) => a + b, 0)}</td></tr>`).join("")}</tbody></table></div>`;
}

// ---------- teachers: search + pages ----------
function drawTeachers() {
  const q = ui.search.trim().toLowerCase();
  const list = state.teachers.filter((x) => !q || x.name.toLowerCase().includes(q)
    || subjectName(x.subject_id).toLowerCase().includes(q) || state.subjects.find((s) => s.id === x.subject_id)?.name.toLowerCase().includes(q));
  const pages = Math.max(1, Math.ceil(list.length / PAGE));
  ui.page = Math.min(ui.page, pages - 1);
  const rows = list.slice(ui.page * PAGE, ui.page * PAGE + PAGE);
  $("#teachers").innerHTML = `
    <h2>${esc(t("teachers_t", { n: state.teachers.length }))}</h2>
    <div class="row"><label class="field grow">${esc(t("find_teacher"))}
      <input type="text" id="t-search" value="${esc(ui.search)}" placeholder="${esc(t("search_ph"))}"></label>
      <span class="hint">${esc(t("n_found", { n: list.length }))}</span></div>
    <div class="scroll"><table class="list">
      <thead><tr><th>${esc(t("col_name"))}</th><th>${esc(t("col_subject"))}</th><th>${esc(t("col_classes"))}</th><th></th></tr></thead>
      <tbody>${rows.map((x) => `<tr><td><bdi>${esc(x.name)}</bdi></td><td>${subjectChip(x.subject_id)}</td>
        <td><div class="chips">${x.class_ids.length ? x.class_ids.map((c) => `<span class="chip">${esc(className(c))}</span>`).join("") : `<span class="muted">${esc(t("classes_none"))}</span>`}</div></td>
        <td class="end"><button class="btn mini secondary" data-week="${x.id}">${esc(t("week"))}</button></td></tr>`).join("")}</tbody>
    </table></div>
    <div class="row center pager">
      <button class="btn mini secondary" id="pg-prev" ${ui.page === 0 ? "disabled" : ""}>${esc(t("prev"))}</button>
      <span class="hint">${esc(t("page_of", { p: ui.page + 1, n: pages }))}</span>
      <button class="btn mini secondary" id="pg-next" ${ui.page >= pages - 1 ? "disabled" : ""}>${esc(t("next"))}</button></div>`;
  const s = $("#t-search");
  s.oninput = () => { ui.search = s.value; ui.page = 0; drawTeachers(); const n = $("#t-search"); n.focus(); n.setSelectionRange(n.value.length, n.value.length); };
  $("#pg-prev").onclick = () => { ui.page--; drawTeachers(); };
  $("#pg-next").onclick = () => { ui.page++; drawTeachers(); };
  $$("[data-week]").forEach((b) => (b.onclick = () => openWeek("teacher", Number(b.dataset.week))));
}

// ---------- add a teacher ----------
function addTeacherPanel() {
  return `
    <h2>${esc(t("add_teacher_t"))}</h2><p class="help">${esc(t("add_teacher_d"))}</p>
    <div class="row">
      <label class="field grow">${esc(t("name_label"))}<input type="text" id="t-name" maxlength="100" placeholder="${esc(t("name_ph"))}"></label>
      <label class="field">${esc(t("subject_label"))}<select id="t-subject">${options(state.subjects, null, (s) => subjectName(s.id))}</select></label>
    </div>
    <div class="field">${esc(t("classes_pick"))}</div>
    ${[1, 2, 3, 4, 5].map((g) => `<div class="grade-row"><strong>${esc(t("grade_n", { n: g }))}</strong>
      ${state.classes.filter((c) => c.grade === g).map((c) => `<label class="check"><input type="checkbox" class="t-class" value="${c.id}"> ${esc(c.name)}</label>`).join("")}</div>`).join("")}
    <div id="t-preview"></div>
    <div class="row" style="margin-top:12px"><button class="btn" id="t-save">${esc(t("add_teacher_btn"))}</button></div>`;
}
function wireAddTeacher() {
  const picked = () => $$(".t-class:checked").map((i) => Number(i.value));
  const preview = () => {
    const subject = Number($("#t-subject").value), ids = picked();
    const takeovers = ids.map((cid) => {
      const old = state.teachers.find((x) => x.subject_id === subject && x.class_ids.includes(cid));
      return old ? t("from_name", { klass: className(cid), name: iso(old.name) }) : null;
    }).filter(Boolean);
    $("#t-preview").innerHTML = !ids.length ? msg("warn", esc(t("no_classes_warn")))
      : takeovers.length ? msg("warn", esc(t("takeover", { subject: subjectName(subject), list: takeovers.join(lang() === "ar" ? "، " : "; ") })))
      : msg("ok", esc(t("teaches", { subject: subjectName(subject), n: ids.length })));
  };
  $("#t-subject").onchange = preview;
  $$(".t-class").forEach((i) => (i.onchange = preview));
  preview();
  $("#t-save").onclick = (e) => busy(e.currentTarget, async () => {
    await updating(() => api("/teachers", { method: "POST", body: { name: $("#t-name").value, subject_id: Number($("#t-subject").value), class_ids: picked() } }));
    await loadBase(); await render();
  });
}

// ---------- rules ----------
function ruleFields(kind) {
  const day = `<label class="field">${esc(t("f_day"))}<select data-p="day">${DAYS.map((d) => `<option value="${d}">${esc(dayName(d))}</option>`).join("")}</select></label>`;
  const period = `<label class="field">${esc(t("f_period"))}<select data-p="period">${PERIODS.map((p) => `<option>${p}</option>`).join("")}</select></label>`;
  const subject = `<label class="field">${esc(t("f_subject"))}<select data-p="subject_id">${options(state.subjects, null, (s) => subjectName(s.id))}</select></label>`;
  if (kind === "subject_not_in_period") return subject + period;
  if (kind === "teacher_unavailable")
    return `<div id="r-teacher"></div><input type="hidden" data-p="teacher_id" value="">` + day + period;
  return `<label class="field">${esc(t("f_class"))}<select data-p="class_id">${options(state.classes, null)}</select></label>` + subject + day + period;
}
function rulesPanel() {
  const byTeacher = new Map(), others = [];
  for (const r of state.rules) {
    if (r.kind === "teacher_unavailable") (byTeacher.get(r.params.teacher_id) ?? byTeacher.set(r.params.teacher_id, []).get(r.params.teacher_id)).push(r);
    else others.push(r);
  }
  return `
    <h2>${esc(t("rule_t"))}</h2><p class="help">${esc(t("rule_d"))}</p>
    <form class="row" id="nl-form"><label class="field grow">${esc(t("rule_label"))}
      <input type="text" id="nl" dir="auto" placeholder="${esc(t("rule_ph"))}"></label>
      <button class="btn" id="nl-go" type="submit">${esc(t("rule_preview"))}</button></form>
    <div id="nl-out"></div>
    <details class="manual"><summary>${esc(t("rule_manual"))}</summary>
      <div class="seg">${["subject_not_in_period", "teacher_unavailable", "pin_lesson"].map((k) =>
        `<button type="button" data-kind="${k}" class="${k === ui.kind ? "on" : ""}">${esc(t(`kind_${k}`))}</button>`).join("")}</div>
      <div class="row" id="r-fields" style="margin-top:12px">${ruleFields(ui.kind)}</div>
      <label class="field" style="margin-top:10px">${esc(t("f_note"))}<input type="text" id="r-note" maxlength="500" placeholder="${esc(t("f_note_ph"))}"></label>
      <div id="r-preview"></div>
      <button class="btn" id="r-save" type="button">${esc(t("rule_save"))}</button>
    </details>
    <h3 class="sub-h">${esc(t("rule_active_t", { n: state.rules.length }))}</h3>
    ${!state.rules.length ? `<p class="help">${esc(t("rule_none"))}</p>` : ""}
    ${others.length ? `<table class="list"><tbody>${others.map((r) => `<tr><td><b>${esc(ruleText(r.kind, r.params))}</b>
      ${r.source_text ? `<div class="help" dir="auto">${esc(r.source_text)}</div>` : ""}</td>
      <td class="end"><button class="btn mini danger" data-del="${r.id}">${esc(t("del"))}</button></td></tr>`).join("")}</tbody></table>` : ""}
    ${byTeacher.size ? `<h3 class="sub-h small">${esc(t("rule_avail_t"))}</h3><table class="list"><tbody>${[...byTeacher].map(([tid, rs]) => `
      <tr><td class="w30"><bdi><b>${esc(teacherName(tid))}</b></bdi><div class="help" dir="auto">${esc(rs[0].source_text ?? "")}</div></td>
      <td><div class="chips">${rs.map((r) => `<span class="chip">${esc(t("dayS" + r.params.day))} ${esc(t("p_short", { n: r.params.period }))}
        <button data-del="${r.id}" aria-label="${esc(t("del"))}">×</button></span>`).join("")}</div></td></tr>`).join("")}</tbody></table>` : ""}
    <p class="help">${esc(t("rule_regen_note"))}</p>`;
}
function wireRules() {
  // plain words -> AI preview -> save
  $("#nl-form").onsubmit = async (e) => {
    e.preventDefault();
    const text = $("#nl").value.trim(), out = $("#nl-out");
    if (!text) return;
    const btn = $("#nl-go"); btn.disabled = true;
    try {
      const p = await api("/rules/parse", { method: "POST", body: { text } });
      ui.parsed = { ...p, text };
      out.innerHTML = `<div class="review"><div class="eyebrow">${esc(t("rule_review"))}</div>
        ${(p.rules?.length ? p.rules : [p]).map((r) => `<b>${esc(ruleText(r.kind, r.params))}</b>`).join("<br>")}${p.explanation ? `<p class="help">${esc(p.explanation)}</p>` : ""}
        <div class="row"><button class="btn" id="nl-save">${esc(t("rule_save"))}</button><button class="btn secondary" id="nl-cancel">${esc(t("cancel"))}</button></div></div>`;
      $("#nl-cancel").onclick = () => { ui.parsed = null; out.innerHTML = ""; };
      $("#nl-save").onclick = (ev) => busy(ev.currentTarget, async () => {
        const body = ui.parsed.rules?.length ? { rules: ui.parsed.rules, source_text: ui.parsed.text }
          : { kind: ui.parsed.kind, params: ui.parsed.params, source_text: ui.parsed.text };
        await updating(() => api("/rules", { method: "POST", body }));
        await savedRule();
      });
    } catch (err) {
      out.innerHTML = msg(err instanceof ApiFail && err.code === "ai_unavailable" ? "warn" : "err",
        esc(err instanceof ApiFail && err.code === "ai_unavailable" ? t("chat_no_ai") : err.message));
    } finally { btn.disabled = false; }
  };
  // build it yourself
  const readParams = () => Object.fromEntries($$("[data-p]").map((s) => [s.dataset.p, Number(s.value)]));
  const preview = () => {
    const bad = ui.kind === "teacher_unavailable" && !$('[data-p="teacher_id"]').value;
    $("#r-preview").innerHTML = bad ? msg("warn", esc(t("ac_pick_first"))) : msg("ok", esc(ruleText(ui.kind, readParams())));
  };
  const mount = () => {
    const host = $("#r-teacher"), hid = $('[data-p="teacher_id"]');
    if (host) teacherPicker(host, { label: t("f_teacher"), onPick: (id) => { hid.value = id ?? ""; preview(); } });
  };
  $$("[data-p]").forEach((s) => (s.onchange = preview));
  mount(); preview();
  $$("[data-kind]").forEach((b) => (b.onclick = () => {
    ui.kind = b.dataset.kind;
    $$("[data-kind]").forEach((x) => x.classList.toggle("on", x === b));
    $("#r-fields").innerHTML = ruleFields(ui.kind);
    $$("[data-p]").forEach((s) => (s.onchange = preview)); mount(); preview();
  }));
  $("#r-save").onclick = (e) => busy(e.currentTarget, async () => {
    if (ui.kind === "teacher_unavailable" && !$('[data-p="teacher_id"]').value) throw new Error(t("ac_pick_first"));
    await updating(() => api("/rules", { method: "POST", body: { kind: ui.kind, params: readParams(), source_text: $("#r-note").value } }));
    await savedRule();
  });
  $$("[data-del]").forEach((b) => (b.onclick = () => busy(b, async () => {
    await updating(() => api(`/rules/${b.dataset.del}`, { method: "DELETE" }));
    state.rules = await api("/rules"); redrawRules();
  })));
}
async function savedRule() {
  ui.parsed = null;
  state.rules = await api("/rules"); redrawRules();
}
function redrawRules() {
  const open = $("details.manual")?.open;
  $("#rules-panel").innerHTML = rulesPanel();
  if (open) $("details.manual").open = true;
  wireRules();
}
