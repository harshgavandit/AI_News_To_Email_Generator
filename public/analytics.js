// Optional analytics is loaded only after a reader opts in on Privacy & Controls.
(() => {
  const key = "informa-analytics-consent";
  function allowed() {
    try {
      return navigator.globalPrivacyControl !== true && navigator.doNotTrack !== "1" &&
        localStorage.getItem(key) === "granted";
    } catch { return false; }
  }
  if (allowed()) {
    window.va = window.va || function () { (window.vaq = window.vaq || []).push(arguments); };
    window.va("beforeSend", (event) => {
      if (!allowed()) return null;
      try {
        const url = new URL(event.url);
        url.search = "";
        url.hash = "";
        return { ...event, url: url.toString() };
      } catch { return null; }
    });
    const script = document.createElement("script");
    script.src = "/_vercel/insights/script.js";
    script.defer = true;
    document.head.append(script);
  }
  window.addEventListener("storage", (event) => {
    if (event.key === key || event.key === null) location.reload();
  });
})();
