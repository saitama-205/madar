// The timetable app after sign-in (/home/). Plain ES modules, no build step.
// Screens: Timetable, Chat, Rules & data, Absences, Check (+ Settings), one per #hash.
// Switching screens is animated without ever freezing the page: the highlight pill starts sliding on the click,
// the old screen fades out, the gradient panel grows/shrinks to its new height and the new screen fades and rises in.
import { $, t, lang, esc, ICON, loadBase, heading, msg } from "./core.js";
import * as timetable from "./pages/timetable.js";
import * as chat from "./pages/chat.js";
import * as rules from "./pages/rules.js";
import * as absences from "./pages/absences.js";
import * as check from "./pages/check.js";
import * as settings from "./pages/settings.js";

const ROUTES = { timetable, chat, rules, absences, check, settings };
const NAV = [["timetable", ICON.grid], ["chat", ICON.diamond], ["rules", ICON.list], ["absences", ICON.clock], ["check", ICON.check]];
const route = () => (location.hash.slice(1) in ROUTES ? location.hash.slice(1) : "timetable");
const reducedMotion = () => matchMedia("(prefers-reduced-motion: reduce)").matches;

export function applyLang() {
  const root = document.documentElement;
  root.lang = lang();
  root.dir = lang() === "ar" ? "rtl" : "ltr";
}
export function applyTheme() {
  document.documentElement.dataset.theme = Session.theme();
}

// ---------- top bar: built once (and again only when the language or theme changes) ----------
let thumbObserver;
function buildTopbar() {
  const dark = Session.theme() === "dark";
  $("#topbar").innerHTML = `
    <div class="left">
      <a class="ibtn glass" id="nav-settings" href="#settings">${ICON.gear}<span class="nt">${esc(t("nav_settings"))}</span></a>
      <a class="ibtn glass flip-rtl" href="../">${ICON.back}<span class="nt">${esc(t("back_start"))}</span></a>
      <button class="ibtn glass square" id="theme" type="button" aria-label="${esc(t(dark ? "theme_to_light" : "theme_to_dark"))}"
        title="${esc(t(dark ? "theme_to_light" : "theme_to_dark"))}">${dark ? ICON.sun : ICON.moon}</button>
    </div>
    <nav class="tabs glass" aria-label="${esc(t("nav_label"))}"><span class="thumb" aria-hidden="true"></span>${NAV.map(([key, icon]) =>
      `<a href="#${key}" data-route="${key}">${icon}<span>${esc(t(`nav_${key}`))}</span></a>`).join("")}</nav>
    <a class="brand glass" href="../" aria-label="MADAR"><i class="brand-mark" aria-hidden="true"></i></a>`;
  $("#theme").onclick = () => {
    Session.setTheme(Session.theme() === "dark" ? "light" : "dark");
    applyTheme(); buildTopbar(); markTopbar(false);
  };
  // Keep the pill on its tab while labels open/close or the window resizes.
  thumbObserver?.disconnect();
  thumbObserver = new ResizeObserver(() => { if (!moving) placeThumb(false); });
  document.querySelectorAll(".tabs a").forEach((a) => thumbObserver.observe(a));
}

let moving = false, movingTimer;
function markTopbar(animate = true) {
  const r = route(), nav = $(".tabs"), links = [...document.querySelectorAll(".tabs a")];
  const apply = () => links.forEach((a) => {
    const on = a.dataset.route === r;
    a.classList.toggle("active", on);
    on ? a.setAttribute("aria-current", "page") : a.removeAttribute("aria-current");
  });
  // On narrow screens the labels open/close as the tab changes, which moves the tabs. Measure where the new tab
  // will END UP (labels snapped), put everything back, then let the labels and the pill animate there together.
  let target = null;
  if (animate) {
    const before = links.map((a) => a.classList.contains("active"));
    nav.classList.add("measure"); apply();
    const act = links.find((a) => a.classList.contains("active"));
    target = act && { x: act.offsetLeft, w: act.offsetWidth };
    links.forEach((a, i) => a.classList.toggle("active", before[i]));
    void nav.offsetWidth; nav.classList.remove("measure");
  }
  apply();
  const s = $("#nav-settings");
  s.classList.toggle("on", r === "settings");
  r === "settings" ? s.setAttribute("aria-current", "page") : s.removeAttribute("aria-current");
  placeThumb(animate, target);
}

function placeThumb(animate, target = null) {
  const thumb = $(".tabs .thumb"), active = $(".tabs a.active");
  if (!thumb) return;
  if (!active) { thumb.style.opacity = "0"; return; }            // Settings is not one of the tabs
  const x = target?.x ?? active.offsetLeft, w = target?.w ?? active.offsetWidth;
  if (animate) {                                                 // ignore the resizes the label animation causes
    moving = true; clearTimeout(movingTimer); movingTimer = setTimeout(() => { moving = false; placeThumb(false); }, 560);
  } else thumb.classList.add("still");
  thumb.style.opacity = "1";
  thumb.style.width = `${w}px`;
  thumb.style.transform = `translateX(${x}px)`;
  if (!animate) { void thumb.offsetWidth; thumb.classList.remove("still"); }
}

// ---------- screens ----------
let first = true, seq = 0;
const EASE = "cubic-bezier(.2,.7,.2,1)";
export async function render() {
  const page = ROUTES[route()], my = ++seq;
  const animate = !first && !reducedMotion();
  first = false;
  markTopbar(animate);                                   // the pill starts moving straight away
  const hero = $(".hero"), parts = [$("#hero"), $("#page")];
  if (animate) {
    parts.forEach((el) => el.getAnimations().forEach((a) => a.cancel()));
    await Promise.all(parts.map((el) => el.animate([{ opacity: 1 }, { opacity: 0 }], { duration: 140, easing: "ease", fill: "forwards" }).finished)).catch(() => {});
    if (my !== seq) return;                              // another tab was clicked meanwhile
  }
  const h0 = hero.offsetHeight;
  window.scrollTo(0, 0);
  const done = page.render().catch((e) => {
    console.error(e);
    $("#page").innerHTML = msg("err", esc(`${t("load_failed")} ${e.message}`));
  });
  if (animate) {
    const h1 = hero.offsetHeight;
    if (h0 !== h1) hero.animate([{ height: `${h0}px` }, { height: `${h1}px` }], { duration: 480, easing: EASE });
    parts.forEach((el) => {
      el.getAnimations().forEach((a) => a.cancel());
      el.animate([{ opacity: 0, transform: "translateY(12px)" }, { opacity: 1, transform: "none" }], { duration: 420, easing: EASE });
    });
  }
  await done;
}
export function rebuildTopbar() { buildTopbar(); markTopbar(false); }
export async function refreshAll() {               // after a language change or a data reset
  applyLang(); await loadBase(); buildTopbar(); markTopbar(false); await render();
}

window.addEventListener("hashchange", render);

(async () => {
  applyLang(); applyTheme(); buildTopbar(); markTopbar(false);
  try { await loadBase(); }
  catch (e) {
    heading("MADAR", t("server_down_t"), t("server_down_s"));
    $("#page").innerHTML = msg("err", esc(e.message));
    return;
  }
  await render();
})();
