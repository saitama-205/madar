// "Build a request": pick a kind and fill dropdowns (class / subject / day / period from the real data, teacher with the
// case-insensitive autocomplete); it writes ONE English sentence into the Scheduler's text box. The user then presses the
// normal Preview button, so nothing is saved here. Only the kinds the backend understands are offered:
// move a lesson, swap two lessons, a subject never in a period, a teacher unavailable, a lesson pinned.
import { $, $$, t, esc, state, api, allLessons, subjectName, dayName, DAYS, PERIODS, teacherPicker } from "../core.js";

const EN_DAYS = ["Sunday", "Monday", "Tuesday", "Wednesday", "Thursday"];
const enSubject = (id) => state.subjects.find((s) => s.id === id)?.name ?? "";

// kind -> [[field, label key, list]]
const FIELDS = {
  move: [["class", "f_class", "classes"], ["fromday", "bf_fromday", "days"], ["fromperiod", "bf_fromperiod", "periods"],
    ["today", "bf_today", "days"], ["toperiod", "bf_toperiod", "periods"]],
  swap: [["class", "f_class", "classes"], ["day1", "bf_day1", "days"], ["period1", "bf_period1", "periods"],
    ["day2", "bf_day2", "days"], ["period2", "bf_period2", "periods"]],
  forbidden: [["subject", "f_subject", "subjects"], ["period", "f_period", "periods"]],
  unavailable: [["teacher", "f_teacher", "teacher"], ["day", "f_day", "days"], ["period", "f_period", "periods"]],
  pin: [["class", "f_class", "classes"], ["subject", "f_subject", "subjects"], ["day", "f_day", "days"], ["period", "f_period", "periods"]],
};
const DEFAULT = { today: 1, day2: 2, period2: 3, toperiod: 1 };       // sensible second slots
const SENTENCE = {
  move: (v) => `Move class ${v.class} ${EN_DAYS[v.fromday]} period ${v.fromperiod} to ${EN_DAYS[v.today]} period ${v.toperiod}`,
  swap: (v) => `Swap class ${v.class} ${EN_DAYS[v.day1]} period ${v.period1} with ${EN_DAYS[v.day2]} period ${v.period2}`,
  forbidden: (v) => `${v.subject} should never be in period ${v.period}`,
  unavailable: (v) => `${v.teacher} can't teach on ${EN_DAYS[v.day]} period ${v.period}`,
  pin: (v) => `Class ${v.class} always has ${v.subject} on ${EN_DAYS[v.day]} period ${v.period}`,
};

const ui = { kind: "move", values: {} };

function listOptions(list) {
  if (list === "classes") return state.classes.map((c) => [c.name, c.name]);
  if (list === "subjects") return state.subjects.map((s) => [s.name, subjectName(s.id)]);
  if (list === "days") return DAYS.map((d) => [d, dayName(d)]);
  return PERIODS.map((p) => [p, String(p)]);
}

// Returns { sentence() } and renders into host. onUse(sentence) is called by the "Put in the box" button.
export function mountBuilder(host, onUse) {
  host.innerHTML = `<details class="builder"><summary>${esc(t("chat_build_t"))}</summary>
    <p class="help">${esc(t("chat_build_d"))}</p>
    <label class="field">${esc(t("chat_build_kind"))}<select id="b-kind">${Object.keys(FIELDS).map((k) =>
      `<option value="${k}" ${k === ui.kind ? "selected" : ""}>${esc(t(`chat_bk_${k}`))}</option>`).join("")}</select></label>
    <div class="bld-grid" id="b-fields"></div>
    <div class="field">${esc(t("chat_build_sentence"))}<div class="bld-sentence" id="b-sentence" dir="ltr"></div></div>
    <div class="row"><button type="button" class="btn mini" id="b-use">${esc(t("chat_build_use"))}</button></div></details>`;
  let tpick = null;

  const read = () => {
    const v = {};
    for (const [name, , list] of FIELDS[ui.kind]) {
      if (list === "teacher") { const x = state.teachers.find((y) => y.id === tpick?.id()); v[name] = x ? x.name : ""; continue; }
      const el = $(`[data-f="${name}"]`, host);
      v[name] = el ? (list === "classes" || list === "subjects" ? el.value : Number(el.value)) : "";
    }
    return v;
  };
  const sentence = () => SENTENCE[ui.kind](read());
  const refresh = () => {
    const missing = ui.kind === "unavailable" && !tpick?.id();
    $("#b-sentence", host).textContent = missing ? t("ac_pick_first") : sentence();
    $("#b-use", host).disabled = missing;
    for (const [name] of FIELDS[ui.kind]) { const el = $(`[data-f="${name}"]`, host); if (el) ui.values[ui.kind + name] = el.value; }
  };
  const drawFields = () => {
    tpick = null;
    $("#b-fields", host).innerHTML = FIELDS[ui.kind].map(([name, label, list]) => list === "teacher"
      ? `<div id="b-teacher"></div>`
      : `<label class="field">${esc(t(label))}<select data-f="${name}">${listOptions(list).map(([val, text]) =>
          `<option value="${esc(val)}" ${String(val) === String(ui.values[ui.kind + name] ?? DEFAULT[name] ?? "") ? "selected" : ""}>${esc(text)}</option>`).join("")}</select></label>`).join("");
    const th = $("#b-teacher", host);
    if (th) tpick = teacherPicker(th, { label: t("f_teacher"), onPick: refresh });
    $$("select[data-f]", host).forEach((s) => (s.onchange = refresh));
    refresh();
  };
  $("#b-kind", host).onchange = (e) => { ui.kind = e.target.value; drawFields(); };
  $("#b-use", host).onclick = () => onUse(sentence());
  drawFields();
}

// A real example from the current timetable: swap two lessons of different subjects in the first class that has lessons.
export async function tryExample() {
  const lessons = await allLessons().catch(() => []);
  const cls = state.classes.find((c) => lessons.some((l) => l.class_id === c.id));
  if (cls) {
    const mine = lessons.filter((l) => l.class_id === cls.id).sort((a, b) => a.day - b.day || a.period - b.period);
    const a = mine[0], b = mine.find((l) => l.subject_id !== a.subject_id && l.day !== a.day);
    if (a && b) return SENTENCE.swap({ class: cls.name, day1: a.day, period1: a.period, day2: b.day, period2: b.period });
  }
  const s = state.subjects.find((x) => x.name === "PE") ?? state.subjects[0];
  return s ? SENTENCE.forbidden({ subject: s.name, period: 7 }) : "PE should never be in period 7";
}
