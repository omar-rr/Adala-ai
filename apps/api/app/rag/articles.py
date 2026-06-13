from __future__ import annotations

from dataclasses import dataclass
import re
import unicodedata


ARABIC_DIGITS = str.maketrans("٠١٢٣٤٥٦٧٨٩", "0123456789")
ARTICLE_NUMBER = r"(?P<number>[0-9٠-٩]+[A-Za-z]?)"
ARTICLE_LABEL = r"(?:Article|Art\.?|Section|Clause|Rule|المادة|الماده|مادة|ماده)"
ARTICLE_MARKER_RE = re.compile(
    rf"(?P<label>{ARTICLE_LABEL})\s*(?:No\.?|Number|رقم)?\s*(?:ال\s*)?[\(\)\[\]{{}}\-:]*\s*"
    rf"{ARTICLE_NUMBER}\s*[\(\)\[\]{{}}]*",
    re.IGNORECASE,
)
ARTICLE_PATTERNS = [
    ARTICLE_MARKER_RE,
    re.compile(rf"(?:الماده|المادة)\s*ال\s*{ARTICLE_NUMBER}", re.IGNORECASE),
    re.compile(
        rf"(?:القانون|قانون)\s*(?:رقم)?\s*(?:ال\s*)?[\(\)\[\]{{}}\-:]*\s*{ARTICLE_NUMBER}",
        re.IGNORECASE,
    ),
]


@dataclass(frozen=True)
class ArticleMarker:
    number: str
    start: int
    end: int


def normalize_digits(value: str) -> str:
    return value.translate(ARABIC_DIGITS)


def normalize_article_number(value: str) -> str:
    value = unicodedata.normalize("NFKC", value).strip()
    value = normalize_digits(value)
    value = re.sub(r"[^0-9A-Za-z]", "", value)
    return value.upper()


def extract_article_number(text: str) -> str | None:
    normalized = unicodedata.normalize("NFKC", text)
    for pattern in ARTICLE_PATTERNS:
        match = pattern.search(normalized)
        if match:
            return normalize_article_number(match.group("number"))
    return None


def _is_heading_range_reference(text: str, start: int, end: int) -> bool:
    before = text[max(0, start - 12) : start]
    after = text[end : end + 18]
    return bool(
        re.search(r"(?:من|الى|إلى|الي|to)\s*$", before, re.IGNORECASE)
        or re.match(r"\s*(?:الى|إلى|الي|to)\b", after, re.IGNORECASE)
    )


def find_article_markers(text: str) -> list[ArticleMarker]:
    normalized = unicodedata.normalize("NFKC", text)
    markers: list[ArticleMarker] = []
    seen_starts: set[int] = set()
    for match in ARTICLE_MARKER_RE.finditer(normalized):
        if match.start() in seen_starts:
            continue
        if _is_heading_range_reference(normalized, match.start(), match.end()):
            continue
        number = normalize_article_number(match.group("number"))
        if not number:
            continue
        markers.append(ArticleMarker(number=number, start=match.start(), end=match.end()))
        seen_starts.add(match.start())
    return markers


def split_article_sections(text: str) -> list[tuple[str | None, str]]:
    normalized = unicodedata.normalize("NFKC", text)
    markers = find_article_markers(normalized)
    if not markers:
        return [(None, normalized)]

    sections: list[tuple[str | None, str]] = []
    preamble = normalized[: markers[0].start].strip()
    if preamble:
        sections.append((None, preamble))

    for index, marker in enumerate(markers):
        next_start = markers[index + 1].start if index + 1 < len(markers) else len(normalized)
        section = normalized[marker.start : next_start].strip()
        if section:
            sections.append((marker.number, section))
    return sections
