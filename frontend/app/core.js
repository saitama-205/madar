// Shared by every screen: API calls, app state, words (t), icons, colours, toasts, dialogs, page header.
import { STRINGS } from "./i18n.js";

// ---------- language ----------
export const lang = () => Session.lang();
export function t(key, params = {}) {
  const s = (STRINGS[lang()] || STRINGS.en)[key] ?? STRINGS.en[key] ?? key;
  return s.replace(/\{(\w+)\}/g, (_, k) => (params[k] ?? `{${k}}`));
}
export const dayName = (d) => t(`day${d}`);
export const dayShort = (d) => t(`dayS${d}`);
export const DAYS = [0, 1, 2, 3, 4];
export const PERIODS = [1, 2, 3, 4, 5, 6, 7];
export const iso = (s) => `⁨${s}⁩`;             // keeps Arabic names from scrambling a sentence

// ---------- HTML helpers ----------
export const $ = (sel, root = document) => root.querySelector(sel);
export const $$ = (sel, root = document) => [...root.querySelectorAll(sel)];
export const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);

// ---------- API ----------
export class ApiFail extends Error {
  constructor(status, code, message) { super(message); this.status = status; this.code = code; }
}
export async function api(path, options = {}) {
  const isForm = options.body instanceof FormData;
  const res = await fetch("/api" + path, {
    ...options,
    headers: options.body && !isForm ? { "Content-Type": "application/json" } : undefined,
    body: options.body ? (isForm ? options.body : JSON.stringify(options.body)) : undefined,
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new ApiFail(res.status, data.error || "http_error", data.message || `Request failed (${res.status})`);
  return data;
}
// A route the backend does not have yet answers 404/405 from the static file server.
export const missingRoute = (e) => e instanceof ApiFail && (e.status === 405 || (e.status === 404 && /^not found$/i.test(e.message)));

// ---------- state ----------
export const state = {
  subjects: [], classes: [], teachers: [], rules: [],
  generated: null, lessons: null,          // lessons of every class, loaded on demand
};
const read = (k) => { try { return localStorage.getItem(k); } catch { return null; } };
const write = (k, v) => { try { localStorage.setItem(k, v); } catch {} };
export const isStale = () => read("madar.stale") === "1";
export const setStale = (v) => write("madar.stale", v ? "1" : "0");
export const lastGenerated = () => Number(read("madar.generatedAt")) || 0;

export async function loadBase() {
  [state.subjects, state.classes, state.teachers, state.rules] = await Promise.all(
    ["/subjects", "/classes", "/teachers", "/rules"].map((p) => api(p)));
  if (state.classes[0]) state.generated = (await api(`/timetable?class_id=${state.classes[0].id}`)).lessons.length > 0;
  else state.generated = false;
}
export async function allLessons() {
  if (!state.lessons) {
    const lists = await Promise.all(state.classes.map((c) => api(`/timetable?class_id=${c.id}`)));
    state.lessons = lists.flatMap((x) => x.lessons);
  }
  return state.lessons;
}
export const dropLessons = () => { state.lessons = null; };

export function markGenerated() {
  state.generated = true; dropLessons(); setStale(false); write("madar.generatedAt", String(Date.now()));
}
// Generate skips classes that are missing a teacher and lists them in r.warnings (it no longer fails the school).
export async function generate() {
  const r = await api("/timetable/generate", { method: "POST" });
  markGenerated();
  return r;
}
export const warnList = (w) => (w?.length ? `<ul class="bul">${w.map((x) => `<li dir="auto">${esc(x)}</li>`).join("")}</ul>` : "");

// ---------- names ----------
export const byId = (list, id) => list.find((x) => x.id === id);
export function subjectName(idOrName) {
  const s = typeof idOrName === "number" ? byId(state.subjects, idOrName) : state.subjects.find((x) => x.name === idOrName);
  if (!s) return String(idOrName);
  return lang() === "ar" && s.name_ar ? s.name_ar : s.name;
}
export const teacherName = (id) => byId(state.teachers, id)?.name ?? `#${id}`;
export const className = (id) => byId(state.classes, id)?.name ?? `#${id}`;
export const gradeOf = (c) => c.grade;

// Subject colours (pastel fill, ink text) and short labels, keyed by the English name the API uses.
const PASTEL = {
  "Islamic Education": "#c9d6ff", Arabic: "#bfe9dc", English: "#ffd9c2", Math: "#d9c9ff", Science: "#c2eefa",
  "Social Studies": "#ffe7a8", Computer: "#bcd0f5", PE: "#ffc9d4", Art: "#e4f5b8", Music: "#e9c9f2",
};
const ABBR = {
  en: { "Islamic Education": "Isl", Arabic: "Ara", English: "Eng", Math: "Mat", Science: "Sci", "Social Studies": "Soc", Computer: "Com", PE: "PE", Art: "Art", Music: "Mus" },
  ar: { "Islamic Education": "إسلامية", Arabic: "عربي", English: "إنجليزي", Math: "رياضيات", Science: "علوم", "Social Studies": "اجتماعيات", Computer: "حاسوب", PE: "بدنية", Art: "فنية", Music: "موسيقى" },
};
export const pastel = (name) => PASTEL[name] ?? `hsl(${[...String(name)].reduce((a, c) => a + c.charCodeAt(0), 0) % 360} 80% 86%)`;
export const abbr = (name) => ABBR[lang()]?.[name] ?? String(name).slice(0, 3);
export const subjectChip = (idOrName) => {
  const en = typeof idOrName === "number" ? byId(state.subjects, idOrName)?.name : idOrName;
  return `<span class="chip" style="background:${pastel(en)}">${esc(subjectName(idOrName))}</span>`;
};
export const options = (list, selected, label = (x) => iso(x.name)) =>
  list.map((x) => `<option value="${x.id}" ${x.id === selected ? "selected" : ""}>${esc(label(x))}</option>`).join("");

// ---------- icons: 24x24, 1.8 px stroke, round caps, currentColor ----------
const svg = (body, fill = false) => `<svg viewBox="0 0 24 24" ${fill ? 'fill="currentColor" stroke="none"'
  : 'fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"'} aria-hidden="true" focusable="false">${body}</svg>`;
export const ICON = {
  grid: svg('<rect x="3.5" y="3.5" width="17" height="17" rx="1.5"/><path d="M3.5 9.2h17M3.5 14.8h17M9.2 3.5v17M14.8 3.5v17"/>'),
  diamond: svg('<path d="M11 2.6c3.5 2.2 6.2 5.1 8.2 9-2 3.9-4.7 6.8-8.2 9-3.5-2.2-6.2-5.1-8.2-9 2-3.9 4.7-6.8 8.2-9z"/><path d="M19.6 2.6l2 2-2 2-2-2z"/>', true),
  list: svg('<path d="M3.5 6h7M3.5 12h7M3.5 18h7M13.5 6h7M13.5 12h7M13.5 18h7"/>'),
  clock: svg('<circle cx="12" cy="12" r="9"/><path d="M12 6.5V12h4.2"/>'),
  check: svg('<rect x="3.5" y="3.5" width="17" height="17" rx="3"/><path d="M8 12.2l2.8 2.8L16.5 9"/>'),
  gear: svg('<circle cx="12" cy="12" r="3"/><path d="M19.4 13.5a1.6 1.6 0 0 0 .3 1.8l.1.1a2 2 0 1 1-2.8 2.8l-.1-.1a1.6 1.6 0 0 0-1.8-.3 1.6 1.6 0 0 0-1 1.5V20a2 2 0 1 1-4 0v-.1a1.6 1.6 0 0 0-1-1.5 1.6 1.6 0 0 0-1.8.3l-.1.1a2 2 0 1 1-2.8-2.8l.1-.1a1.6 1.6 0 0 0 .3-1.8 1.6 1.6 0 0 0-1.5-1H4a2 2 0 1 1 0-4h.1a1.6 1.6 0 0 0 1.5-1 1.6 1.6 0 0 0-.3-1.8l-.1-.1a2 2 0 1 1 2.8-2.8l.1.1a1.6 1.6 0 0 0 1.8.3h.1a1.6 1.6 0 0 0 1-1.5V4a2 2 0 1 1 4 0v.1a1.6 1.6 0 0 0 1 1.5 1.6 1.6 0 0 0 1.8-.3l.1-.1a2 2 0 1 1 2.8 2.8l-.1.1a1.6 1.6 0 0 0-.3 1.8v.1a1.6 1.6 0 0 0 1.5 1H20a2 2 0 1 1 0 4h-.1a1.6 1.6 0 0 0-1.5 1z"/>'),
  back: svg('<path d="M20 12H5M11 5.5L4.5 12 11 18.5"/>'),
  sun: svg('<circle cx="12" cy="12" r="4"/><path d="M12 2.5v2M12 19.5v2M4.6 4.6l1.4 1.4M18 18l1.4 1.4M2.5 12h2M19.5 12h2M4.6 19.4L6 18M18 6l1.4-1.4"/>'),
  moon: svg('<path d="M20 14.5A8 8 0 0 1 9.5 4 8 8 0 1 0 20 14.5z"/>'),
  upload: svg('<path d="M12 15.5V4M7 8.5l5-5 5 5M4.5 15v3.5a2 2 0 0 0 2 2h11a2 2 0 0 0 2-2V15"/>'),
  download: svg('<path d="M12 4v11.5M7 10.5l5 5 5-5M4.5 15v3.5a2 2 0 0 0 2 2h11a2 2 0 0 0 2-2V15"/>'),
  pencil: svg('<path d="M4 20l1-4.2L16.6 4.2a2 2 0 0 1 2.8 0l.4.4a2 2 0 0 1 0 2.8L8.2 19 4 20z"/><path d="M14.5 6.3l3.2 3.2"/>'),
  send: svg('<path d="M4 12l16-7-6 16-2.5-6.5L4 12z"/>'),
};

// ---------- feedback ----------
let toastTimer;
// kind: false/"ok" (dark), true/"err" (red), "warn" (yellow). sticky: stays until the next toast.
export function toast(text, kind = false, sticky = false) {
  const el = $("#toast");
  const k = kind === true ? "err" : kind || "";
  el.textContent = text;
  el.className = "toast show" + (k ? " " + k : "");
  clearTimeout(toastTimer);
  if (!sticky) toastTimer = setTimeout(() => (el.className = "toast"), k === "warn" ? 9000 : 4000);
}

// Every change on the server regenerates the timetable by itself (the response has generated / violations / warnings).
// updating(work): show "Updating timetable…" while work() runs, then "Timetable updated" (yellow when there is
// something to know: classes skipped, rule problems) or the reason it could not be rebuilt.
export function reportUpdate(r) {
  if (!r || r.generated === undefined) return r;
  if (r.generated) {
    markGenerated();
    const notes = [...(r.warnings || []), ...(r.violations || [])];
    toast(notes.length ? `${t("tt_updated")}: ${notes.slice(0, 3).join(" ")}` : t("tt_updated"), notes.length ? "warn" : false);
  } else {
    toast(t("tt_not_updated", { msg: (r.warnings || [])[0] || "" }), "warn");
  }
  return r;
}
export async function updating(work) {
  toast(t("updating"), "warn", true);
  try { return reportUpdate(await work()); }
  catch (e) { toast(e.message, true); throw e; }
}
export async function busy(button, work) {
  button.disabled = true;
  try { await work(); } catch (e) { toast(e.message, true); } finally { button.disabled = false; }
}
export const msg = (kind, html) => `<div class="msg ${kind}" role="${kind === "err" ? "alert" : "status"}">${html}</div>`;

// A confirm dialog built into the page (window.confirm is blocked in some viewers).
export function confirmBox(text, okLabel, danger = false) {
  return new Promise((resolve) => {
    const dlg = document.createElement("dialog");
    dlg.className = "dlg";
    dlg.innerHTML = `<p>${esc(text)}</p><div class="row end"><button class="btn secondary" value="no">${esc(t("cancel"))}</button>
      <button class="btn ${danger ? "danger-fill" : ""}" value="yes">${esc(okLabel)}</button></div>`;
    document.body.appendChild(dlg);
    dlg.addEventListener("click", (e) => { const v = e.target.closest("button")?.value; if (v) dlg.close(v); });
    dlg.addEventListener("close", () => { resolve(dlg.returnValue === "yes"); dlg.remove(); });
    dlg.showModal();
  });
}

// ---------- page header (one glass card on the gradient) ----------
export function heading(eyebrow, title, sentence) {
  const hero = $("#hero");
  hero.className = "hero-cards single";
  hero.innerHTML = `<div class="card glass head"><div class="eyebrow">${esc(eyebrow)}</div><h1 class="title">${esc(title)}</h1><p class="help">${esc(sentence)}</p></div>`;
}

export const ruleText = (kind, p) => {
  if (kind === "subject_not_in_period") return t("rule_desc_subject", { subject: subjectName(p.subject_id), period: p.period });
  if (kind === "teacher_unavailable") return t("rule_desc_teacher", { teacher: iso(teacherName(p.teacher_id)), day: dayName(p.day), period: p.period });
  if (kind === "pin_lesson") return t("rule_desc_pin", { klass: className(p.class_id), subject: subjectName(p.subject_id), day: dayName(p.day), period: p.period });
  return kind;
};

// ---------- teacher autocomplete: type any part of a name (any case) -> pick -> you get the teacher's id ----------
const fold = (s) => String(s).toLowerCase().replace(/[ً-ْٰـ]/g, "")
  .replace(/[أإآٱ]/g, "ا").replace(/ى/g, "ي").replace(/ة/g, "ه");
export function teacherMatches(q) {
  const f = fold(q).trim();
  return state.teachers.filter((x) => !f || fold(x.name).includes(f));
}
let acSeq = 0;
// host: an element to fill. Returns { id() -> number|null, set(id), clear() }.
export function teacherPicker(host, { label, id = null, placeholder = "", onPick = () => {} } = {}) {
  const uid = `ac${++acSeq}`;
  host.innerHTML = `<div class="field"><label for="${uid}">${esc(label ?? t("pick_teacher"))}</label>
    <div class="ac"><input id="${uid}" type="text" dir="auto" autocomplete="off" role="combobox" aria-expanded="false"
      aria-controls="${uid}-l" aria-autocomplete="list" placeholder="${esc(placeholder || t("ac_ph"))}">
      <ul class="ac-list" id="${uid}-l" role="listbox" hidden></ul></div></div>`;
  const input = host.querySelector("input"), list = host.querySelector("ul");
  let picked = null, shown = [], active = -1;
  const close = () => { list.hidden = true; input.setAttribute("aria-expanded", "false"); active = -1; };
  const choose = (x) => { picked = x.id; input.value = x.name; close(); onPick(x.id); };
  const mark = () => list.querySelectorAll("li").forEach((li, i) => li.classList.toggle("on", i === active));
  function open() {
    shown = teacherMatches(input.value).slice(0, 30);
    list.innerHTML = shown.length ? shown.map((x, i) => `<li role="option" data-i="${i}"><bdi>${esc(x.name)}</bdi><small>${esc(subjectName(x.subject_id))}</small></li>`).join("")
      : `<li class="none" role="presentation">${esc(t("ac_none"))}</li>`;
    list.hidden = false; input.setAttribute("aria-expanded", "true"); active = -1;
  }
  input.addEventListener("input", () => { picked = null; onPick(null); open(); });
  input.addEventListener("focus", open);
  input.addEventListener("blur", () => setTimeout(close, 120));
  list.addEventListener("pointerdown", (e) => {
    const li = e.target.closest("li[data-i]"); if (!li) return;
    e.preventDefault(); choose(shown[Number(li.dataset.i)]);
  });
  input.addEventListener("keydown", (e) => {
    if (e.key === "ArrowDown" || e.key === "ArrowUp") {
      e.preventDefault(); if (list.hidden) open();
      if (shown.length) { active = (active + (e.key === "ArrowDown" ? 1 : -1) + shown.length) % shown.length; mark(); list.children[active]?.scrollIntoView({ block: "nearest" }); }
    } else if (e.key === "Enter" && !list.hidden && shown.length && active >= 0) { e.preventDefault(); choose(shown[active]); }
    else if (e.key === "Enter" && !list.hidden && shown.length === 1) { e.preventDefault(); choose(shown[0]); }
    else if (e.key === "Escape") close();
  });
  const api_ = {
    id: () => picked,
    set(tid) { const x = byId(state.teachers, tid); picked = x ? x.id : null; input.value = x ? x.name : ""; close(); },
    clear() { picked = null; input.value = ""; close(); },
    focus: () => input.focus(),
  };
  if (id != null) api_.set(id);
  return api_;
}
