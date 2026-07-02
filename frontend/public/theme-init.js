// Blocking, classic (non-module) script: runs in <head> before first paint to
// apply the persisted theme and avoid a flash of the wrong theme (FOUC). Must
// use the SAME localStorage key as src/lib/theme.ts ("knowtwin-theme").
(function () {
  try {
    var t = localStorage.getItem("knowtwin-theme");
    if (t === "light" || t === "dark") {
      document.documentElement.setAttribute("data-theme", t);
    }
  } catch (e) {
    /* storage disabled — index.html's default data-theme="light" stands */
  }
})();
