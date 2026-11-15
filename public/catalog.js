const topicLabels = {
  ai: "AI & Machine Learning",
  startups: "Startups & Venture",
  security: "Cybersecurity & Privacy",
  software: "Software & Cloud",
  chips: "Chips & Hardware",
  bigtech: "Tech Companies",
  research: "Research & Science",
  industry: "Industry & Policy",
  outages: "Service Outages",
  video: "Video",
};

const regionLabels = {
  Global: "Global publishers",
  APAC: "Asia-Pacific",
  EU: "Europe",
  Africa: "Africa",
  MENA: "Middle East & North Africa",
  LatAm: "Latin America",
  NA: "North America",
};

export const languageOptions = {
  en: "English",
  fr: "French",
  de: "German",
  ja: "Japanese",
  "pt-BR": "Portuguese (Brazil)",
  "es-MX": "Spanish (Mexico)",
};

export const coverageLabels = {
  reporting: "Independent reporting",
  publisher: "Publisher update",
  discussion: "Community discussion",
  advisory: "Security advisory",
  preprint: "Research preprint",
  status: "Official status",
};

export function topicOptions(topics) {
  if (!topics) return topicLabels;
  // Keep the same editorial order even when the API changes its object order.
  return Object.fromEntries(
    Object.keys({ ...topicLabels, ...topics }).filter((id) => Object.hasOwn(topics, id))
      .map((id) => [id, topics[id]]),
  );
}

export function regionOptions(regions) {
  return regions ? { ...regions, ...(regions.Global ? { Global: regionLabels.Global } : {}) } : regionLabels;
}

export function regionId(record) {
  return record.region_id || ({
    Asia: "APAC",
    India: "APAC",
    Europe: "EU",
    "Latin America": "LatAm",
    "North America": "NA",
    "Middle East": "MENA",
    "Middle East & North Africa": "MENA",
  })[record.region] || record.region;
}

const languageNames = new Intl.DisplayNames(undefined, { type: "language" });

export function originalLanguage(language) {
  if (typeof language !== "string" || /^en(?:-|$)/i.test(language)) return "";
  try {
    return languageNames.of(language);
  } catch {
    return "";
  }
}

export function optionLabel(label, count) {
  return Number.isInteger(count) ? `${label} (${count.toLocaleString()})` : label;
}

export function fillOptions(select, options, allLabel, counts, selected = select.value) {
  const entries = [["", allLabel], ...Object.entries(options)];
  for (const [index, [id, label]] of entries.entries()) {
    let option = select.options[index];
    if (!option) {
      option = document.createElement("option");
      select.add(option);
    }
    option.value = id;
    option.textContent = optionLabel(label, counts?.[id || "all"]);
  }
  select.options.length = entries.length;
  select.value = Object.hasOwn(options, selected) ? selected : "";
}
