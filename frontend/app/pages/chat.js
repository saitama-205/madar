// Chat: type a request in English or Arabic -> the backend's AI turns it into a rule (POST /api/rules/parse)
// -> preview bubble -> Apply (save rule + regenerate) or Cancel. Nothing changes before Apply.
import { $, t, esc, iso, api, ApiFail, updating, state, ruleText, heading, ICON, teacherPicker, setStale, reportUpdate } from "../core.js";

let picker = null;          // optional teacher autocomplete next to the text box

const thread = [];            // { who: "me" | "bot", html, proposal? } kept while the app is open
let pending = null;           // the proposal waiting for Apply / Cancel

// Tappable examples under the text box (one of them Arabic on purpose: Arabic requests work in any UI language).
const EXAMPLES = ["Swap class 1/1 Sunday period 1 with Tuesday period 3", "No PE in period 7",
  "بدّل حصة الصف 1/1 يوم الأحد الحصة 1 مع يوم الثلاثاء الحصة 3"];

export async function render() {
  heading(t("head_chat_e"), t("head_chat_t"), t("head_chat_s"));
  $("#page").innerHTML = `
    <div class="chat-layout">
      <section class="panel chat">
        <div class="chat-head"><span class="chat-ico">${ICON.diamond}</span>
          <div><b>${esc(t("chat_assistant"))}</b><div class="live"><i></i>${esc(t("chat_ready"))}</div></div></div>
        <div class="thread" id="thread" aria-live="polite"></div>
        <div id="chat-teacher"></div>
        <form class="composer" id="composer">
          <input type="text" id="ask" autocomplete="off" placeholder="${esc(t("chat_placeholder"))}" aria-label="${esc(t("chat_placeholder"))}">
          <button class="btn" id="send" type="submit">${esc(t("chat_send"))}</button>
        </form>
        <div class="chips ex" aria-label="${esc(t("chat_try"))}">${EXAMPLES.map((x) => `<button type="button" class="chip example" dir="auto">${esc(x)}</button>`).join("")}</div>
      </section>
      <aside class="side">
        <section class="panel" id="saved-rules"></section>
        <section class="panel">
          <div class="eyebrow">${esc(t("chat_know_e"))}</div><h2>${esc(t("chat_know_t"))}</h2>
          <ul class="bul"><li>${esc(t("chat_know_1"))}</li><li>${esc(t("chat_know_2", { teacher: iso(state.teachers[0]?.name ?? "") }))}</li>
            <li>${esc(t("chat_know_3"))}</li><li>${esc(t("chat_know_4"))}</li><li>${esc(t("chat_know_5"))}</li><li>${esc(t("chat_know_ar"))}</li></ul>
        </section>
        <section class="panel">
          <div class="eyebrow">${esc(t("chat_not_e"))}</div><h2>${esc(t("chat_not_t"))}</h2>
          <ul class="bul"><li>${esc(t("chat_not_1"))}</li><li>${esc(t("chat_not_2"))}</li></ul>
        </section>
      </aside>
    </div>`;

  document.querySelectorAll(".example").forEach((b) => (b.onclick = () => { $("#ask").value = b.textContent; $("#ask").focus(); }));
  $("#composer").onsubmit = (e) => { e.preventDefault(); ask(); };
  picker = teacherPicker($("#chat-teacher"), { label: t("chat_teacher_pick"), placeholder: t("chat_teacher_ph"),
    onPick: (id) => { const x = state.teachers.find((y) => y.id === id); const box = $("#ask");
      if (x && !box.value.toLowerCase().includes(x.name.toLowerCase())) { box.value = (box.value.trim() + " " + x.name).trim(); box.focus(); } } });
  drawThread(); drawSaved();
}

function drawThread() {
  const box = $("#thread");
  const hello = `<div class="bubble bot"><b>${esc(t("chat_hello_t"))}</b><p>${esc(t("chat_hello"))}</p></div>`;
  box.innerHTML = hello + thread.map((m) => `<div class="bubble ${m.who}" dir="auto">${m.html}</div>`).join("");
  if (pending) {
    $("#apply").onclick = apply;
    $("#cancel").onclick = () => { settle(""); say("bot", esc(t("chat_cancelled"))); };
  }
  box.scrollTop = box.scrollHeight;
}
async function drawSaved() {
  const box = $("#saved-rules");
  if (!box) return;
  const rules = state.rules;
  box.innerHTML = `<div class="eyebrow">${esc(t("chat_saved_e"))}</div><h2>${esc(t("chat_saved_t", { n: rules.length }))}</h2>
    ${rules.length ? `<ul class="saved">${rules.map((r) => `<li><span dir="auto">${esc(ruleText(r.kind, r.params))}</span>
      <button type="button" class="chip" data-del="${r.id}" aria-label="${esc(t("del"))}">${esc(t("del"))}</button></li>`).join("")}</ul>`
      : `<p class="help">${esc(t("chat_saved_none"))}</p>`}`;
  box.querySelectorAll("[data-del]").forEach((b) => (b.onclick = async () => {
    b.disabled = true;
    try {
      await updating(() => api(`/rules/${b.dataset.del}`, { method: "DELETE" }));
      state.rules = await api("/rules"); drawSaved();
    } catch (e) { b.disabled = false; }
  }));
}
const say = (who, html) => { thread.push({ who, html }); drawThread(); };
// The open proposal loses its buttons once it is answered (or a new request replaces it).
function settle(replacement) {
  const open = thread.findLast((m) => m.proposal);
  if (open) { open.html = open.html.replace(/<div class="row acts">[\s\S]*<\/div>/, replacement); open.proposal = false; }
  pending = null;
}

async function ask() {
  const input = $("#ask"), text = input.value.trim();
  if (!text) return;
  settle("");
  say("me", esc(text));
  input.value = ""; picker?.clear();
  const send = $("#send"); send.disabled = true; send.textContent = t("chat_checking");
  try {
    const p = await api("/rules/parse", { method: "POST", body: { text } });
    const tid = picker?.id();                       // a teacher picked from the list wins over the AI's reading of the name
    if (tid != null && p.kind === "teacher_unavailable") {
      p.params = { ...p.params, teacher_id: tid };
      p.rules = [{ kind: p.kind, params: p.params }];
    }
    const list = p.rules?.length ? p.rules : [{ kind: p.kind, params: p.params }];
    pending = { ...p, text };
    thread.push({ who: "bot", proposal: true, html: `
      <b>${esc(t("chat_proposal"))}</b>
      <div class="tile"><span class="eyebrow">${esc(t(p.swap ? "kind_swap" : `kind_${p.kind}`))}</span>${list.map((r) => `<strong>${esc(ruleText(r.kind, r.params))}</strong>`).join("")}</div>
      ${p.explanation ? `<p>${esc(p.explanation)}</p>` : ""}
      <div class="row acts"><button class="btn" id="apply">${esc(t("chat_apply"))}</button>
        <button class="btn secondary" id="cancel">${esc(t("chat_cancel"))}</button></div>` });
    drawThread();
  } catch (e) {
    const html = e instanceof ApiFail && e.code === "ai_unavailable" ? esc(t("chat_no_ai"))
      : `<b>${esc(t("chat_couldnt"))}</b><p>${esc(e.message)}</p>`;
    say("bot", html);
  } finally { send.disabled = false; send.textContent = t("chat_send"); }
}

async function apply() {
  if (!pending) return;
  const p = pending;
  settle(`<p class="muted">${esc(t("chat_applying"))}</p>`);      // progress line while it saves and rebuilds
  drawThread();
  try {
    const body = p.rules?.length ? { rules: p.rules, source_text: p.text } : { kind: p.kind, params: p.params, source_text: p.text };
    const r = await updating(() => api("/rules", { method: "POST", body }));
    state.rules = await api("/rules"); drawSaved();
    say("bot", esc(r.generated ? t("chat_applied") : t("chat_applied_fail", { msg: (r.warnings || [])[0] || "" })));
  } catch (e) { say("bot", `<b>${esc(t("chat_couldnt"))}</b><p>${esc(e.message)}</p>`); }
}
