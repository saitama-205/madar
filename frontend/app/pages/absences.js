// Absences: write the excuse (matched to a teacher name, no AI) or pick the teacher, pick the day,
// then POST /api/absences lists every lesson that needs cover with ranked substitutes. Nothing is saved.
import { $, $$, t, esc, iso, api, state, subjectName, dayName, DAYS, options, msg, heading, ICON } from "../core.js";

const ui = { text: "", teacherId: null, day: Math.min(Math.max(new Date().getDay(), 0), 4), result: null, choices: null };
if (new Date().getDay() > 4) ui.day = 0;                   // Friday / Saturday: start from Sunday

// Arabic spelling variants count as the same letters (أ إ آ -> ا, ة -> ه, ى -> ي, no tashkeel or tatweel).
const norm = (s) => String(s).toLowerCase().replace(/[ً-ْٰـ]/g, "")
  .replace(/[أإآٱ]/g, "ا").replace(/ة/g, "ه").replace(/ى/g, "ي").replace(/[^\p{L}\p{N}\s]/gu, " ").replace(/\s+/g, " ").trim();

// A teacher matches when their first name is a whole word of the excuse; a matching initial ranks them higher.
function matchTeachers(text) {
  const words = norm(text).split(" ");
  const found = [];
  for (const x of state.teachers) {
    const parts = norm(x.name).split(" ").filter(Boolean);
    if (!parts.length) continue;
    const i = words.indexOf(parts[0]);
    if (i < 0) continue;
    const initial = parts[1]?.[0];
    const strong = initial && words[i + 1]?.startsWith(initial);
    found.push({ x, score: strong ? 2 : 1 });
  }
  const best = Math.max(0, ...found.map((f) => f.score));
  return found.filter((f) => f.score === best).map((f) => f.x);
}

export async function render() {
  heading(t("head_abs_e"), t("head_abs_t"), t("head_abs_s"));
  ui.teacherId ??= state.teachers[0]?.id ?? null;
  $("#page").innerHTML = `
    <section class="panel">
      <h2>${esc(t("abs_card_t"))}</h2><p class="help">${esc(t("abs_card_d"))}</p>
      <form id="abs-form">
        <label class="field">${esc(t("abs_excuse"))}<input type="text" id="excuse" dir="auto" value="${esc(ui.text)}" placeholder="${esc(t("abs_excuse_ph"))}"></label>
        <div id="who-pick"></div>
        <div class="row" style="margin-top:12px">
          <label class="field grow">${esc(t("abs_or_pick"))}<select id="abs-teacher">${options(state.teachers, ui.teacherId,
            (x) => `${iso(x.name)} · ${subjectName(x.subject_id)}`)}</select></label>
          <label class="field">${esc(t("abs_day"))}<select id="abs-day">${DAYS.map((d) =>
            `<option value="${d}" ${d === ui.day ? "selected" : ""}>${esc(dayName(d))}</option>`).join("")}</select></label>
        </div>
        <div class="row" style="margin-top:14px"><button class="btn" id="abs-go" type="submit">${ICON.clock}<span>${esc(t("abs_find"))}</span></button></div>
      </form>
      <p class="help small">${esc(t("abs_long_na"))}</p>
    </section>
    <div id="abs-out"></div>`;

  const sel = $("#abs-teacher");
  sel.onchange = () => { ui.teacherId = Number(sel.value); ui.text = ""; $("#excuse").value = ""; $("#who-pick").innerHTML = ""; };
  $("#abs-day").onchange = (e) => { ui.day = Number(e.target.value); };
  $("#excuse").oninput = (e) => { ui.text = e.target.value; };
  $("#abs-form").onsubmit = (e) => { e.preventDefault(); find(); };
  if (ui.result) drawResult();
}

async function find() {
  const text = $("#excuse").value.trim();
  const pick = $("#who-pick");
  pick.innerHTML = "";
  if (text) {                                     // the excuse wins over the list when it names someone
    const hits = matchTeachers(text);
    if (!hits.length) { pick.innerHTML = msg("warn", esc(t("abs_not_found"))); return; }
    if (hits.length > 1) {
      pick.innerHTML = `<div class="choose"><b>${esc(t("abs_pick_t"))}</b><div class="chips">${hits.map((x) =>
        `<button type="button" class="chip pick" data-id="${x.id}"><bdi>${esc(x.name)}</bdi> · ${esc(subjectName(x.subject_id))}</button>`).join("")}</div></div>`;
      $$(".pick").forEach((b) => (b.onclick = () => { setTeacher(Number(b.dataset.id)); pick.innerHTML = ""; run(); }));
      return;
    }
    setTeacher(hits[0].id);
  } else if (ui.teacherId == null) { pick.innerHTML = msg("warn", esc(t("abs_empty"))); return; }
  await run();
}
function setTeacher(id) { ui.teacherId = id; $("#abs-teacher").value = String(id); }

async function run() {
  const btn = $("#abs-go"); btn.disabled = true;
  try {
    const list = await api("/absences", { method: "POST", body: { teacher_id: ui.teacherId, day: ui.day } });
    ui.result = { teacherId: ui.teacherId, day: ui.day, list };
    drawResult();
  } catch (e) { $("#abs-out").innerHTML = msg("err", esc(e.message)); }
  finally { btn.disabled = false; }
}

function drawResult() {
  const { teacherId, day, list } = ui.result;
  const name = state.teachers.find((x) => x.id === teacherId)?.name ?? "";
  const head = `<h2>${esc(t("abs_result_t", { teacher: iso(name), day: dayName(day) }))}</h2>`;
  if (!list.length) { $("#abs-out").innerHTML = `<section class="panel">${head}${msg("ok", esc(t("abs_no_lessons", { teacher: iso(name), day: dayName(day) })))}</section>`; return; }
  $("#abs-out").innerHTML = `<section class="panel">${head}
    ${list.map((item) => `
      <div class="cover">
        <div class="cover-h">${esc(t("abs_lesson", { n: item.period, klass: item.class, subject: subjectName(item.subject) }))}</div>
        ${item.substitutes.length ? `<ol class="subs">${item.substitutes.map((s, i) => `
          <li class="${i === 0 ? "best" : ""}"><bdi><b>${esc(s.name)}</b></bdi>${i === 0 ? ` <span class="tag">${esc(t("abs_best"))}</span>` : ""}
            <div class="help">${esc(t(s.reason === "same_subject_free" ? "abs_same" : "abs_free_only"))} · ${esc(t("abs_load", { n: s.day_load }))}</div></li>`).join("")}</ol>
          ${item.explanation ? `<p class="help" dir="auto">${esc(item.explanation)}</p>` : ""}`
        : msg("warn", esc(t("abs_no_sub")))}
      </div>`).join("")}
    <p class="help">${esc(t("abs_not_saved"))}</p></section>`;
}
