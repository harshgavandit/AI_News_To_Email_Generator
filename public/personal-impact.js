import { readingGroups } from "./privacy-data.js";
import { appendClaimEvidence } from "./claim-evidence.js";
import { node, requestJSON, sourceLink } from "./evidence-ui.js";

const key = readingGroups.impact.key;
const providers = { "google-cloud": "Google Cloud", azure: "Azure", cloudflare: "Cloudflare" };

export function readTargets(storage = window.localStorage) {
  try {
    const saved = JSON.parse(storage.getItem(key));
    return Object.fromEntries(["cloud", "packages"].map(kind => [kind,
      Array.isArray(saved?.[kind]) ? saved[kind].filter(row => row && typeof row === "object").slice(0, 5) : []]));
  } catch {
    return { cloud: [], packages: [] };
  }
}

function targetLabel(target) {
  return target.provider ? [providers[target.provider], target.service, target.region].join(" · ") :
    `${target.ecosystem} · ${target.name} ${target.version}`;
}

export function initImpactSettings(root) {
  if (!root) return;
  const list = root.querySelector("[data-impact-list]");
  const status = root.querySelector("[data-impact-status]");
  function save(targets, message) {
    try {
      localStorage.setItem(key, JSON.stringify(targets));
      status.textContent = message;
      render();
    } catch { status.textContent = "This browser could not save your impact settings."; }
  }
  function render() {
    list.replaceChildren();
    const targets = readTargets();
    for (const kind of ["cloud", "packages"]) {
      for (const target of targets[kind]) {
        const item = node("li", targetLabel(target));
        const remove = node("button", "Remove", "text-button");
        remove.type = "button";
        remove.setAttribute("aria-label", `Remove ${targetLabel(target)}`);
        remove.addEventListener("click", () => {
          const current = readTargets();
          current[kind] = current[kind].filter(row => targetLabel(row) !== targetLabel(target));
          save(current, "Target removed.");
          root.querySelector(`[data-impact-kind="${kind}"] select`).focus();
        });
        item.append(" ", remove);
        list.append(item);
      }
    }
    if (!list.children.length) list.append(node("li", "No targets saved yet."));
  }
  for (const form of root.querySelectorAll("[data-impact-kind]")) {
    form.addEventListener("submit", event => {
      event.preventDefault();
      const kind = form.dataset.impactKind;
      const targets = readTargets();
      const target = Object.fromEntries([...form.elements].filter(el => el.name).map(el => [el.name, el.value.trim()]));
      if (targets[kind].some(row => targetLabel(row).toLowerCase() === targetLabel(target).toLowerCase())) {
        status.textContent = "This target is already saved.";
        return;
      }
      if (targets[kind].length >= 5) { status.textContent = "Remove a target before adding another of this type."; return; }
      targets[kind].push(target);
      save(targets, "Target saved in this browser.");
    });
  }
  render();
}

export function impactPanel(articleId) {
  const section = node("section", null, "impact-panel");
  const button = node("button", "Check personal impact", "button secondary");
  const ai = node("input");
  ai.type = "checkbox";
  const label = node("label");
  label.append(ai, " Explain matching cloud reports with AI");
  const settings = node("a", "Manage my targets");
  settings.href = "/research.html#impact-settings";
  const status = node("p", "", "small");
  const output = node("div");
  status.setAttribute("role", "status");
  button.type = "button";
  button.addEventListener("click", async () => {
    const targets = readTargets();
    output.replaceChildren();
    if (!targets.cloud.length && !targets.packages.length) {
      status.textContent = "Save a package version or a cloud service and region first.";
      return;
    }
    status.textContent = "Checking publisher evidence…";
    button.disabled = true;
    try {
      const data = await requestJSON("/api/intelligence/personal-impact", { method: "POST",
        signal: AbortSignal.timeout(25000), body: { ...targets, article_id: articleId, explain: ai.checked } });
      for (const item of [...data.cloud, ...data.packages]) {
        const row = node("article");
        row.append(node("h4", targetLabel(item.target)),
          node("p", `${item.status === "match" ? "Evidence match" : "Unknown"} · ${item.message}`));
        for (const evidence of item.evidence) {
          row.append(sourceLink({ ...evidence, title: `Read ${evidence.publisher} evidence ↗` }));
          if (evidence.excerpt) row.append(node("blockquote", evidence.excerpt));
        }
        output.append(row);
      }
      for (const claim of data.explanation?.claims || []) {
        const finding = node("p", claim.text);
        const entry = node("div");
        entry.append(finding);
        appendClaimEvidence(entry, claim, data.explanation_evidence, (url, title) => sourceLink({ url, title }));
        output.append(entry);
      }
      if (data.explanation?.limitations) output.append(node("p", data.explanation.limitations, "small"));
      status.textContent = "Impact check complete.";
    } catch (error) { status.textContent = error.message; }
    finally { button.disabled = false; }
  });
  section.append(node("h3", "Does this affect me?"), settings, label, button, status, output);
  return section;
}
