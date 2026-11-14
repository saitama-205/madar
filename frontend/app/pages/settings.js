// Settings: language, appearance (dark mode), account, start page, sign out, demo data, links.
import { $, t, esc, api, ApiFail, generate, setStale, toast, busy, confirmBox, heading } from "../core.js";
import { applyLang, applyTheme, refreshAll, rebuildTopbar } from "../main.js";

const seg = (id, items, value) => `<div class="seg" id="${id}" role="group">${items.map(([v, label]) =>
  `<button type="button" data-v="${v}" class="${v === value ? "on" : ""}" aria-pressed="${v === value}">${esc(label)}</button>`).join("")}</div>`;
const row = (title, hint, control) => `<div class="set-row"><div><b>${esc(title)}</b><p class="help">${esc(hint)}</p></div><div class="set-ctl">${control}</div></div>`;

export async function render() {
  heading(t("head_set_e"), t("head_set_t"), t("head_set_s"));
  const s = Session.current() ?? {};
  $("#page").innerHTML = `
    <section class="panel settings">
      ${row(t("set_language"), t("set_language_hint"), seg("set-lang", [["en", "English"], ["ar", "العربية"]], Session.lang()))}
      ${row(t("set_theme"), t("set_theme_hint"), seg("set-theme", [["light", t("light")], ["dark", t("dark")]], Session.theme()))}
      ${row(t("set_account"), t("set_account_hint", { id: s.school_id ?? "" }), "")}
      ${row(t("set_start"), t("set_start_hint"), `<a class="btn secondary" href="../">${esc(t("set_start_btn"))}</a>`)}
      ${row(t("set_session"), t("set_session_hint"), `<button class="btn" id="signout">${esc(t("sign_out"))}</button>`)}
      ${row(t("set_check"), t("set_check_hint"), `<a class="btn secondary" href="#check">${esc(t("open"))}</a>`)}
      ${row(t("set_ai"), t("set_ai_hint"), `<div id="ai-ctl" class="ai-ctl"><span class="muted">${esc(t("loading"))}</span></div>`)}
      ${row(t("set_api"), t("set_api_hint"), `<a class="btn secondary" href="/docs" target="_blank" rel="noopener">${esc(t("open"))}</a>`)}
      ${row(t("set_demo"), t("set_demo_hint"), `<button class="btn danger" id="reset">${esc(t("set_demo_btn"))}</button>`)}
    </section>`;

  drawAiModel();
  $("#set-lang").onclick = async (e) => {
    const v = e.target.closest("button")?.dataset.v;
    if (!v || v === Session.lang()) return;
    Session.setLang(v); applyLang(); await refreshAll();
  };
  $("#set-theme").onclick = (e) => {
    const v = e.target.closest("button")?.dataset.v;
    if (!v || v === Session.theme()) return;
    Session.setTheme(v); applyTheme(); rebuildTopbar();
    e.currentTarget.querySelectorAll("button").forEach((b) => { b.classList.toggle("on", b.dataset.v === v); b.setAttribute("aria-pressed", String(b.dataset.v === v)); });
  };
  $("#signout").onclick = () => { Session.signOut(); location.href = "../"; };
  $("#reset").onclick = async (e) => {
    const btn = e.currentTarget;                       // the event forgets its button once we await the dialog
    if (!(await confirmBox(t("set_demo_q"), t("set_demo_btn"), true))) return;
    await busy(btn, async () => {
      await api("/reset", { method: "POST" });
      try { await generate(); } catch { setStale(true); }
      toast(t("set_demo_done"));
      await refreshAll();
    });
  };
}

// The AI model: a fixed whitelist from the server (GET/PUT /api/settings/ai). No key and no custom model here.
async function drawAiModel() {
  const box = $("#ai-ctl");
  if (!box) return;
  let info;
  try { info = await api("/settings/ai"); }
  catch { box.innerHTML = `<span class="muted">${esc(t("ai_model_na"))}</span>`; return; }
  const label = (id) => info.models.find((m) => m.id === id)?.label ?? id;
  box.innerHTML = `<label class="field">${esc(t("ai_model"))}<select id="ai-model">${info.models.map((m) =>
      `<option value="${esc(m.id)}" ${m.id === info.model ? "selected" : ""}>${esc(m.label)}</option>`).join("")}
      ${info.models.some((m) => m.id === info.model) ? "" : `<option value="${esc(info.model)}" selected disabled>${esc(info.model)}</option>`}</select></label>
    <p class="help" id="ai-active">${esc(t("ai_active", { model: label(info.model) }))}${info.ai_configured ? "" : " · " + esc(t("ai_no_key"))}</p>`;
  $("#ai-model").onchange = async (e) => {
    const sel = e.target; sel.disabled = true;
    try {
      const r = await api("/settings/ai", { method: "PUT", body: { model: sel.value } });
      $("#ai-active").textContent = t("ai_active", { model: label(r.model) }) + (r.ai_configured ? "" : " · " + t("ai_no_key"));
      toast(t("ai_changed", { model: label(r.model) }));
    } catch (err) { toast(err.message, true); sel.value = info.model; }
    finally { sel.disabled = false; }
  };
}
