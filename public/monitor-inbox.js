export async function monitorInbox(path = "", { method = "GET", body, signal } = {}) {
  const response = await fetch(`/api/intelligence/inbox${path}`, {
    method, signal: signal || AbortSignal.timeout(15000), cache: "no-store", credentials: "same-origin",
    ...(body === undefined ? {} : { headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) }),
  });
  const data = await response.json().catch(() => null);
  if (!response.ok) {
    const error = new Error(typeof data?.detail === "string" ? data.detail : "Background monitoring could not be reached.");
    error.status = response.status;
    throw error;
  }
  return data;
}
