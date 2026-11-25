const messages = {
  accepted: ["Accepted for delivery", "The sending service accepted your brief. Check your inbox and spam folder."],
  sent: ["Sending to your mail server", "The provider is attempting delivery. Confirmation may follow."],
  delivered: ["Delivery confirmed", "Your receiving mail server accepted the brief. Check spam or promotions if it is missing."],
  delivery_delayed: ["Delivery is delayed", "The provider is retrying delivery. You can download a copy while you wait."],
  bounced: ["The inbox rejected this email", "Check the address or verify a different inbox. This address is paused for future sends."],
  failed: ["The provider could not deliver this email", "You can still copy your brief or download its HTML or email file."],
  suppressed: ["Delivery to this inbox is paused", "Verify a different inbox to receive briefs. Your preview is still available."],
  complained: ["Delivery to this inbox is paused", "Further emails have been stopped following the receiving provider’s feedback."],
  unconfirmed: ["Delivery could not be confirmed", "Check your inbox before sending another brief. This attempt counts toward your daily allowance."],
};

export function createDeliveryStatus(request, readableTime) {
  const panels = [...document.querySelectorAll(".delivery-receipt")];
  let previewId = "", controller, timer;
  let checks = 0;
  function clear() {
    clearTimeout(timer);
    controller?.abort();
    controller = null;
    previewId = "";
    for (const panel of panels) panel.hidden = true;
    try { sessionStorage.removeItem("informa-mail-receipt"); } catch {}
  }
  async function check() {
    if (!previewId || controller) return;
    const active = controller = new AbortController();
    for (const panel of panels) panel.querySelector("button").disabled = true;
    try {
      const receipt = await request(`/api/mail/delivery/${encodeURIComponent(previewId)}`, { signal: active.signal });
      if (controller !== active) return;
      const [label, explanation] = messages[receipt.status] || messages.unconfirmed;
      const visibility = receipt.status === "accepted" && receipt.tracking === false
        ? " This mail connection only reports acceptance; inbox delivery remains unverified."
        : "";
      for (const panel of panels) {
        panel.hidden = false;
        panel.querySelector(".receipt-state").textContent = label;
        panel.querySelector(".receipt-detail").textContent = `${explanation}${visibility} ${receipt.remaining_today} of ${receipt.limit ?? 3} briefs left today (${receipt.timezone || "UTC"}). Updated ${readableTime(receipt.updated_at)}.`;
      }
      return receipt;
    } catch (error) {
      if (controller !== active || active.signal.aborted) return;
      if ([401, 404].includes(error.status)) clear();
      else for (const panel of panels) {
        panel.hidden = false;
        panel.querySelector(".receipt-state").textContent = "Delivery status is temporarily unavailable";
        panel.querySelector(".receipt-detail").textContent = "Check your inbox before requesting another brief. You can check the status again here.";
      }
    } finally {
      if (controller === active) controller = null;
      for (const panel of panels) panel.querySelector("button").disabled = false;
    }
  }
  async function poll() {
    if (!previewId || document.hidden || checks++ >= 12) return;
    const receipt = await check();
    if (receipt?.tracking && ["accepted", "sent", "delivery_delayed"].includes(receipt.status))
      timer = setTimeout(poll, 5000);
  }
  function track(id) {
    if (!/^[A-Za-z0-9_-]{24,80}$/.test(id || "")) return;
    clear();
    previewId = id;
    checks = 0;
    try { sessionStorage.setItem("informa-mail-receipt", id); } catch {}
    void poll();
  }
  for (const panel of panels) panel.querySelector("button").addEventListener("click", check);
  document.addEventListener("visibilitychange", () => {
    clearTimeout(timer);
    if (!document.hidden && previewId && checks < 12) void poll();
  });
  return { track, clear, restore() {
    try { const saved = sessionStorage.getItem("informa-mail-receipt"); if (saved) track(saved); } catch {}
  } };
}
