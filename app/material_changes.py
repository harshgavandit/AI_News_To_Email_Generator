"""Classify supported changes conservatively from retained publisher text."""
import re

from app.discovery import search_text
from app.sources import BY_ID

LABELS = {
    "confirmed": "Officially confirmed",
    "expanded": "Scope expanded",
    "resolved": "Resolved",
    "correction": "Correction",
    "mitigated": "Mitigation reported",
    "released": "Release reported",
    "completed": "Completion reported",
    "material_update": "New information",
    "source_revision": "Publisher revised this item",
    "first_report": "First report",
    "additional_reporting": "Additional reporting",
}
PATTERNS = {
    "correction": r"\b(?:correction\s*:|we (?:corrected|retract)\b|retracted (?:its|the) (?:report|claim)\b|earlier version incorrectly\b)",
    "resolved": r"\b(?:has been restored|(?:fully |now )restored|(?:incident|outage) (?:is |was |has been )resolved|all systems operational|services? (?:are|is) back online)\b",
    "mitigated": r"\b(?:mitigation (?:deployed|applied)|(?:incident|impact) (?:is |was |has been )mitigated|recovery (?:has begun|is underway))\b",
    "expanded": r"\b(?:now affects?|also affects?|spread to|expanded (?:to|beyond)|additional (?:regions|services|customers) (?:are |were )?affected)\b",
    "confirmed": r"\b(?:confirmed|acknowledged|officially announced)\b",
    "released": r"\b(?:now available|has (?:released|shipped)|rollout (?:has begun|is underway))\b",
    "completed": r"\b(?:closed the acquisition|completed the (?:sale|acquisition|merger)|deal (?:has closed|is complete))\b",
}
UNCERTAIN = re.compile(r"\b(?:not|never|no|may|could|might|if|expects?|unconfirmed|rumou?rs?)\b", re.I)
QUANTITIES = re.compile(r"\b\d+(?:[.,]\d+)*\s*(?:%|million|billion|hours?|regions?|users?|devices?)\b", re.I)
SENTENCE = re.compile(r"(?<=[.!?])\s+(?=[A-Z])|[\r\n]+")


def evidence_text(row):
    return f"{row['title']}\n{row.get('description') or row.get('excerpt') or ''}"


def signals(row):
    text = evidence_text(row)
    source = BY_ID.get(row.get("source_id"))
    primary = bool(source and source.coverage in {"status", "advisory", "release"})
    result = {}
    for sentence in SENTENCE.split(text):
        for kind, pattern in PATTERNS.items():
            if (kind == "confirmed" and not primary) or kind in result or UNCERTAIN.search(sentence):
                continue
            if re.search(pattern, sentence, re.I) and "?" not in sentence:
                result[kind] = sentence.strip()[:320]
    if quantities := QUANTITIES.findall(text):
        result["material_update"] = set(map(search_text, quantities))
    return result


def change_kind(row, earlier, *, same_article=False):
    current = signals(row)
    prior = [signals(entry) for entry in earlier]
    for kind in PATTERNS:
        if kind not in current:
            continue
        if any(kind in entry for entry in prior):
            continue
        return kind
    earlier_quantities = set().union(*(entry.get("material_update", set()) for entry in prior))
    if earlier_quantities and current.get("material_update", set()) - earlier_quantities:
        return "material_update"
    return "source_revision" if same_article else "additional_reporting"
