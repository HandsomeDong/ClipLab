from __future__ import annotations

import re
from pathlib import Path

_URL_PATTERN = re.compile(r"https?://[^\s<>\"{}|\\^`\[\]]+", re.IGNORECASE)
_INVALID_FILENAME_CHARS = re.compile(r"[\n\r\t:\/\\\*\?\"<>\|\xa0]+")
_EXTRA_SPACES = re.compile(r"\s+")
_CHINESE_CHAR_PATTERN = re.compile(r"[\u4e00-\u9fff]")


def extract_urls(text: str) -> list[str]:
    return [normalize_extracted_url(url) for url in _URL_PATTERN.findall(text or "")]


def normalize_extracted_url(url: str) -> str:
    return url.rstrip("，。；！？、【】《》）】』」'\".,;!?)]}>")


def sanitize_title(title: str) -> str:
    cleaned = _INVALID_FILENAME_CHARS.sub(" ", title or "")
    cleaned = _EXTRA_SPACES.sub(" ", cleaned).strip()
    if not cleaned:
        return ""

    total_chinese = len(_CHINESE_CHAR_PATTERN.findall(cleaned))
    if total_chinese <= 10:
        return cleaned.strip(" .-_#")

    chinese_count = 0
    result: list[str] = []
    for char in cleaned:
        if _CHINESE_CHAR_PATTERN.match(char):
            chinese_count += 1
        result.append(char)
        if chinese_count >= 10:
            break
    return "".join(result).strip(" .-_#")


def build_output_path(output_dir: str, title: str, fallback_stem: str) -> Path:
    stem = sanitize_title(title) or fallback_stem
    base = Path(output_dir)
    base.mkdir(parents=True, exist_ok=True)
    output = base / f"{stem}.mp4"
    if not output.exists():
        return output

    index = 2
    while True:
        candidate = base / f"{stem} ({index}).mp4"
        if not candidate.exists():
            return candidate
        index += 1
