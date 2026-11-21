"""Identify the language of the text readers see using a local detector."""
from functools import lru_cache
import re
from threading import Lock
import unicodedata

from langdetect import DetectorFactory, LangDetectException
from langdetect.detector_factory import PROFILES_DIRECTORY


_factory = DetectorFactory()
_factory.set_seed(0)
_profiles_lock = Lock()
_url = re.compile(r"https?://\S+", re.IGNORECASE)
_language_code = re.compile(r"[a-z]{2}(?:-[A-Z]{2})?")
_kana = re.compile(r"[\u3041-\u3096\u30a1-\u30fa]")
_japanese_text = re.compile(r"[\u3041-\u3096\u30a1-\u30fa\u3400-\u9fff]")
_hangul = re.compile(r"[\uac00-\ud7a3]")


@lru_cache(maxsize=4096)
def _detect(text):
    text = " ".join(_url.sub(" ", unicodedata.normalize("NFKC", text)).split())
    letters = [char for char in text if char.isalpha()]
    # Short headlines dominated by kana or Hangul provide strong script evidence.
    if _kana.search(text) and len(_japanese_text.findall(text)) >= max(4, len(letters) * 0.6):
        return "ja"
    if len(_hangul.findall(text)) >= max(4, len(letters) * 0.6):
        return "ko"
    if len(letters) < 18 and sum(not char.isascii() for char in letters) < 8:
        return "und"
    with _profiles_lock:
        if not _factory.langlist:
            _factory.load_profile(PROFILES_DIRECTORY)
    detector = _factory.create()
    detector.n_trial = 3
    detector.append(text)
    try:
        prediction = detector.get_probabilities()[0]
    except (LangDetectException, IndexError):
        return "und"
    if prediction.prob < 0.87:
        return "und"
    return {"zh-cn": "zh-CN", "zh-tw": "zh-TW"}.get(prediction.lang, prediction.lang)


def article_language(article):
    """Inspect the headline and bounded publisher excerpt, independent of region."""
    stored = article.get("detected_language")
    if isinstance(stored, str) and (stored == "und" or _language_code.fullmatch(stored)):
        return stored
    title = str(article.get("title") or "")[:500]
    excerpt = str(article.get("description") or article.get("cleanSummary") or "")[:600]
    # Detect the title first so an English boilerplate excerpt cannot relabel a foreign headline.
    language = _detect(title)
    return language if language != "und" else _detect(f"{title} {excerpt}"[:800])


def excerpt_language(excerpt):
    return _detect(str(excerpt or "")[:600])


def is_english_article(article):
    return article_language(article) == "en" and excerpt_language(article.get("description")) in ("en", "und")


def is_not_foreign_article(article):
    """True unless the headline or excerpt is confidently in a language other than English.

    Used to keep English-only feeds English without discarding short headlines that the
    detector cannot classify ("und"), such as product names or version announcements.
    """
    return (article_language(article) in ("en", "und")
            and excerpt_language(article.get("description")) in ("en", "und"))
