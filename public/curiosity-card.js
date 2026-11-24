// Behaviour for the server-rendered single-card page (/cards/<id>): sharing and anonymous usage counts.
import { bindCardTracking, track } from "./curiosity-events.js";
import { shareCard, shareMessage } from "./curiosity-share.js";

export function startCardPage(doc = document) {
  const main = doc.querySelector("[data-card-id]");
  const article = main?.querySelector("[data-curiosity-id]");
  if (!main || !article) return;
  const id = main.dataset.cardId;
  bindCardTracking(main, "card_page");
  track("card_view", { cardId: id, surface: "card_page" });
  const button = article.querySelector("[data-card-share]");
  const status = article.querySelector(".curiosity-card-status");
  if (!button) return;
  button.hidden = false;
  button.addEventListener("click", async () => {
    const title = article.querySelector(".curiosity-card-title")?.textContent || "";
    const result = await shareCard({ id, title });
    if (status) status.textContent = shareMessage(result);
  });
}

if (typeof window !== "undefined" && document.querySelector("[data-card-id]")) startCardPage();
