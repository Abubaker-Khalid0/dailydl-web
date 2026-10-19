"""Validated public inputs and portable filenames."""

import re
import unicodedata
from urllib.parse import parse_qs, urlsplit

ID = re.compile(r"[A-Za-z0-9]{5,12}\Z")
LANGUAGE = re.compile(r"[A-Za-z0-9_-]{1,32}\Z")
HOSTS = {
    "dailymotion.com",
    "www.dailymotion.com",
    "m.dailymotion.com",
    "geo.dailymotion.com",
}


def canonical_url(value: str) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > 2048:
        raise ValueError("Enter a Dailymotion video URL or video ID.")
    value = value.strip()
    if ID.fullmatch(value):
        video_id = value
    else:
        parsed = urlsplit(value)
        if parsed.scheme not in {"http", "https"} or parsed.username or parsed.password:
            raise ValueError("Only public Dailymotion video URLs are supported.")
        if parsed.port not in {None, 80, 443}:
            raise ValueError("Custom URL ports are not supported.")
        host = (parsed.hostname or "").lower()
        path = parsed.path.rstrip("/")
        if host in {"dai.ly", "www.dai.ly"}:
            match = re.fullmatch(r"/([A-Za-z0-9]{5,12})", path)
            video_id = match[1] if match else ""
        elif host in HOSTS:
            match = re.fullmatch(
                r"/(?:embed/)?video/([A-Za-z0-9]{5,12})(?:_[^/]*)?", path
            )
            video_id = match[1] if match else ""
            if not video_id and re.fullmatch(r"/player(?:/[^/]+)?(?:\.html)?", path):
                video_id = parse_qs(parsed.query).get("video", [""])[0]
        else:
            raise ValueError("The URL must belong to dailymotion.com or dai.ly.")
        if not ID.fullmatch(video_id):
            raise ValueError("The URL does not contain a valid video ID.")
    return f"https://www.dailymotion.com/video/{video_id}"


def quality_value(value: str) -> str:
    if not isinstance(value, str):
        raise ValueError("Quality must be best, worst, or a resolution such as 720.")
    if value in {"best", "worst"}:
        return value
    if re.fullmatch(r"\d{2,4}", value) and 64 <= int(value) <= 4320:
        return str(int(value))
    raise ValueError("Quality must be best, worst, or a resolution from 64 to 4320.")


def subtitle_languages(value: list) -> list[str]:
    if not isinstance(value, list) or len(value) > 20:
        raise ValueError("Select up to 20 subtitle languages.")
    if not all(isinstance(lang, str) and LANGUAGE.fullmatch(lang) for lang in value):
        raise ValueError("Invalid subtitle language.")
    return list(dict.fromkeys(value))


def safe_name(title: str) -> str:
    text = unicodedata.normalize("NFKC", title)
    text = re.sub(r'[<>:"/\\|?*\x00-\x1f\x7f]', "_", text)
    text = re.sub(r"\s+", " ", text).strip(" ._")[:70].rstrip(" .")
    if not text or re.match(
        r"^(CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])(?:\.|$)", text, re.I
    ):
        text = "video"
    return text


def display_quality(fmt: dict) -> int:
    width, height = fmt.get("width") or 0, fmt.get("height") or 0
    return int(min(width, height) if width and height else height or width)
