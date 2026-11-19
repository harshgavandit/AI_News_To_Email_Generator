// Each optional collector has its own choice on Privacy & Controls.
(() => {
  const audience = "informa-analytics-consent";
  const performance = "informa-performance-consent";
  function allowed(key) {
    try {
      return navigator.globalPrivacyControl !== true && navigator.doNotTrack !== "1" &&
        localStorage.getItem(key) === "granted";
    } catch { return false; }
  }
  function load(key, command, source) {
    if (!allowed(key)) return;
    const queue = `${command}q`;
    window[command] ||= function () { (window[queue] ||= []).push(arguments); };
    window[command]("beforeSend", (event) => {
      if (!allowed(key)) return null;
      try {
        const url = new URL(event.url);
        url.search = "";
        url.hash = "";
        return { ...event, url: url.toString() };
      } catch { return null; }
    });
    const script = document.createElement("script");
    script.src = source;
    script.defer = true;
    document.head.append(script);
  }
  if (!document.currentScript?.hasAttribute("data-performance-only")) {
    load(audience, "va", "/_vercel/insights/script.js");
  }
  load(performance, "si", "/_vercel/speed-insights/script.js");
  window.addEventListener("storage", (event) => {
    if (event.key === audience || event.key === performance || event.key === null) location.reload();
  });
})();
