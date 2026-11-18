"""Exact package checks and conservative matching against official archive entries."""
import hashlib
import json
import re
import time
from typing import Literal

import httpx
from pydantic import BaseModel, ConfigDict, Field

from app.discovery import search_terms
from app.sanitation import sanitize_text


class PackageCheck(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    ecosystem: Literal["npm", "PyPI", "Go", "crates.io", "Maven", "NuGet", "RubyGems"]
    name: str = Field(min_length=1, max_length=160, pattern=r"^[A-Za-z0-9@_][A-Za-z0-9@._/+\-:]*$")
    version: str = Field(min_length=1, max_length=80, pattern=r"^[vV]?\d[A-Za-z0-9._+\-]*$")


def mentions(label, rows):
    service, _, region = label.partition("|")
    target = set(search_terms(service))
    scope = set(search_terms(region))
    if not target:
        return []
    result = []
    for row in rows:
        if row.get("coverage") not in {"status", "release", "advisory"}:
            continue
        text = set(search_terms(" ".join((row["title"], row.get("publisher", ""), row.get("cleanSummary", "")))))
        if target <= text and scope <= text:
            result.append(row)
    return result


def advisories(store, package):
    payload = {"package": {"ecosystem": package.ecosystem, "name": package.name}, "version": package.version}
    cache_key = hashlib.sha256(("osv-v2:" + json.dumps(payload, sort_keys=True)).encode()).hexdigest()
    now = time.time()
    cached = store.get_summary(cache_key)
    if cached and cached["checked_at"] >= now - 900:
        return cached
    response = httpx.post("https://api.osv.dev/v1/query", json=payload, timeout=6)
    response.raise_for_status()
    data = response.json()
    if not isinstance(data, dict):
        raise ValueError("Invalid OSV response")
    records = data.get("vulns", [])
    if not isinstance(records, list):
        raise ValueError("Invalid OSV response")
    evidence = []
    for record in records[:20]:
        ident = record.get("id") if isinstance(record, dict) else None
        if not isinstance(ident, str) or record.get("withdrawn") or not re.fullmatch(r"[A-Za-z0-9._-]{1,100}", ident):
            continue
        aliases = record.get("aliases")
        evidence.append({"id": ident, "title": sanitize_text(record.get("summary") or "", 300) or ident,
                         "excerpt": sanitize_text(record.get("details") or "", 650),
                         "publisher": "OSV", "url": f"https://osv.dev/vulnerability/{ident}",
                         "published_at": record.get("published") or "",
                         "aliases": [alias for alias in (aliases if isinstance(aliases, list) else [])[:20]
                                     if isinstance(alias, str) and re.fullmatch(r"[A-Za-z0-9._-]{1,100}", alias)]})
    result = {"evidence": evidence, "partial": bool(data.get("next_page_token")) or len(records) > 20, "checked_at": now}
    store.save_summary(cache_key, result, replace=True)
    return result
