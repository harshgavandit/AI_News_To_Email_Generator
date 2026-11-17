"""Extract short, attributed highlights from text already available in the reader."""
import re

from bs4 import BeautifulSoup

from app.discovery import search_terms, search_text
from app.sanitation import SENTENCES


def article_summary(article, reading):
    excerpt = article["cleanSummary"]
    result = {"text": excerpt, "basis": article["summary_basis"], "limited_source": True, "highlights": []}
    if reading:
        soup = BeautifulSoup(reading["html"], "html.parser")
        blocks = [block.get_text(" ", strip=True) for block in soup.select("p, li") if not block.find(["p", "li"])]
        highlights = select_highlights(article["title"], blocks)
        if highlights:
            return {"text": " ".join(highlights), "basis": "licensed_article_extract",
                    "limited_source": False, "highlights": highlights}
    if article["summary_basis"] == "publisher_excerpt" and article["has_excerpt"]:
        highlights = select_highlights(article["title"], [excerpt], limit=1, budget=220)
        if highlights and search_text(highlights[0]) != search_text(excerpt):
            result["highlights"] = highlights
    return result


def select_highlights(title, blocks, *, limit=3, budget=400):
    title_key = search_text(title)
    title_terms = {term for term in search_terms(title) if len(term) > 2}
    unique = {title_key}
    sentences = []
    for block in blocks:
        for sentence in SENTENCES.split(" ".join(block.split())):
            key = search_text(sentence)
            if not 24 <= len(sentence) <= min(budget, 245) or key in unique or not any(c.isalpha() for c in sentence):
                continue
            unique.add(key)
            # Lead sentences and title terms identify the subject without introducing new claims.
            terms = set(re.findall(r"\S+", key))
            score = min(4, len(title_terms & terms)) + 2 / (1 + len(sentences) / 4)
            sentences.append((score, sentence))

    selected = []
    for index, (_, sentence) in sorted(enumerate(sentences), key=lambda pair: (-pair[1][0], pair[0])):
        if len(sentence) + bool(selected) <= budget:
            selected.append((index, sentence))
            budget -= len(sentence) + (len(selected) > 1)
            if len(selected) == limit:
                break
    return [sentence for _, sentence in sorted(selected)]
