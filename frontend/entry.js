// MADAR entry page: one scrolling page, landing (#top) -> login (#login). English + Arabic (RTL).
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
  stage.style.cssText = `width:min(600px,var(--stage-max,80%));aspect-ratio:600/500;` +
    `--hd:url("${asset("assets/logo_hd.png")}");--edge:url("${asset("assets/logo_edge.png")}");--sy:16deg;--sx:6deg;`;
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

  // ---------- scroll effects ----------
  const root = document.documentElement;
  const prog = () => root.style.setProperty("--p", Math.min(Math.max(scrollY / innerHeight, 0), 1).toFixed(3));
  addEventListener("scroll", prog, { passive: true });
  addEventListener("resize", prog);
  prog();

  const revealObs = new IntersectionObserver((es) => es.forEach((e) => {
    if (e.isIntersecting) { e.target.classList.add("in"); revealObs.unobserve(e.target); }
  }), { threshold: 0.15 });
  const observeReveals = () => document.querySelectorAll(".reveal:not(.in)").forEach((el) => revealObs.observe(el));
  // Pause the gradient while it is off-screen.
  const visObs = new IntersectionObserver((es) => es.forEach((e) => e.target.classList.toggle("vis", e.isIntersecting)));
  document.querySelectorAll(".aurora").forEach((el) => visObs.observe(el));

  document.querySelector(".cue a").addEventListener("click", (e) => {
    e.preventDefault();
    $("#login").scrollIntoView({ behavior: reducedMotion ? "auto" : "smooth" });
  });

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
  const st = { lang: Session.lang(), school: remembered, pw: "", remember: Boolean(remembered), first: true, busy: false };
  const body = $("#login-body");

  function renderLogin() {
    const lang = st.lang;
    const t = (key) => tr(lang, key);
    const reveal = st.first ? "reveal" : "reveal in";
    st.first = false;

    body.dir = lang === "ar" ? "rtl" : "ltr";
    body.lang = lang;
    root.lang = lang;
    body.innerHTML = `
      <div class="lang-row">
        <button class="lang" id="lang" type="button" aria-label="${t("lang_aria")}" lang="${lang === "en" ? "ar" : "en"}">${t("lang_switch")}</button>
      </div>
      <div class="login-grid">
        <div class="intro ${reveal}" style="--d:.15s">
          <div class="intro-top">
            <div class="eyebrow">${t("eyebrow")}</div>
            <h1 class="h1">${t("h1")}</h1>
            <h2 class="h2">${t("h2")}</h2>
          </div>
          <div class="intro-bot">
            <p class="help">${t("help")}</p>
            ${CONFIG.MOCK_MODE ? `<p class="demo">${t("demo")}</p>` : ""}
          </div>
        </div>
        <form class="form ${reveal}" style="--d:.3s" id="login-form" novalidate>
          <label class="flabel" for="school">${t("school_id")}</label>
          <div class="m-field" id="f-school">
            <div class="ctrl">
              <input id="school" name="school_id" autocomplete="username" inputmode="numeric"
                     maxlength="${CONFIG.SCHOOL_ID_LEN}" aria-describedby="school-err" dir="ltr">
            </div>
            <div class="err" id="school-err" aria-live="polite"></div>
          </div>
          <label class="flabel" for="pw">${t("password")}</label>
          <div class="m-field" id="f-pw">
            <div class="ctrl">
              <input id="pw" name="password" type="password" autocomplete="current-password" aria-describedby="pw-err">
              <button class="eye" id="eye" type="button" aria-label="${t("show_pw")}" aria-pressed="false">${ICON.eye}</button>
            </div>
            <div class="err" id="pw-err" aria-live="polite"></div>
          </div>
          <div class="row">
            <label class="check"><input type="checkbox" id="remember"> <span>${t("remember")}</span></label>
            <span class="flink" id="forgot" tabindex="0" role="button">${t("forgot")}</span>
          </div>
          <button class="m-btn" id="login-btn" type="submit">
            <span class="label">${t("login")}</span><span class="spin" aria-hidden="true"></span>
          </button>
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

    observeReveals();
  }

  renderLogin();
  renderResume(st.lang);
}
