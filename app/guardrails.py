"""Source-only checks for public questions and answers."""

import re
import unicodedata
from typing import Literal

MAX_QUESTION = 320
REFUSAL = "I can answer questions about technology news in Informa's archive."
INSUFFICIENT = "Not enough coverage to answer this."
INJECTION = re.compile(
    r"\b(?:ignore|disregard|override|forget|bypass)\b.{0,48}\b(?:instructions?|rules?|guardrails?|system|policy)\b"
    r"|\b(?:system|developer|hidden|initial)\s+(?:prompt|message|instructions?)\b"
    r"|\b(?:reveal|print|repeat|show|disclose)\b.{0,24}\b(?:your|the)\s+(?:prompt|instructions?)\b"
    r"|\b(?:act as|pretend you(?: are|'re)|role[- ]?play|you are now|jailbreak)\b"
    r"|<\s*/?\s*(?:system|assistant|developer|user)\b|\[/?(?:INST|SYSTEM|ASSISTANT|DEVELOPER)\]",
    re.I,
)
OFF_TOPIC = re.compile(
    r"\b(?:do|solve|complete|write|help with)\b.{0,28}\b(?:my\s+)?(?:homework|assignment|essay)\b"
    r"|\b(?:write|give me|generate|debug|fix)\b.{0,40}\b(?:code|script|function|program)\b"
    r"|\b(?:medical|legal|financial|investment)\s+advice\b"
    r"|\b(?:what(?:'s| is) the weather|write (?:a |me a )?(?:poem|song)|solve (?:this |my )?math)\b"
    r"|\b(?:diagnose me|should i (?:buy|sell|invest|sue|take)|what (?:medicine|dose) should i)\b",
    re.I,
)
PERSONAL = re.compile(
    r"[\w.+%-]+@[\w.-]+\.[A-Za-z]{2,}|(?<!\w)(?:\+?\d[ ().-]*){10,15}(?!\w)"
    r"|\b(?:sk-(?:proj-)?[A-Za-z0-9_-]{15,}|(?:postgres(?:ql)?|mysql)://\S+)"
    r"|\b(?:my (?:name|address|phone number|email|password) is)\b",
    re.I,
)
URLS = re.compile(
    r"(?:\b(?:[a-z][a-z0-9+.-]*://|www\.|mailto:|javascript:)|(?<![\w:])//)[^\s<>\"“”]+",
    re.I,
)
MARKER = re.compile(r"\[([1-9]\d{0,2})\]")
GARBAGE = re.compile(r"(?:asdf|qwerty|lorem ipsum|test(?:ing)?)[\s.!?]*", re.I)
QUOTES = re.compile(
    r'"([^"\n]+)"|“([^”\n]+)”|(?<!\w)‘([^’\n]+)’|(?<!\w)\'([^\'\n]+)\'(?!\w)'
)


def rejection(question: str) -> str | None:
    normalized = unicodedata.normalize("NFKC", question)
    normalized = " ".join(
        "".join(c for c in normalized if unicodedata.category(c) != "Cf").split()
    )
    letters = [c.casefold() for c in normalized if c.isalpha()]
    if (
        len(normalized) > MAX_QUESTION
        or len(letters) < 3
        or len(set(letters)) < 3
        or GARBAGE.fullmatch(normalized)
    ):
        return "Enter a technology news question between 3 and 320 characters."
    if PERSONAL.search(normalized):
        return "Remove personal or account information before asking a question."
    if INJECTION.search(normalized) or OFF_TOPIC.search(normalized):
        return REFUSAL
    return None


def outcome(
    status: Literal["answered", "refused", "insufficient"],
    answer: str = "",
    citations: list[dict] | None = None,
    *,
    sourced: bool = False,
    quotes_verified: bool = False,
    links_clean: bool = True,
) -> dict:
    return {
        "status": status,
        "answer": answer or (REFUSAL if status == "refused" else INSUFFICIENT),
        "citations": citations or [],
        "checks": {
            "sourced": sourced,
            "quotes_verified": quotes_verified,
            "links_clean": links_clean,
        },
    }


def _citations_for(line: str, records: dict[int, dict]) -> tuple[str, list[int]]:
    text = MARKER.sub("", line).strip()
    numbers = [int(number) for number in MARKER.findall(line)]
    suffix = " ".join(f"[{number}]" for number in numbers)
    if (
        not numbers
        or any(number not in records for number in numbers)
        or line != f"{text} {suffix}"
    ):
        return text, []
    return text, numbers


def _source_span(text: str, source: str) -> bool:
    # A sentence can be the entire excerpt or an intact sentence within it. Requiring an
    # intact span prevents a model from turning part of a sentence into a different claim.
    text, source = " ".join(text.split()), " ".join(source.split())
    if len(text) < 12 or re.search(r"[.!?][\"”]?\s+[A-Z0-9“\"]", text):
        return False
    return text == source or bool(
        re.search(r"(?:^|[.!?] )" + re.escape(text) + r"(?=$| [A-Z0-9“\"])", source)
        and text.endswith((".", "!", "?", '."', "!”", "?”", ".”"))
    )


def check_answer(answer: str, evidence: list[dict]) -> dict:
    """Allow only complete source excerpts/sentences with explicit numbered sources."""
    records = dict(enumerate(evidence, 1))
    urls = {row["url"] for row in evidence}
    used: set[int] = set()
    sourced = quotes_verified = links_clean = True
    lines = answer.strip().splitlines()
    if not 1 <= len(lines) <= 6:
        return outcome("insufficient")
    for line in lines:
        text, numbers = _citations_for(line.strip(), records)
        sources = [records[n]["excerpt"] for n in numbers]
        actual_urls = [match.rstrip(".,;:!?)") for match in URLS.findall(text)]
        links_clean &= all(url in urls for url in actual_urls)
        quotes_verified &= all(
            any(next(part for part in groups if part) in source for source in sources)
            for groups in QUOTES.findall(text)
        )
        quoted = (
            text[1:-1]
            if text.startswith(('"', "“")) and text.endswith(('"', "”"))
            else text
        )
        sourced &= bool(sources) and all(
            _source_span(quoted, source) for source in sources
        )
        sourced &= not bool(re.search(r"[<>]", text) or PERSONAL.search(text))
        sourced &= not bool(INJECTION.search(text))
        used.update(numbers)
    if not (sourced and quotes_verified and links_clean):
        # Discard the complete answer, including any foreign URL.
        return outcome(
            "insufficient",
            sourced=sourced,
            quotes_verified=quotes_verified,
            links_clean=links_clean,
        )
    citations = [
        {
            "n": n,
            **{
                key: records[n][key]
                for key in ("id", "title", "publisher", "url", "published_at")
            },
        }
        for n in sorted(used)
    ]
    return outcome("answered", answer, citations, sourced=True, quotes_verified=True)


_TYPOGRAPHY = str.maketrans(
    {
        "“": '"',
        "”": '"',
        "„": '"',
        "‘": "'",
        "’": "'",
        "–": "-",
        "—": "-",
        "\u00a0": " ",
    }
)
_SENTENCE_END = re.compile(r"(?<=[.!?])[\"”’']?\s+")


def _loose(text: str) -> str:
    text = unicodedata.normalize("NFKC", text).translate(_TYPOGRAPHY)
    text = " ".join(text.split()).rstrip(" .!?…").rstrip(".")
    return text.casefold()


def snap_sentence(text: str, source: str) -> str | None:
    """Return the exact source sentence that ``text`` reproduces up to typography.

    Models often change curly quotes, dashes, spacing or the final full stop when copying a
    sentence. Matching after normalising only those differences, and then using the source's
    own wording, keeps answers verbatim without rejecting faithful copies.
    """
    wanted = _loose(text)
    if len(wanted) < 12:
        return None
    for sentence in _SENTENCE_END.split(" ".join(source.split())):
        sentence = sentence.strip()
        if sentence and _loose(sentence) == wanted:
            return sentence
    return None


def _snap_claim(claim: dict, evidence: list[dict], numbers: dict) -> dict:
    ids, quotes = list(claim["source_ids"]), list(claim["quotes"])
    text = claim["text"]
    for index, (ident, quote) in enumerate(zip(ids, quotes)):
        if ident not in numbers:
            continue
        excerpt = evidence[numbers[ident] - 1]["excerpt"]
        if quote in excerpt and _source_span(quote.strip(), excerpt):
            continue
        snapped = snap_sentence(quote, excerpt)
        if snapped:
            if _loose(text) == _loose(quote):
                text = snapped
            quotes[index] = snapped
    return {**claim, "text": text, "quotes": quotes}


def check_claims(claims: list[dict], evidence: list[dict]) -> dict:
    numbers = {row["id"]: number for number, row in enumerate(evidence, 1)}
    lines = []
    for claim in claims:
        claim = _snap_claim(claim, evidence, numbers)
        ids, quotes = claim["source_ids"], claim["quotes"]
        if (
            not ids
            or len(ids) != len(quotes)
            or any(ident not in numbers for ident in ids)
            or "\n" in claim["text"]
        ):
            return outcome("insufficient")
        if any(
            quote not in evidence[numbers[ident] - 1]["excerpt"]
            for ident, quote in zip(ids, quotes, strict=True)
        ):
            return outcome("insufficient")
        markers = " ".join(f"[{numbers[ident]}]" for ident in ids)
        lines.append(f"{claim['text'].strip()} {markers}")
    return check_answer("\n".join(lines), evidence)
