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
    document.querySelector('meta[name="theme-color"]').content = dark ? "#111917" : "#f4f6f8";
  };

  // Apply before the stylesheets load to avoid flashing the other theme.
  apply();
  systemTheme.addEventListener("change", apply);

  document.addEventListener("DOMContentLoaded", () => {
    const select = document.getElementById("site-theme");
    select.value = preference;
    select.disabled = false;
    select.addEventListener("change", () => {
      preference = valid(select.value);
      try {
        localStorage.setItem(key, preference);
      } catch {}
      apply();
    });
    window.addEventListener("storage", (event) => {
      if (event.key !== key && event.key !== null) return;
      preference = valid(event.newValue);
      select.value = preference;
      apply();
    });
  });
})();
