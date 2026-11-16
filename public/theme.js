"use strict";

(() => {
  const key = "informa-theme";
  const root = document.documentElement;
  const systemTheme = matchMedia("(prefers-color-scheme: dark)");
  const valid = (value) => ["system", "light", "dark"].includes(value) ? value : "system";
  let preference = "system";
  try {
    preference = valid(localStorage.getItem(key));
  } catch {}

  const apply = () => {
    const dark = preference === "dark" || (preference === "system" && systemTheme.matches);
    root.dataset.theme = dark ? "dark" : "light";
    const meta = document.querySelector('meta[name="theme-color"]');
    if (meta) meta.content = dark ? "#131b17" : "#f6f7f4";
  };

  // Apply before the stylesheets load to avoid flashing the other theme.
  apply();
  systemTheme.addEventListener("change", apply);

  document.addEventListener("DOMContentLoaded", () => {
    const select = document.getElementById("site-theme");
    if (select) {
      select.value = preference;
      select.disabled = false;
      select.addEventListener("change", () => {
        preference = valid(select.value);
        try {
          localStorage.setItem(key, preference);
        } catch {}
        apply();
      });
    }
    window.addEventListener("storage", (event) => {
      if (event.key !== key && event.key !== null) return;
      preference = valid(event.newValue);
      if (select) select.value = preference;
      apply();
    });
  });
})();
