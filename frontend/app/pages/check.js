// Check: GET /api/analytics (all computed in Python): the hard-rule re-check, teacher workload, gaps,
// hard subjects by period, lessons per class per day. POST /api/analytics/insights: the AI explains them.
import { $, $$, t, esc, iso, api, ApiFail, lang, subjectName, dayShort, DAYS, PERIODS, msg, heading, ICON } from "../core.js";

const HARD = ["hr1", "hr2", "hr3", "hr4", "hr5", "hr6", "hr7"];
const open = { load: false, gaps: false };
let data = null;

export async function render() {
  heading(t("head_check_e"), t("head_check_t"), t("head_check_s"));
  $("#page").innerHTML = `<div class="empty">${esc(t("loading"))}</div>`;
  try { data = await api("/analytics"); }
  catch (e) {
    $("#page").innerHTML = msg(e instanceof ApiFail && e.status === 409 ? "warn" : "err",
      esc(e instanceof ApiFail && e.status === 409 ? t("chk_no_tt") : e.message));
    return;
  }
  const ok = data.rule_check.ok, v = data.rule_check.violations || [];
  $("#page").innerHTML = `
    <section class="panel result ${ok ? "pass" : "fail"}">
      <h2>${esc(t("chk_result_t"))}</h2>
      <div class="verdict"><span class="vmark" aria-hidden="true"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.6" stroke-linecap="round" stroke-linejoin="round">${ok ? '<path d="M5 12.5l4.5 4.5L19 7.5"/>' : '<path d="M12 6v8M12 18.2v.1"/>'}</svg></span>
        <div><div class="vtitle">${esc(ok ? t("chk_ok_t", { n: HARD.length }) : t("chk_bad_t", { n: v.length }))}</div>
        <p class="help">${esc(ok ? t("chk_ok_d") : t("chk_bad_d"))}</p></div></div>
      ${v.length ? `<ul class="bul">${v.map((x) => `<li dir="auto">${esc(x)}</li>`).join("")}</ul>` : ""}
      <table class="list"><thead><tr><th>${esc(t("chk_rules_t"))}</th><th></th></tr></thead><tbody>
        ${HARD.map((k) => `<tr><td>${esc(t(k))}</td><td class="end">${ok ? `<span class="badge-pass">${esc(t("chk_pass"))}</span>` : ""}</td></tr>`).join("")}
      </tbody></table>
    </section>
    <section class="panel" id="ai-panel">
      <div class="row spread"><div><h2>${esc(t("chk_ai_t"))}</h2><p class="help">${esc(t("chk_ai_d"))}</p></div>
        <button class="btn" id="ai-go">${ICON.diamond}<span>${esc(t("chk_ai_btn"))}</span></button></div>
      <div id="ai-out"></div>
    </section>
    <div class="two">
      <section class="panel" id="load"></section>
      <section class="panel" id="gaps"></section>
    </div>
    <div class="two">
      <section class="panel">${hardTable()}</section>
      <section class="panel">${classLoad()}</section>
    </div>`;
  drawLoad(); drawGaps();
  $("#ai-go").onclick = insights;
}

function drawLoad() {
  const rows = [...data.teacher_load].sort((a, b) => b.per_week - a.per_week);
  const max = Math.max(1, ...rows.map((r) => r.per_week)), dayMax = Math.max(1, ...rows.flatMap((r) => r.per_day));
  const shown = open.load ? rows : rows.slice(0, 10);
  $("#load").innerHTML = `
    <h2>${esc(t("chk_load_t"))}</h2><p class="help">${esc(t("chk_load_d"))}</p>
    <div class="bars">${shown.map((r) => `
      <div class="bar-row"><div class="bar-name"><bdi>${esc(r.teacher)}</bdi><span class="muted"> · ${esc(subjectName(r.subject))}</span></div>
        <div class="bar"><i style="width:${(r.per_week / max) * 100}%"></i></div><b class="num">${r.per_week}</b>
        <div class="days" aria-label="${esc(r.per_day.join(", "))}">${r.per_day.map((n, d) =>
          `<i title="${esc(dayShort(d))}: ${n}" style="height:${Math.max(8, (n / dayMax) * 100)}%"></i>`).join("")}</div></div>`).join("")}</div>
    ${rows.length > 10 ? `<button class="link" id="load-more">${esc(open.load ? t("show_less") : t("show_all", { n: rows.length }))}</button>` : ""}`;
  $("#load-more")?.addEventListener("click", () => { open.load = !open.load; drawLoad(); });
}

function drawGaps() {
  const per = new Map();
  for (const g of data.teacher_gaps) {
    const x = per.get(g.teacher_id) ?? { name: g.teacher, total: 0, days: [] };
    x.total += g.gap_periods; x.days.push(g.day); per.set(g.teacher_id, x);
  }
  const rows = [...per.values()].sort((a, b) => b.total - a.total);
  const shown = open.gaps ? rows : rows.slice(0, 10);
  $("#gaps").innerHTML = `
    <h2>${esc(t("chk_gaps_t"))}</h2><p class="help">${esc(t("chk_gaps_d"))} ${esc(t("chk_gaps_n", { n: data.teacher_gaps.length }))}</p>
    <table class="list"><tbody>${shown.map((r) => `<tr><td><bdi>${esc(r.name)}</bdi></td>
      <td>${r.days.sort().map((d) => `<span class="chip">${esc(dayShort(d))}</span>`).join(" ")}</td><td class="end num">${r.total}</td></tr>`).join("")}</tbody></table>
    ${rows.length > 10 ? `<button class="link" id="gaps-more">${esc(open.gaps ? t("show_less") : t("show_all", { n: rows.length }))}</button>` : ""}`;
  $("#gaps-more")?.addEventListener("click", () => { open.gaps = !open.gaps; drawGaps(); });
}

function hardTable() {
  const subjects = Object.keys(data.hard_subjects_by_period);
  const max = Math.max(1, ...subjects.flatMap((s) => data.hard_subjects_by_period[s]));
  return `<h2>${esc(t("chk_hard_t"))}</h2><p class="help">${esc(t("chk_hard_d"))}</p>
    <div class="scroll"><table class="list heat"><thead><tr><th></th>${PERIODS.map((p) => `<th>${esc(t("p_short", { n: p }))}</th>`).join("")}</tr></thead>
    <tbody>${subjects.map((s) => `<tr><th>${esc(subjectName(s))}</th>${data.hard_subjects_by_period[s].map((n) =>
      `<td style="--a:${(n / max).toFixed(2)}">${n}</td>`).join("")}</tr>`).join("")}</tbody></table></div>`;
}

function classLoad() {
  const short = data.class_load.filter((c) => c.per_day.some((n) => n < 7));
  return `<h2>${esc(t("chk_class_t"))}</h2>
    ${short.length ? msg("warn", `<div><b>${esc(t("chk_class_bad"))}</b><ul class="bul">${short.map((c) =>
      `<li>${esc(c.class)}: ${c.per_day.map((n, d) => `${esc(dayShort(d))} ${n}`).join(" · ")}</li>`).join("")}</ul></div>`)
      : msg("ok", esc(t("chk_class_ok")))}`;
}

async function insights() {
  const btn = $("#ai-go"), out = $("#ai-out");
  btn.disabled = true; out.innerHTML = `<p class="help">${esc(t("chk_ai_wait"))}</p>`;
  try {
    const r = await api("/analytics/insights", { method: "POST", body: { language: lang() } });
    out.innerHTML = `<div class="review" dir="auto"><p>${esc(r.summary)}</p>
      ${r.recommendations?.length ? `<ul class="bul">${r.recommendations.map((x) => `<li>${esc(x)}</li>`).join("")}</ul>` : ""}</div>`;
  } catch (e) {
    out.innerHTML = msg("warn", esc(e instanceof ApiFail && e.code === "ai_unavailable" ? t("chk_ai_na") : e.message));
  } finally { btn.disabled = false; }
}
