// Share a Curiosity Card's own page: the system share sheet where available, otherwise copy the link.

export function cardPageUrl(id, origin = globalThis.location?.origin || "") {
  return `${origin}/cards/${encodeURIComponent(String(id))}`;
}

export async function shareCard(card, { nav = globalThis.navigator, origin = globalThis.location?.origin || "" } = {}) {
  const url = cardPageUrl(card.id, origin);
  if (typeof nav?.share === "function") {
    try {
      await nav.share({ title: String(card.title || "Curiosity Card"), url });
      return { outcome: "shared", url };
    } catch (error) {
      if (error?.name === "AbortError") return { outcome: "cancelled", url };
    }
  }
  try {
    await nav.clipboard.writeText(url);
    return { outcome: "copied", url };
  } catch {
    return { outcome: "manual", url };
  }
}

export function shareMessage(result) {
  return {
    shared: "Shared.", copied: "Link copied. Paste it anywhere to share this story.", cancelled: "",
    manual: `Copy this link to share the story: ${result.url}`,
  }[result.outcome] ?? "";
}
