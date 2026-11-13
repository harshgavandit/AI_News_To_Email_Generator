"""Bounded cleanup of untrusted feed excerpts, including legacy stored rows."""
import re
from bs4 import BeautifulSoup

URL = re.compile(r"(?:https?://|www\.)[^\s<>\"'()]+", re.I)
HASHTAG = re.compile(r"(?<!\w)#[\w-]+")
TIMESTAMP = re.compile(r"(?:^|\s)\d{1,2}:\d{2}(?::\d{2})?\s*(?:-\s*)?", re.M)

# Matches promotional segments, sponsor mentions, social link trees, and channel calls-to-action
PROMO_PATTERNS = [
    r"thanks to .+ for sponsoring",
    r"sponsored by",
    r"sponsor(?:ed)?\s*:",
    r"this (?:video|episode|post|newsletter) is sponsored",
    r"use (?:my |the )?(?:code|coupon|link)",
    r"apply for a pass",
    r"get \d+% off",
    r"affiliate links?",
    r"follow (?:me|us)",
    r"subscribe to (?:my|our|the channel)",
    r"join (?:my|our|the) (?:discord|newsletter|community|patreon|slack)",
    r"support (?:me|us) on",
    r"connect with me",
    r"my socials",
    r"social links",
    r"(?:twitter|x\.com|instagram|discord|spotify|tiktok|linkedin|github|patreon)\.com/[\w./-]+",
    r"discord\.gg/[\w./-]+",
    r"bit\.ly/[\w./-]+",
    r"linktr\.ee/[\w./-]+",
    r"t\.me/[\w./-]+",
    r"patreon\.com/[\w./-]+",
    r"check out (?:my|our) (?:podcast|merch|course|channel)",
    r"sign up (?:at|for|here)",
    r"all rights reserved",
    r"leave a comment",
    r"smash that like button",
    r"bell icon",
]

PROMO_RE = re.compile(r"(?:" + "|".join(PROMO_PATTERNS) + r")", re.I)


def sanitize_text(value, limit=4000):
    """Keep editorial sentences; drop promotional lines, social links, sponsor pitches, and embedded URLs."""
    text = str(value or "")[:32000]
    if "<" in text or "&" in text:
        soup = BeautifulSoup(text, "html.parser")
        for tag in soup(["script", "style", "iframe", "noscript", "svg"]):
            tag.decompose()
        for tag in soup.find_all(["br", "p", "div", "li", "h1", "h2", "h3", "h4", "h5", "h6"]):
            tag.insert_before("\n")
        text = soup.get_text(" ")

    kept = []
    # Split text into lines or sentences
    for line in re.split(r"[\r\n]+", text):
        line = line.strip()
        if not line:
            continue
        if PROMO_RE.search(line):
            continue
        # Remove timestamps, hashtags, URLs, and handles
        line = TIMESTAMP.sub("", line)
        line = HASHTAG.sub("", line)
        line = URL.sub("", line)
        line = re.sub(r"(?<!\w)@[\w.-]+", "", line)
        line = " ".join(line.split()).strip(" |•–—*[]():;\"'")
        if line and re.search(r"\w", line):
            # Check sentence level within line
            sentences = re.split(r"(?<=[.!?])\s+(?=[A-Z0-9])", line)
            for sentence in sentences:
                sentence = sentence.strip(" |•–—*[]():;\"'")
                if not sentence or PROMO_RE.search(sentence):
                    continue
                if len(sentence) > 3 and re.search(r"[a-zA-Z]", sentence):
                    kept.append(sentence)

    cleaned = " ".join(kept)[:limit].strip()
    return cleaned


def sanitize_article(article):
    result = dict(article)
    for key in ("title", "description", "summary", "cleanSummary", "whyItMatters", "keyTakeaway"):
        if key in result:
            result[key] = sanitize_text(result[key], 500 if key == "title" else 4000)
    return result
