// All sign-in goes through this file. The UI only calls MadarAuth.auth.login(schoolId, password).
// Contract:  async login(school_id, password) -> { ok, code, role, school_id }
//   code: "ok" | "bad_credentials" | "locked" | "network" | "not_admin"
// To connect a real back end, write a class with the same login() (e.g. a fetch to /api/login) and return it
// from getAuth() instead of MockAuth. The AdminOnly wrapper stays.
(function () {
  const CONFIG = {
    MOCK_MODE: true,          // demo: any 4-digit School ID + password "madar"
    MAX_FAILED_LOGINS: 5,     // mock lock-out rules (the real back end should enforce its own)
    LOCKOUT_SECONDS: 30,
    SCHOOL_ID_LEN: 4,
  };

  const Role = { ADMIN: "admin", TEACHER: "teacher", STUDENT: "student", PARENT: "parent" };
  const result = (ok, code, role = null, school_id = "") => ({ ok, code, role, school_id });

  // Trim spaces and turn Arabic-Indic digits into 0-9 so ٠١٢٣ and 0123 are the same ID.
  const ARABIC = "٠١٢٣٤٥٦٧٨٩", PERSIAN = "۰۱۲۳۴۵۶۷۸۹";
  function normalizeSchoolId(value) {
    return String(value || "").trim().replace(/[٠-٩۰-۹]/g, (d) => String(ARABIC.includes(d) ? ARABIC.indexOf(d) : PERSIAN.indexOf(d)));
  }
  function isValidSchoolId(value) {
    return new RegExp(`^[0-9]{${CONFIG.SCHOOL_ID_LEN}}$`).test(normalizeSchoolId(value));
  }

  class MockAuth {
    constructor() { this.fails = {}; this.lockedUntil = {}; }
    async login(schoolId, password) {
      await new Promise((r) => setTimeout(r, 800));                 // pretend network delay
      const now = Date.now();
      if ((this.lockedUntil[schoolId] || 0) > now) return result(false, "locked");
      if (password === "madar") { delete this.fails[schoolId]; return result(true, "ok", Role.ADMIN, schoolId); }
      this.fails[schoolId] = (this.fails[schoolId] || 0) + 1;
      if (this.fails[schoolId] >= CONFIG.MAX_FAILED_LOGINS) {
        this.fails[schoolId] = 0;
        this.lockedUntil[schoolId] = now + CONFIG.LOCKOUT_SECONDS * 1000;
        return result(false, "locked");
      }
      return result(false, "bad_credentials");                       // same message for wrong ID or password
    }
  }

  // Wraps any back end so that ONLY admin accounts can sign in (one rule, whatever the back end).
  class AdminOnly {
    constructor(inner) { this.inner = inner; }
    async login(schoolId, password) {
      let res;
      try { res = await this.inner.login(schoolId, password); } catch { return result(false, "network"); }
      if (res.ok && res.role !== Role.ADMIN) return result(false, "not_admin");
      return res;
    }
  }

  function getAuth() {
    if (CONFIG.MOCK_MODE) return new AdminOnly(new MockAuth());
    throw new Error("Real back end not connected yet: add an HttpAuth class here and return it.");
  }

  window.MadarAuth = { CONFIG, Role, auth: getAuth(), normalizeSchoolId, isValidSchoolId };
})();
