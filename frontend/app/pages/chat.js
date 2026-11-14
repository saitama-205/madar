// Chat: type a request in English or Arabic -> the backend's AI turns it into a rule (POST /api/rules/parse)
// -> preview bubble -> Apply (save rule + regenerate) or Cancel. Nothing changes before Apply.
import { $, t, esc, iso, api, ApiFail, generate, state, ruleText, heading, ICON, lang } from "../core.js";

const thread = [];            // { who: "me" | "bot", html, proposal? } kept while the app is open
let pending = null;           // the proposal waiting for Apply / Cancel

const examples = () => {
  const teacher = state.teachers[0]?.name ?? "";
  return lang() === "ar"
    ? ["التربية البدنية لا تكون في الحصة السابعة", "الرياضيات لا تكون في الحصة الأولى", `${iso(teacher)} لا تدرّس يوم الأحد الحصة الأولى`]
    : ["PE should never be in period 7", "Math shouldn't be in period 1", `${iso(teacher)} can't teach on Sunday period 1`];
};

export async function render() {
  heading(t("head_chat_e"), t("head_chat_t"), t("head_chat_s"));
  $("#page").innerHTML = `
    <div class="chat-layout">
      <section class="panel chat">
        <div class="chat-head"><span class="chat-ico">${ICON.diamond}</span>
          <div><b>${esc(t("chat_assistant"))}</b><div class="live"><i></i>${esc(t("chat_ready"))}</div></div></div>
        <div class="thread" id="thread" aria-live="polite"></div>
        <form class="composer" id="composer">
          <input type="text" id="ask" autocomplete="off" placeholder="${esc(t("chat_placeholder"))}" aria-label="${esc(t("chat_placeholder"))}">
          <button class="btn" id="send" type="submit">${esc(t("chat_send"))}</button>
        </form>
      </section>
      <aside class="side">
        <section class="panel">
          <div class="eyebrow">${esc(t("chat_try_e"))}</div><h2>${esc(t("chat_try"))}</h2>
          <p class="help">${esc(t("chat_try_hint"))}</p>
          <div class="examples">${examples().map((x) => `<button type="button" class="example">${esc(x)}</button>`).join("")}</div>
        </section>
        <section class="panel">
          <div class="eyebrow">${esc(t("chat_know_e"))}</div><h2>${esc(t("chat_know_t"))}</h2>
          <ul class="bul"><li>${esc(t("chat_know_1"))}</li><li>${esc(t("chat_know_2", { teacher: iso(state.teachers[0]?.name ?? "") }))}</li>
            <li>${esc(t("chat_know_3"))}</li><li>${esc(t("chat_know_ar"))}</li></ul>
        </section>
        <section class="panel">
          <div class="eyebrow">${esc(t("chat_not_e"))}</div><h2>${esc(t("chat_not_t"))}</h2>
          <ul class="bul"><li>${esc(t("chat_not_1"))}</li><li>${esc(t("chat_not_2"))}</li></ul>
        </section>
      </aside>
    </div>`;

  document.querySelectorAll(".example").forEach((b) => (b.onclick = () => { $("#ask").value = b.textContent.replace(/[\u2068\u2069]/g, ""); $("#ask").focus(); }));
  $("#composer").onsubmit = (e) => { e.preventDefault(); ask(); };
  drawThread();
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
  input.value = "";
  const send = $("#send"); send.disabled = true; send.textContent = t("chat_checking");
  try {
    const p = await api("/rules/parse", { method: "POST", body: { text } });
    pending = { ...p, text };
    thread.push({ who: "bot", proposal: true, html: `
      <b>${esc(t("chat_proposal"))}</b>
      <div class="tile"><span class="eyebrow">${esc(t(`kind_${p.kind}`))}</span><strong>${esc(ruleText(p.kind, p.params))}</strong></div>
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
    await api("/rules", { method: "POST", body: { kind: p.kind, params: p.params, source_text: p.text } });
    state.rules = await api("/rules");
  } catch (e) { say("bot", `<b>${esc(t("chat_couldnt"))}</b><p>${esc(e.message)}</p>`); return; }
  try { await generate(); say("bot", esc(t("chat_applied"))); }
  catch (e) { say("bot", esc(t("chat_applied_fail", { msg: e.message }))); }
}
