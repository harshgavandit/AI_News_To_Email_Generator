import { coverageLabels } from "./catalog.js";

export function sourceEvidence(document, source, quote, sourceLink) {
  const details = document.createElement("details");
  details.className = "claim-evidence";
  const summary = document.createElement("summary");
  summary.textContent = `Evidence from ${source.publisher || "the source"}`;
  const excerpt = document.createElement("blockquote");
  excerpt.dir = "auto";
  if (source.language) excerpt.lang = source.language;
  excerpt.textContent = quote || source.excerpt || "Only the headline is available in the archive.";
  const attribution = document.createElement("p");
  attribution.className = "small";
  const type = coverageLabels[source.coverage] || "Publisher source";
  attribution.textContent = [type, source.published_at?.slice(0, 10),
    quote ? "Cited passage" : "Publisher evidence"].filter(Boolean).join(" · ");
  details.append(summary, excerpt, attribution, sourceLink(source.url, "Read original ↗"));
  return details;
}

export function appendClaimEvidence(item, claim, evidence, sourceLink) {
  const ids = claim.source_ids || (claim.source_id ? [claim.source_id] : []);
  const quotes = claim.quotes || [claim.quote];
  ids.forEach((id, index) => {
    const source = evidence.find(row => row.id === id);
    if (source) item.append(sourceEvidence(item.ownerDocument, source, quotes[index], sourceLink));
  });
}
