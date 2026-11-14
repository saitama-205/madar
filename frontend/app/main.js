// The timetable app after sign-in (/home/). Plain ES modules, no build step.
// Screens: Timetable, Chat, Rules & data, Absences, Check (+ Settings), one per #hash.
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

export function applyLang() {
  const root = document.documentElement;
  root.lang = lang();
  root.dir = lang() === "ar" ? "rtl" : "ltr";
}
export function applyTheme() {
  document.documentElement.dataset.theme = Session.theme();
}

function renderTopbar() {
  const r = route(), dark = Session.theme() === "dark";
  $("#topbar").innerHTML = `
    <div class="left">
      <a class="ibtn glass ${r === "settings" ? "on" : ""}" href="#settings" ${r === "settings" ? 'aria-current="page"' : ""}>${ICON.gear}<span class="nt">${esc(t("nav_settings"))}</span></a>
      <a class="ibtn glass flip-rtl" href="../">${ICON.back}<span class="nt">${esc(t("back_start"))}</span></a>
      <button class="ibtn glass square" id="theme" type="button" aria-label="${esc(t(dark ? "theme_to_light" : "theme_to_dark"))}"
        title="${esc(t(dark ? "theme_to_light" : "theme_to_dark"))}">${dark ? ICON.sun : ICON.moon}</button>
    </div>
    <nav class="tabs glass" aria-label="${esc(t("nav_label"))}">${NAV.map(([key, icon]) =>
      `<a href="#${key}" class="${key === r ? "active" : ""}" ${key === r ? 'aria-current="page"' : ""}>${icon}<span>${esc(t(`nav_${key}`))}</span></a>`).join("")}</nav>
    <a class="brand glass" href="../" aria-label="MADAR"><i class="brand-mark" aria-hidden="true"></i></a>`;
  $("#theme").onclick = () => {
    Session.setTheme(Session.theme() === "dark" ? "light" : "dark");
    applyTheme(); renderTopbar();
  };
}

export async function render() {
  renderTopbar();
  const page = ROUTES[route()];
  try { await page.render(); }
  catch (e) {
    console.error(e);
    $("#page").innerHTML = msg("err", esc(`${t("load_failed")} ${e.message}`));
  }
  if (document.activeElement === document.body) window.scrollTo(0, 0);
}
export async function refreshAll() {               // after a language change or a data reset
  applyLang(); await loadBase(); await render();
}

window.addEventListener("hashchange", render);

(async () => {
  applyLang(); applyTheme();
  try { await loadBase(); }
  catch (e) {
    renderTopbar();
    heading("MADAR", t("server_down_t"), t("server_down_s"));
    $("#page").innerHTML = msg("err", esc(e.message));
    return;
  }
  await render();
})();
