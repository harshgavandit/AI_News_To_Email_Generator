"use strict";

(() => {
  const key = "informa-theme";
  const root = document.documentElement;
  const systemTheme = matchMedia("(prefers-color-scheme: dark)");
  // Readers choose light or dark. Until they choose (or if an older "system" choice is saved),
  // the first look matches the device so the page never opens in the opposite theme.
  const valid = (value) => ["light", "dark"].includes(value) ? value : null;
  let preference = null;
  try {
    preference = valid(localStorage.getItem(key));
  } catch {}

  const current = () => preference || (systemTheme.matches ? "dark" : "light");
  let select = null;

  const apply = () => {
    const theme = current();
    root.dataset.theme = theme;
    const meta = document.querySelector('meta[name="theme-color"]');
    if (meta) meta.content = theme === "dark" ? "#040b19" : "#f3f7fc";
    if (select) select.value = theme;
  };

  // Apply before the stylesheets load to avoid flashing the other theme.
  apply();
  systemTheme.addEventListener("change", apply);

  document.addEventListener("DOMContentLoaded", () => {
    select = document.getElementById("site-theme");
    if (select) {
      for (const option of [...select.options]) if (!valid(option.value)) option.remove();
      select.value = current();
      select.disabled = false;
      select.addEventListener("change", () => {
        preference = valid(select.value) || current();
        try {
          localStorage.setItem(key, preference);
        } catch {}
        // Cross-fade the change where supported; reduced motion switches instantly.
        const animate = document.startViewTransition && !matchMedia("(prefers-reduced-motion: reduce)").matches;
        if (!animate) {
          apply();
          return;
        }
        const transition = document.startViewTransition(apply);
        // A new theme change or navigation can cancel the animation while the change still applies.
        transition.ready.catch(() => {});
        transition.updateCallbackDone.catch(() => {});
        transition.finished.catch(() => {});
      });
    }
    window.addEventListener("storage", (event) => {
      if (event.key !== key && event.key !== null) return;
      preference = valid(event.newValue);
      apply();
    });
  });
})();
