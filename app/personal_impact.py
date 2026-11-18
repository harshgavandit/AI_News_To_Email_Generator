"""Evidence-bound, reader-initiated impact checks."""
import re
from typing import Literal

import httpx
from pydantic import BaseModel, ConfigDict, Field

from app import ai_insights, research, stack_intelligence
from app.discovery import search_text
from app.intelligence import references

CLOUD_STATUS = {"azure": "azure-status", "google-cloud": "google-cloud-status",
                "cloudflare": "cloudflare-status"}
NEGATIVE = re.compile(r"\b(?:not|no|unaffected|outside|might|may|possible|investigating whether)\b", re.I)
SCOPE = re.compile(r"\b(?:affected|affects?|impact(?:ed|s|ing)?|disruption|outage|degradation|unavailable)\b", re.I)


class CloudTarget(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    provider: Literal[tuple(CLOUD_STATUS)]
    service: str = Field(min_length=2, max_length=60, pattern=r"^[\p{L}\p{N}][\p{L}\p{N} ._+/-]*$")
    region: str = Field(min_length=2, max_length=60, pattern=r"^[\p{L}\p{N}][\p{L}\p{N} ._+/-]*$")


class ImpactRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    article_id: str = Field(pattern=r"^[a-zA-Z0-9_-]{1,40}$")
    packages: list[stack_intelligence.PackageCheck] = Field(default_factory=list, max_length=5)
    cloud: list[CloudTarget] = Field(default_factory=list, max_length=5)
    explain: bool = False


def phrase(value, text):
    normalized = search_text(value)
    return bool(normalized and f" {normalized} " in f" {search_text(text)} ")


def cloud_result(target, articles):
    status_feed = CLOUD_STATUS[target.provider]
    for row in articles:
        if row.get("source_id") != status_feed or row.get("coverage") != "status":
            continue
        evidence = research.evidence_record(row)
        text = f"{evidence['title']}\n{evidence['excerpt']}"
        for sentence in re.split(r"[\n.!?;]+\s*|\b(?:while|whereas|but)\b", text, flags=re.I):
            if (not NEGATIVE.search(sentence) and SCOPE.search(sentence)
                    and phrase(target.service, sentence) and phrase(target.region, sentence)):
                return {"status": "match", "message": "The provider names this service and region in the incident report.",
                        "evidence": [{**evidence, "excerpt": sentence.strip()[:650]}]}
    return {"status": "unknown", "message": "An official status report did not establish impact for this service and region.",
            "evidence": []}


def package_result(store, package, advisory_ids):
    if not advisory_ids:
        return {"status": "unknown", "message": "The story does not name an advisory that can be compared with this version.",
                "evidence": []}
    try:
        result = stack_intelligence.advisories(store, package)
    except (httpx.HTTPError, ValueError):
        return {"status": "unknown", "message": "The advisory registry could not be checked.", "evidence": []}
    matched = [{key: row[key] for key in ("id", "title", "publisher", "url", "published_at")}
               for row in result["evidence"]
               if advisory_ids.intersection(value.upper() for value in [row["id"], *row.get("aliases", [])])]
    if matched:
        # Version impact comes from the exact registry match, independent of any generated explanation.
        return {"status": "match", "message": "The advisory registry lists this exact package version for an advisory in the story.",
                "evidence": matched}
    return {"status": "unknown", "message": "The registry did not establish a match with the advisories in this story.",
            "evidence": []}


def check(store, body, articles):
    ids = set().union(*(references({"title": article["title"], "description": article.get("cleanSummary", "")})
                        for article in articles))
    packages = []
    # A capped number of exact-version queries keeps an incomplete registry from delaying the reader.
    from concurrent.futures import ThreadPoolExecutor
    if body.packages:
        with ThreadPoolExecutor(max_workers=3) as pool:
            results = pool.map(lambda package: package_result(store, package, ids), body.packages)
            packages = [{"target": package.model_dump(), **item} for package, item in zip(body.packages, results, strict=True)]
    cloud = [{"target": target.model_dump(), **cloud_result(target, articles)} for target in body.cloud]
    matched_status = [row for item in cloud for row in item["evidence"]]
    answer = (ai_insights.explain(store, matched_status, prompt=ai_insights.PROMPT +
              "\nExplain only the provider-reported status and named scope. Do not infer a reader's own outage or recommend actions.")
              if body.explain and matched_status else None)
    return {"cloud": cloud, "packages": packages, "explanation": answer, "explanation_evidence": matched_status}
