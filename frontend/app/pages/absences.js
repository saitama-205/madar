// Report an absence. Pick the absent teacher (type any part of the name: case does not matter and small typos are
// forgiven with "Did you mean...?"), then:
//   Short-term: pick one or more days -> POST /api/absences { mode: "short", days } -> ranked cover teachers per lesson.
//   Long-term:  POST /api/absences { mode: "long" } -> every class with ranked teachers who can take the subject over;
//               after the user confirms, POST /api/absences/apply { teacher_id, assignments: [{ class_id, substitute_id }] }.
// Short-term changes nothing. Long-term changes only after Confirm, and the server then rebuilds the timetable.
import { $, $$, t, esc, iso, api, state, subjectName, dayName, DAYS, msg, heading, ICON, lang, teacherPicker,
  teacherMatches, fuzzyTeachers, updating, loadBase, confirmBox, busy, warnList } from "../core.js";

const today = new Date().getDay();
const ui = { mode: "short", teacherId: null, days: new Set([today >= 0 && today <= 4 ? today : 0]), result: null, applied: null };
let picker = null;

export async function render() {
  heading(t("head_abs_e"), t("head_abs_t"), t("head_abs_s"));
  $("#page").innerHTML = `
    <section class="panel">
      <h2>${esc(t("abs_card_t"))}</h2><p class="help">${esc(t("abs_card_d"))}</p>
      <div class="seg" role="group" aria-label="${esc(t("abs_mode"))}">
        ${["short", "long"].map((m) => `<button type="button" data-mode="${m}" class="${ui.mode === m ? "on" : ""}" aria-pressed="${ui.mode === m}">${esc(t(`abs_mode_${m}`))}</button>`).join("")}</div>
      <p class="help" id="mode-help">${esc(t(`abs_mode_${ui.mode}_d`))}</p>
      <form id="abs-form">
        <div id="abs-teacher"></div>
        <div id="who-pick"></div>
        <div class="field days" id="days-box" ${ui.mode === "long" ? "hidden" : ""}>${esc(t("abs_days"))}
          <div class="chips">${DAYS.map((d) => `<label class="chip daychip ${ui.days.has(d) ? "on" : ""}"><input type="checkbox" value="${d}" ${ui.days.has(d) ? "checked" : ""}> ${esc(dayName(d))}</label>`).join("")}</div></div>
        <div class="row" style="margin-top:14px"><button class="btn" id="abs-go" type="submit">${ICON.clock}<span>${esc(t(ui.mode === "short" ? "abs_find" : "abs_find_long"))}</span></button></div>
      </form>
    </section>
    <div id="abs-out"></div>`;

  picker = teacherPicker($("#abs-teacher"), { label: t("abs_teacher"), id: ui.teacherId,
    onPick: (id) => { ui.teacherId = id; if (id != null) $("#who-pick").innerHTML = ""; } });
  $$("[data-mode]").forEach((b) => (b.onclick = () => { ui.mode = b.dataset.mode; ui.result = null; ui.applied = null; render(); }));
  $$("#days-box input").forEach((i) => (i.onchange = () => {
    const d = Number(i.value);
    i.checked ? ui.days.add(d) : ui.days.delete(d);
    i.closest(".chip").classList.toggle("on", i.checked);
  }));
  $("#abs-form").onsubmit = (e) => { e.preventDefault(); find(); };
  if (ui.result) (ui.result.mode === "long" ? drawLong : drawShort)();
}

// The teacher comes from the list; if the box was typed but nothing picked, resolve the text here.
function resolveTeacher() {
  const pick = $("#who-pick");
  pick.innerHTML = "";
  if (picker.id() != null) return picker.id();
  const text = picker.text().trim();
  if (!text) { pick.innerHTML = msg("warn", esc(t("abs_empty"))); return null; }
  const exact = teacherMatches(text);
  if (exact.length === 1) { picker.set(exact[0].id); return exact[0].id; }
  const options = exact.length ? exact : fuzzyTeachers(text);
  if (!options.length) { pick.innerHTML = msg("warn", esc(t("abs_not_found"))); return null; }
  pick.innerHTML = `<div class="choose"><b>${esc(exact.length ? t("abs_pick_t") : t("ac_didyou"))}</b><div class="chips">${options.slice(0, 8).map((x) =>
    `<button type="button" class="chip pick" data-id="${x.id}"><bdi>${esc(x.name)}</bdi> · ${esc(subjectName(x.subject_id))}</button>`).join("")}</div></div>`;
  $$(".pick").forEach((b) => (b.onclick = () => { picker.set(Number(b.dataset.id)); ui.teacherId = Number(b.dataset.id); pick.innerHTML = ""; find(); }));
  return null;
}

async function find() {
  const id = resolveTeacher();
  if (id == null) return;
  ui.teacherId = id; ui.applied = null;
  const days = [...ui.days].sort();
  if (ui.mode === "short" && !days.length) { $("#who-pick").innerHTML = msg("warn", esc(t("abs_pick_day"))); return; }
  const btn = $("#abs-go"); btn.disabled = true;
  $("#abs-out").innerHTML = "";
  try {
    const body = ui.mode === "short" ? { teacher_id: id, mode: "short", days, lang: lang() } : { teacher_id: id, mode: "long", lang: lang() };
    const r = await api("/absences", { method: "POST", body });
    ui.result = ui.mode === "short" ? { mode: "short", teacherId: id, days, list: r } : { ...r, teacherId: id, choice: {} };
    (ui.mode === "short" ? drawShort : drawLong)();
  } catch (e) { $("#abs-out").innerHTML = msg("err", esc(e.message)); }
  finally { btn.disabled = false; }
}

const tname = (id) => state.teachers.find((x) => x.id === id)?.name ?? "";

// ---------- short-term: suggestions only ----------
function drawShort() {
  const { teacherId, days, list } = ui.result;
  const name = tname(teacherId);
  $("#abs-out").innerHTML = days.map((day) => {
    const items = list.filter((x) => x.day === day);
    const head = `<h2>${esc(t("abs_result_t", { teacher: iso(name), day: dayName(day) }))}</h2>`;
    if (!items.length) return `<section class="panel">${head}${msg("ok", esc(t("abs_no_lessons", { teacher: iso(name), day: dayName(day) })))}</section>`;
    return `<section class="panel">${head}${items.map((item) => `
      <div class="cover">
        <div class="cover-h">${esc(t("abs_lesson", { n: item.period, klass: item.class, subject: subjectName(item.subject) }))}</div>
        ${item.substitutes.length ? `<ol class="subs">${item.substitutes.map((s, i) => `
          <li class="${i === 0 ? "best" : ""}"><bdi><b>${esc(s.name)}</b></bdi>${i === 0 ? ` <span class="tag">${esc(t("abs_best"))}</span>` : ""}
            <div class="help">${esc(t(s.reason === "same_subject_free" ? "abs_same" : "abs_free_only"))} · ${esc(t("abs_load", { n: s.day_load }))}</div></li>`).join("")}</ol>
          ${item.explanation ? `<p class="help" dir="auto">${esc(item.explanation)}</p>` : ""}`
        : msg("warn", esc(t("abs_no_sub")))}
      </div>`).join("")}
      <p class="help">${esc(t("abs_not_saved"))}</p></section>`;
  }).join("");
}

// ---------- long-term: choose who takes each class over, then confirm ----------
function drawLong() {
  const r = ui.result;
  const name = tname(r.teacherId);
  if (ui.applied) { $("#abs-out").innerHTML = `<section class="panel"><h2>${esc(t("abs_applied_t", { teacher: iso(name) }))}</h2>
    <ul class="bul">${ui.applied.map((x) => `<li>${esc(t("abs_applied_row", { klass: x.class, subject: subjectName(x.subject), name: iso(x.to_teacher) }))}</li>`).join("")}</ul></section>`; return; }
  if (!r.assignments.length) { $("#abs-out").innerHTML = `<section class="panel"><h2>${esc(t("abs_long_t", { teacher: iso(name) }))}</h2>${msg("ok", esc(t("abs_long_none", { teacher: iso(name) })))}</section>`; return; }
  for (const a of r.assignments) if (!(a.class_id in r.choice)) r.choice[a.class_id] = (a.substitutes.find((s) => !s.over_capacity) ?? null)?.teacher_id ?? null;
  $("#abs-out").innerHTML = `<section class="panel"><h2>${esc(t("abs_long_t", { teacher: iso(name) }))}</h2>
    <p class="help">${esc(t("abs_long_d"))}</p>
    ${r.warnings?.length ? msg("warn", warnList(r.warnings)) : ""}
    ${r.assignments.map((a) => `
      <fieldset class="cover" data-class="${a.class_id}"><legend class="cover-h">${esc(t("abs_long_row", { klass: a.class, subject: subjectName(a.subject), n: a.per_week }))}</legend>
        ${a.substitutes.length ? `<ol class="subs">${a.substitutes.map((s, i) => `
          <li class="${i === 0 ? "best" : ""}"><label class="pickrow"><input type="radio" name="c${a.class_id}" value="${s.teacher_id}" ${r.choice[a.class_id] === s.teacher_id ? "checked" : ""}>
            <span><bdi><b>${esc(s.name)}</b></bdi>${i === 0 ? ` <span class="tag">${esc(t("abs_best"))}</span>` : ""}
            <span class="help block">${esc(t("abs_room", { after: s.load_after, cap: s.capacity }))}${s.over_capacity ? ` · <b class="bad">${esc(t("abs_over"))}</b>` : ""}${s.clashes ? ` · ${esc(t("abs_clash", { n: s.clashes }))}` : ""}</span></span></label></li>`).join("")}</ol>`
        : msg("warn", esc(t("abs_no_sub_long")))}
      </fieldset>`).join("")}
    <div class="row"><button class="btn" id="abs-apply">${esc(t("abs_apply"))}</button></div><div id="apply-out"></div></section>`;
  $$("#abs-out input[type=radio]").forEach((i) => (i.onchange = () => { r.choice[Number(i.closest("fieldset").dataset.class)] = Number(i.value); }));
  $("#abs-apply").onclick = (e) => {
    const btn = e.currentTarget;
    const assignments = r.assignments.filter((a) => r.choice[a.class_id] != null).map((a) => ({ class_id: a.class_id, substitute_id: r.choice[a.class_id] }));
    if (!assignments.length) { $("#apply-out").innerHTML = msg("warn", esc(t("abs_none_chosen"))); return; }
    confirmBox(t("abs_apply_q", { n: assignments.length, teacher: tname(r.teacherId) }), t("abs_apply"), true).then((yes) => {
      if (!yes) return;
      busy(btn, async () => {
        const res = await updating(() => api("/absences/apply", { method: "POST", body: { teacher_id: r.teacherId, assignments } }));
        ui.applied = res.reassigned;
        await loadBase();
        drawLong();
      });
    });
  };
}
