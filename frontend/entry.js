// MADAR entry page: landing -> (morph) -> login. English + Arabic (RTL).
// Sign-in goes only through MadarAuth (services/auth.js); the session through Session (services/session.js).
{
  // ---------- text (i18n) ----------
  const STRINGS = {
    en: {
      eyebrow: "MADAR / SCHOOL SCHEDULER",
      h1: "WELCOME BACK",
      h2: "SIGN IN TO THE SCHOOL ACCOUNT",
      help: "Use the School ID and password issued by your school administrator.",
      school_id: "School ID",
      password: "Password",
      login: "LOGIN",
      remember: "Remember me",
      forgot: "Forgot password?",
      forgot_toast: "Please contact your school administrator.",
      err_id: "School ID is required",
      err_pw: "Password is required",
      lang_switch: "عربي",
      lang_aria: "Switch to Arabic",
      bad_credentials: "Wrong School ID or password.",
      locked: "Too many attempts. Please try again in a moment.",
      network: "Can't reach the school server. Check the connection and try again.",
      not_admin: "Only admins can sign in. This account doesn't have admin access.",
      continue_home: "Continue to timetable",
      demo: "DEMO MODE: any 4 numbers as School ID, password \"madar\".",
      err_id_fmt: "School ID must be exactly 4 digits",
      show_pw: "Show password",
      hide_pw: "Hide password",
      theme_to_dark: "Switch to dark mode",
      theme_to_light: "Switch to light mode",
    },
    ar: {
      eyebrow: "مدار / جدولة المدارس",
      h1: "أهلاً بعودتك",
      h2: "سجّل الدخول إلى حساب المدرسة",
      help: "استخدم رقم المدرسة وكلمة المرور اللذين زوّدتك بهما إدارة المدرسة.",
      school_id: "رقم المدرسة",
      password: "كلمة المرور",
      login: "تسجيل الدخول",
      remember: "تذكرني",
      forgot: "نسيت كلمة المرور؟",
      forgot_toast: "يرجى التواصل مع إدارة المدرسة.",
      err_id: "رقم المدرسة مطلوب",
      err_pw: "كلمة المرور مطلوبة",
      lang_switch: "EN",
      lang_aria: "التبديل إلى الإنجليزية",
      bad_credentials: "رقم المدرسة أو كلمة المرور غير صحيحة.",
      locked: "محاولات كثيرة. حاول مرة أخرى بعد قليل.",
      network: "تعذّر الوصول إلى خادم المدرسة. تحقق من الاتصال وحاول مجددًا.",
      not_admin: "الدخول للمدراء فقط. هذا الحساب لا يملك صلاحية المدير.",
      continue_home: "المتابعة إلى الجدول",
      demo: "وضع تجريبي: أي 4 أرقام كرقم مدرسة، وكلمة المرور «madar».",
      err_id_fmt: "رقم المدرسة يجب أن يتكون من 4 أرقام بالضبط",
      show_pw: "إظهار كلمة المرور",
      hide_pw: "إخفاء كلمة المرور",
      theme_to_dark: "التبديل إلى الوضع الداكن",
      theme_to_light: "التبديل إلى الوضع الفاتح",
    },
  };
  const tr = (lang, key) => (STRINGS[lang] || STRINGS.en)[key] ?? STRINGS.en[key];

  const $ = (sel, root = document) => root.querySelector(sel);
  const asset = (path) => new URL(path, document.baseURI).href;   // absolute, so CSS variables resolve anywhere
  const reducedMotion = matchMedia("(prefers-reduced-motion:reduce)").matches;

  // Icons: 24x24, 1.8 px stroke, currentColor.
  const svg = (body) => `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true" focusable="false">${body}</svg>`;
  const ICON = {
    back: svg('<path d="M20 12H5M11 5.5L4.5 12 11 18.5"/>'),
    eye: svg('<path d="M2.5 12S6 5.5 12 5.5 21.5 12 21.5 12 18 18.5 12 18.5 2.5 12 2.5 12z"/><circle cx="12" cy="12" r="3"/>'),
    sun: svg('<circle cx="12" cy="12" r="4"/><path d="M12 2.5v2M12 19.5v2M4.6 4.6l1.4 1.4M18 18l1.4 1.4M2.5 12h2M19.5 12h2M4.6 19.4L6 18M18 6l1.4-1.4"/>'),
    moon: svg('<path d="M20 14.5A8 8 0 0 1 9.5 4 8 8 0 1 0 20 14.5z"/>'),
    eyeOff: svg('<path d="M3.5 3.5l17 17M10.6 5.6A9.6 9.6 0 0 1 12 5.5c6 0 9.5 6.5 9.5 6.5a17 17 0 0 1-3 3.7M6.2 7.4A16.6 16.6 0 0 0 2.5 12S6 18.5 12 18.5a9.3 9.3 0 0 0 4.2-1M9.9 9.9a3 3 0 0 0 4.2 4.2"/>'),
  };

  // ---------- aurora panels ----------
  const BLOBS = [["b1", "#0000ff"], ["b2", "#431fff"], ["b3", "#baf4e5"], ["b4", "#b79cff"], ["b5", "#ffffff"],
                 ["b6", "#1c45d5"], ["b7", "#6c98e3"], ["b8", "#ffffff"], ["b9", "#1a7bff"]];
  document.querySelectorAll("[data-blobs]").forEach((panel) => {
    panel.insertAdjacentHTML("afterbegin", `<div class="blobs" aria-hidden="true">${
      BLOBS.map(([c, col]) => `<div class="blob ${c}" style="background:${col}"></div>`).join("")}</div>`);
  });

  // ---------- frosted-glass 3D logo ----------
  // A stack of outline-only copies pushed back in depth = see-through glass side walls.
  const DEPTH_LAYERS = 24, LAYER_STEP_PX = 1.6, FRONT = [225, 238, 255], BACK = [120, 165, 255];
  function extrusion() {
    let html = `<div class="layer back" style="transform:translateZ(-${(DEPTH_LAYERS * LAYER_STEP_PX).toFixed(1)}px);background:rgba(255,255,255,.12)"></div>`;
    for (let i = DEPTH_LAYERS; i > 0; i--) {
      const t = i / DEPTH_LAYERS;
      const [r, g, b] = FRONT.map((f, k) => Math.round(f + (BACK[k] - f) * t));
      html += `<div class="layer" style="transform:translateZ(-${(i * LAYER_STEP_PX).toFixed(1)}px);background:rgba(${r},${g},${b},.4)"></div>`;
    }
    return html;
  }
  const stage = $("#logo-stage");
  // Size comes from .mark (morph.css); the stage only carries the image addresses and the sway angles.
  stage.style.cssText = `--hd:url("${asset("assets/logo_hd.png")}");--edge:url("${asset("assets/logo_edge.png")}");--sy:16deg;--sx:6deg;`;
  stage.innerHTML = `<div class="sway" aria-hidden="true"><div class="tilt" data-k="1">${extrusion()}` +
    `<img class="face" src="assets/logo_hd.png" alt="" aria-hidden="true"><div class="glow"></div><div class="sheen"></div></div></div>`;

  // Slight tilt with the mouse.
  document.addEventListener("mousemove", (e) => {
    const x = e.clientX / innerWidth - 0.5, y = e.clientY / innerHeight - 0.5;
    document.querySelectorAll(".tilt").forEach((t) => {
      const k = parseFloat(t.dataset.k || 1);
      t.style.transform = `rotateY(${x * 30 * k}deg) rotateX(${-y * 22 * k}deg)`;
    });
  });
  document.addEventListener("mouseleave", () => document.querySelectorAll(".tilt").forEach((t) => (t.style.transform = "")));

  const root = document.documentElement;
  // Pause the gradient while the panel is off-screen (e.g. scrolled down to a long form on a phone).
  const visObs = new IntersectionObserver((es) => es.forEach((e) => e.target.classList.toggle("vis", e.isIntersecting)));
  visObs.observe($("#slide"));

  // ---------- toast ----------
  let toastTimer;
  function toast(text, negative = false) {
    const el = $("#toast");
    el.textContent = text;
    el.className = "toast show" + (negative ? " negative" : "");
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => (el.className = "toast"), 3500);
  }

  // ---------- "Continue to timetable" (already signed in) ----------
  function renderResume(lang) {
    const pill = $("#resume");
    if (!Session.current()) { pill.hidden = true; return; }
    pill.hidden = false;
    pill.dir = lang === "ar" ? "rtl" : "ltr";
    pill.lang = lang;
    pill.innerHTML = `<span>${tr(lang, "continue_home")}</span>${ICON.back}`;
  }

  // ---------- login ----------
  const { auth, CONFIG, normalizeSchoolId, isValidSchoolId } = window.MadarAuth;
  const remembered = Session.rememberedId();
  const st = { lang: Session.lang(), school: remembered, pw: "", remember: Boolean(remembered), busy: false };
  const body = $("#login");

  function renderLogin() {
    const lang = st.lang;
    const t = (key) => tr(lang, key);
    const dark = root.dataset.theme === "dark";
    body.dir = lang === "ar" ? "rtl" : "ltr";
    body.lang = lang;
    root.lang = lang;
    body.innerHTML = `
      <div class="lang-row rv" style="--i:0">
        <button class="lang theme-btn" id="theme" type="button" aria-label="${t(dark ? "theme_to_light" : "theme_to_dark")}"
          title="${t(dark ? "theme_to_light" : "theme_to_dark")}">${dark ? ICON.sun : ICON.moon}</button>
        <button class="lang" id="lang" type="button" aria-label="${t("lang_aria")}" lang="${lang === "en" ? "ar" : "en"}">${t("lang_switch")}</button>
      </div>
      <div class="login-grid">
        <div class="intro">
          <div class="intro-top">
            <div class="eyebrow rv" style="--i:1">${t("eyebrow")}</div>
            <h1 class="h1 rv" style="--i:2">${t("h1")}</h1>
            <h2 class="h2 rv" style="--i:3">${t("h2")}</h2>
          </div>
          <div class="intro-bot">
            <p class="help rv" style="--i:5">${t("help")}</p>
            ${CONFIG.MOCK_MODE ? `<p class="demo rv" style="--i:6">${t("demo")}</p>` : ""}
          </div>
        </div>
        <form class="form" id="login-form" novalidate>
          <div class="rv" style="--i:2">
          <label class="flabel" for="school">${t("school_id")}</label>
          <div class="m-field" id="f-school">
            <div class="ctrl">
              <input id="school" name="school_id" autocomplete="username" inputmode="numeric"
                     maxlength="${CONFIG.SCHOOL_ID_LEN}" aria-describedby="school-err" dir="ltr">
            </div>
            <div class="err" id="school-err" aria-live="polite"></div>
          </div>
          </div>
          <div class="rv" style="--i:3">
          <label class="flabel" for="pw">${t("password")}</label>
          <div class="m-field" id="f-pw">
            <div class="ctrl">
              <input id="pw" name="password" type="password" autocomplete="current-password" aria-describedby="pw-err">
              <button class="eye" id="eye" type="button" aria-label="${t("show_pw")}" aria-pressed="false">${ICON.eye}</button>
            </div>
            <div class="err" id="pw-err" aria-live="polite"></div>
          </div>
          </div>
          <div class="row rv" style="--i:4">
            <label class="check"><input type="checkbox" id="remember"> <span>${t("remember")}</span></label>
            <span class="flink" id="forgot" tabindex="0" role="button">${t("forgot")}</span>
          </div>
          <div class="rv" style="--i:5">
            <button class="m-btn" id="login-btn" type="submit">
              <span class="label">${t("login")}</span><span class="spin" aria-hidden="true"></span>
            </button>
          </div>
        </form>
      </div>`;

    const school = $("#school"), pw = $("#pw"), remember = $("#remember"), btn = $("#login-btn");
    school.value = st.school;
    pw.value = st.pw;
    remember.checked = st.remember;

    // Validation: messages under each field, announced politely. Checked on leaving a field and on submit;
    // once a field shows an error it re-checks as you type.
    const setErr = (field, input, msg) => {
      field.classList.toggle("invalid", Boolean(msg));
      field.querySelector(".err").textContent = msg;
      input.setAttribute("aria-invalid", msg ? "true" : "false");
      return !msg;
    };
    const checkSchool = () => setErr($("#f-school"), school,
      !school.value.trim() ? t("err_id") : !isValidSchoolId(school.value) ? t("err_id_fmt") : "");
    const checkPw = () => setErr($("#f-pw"), pw, pw.value ? "" : t("err_pw"));
    school.addEventListener("blur", () => school.value && checkSchool());
    school.addEventListener("input", () => $("#f-school").classList.contains("invalid") && checkSchool());
    pw.addEventListener("input", () => $("#f-pw").classList.contains("invalid") && checkPw());

    $("#eye").addEventListener("click", (e) => {
      const show = pw.type === "password";
      pw.type = show ? "text" : "password";
      e.currentTarget.innerHTML = show ? ICON.eyeOff : ICON.eye;
      e.currentTarget.setAttribute("aria-pressed", String(show));
      e.currentTarget.setAttribute("aria-label", t(show ? "hide_pw" : "show_pw"));
    });

    const forgot = () => toast(t("forgot_toast"));
    $("#forgot").addEventListener("click", forgot);
    $("#forgot").addEventListener("keydown", (e) => {
      if (e.key === "Enter" || e.key === " ") { e.preventDefault(); forgot(); }
    });

    $("#theme").addEventListener("click", () => {
      Object.assign(st, { school: school.value, pw: pw.value, remember: remember.checked });
      Session.setTheme(dark ? "light" : "dark");
      root.dataset.theme = Session.theme();
      renderLogin();
      $("#theme").focus();
    });

    $("#lang").addEventListener("click", () => {
      Object.assign(st, { school: school.value, pw: pw.value, remember: remember.checked, lang: lang === "en" ? "ar" : "en" });
      Session.setLang(st.lang);                     // the app opens in the same language
      renderLogin();
      renderResume(st.lang);
      $("#lang").focus();
    });

    // Enter in either field submits (real <form>).
    $("#login-form").addEventListener("submit", async (e) => {
      e.preventDefault();
      if (st.busy) return;
      const okId = checkSchool(), okPw = checkPw();
      if (!okId || !okPw) { (okId ? pw : school).focus(); return; }

      st.busy = true;
      btn.disabled = true; btn.classList.add("loading"); btn.setAttribute("aria-busy", "true");
      const res = await auth.login(normalizeSchoolId(school.value), pw.value);
      if (res.ok) {
        if (remember.checked) Session.rememberId(res.school_id); else Session.forgetId();
        Session.signIn({ school_id: res.school_id, role: res.role });
        Session.setLang(lang);
        location.href = "home/";
        return;                                     // keep the loading state while the next page opens
      }
      st.busy = false;
      btn.disabled = false; btn.classList.remove("loading"); btn.removeAttribute("aria-busy");
      toast(t(res.code), true);
      pw.value = "";
      pw.focus();
    });
  }

  renderLogin();
  renderResume(st.lang);

  // ---------- morph: landing <-> login ----------
  // Triggers: arrow click, scroll down (wheel, swipe up, ArrowDown / PageDown / Space), click or Enter on the icon.
  // Scrolling up at the top of the login (or Escape) plays it back. Input is ignored while it plays.
  const slide = $("#slide"), mark = $("#mark"), cue = $("#cue");
  const IMG_W = 1541, IMG_H = 364, DIAMOND = { x0: 1186, y0: 20, x1: 1520, y1: 298 };   // diamond's box in the PNG
  const OPEN_MS = reducedMotion ? 0 : 1800, CLOSE_MS = reducedMotion ? 0 : 1300;
  let busyUntil = 0, timer = 0;

  // Where the icon lands, measured on the real page at every trigger (any window size). The icon and the wordmark
  // are both centred in the panel and stay centred while it shrinks, so the flight is the diamond's offset from
  // the wordmark's centre, and the scale is the diamond's width over the icon's width.
  function fit() {
    const r = $(".word img").getBoundingClientRect();
    const cx = ((DIAMOND.x0 + DIAMOND.x1) / 2) / IMG_W, cy = ((DIAMOND.y0 + DIAMOND.y1) / 2) / IMG_H;
    root.style.setProperty("--dx", (r.width * (cx - 0.5)).toFixed(2) + "px");
    root.style.setProperty("--dy", (r.height * (cy - 0.5)).toFixed(2) + "px");
    root.style.setProperty("--s", ((r.width * (DIAMOND.x1 - DIAMOND.x0) / IMG_W) / mark.offsetWidth).toFixed(4));
  }

  function opened(on) {                       // accessibility side of the state
    mark.setAttribute("aria-expanded", String(on));
    mark.tabIndex = on ? -1 : 0;
    cue.tabIndex = on ? -1 : 0;
    body.inert = !on;
    try { history.replaceState(null, "", on ? "#login" : location.pathname + location.search); } catch {}
  }

  const isOpen = () => root.classList.contains("go");
  const isDone = () => root.classList.contains("done");
  const busy = () => Date.now() < busyUntil;
  const atTop = () => (window.scrollY || root.scrollTop) <= 0;

  function open(byKeyboard) {
    if (isOpen() || busy()) return;
    fit();
    busyUntil = Date.now() + OPEN_MS;
    root.classList.add("go");
    opened(true);
    clearTimeout(timer);
    timer = setTimeout(() => {
      root.classList.add("done");
      root.classList.remove("lock");             // the login content can scroll now
      if (byKeyboard) $("#school").focus({ preventScroll: true });
    }, OPEN_MS);
  }

  function close(byKeyboard) {
    if (!isDone() || busy()) return;
    clearTimeout(timer);
    busyUntil = Date.now() + CLOSE_MS;
    root.classList.add("lock");
    window.scrollTo(0, 0);
    root.classList.remove("done", "go");           // the same transitions play backwards
    opened(false);
    if (byKeyboard) mark.focus({ preventScroll: true });
  }

  mark.addEventListener("click", () => open(false));
  mark.addEventListener("keydown", (e) => {
    if (e.key === "Enter" || e.key === " ") { e.preventDefault(); e.stopPropagation(); open(true); }
  });
  cue.addEventListener("click", (e) => open(e.detail === 0));        // detail 0 = pressed with the keyboard

  addEventListener("wheel", (e) => {
    if (!isDone() || busy()) {                                       // landing or playing: the page never scrolls
      e.preventDefault();
      if (!isOpen() && e.deltaY > 2) open(false);
      return;
    }
    if (e.deltaY < -2 && atTop()) { e.preventDefault(); close(false); }
  }, { passive: false });

  let touchY = null;
  addEventListener("touchstart", (e) => { touchY = e.touches[0].clientY; }, { passive: true });
  addEventListener("touchmove", (e) => { if (!isDone() || busy()) e.preventDefault(); }, { passive: false });
  addEventListener("touchend", (e) => {
    if (touchY === null) return;
    const dy = touchY - e.changedTouches[0].clientY;                 // > 0 = swipe up = scroll down
    touchY = null;
    if (dy > 30) open(false);
    else if (dy < -30 && atTop()) close(false);
  }, { passive: true });

  const SCROLL_KEYS = ["ArrowDown", "PageDown", " ", "ArrowUp", "PageUp", "Home", "End"];
  addEventListener("keydown", (e) => {
    const typing = e.target.closest && e.target.closest("input, textarea, select, [contenteditable]");
    if (typing) return;
    if (!isDone() || busy()) {
      if (SCROLL_KEYS.includes(e.key)) e.preventDefault();
      if (!isOpen() && ["ArrowDown", "PageDown", " "].includes(e.key)) open(true);
      return;
    }
    if (e.key === "Escape" || ((e.key === "ArrowUp" || e.key === "PageUp") && atTop())) { e.preventDefault(); close(true); }
  });

  addEventListener("resize", () => { if (isOpen()) fit(); });
  addEventListener("hashchange", () => { if (location.hash === "#login") open(false); });   // a link to #login on this page

  // Opened straight away (link to .../#login, e.g. from the timetable's sign-in guard): no animation.
  if (isOpen()) {
    fit();
    opened(true);
    requestAnimationFrame(() => requestAnimationFrame(() => root.classList.remove("instant")));
  }
}
