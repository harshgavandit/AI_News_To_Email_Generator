// Installable app support on every page: registers the service worker, offers "Install the app"
// where the browser allows it, mounts device-alert controls and keeps alert follows in sync.
import { mountAlertPanel, syncAlerts } from "./push-alerts.js";

let deferredInstall = null;

function installButtons() {
  return [...document.querySelectorAll("[data-install-app]")];
}

function showInstall(visible) {
  for (const button of installButtons()) button.hidden = !visible;
}

export function bindInstall(win = window) {
  win.addEventListener("beforeinstallprompt", (event) => {
    event.preventDefault();
    deferredInstall = event;
    showInstall(true);
  });
  win.addEventListener("appinstalled", () => {
    deferredInstall = null;
    showInstall(false);
  });
  for (const button of installButtons()) button.addEventListener("click", async () => {
    if (!deferredInstall) return;
    const prompt = deferredInstall;
    deferredInstall = null;
    showInstall(false);
    await prompt.prompt();
  });
}

export function startPwa(win = window) {
  bindInstall(win);
  for (const panel of document.querySelectorAll("[data-alert-panel]")) mountAlertPanel(panel);
  if (!("serviceWorker" in win.navigator) || !win.isSecureContext) return Promise.resolve("unsupported");
  return win.navigator.serviceWorker.register("/sw.js", { scope: "/", updateViaCache: "none" })
    .then(() => win.navigator.serviceWorker.ready)
    .then((registration) => ("PushManager" in win ? syncAlerts({ registration }) : "unsupported"))
    .catch(() => "error");
}

if (typeof window !== "undefined" && !window.__informaPwaTest) {
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", () => startPwa(), { once: true });
  else startPwa();
}
