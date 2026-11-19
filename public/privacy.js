import { clearReadingData, dataCounts, readBrowserData, readingGroups } from "/privacy-data.js";
import { monitorInbox } from "./monitor-inbox.js";

const byId = (id) => document.getElementById(id);
const feedback = byId("privacy-status");
const dialog = byId("clear-data-dialog");
let pending = [];

function refresh() {
  try {
    const counts = dataCounts(readBrowserData(localStorage));
    byId("export-browser-data").disabled = false;
    byId("clear-browser-data").disabled = false;
    for (const [key, count] of Object.entries(counts)) byId(`count-${key}`).textContent = String(count);
    byId("privacy-storage-note").textContent = "Stored in this browser. These reading lists do not sync to an account.";
  } catch {
    byId("privacy-storage-note").textContent = "Browser storage is unavailable. Reading data cannot be inspected or changed here.";
    byId("export-browser-data").disabled = true;
    byId("clear-browser-data").disabled = true;
    for (const input of document.querySelectorAll("[name=clear-group]")) input.disabled = true;
  }
}

byId("export-browser-data").addEventListener("click", () => {
  try {
    const payload = { product: "Informa AI", version: 1, exported_at: new Date().toISOString(),
      scope: "Reading data and preferences from this browser only. Email and author-review records are not included.",
      data: readBrowserData(localStorage) };
    const url = URL.createObjectURL(new Blob([JSON.stringify(payload, null, 2)], { type: "application/json" }));
    const link = document.createElement("a");
    link.href = url;
    link.download = "informa-ai-browser-data.json";
    link.click();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
    feedback.textContent = "Your browser data export is ready. Keep the downloaded file private.";
  } catch { feedback.textContent = "The export could not be created. Check that browser storage and downloads are available."; }
});

byId("clear-browser-data").addEventListener("click", () => {
  pending = [...document.querySelectorAll("[name=clear-group]:checked")].map((input) => input.value);
  if (!pending.length) {
    feedback.textContent = "Select the reading data you want to clear first.";
    return;
  }
  byId("clear-data-list").replaceChildren(...pending.map((group) => {
    const row = document.createElement("li");
    row.textContent = readingGroups[group].label;
    return row;
  }));
  dialog.showModal();
});
byId("cancel-clear-data").addEventListener("click", () => dialog.close());
byId("confirm-clear-data").addEventListener("click", () => {
  try {
    const cleared = clearReadingData(localStorage, pending);
    feedback.textContent = `Cleared: ${cleared.join(", ")}. Your appearance and analytics choices were kept.`;
    for (const input of document.querySelectorAll("[name=clear-group]")) input.checked = false;
  } catch { feedback.textContent = "Some data could not be cleared. Check your browser storage settings and review the counts before trying again."; }
  dialog.close();
  refresh();
});

const monitorStatus = byId("privacy-monitor-status");
const deleteMonitor = byId("delete-background-watches");
function showMonitoring(active) {
  monitorStatus.textContent = active ? "Background monitoring is enabled in this browser." : "This browser has no active background monitoring session.";
  deleteMonitor.hidden = !active;
}
monitorInbox().then((data) => showMonitoring(data?.active)).catch(() => {
  monitorStatus.textContent = "Background monitoring status is temporarily unavailable.";
});
deleteMonitor.addEventListener("click", async () => {
  deleteMonitor.disabled = true;
  try {
    await monitorInbox("", { method: "DELETE" });
    showMonitoring(false);
    try { localStorage.setItem("informa-reader-reset", String(Date.now())); } catch { /* Other tabs check on their next poll. */ }
    monitorStatus.textContent = "Background watches and alert history were deleted.";
  } catch (error) {
    monitorStatus.textContent = error.message;
  } finally { deleteMonitor.disabled = false; }
});

function bindAnalyticsChoice(choice, status, key, label) {
  function reflect() {
    choice.value = "denied";
    choice.disabled = navigator.globalPrivacyControl === true || navigator.doNotTrack === "1";
    if (choice.disabled) {
      status.textContent = "This setting is off because your browser requests privacy protection.";
      return;
    }
    try {
      const enabled = localStorage.getItem(key) === "granted";
      choice.value = enabled ? "granted" : "denied";
      status.textContent = `${label} ${enabled ? "enabled" : "disabled"} in this browser.`;
    } catch {
      choice.disabled = true;
      status.textContent = "This setting is unavailable because browser storage is blocked.";
    }
  }
  choice.addEventListener("change", () => {
    try {
      localStorage.setItem(key, choice.value);
      location.reload();
    } catch { status.textContent = "Your choice could not be saved. Check browser storage settings before trying again."; }
  });
  window.addEventListener("storage", (event) => { if (event.key === key || event.key === null) reflect(); });
  reflect();
}
bindAnalyticsChoice(byId("analytics-choice"), byId("analytics-status"), "informa-analytics-consent", "Audience analytics");
bindAnalyticsChoice(byId("performance-choice"), byId("performance-status"), "informa-performance-consent", "Performance metrics");
window.addEventListener("storage", refresh);
refresh();
