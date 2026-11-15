"""Select relevant articles before the expensive model stage."""
import re
from collections import Counter

from app.discovery import search_terms, search_text

STOP = frozenset("a an and about with in on the for to of or my i ai latest want how is are what more using use".split())


def words(text):
    return set(re.findall(r"[\w][\w+-]{1,}", text.casefold())) - STOP


def select_candidates(articles, focus, count, sources):
    topics = [term for term in search_terms(focus) if term not in STOP]
    allowed = set(sources)
    rows = []
    for article in articles:
        if article["source"] not in allowed and article.get("source_id") not in allowed:
            continue
        title = words(article["title"])
        normalized_title = search_text(article["title"])
        excerpt = search_text(article["description"])
        score = sum(3 * (term in normalized_title) + (term in excerpt) for term in topics)
        rows.append((score, article["published_at"], article["id"], title, article))
    rows.sort(key=lambda row: row[:3], reverse=True)
    picked, deferred, seen_titles = [], [], []
    publishers = Counter()
    for _, _, _, tokens, article in rows:
        if tokens and any(tokens == old or (len(tokens & old) >= 4 and len(tokens & old) / len(tokens | old) >= .8) for old in seen_titles):
            continue
        seen_titles.append(tokens)
        publisher = article["publisher"]
        if publishers[publisher] >= max(1, (count + 1) // 2):
            deferred.append(article)
        else:
            picked.append(article)
            publishers[publisher] += 1
        if len(picked) == count:
            break
    return (picked + deferred)[:count]
