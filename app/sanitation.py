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
    r"apply for an? (?:[\w-]+ )?pass",
    r"get \d+% off",
    r"affiliate links?",
    r"follow (?:me|us)",
    r"subscribe to (?:my|our|the channel)",
    r"join (?:my|our|the) (?:discord|newsletter|community|patreon|slack)",
    r"support (?:me|us) on",
    r"connect with me",
    r"my socials",
    r"social links",
    r"(?:twitter|x|instagram|discord|spotify|tiktok|linkedin|patreon)\.com/[\w./-]+",
    r"(?:^|\s)(?:x|twitter|instagram|discord|spotify|linkedin|links)\s*:",
    r"media\s*/\s*sponsorship inquiries|join the frontier|join my newsletter",
    r"discord\.gg/[\w./-]+",
    r"bit\.ly/[\w./-]+",
    r"linktr\.ee/[\w./-]+",
    r"t\.me/[\w./-]+",
    r"patreon\.com/[\w./-]+",
    r"check out (?:my|our) (?:podcast|merch|course|channel)",
    r"sign up (?:at|for|here)",
    r"all rights reserved",
    r"leave a comment",
    r"continue reading (?:on medium|on dev community)",
    r"smash that like button",
    r"bell icon",
]

PROMO_RE = re.compile(r"(?:" + "|".join(PROMO_PATTERNS) + r")", re.I)
SENTENCES = re.compile(r"(?<=[.!?])\s+(?=[^\W_])|(?<=[。！？])\s*(?=\w)")
DIRECTIONAL = "👇👉🔗✅👆➡️⬇️🏼🏻🏽🏾🏿 \t"


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
        line = line.strip(DIRECTIONAL)
        if not line:
            continue
        for sentence in SENTENCES.split(line):
            if PROMO_RE.search(sentence):
                continue
            sentence = TIMESTAMP.sub("", sentence)
            sentence = HASHTAG.sub("", URL.sub("", sentence))
            sentence = re.sub(r"(?<!\w)@[\w.-]+", "", sentence)
            sentence = " ".join(sentence.split()).strip(DIRECTIONAL + "|•–—*[]():;\"'")
            if any(char.isalpha() for char in sentence):
                kept.append(sentence)

    cleaned = " ".join(kept)[:limit].strip()
    return cleaned


def sanitize_story_excerpt(raw_text: str, source: str, title: str = "", *, channel: str = "",
                           video_fallback: bool = True) -> str:
    excerpt = " ".join(SENTENCES.split(sanitize_text(raw_text))[:2])
    if not excerpt and video_fallback and source == "youtube" and title:
        excerpt = f"Video by {channel or 'a featured creator'} covering {sanitize_text(title, 180)}."
    if len(excerpt) > 220:
        head = excerpt[:219]
        boundary = head.rfind(" ")
        return (head[:boundary] if boundary > 189 else head).rstrip(" ,:;–—") + "…"
    return excerpt


def sanitize_article(article):
    result = dict(article)
    for key in ("title", "description", "summary", "cleanSummary", "whyItMatters", "keyTakeaway"):
        if key in result:
            result[key] = sanitize_text(result[key], 500 if key == "title" else 4000)
    return result
