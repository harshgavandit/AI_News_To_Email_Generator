function moment(value) {
  return value && !Number.isNaN(Date.parse(value)) ? new Date(value).toLocaleString() : "No recorded check";
}

export function coverageWarning(snapshot) {
  const counts = snapshot?.counts;
  if (!counts) return "";
  if (!counts.enabled) return "No enabled feeds were found in this source scope.";
  const notes = [];
  if (counts.stale) notes.push(`${counts.stale} overdue`);
  if (counts.failed) notes.push(`${counts.failed} with failed checks`);
  if (counts.pending) notes.push(`${counts.pending} awaiting a successful check`);
  return notes.length ? `Some sources are catching up · ${notes.join(" · ")}.` : "";
}

export function nextSweepText(snapshot) {
  const next = Date.parse(snapshot?.next_full_sweep_at);
  return Number.isFinite(next) && next > Date.now()
    ? `Next full sweep: ${moment(snapshot.next_full_sweep_at)} (your local time).`
    : "";
}

export function editionFreshnessText(snapshot) {
  if (!snapshot?.counts?.enabled) return "";
  return [
    snapshot.checked_at ? `Latest source check: ${moment(snapshot.checked_at)}.` : "",
    nextSweepText(snapshot)].filter(Boolean).join(" ");
}

export function freshnessNotice(snapshot, doc = document, { compact = false } = {}) {
  if (!snapshot?.counts) return null;
  const section = doc.createElement("section");
  section.className = "reader-freshness";
  section.setAttribute("aria-label", "Source check freshness");
  const scope = doc.createElement("strong");
  scope.textContent = snapshot.scope;
  const summary = doc.createElement("p");
  summary.textContent = [`Latest recorded check: ${moment(snapshot.checked_at)}.`, coverageWarning(snapshot),
    nextSweepText(snapshot)].filter(Boolean).join(" ");
  if (compact) {
    const detail = doc.createElement("details");
    const heading = doc.createElement("summary");
    heading.textContent = coverageWarning(snapshot) ? "Some sources are catching up" : "Source check details";
    detail.append(heading, scope, summary);
    section.append(detail);
  } else section.append(scope, summary);
  if (snapshot.feeds?.length) {
    const detail = doc.createElement("details");
    const heading = doc.createElement("summary");
    heading.textContent = "Check times by source";
    const list = doc.createElement("ul");
    for (const feed of snapshot.feeds) {
      const row = doc.createElement("li");
      row.textContent = `${feed.label} · ${feed.freshness} · ${moment(feed.checked_at)}`;
      list.append(row);
    }
    detail.append(heading, list);
    section.append(detail);
  }
  return section;
}
