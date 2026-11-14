// Who is signed in, and in which language. Kept in this browser (localStorage), like NiceGUI's app.storage.user.
// Shared by the entry page and the app (/home).
(function () {
  const mem = {};                                    // fallback when storage is blocked
  const get = (k) => { try { const v = localStorage.getItem(k); return v === null ? undefined : JSON.parse(v); } catch { return mem[k]; } };
  const set = (k, v) => { try { localStorage.setItem(k, JSON.stringify(v)); } catch { mem[k] = v; } };
  const del = (k) => { try { localStorage.removeItem(k); } catch { delete mem[k]; } };

  window.Session = {
    current: () => get("madar.auth") || null,                       // { school_id, role } or null
    signIn: (auth) => set("madar.auth", auth),
    signOut: () => del("madar.auth"),
    lang: () => (get("madar.lang") === "ar" ? "ar" : "en"),
    setLang: (code) => set("madar.lang", code),
    // "light" or "dark": the saved choice, else the device's setting.
    theme: () => get("madar.theme") || (matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light"),
    setTheme: (v) => set("madar.theme", v === "dark" ? "dark" : "light"),
    rememberedId: () => get("madar.school_id") || "",
    rememberId: (id) => set("madar.school_id", id),
    forgetId: () => del("madar.school_id"),
  };
})();
