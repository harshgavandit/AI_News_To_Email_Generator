// Plain-language lines about how a grouped story was covered (first publisher, lead time, regions).
export function leadText(minutes) {
  if (!Number.isFinite(minutes) || minutes < 1) return "";
  if (minutes < 60) return `${minutes} min before the next publisher`;
  const hours = Math.round(minutes / 60);
  if (hours < 48) return `${hours} h before the next publisher`;
  return `${Math.round(hours / 24)} days before the next publisher`;
}

export function firstReportedText(summary) {
  if (!summary?.first_reported_by) return "";
  const lead = leadText(summary.lead_minutes);
  return `First reported by ${summary.first_reported_by}${lead ? `, ${lead}` : ""}`;
}

export function regionsText(summary, limit = 4) {
  const regions = (summary?.regions || []).slice(0, limit);
  if (!regions.length) return "";
  return regions.map((region) => `${region.label.replace(" publishers", "")} ${region.count}`).join(" · ");
}

export function coverageSummaryNode(summary, doc = globalThis.document) {
  if (!summary || summary.publishers < 2) return null;
  const box = doc.createElement("p");
  box.className = "coverage-summary";
  const first = firstReportedText(summary);
  const regions = regionsText(summary);
  box.textContent = [first, `${summary.publishers} publishers`, regions && `By region: ${regions}`].filter(Boolean).join(" · ");
  return box;
}
