"""Dailymotion-only yt-dlp adapter. Executed inside a supervised worker."""

import json
import re
import shutil
from pathlib import Path
from urllib.parse import urlsplit

from yt_dlp import YoutubeDL
from yt_dlp.extractor.dailymotion import DailymotionIE

from .model import canonical_url, display_quality, quality_value, subtitle_languages


def public_error(error: Exception) -> str:
    """Do not expose expiring CDN URLs, headers or local tracebacks to clients."""
    text = re.sub(r"https?://\S+", "[remote URL]", str(error))
    text = re.sub(r"\x1b\[[0-9;]*m", "", text)
    return text.removeprefix("ERROR: ")[:800]


class QuietLogger:
    def __init__(self):
        self.warnings = []

    def debug(self, message):
        pass

    def warning(self, message):
        if len(self.warnings) < 10:
            self.warnings.append(public_error(Exception(message)))

    def error(self, message):
        pass


class DailymotionDL(YoutubeDL):
    def urlopen(self, request):
        url = request if isinstance(request, str) else request.url
        parsed = urlsplit(url)
        host = (parsed.hostname or "").lower()
        allowed = any(
            host == suffix or host.endswith("." + suffix)
            for suffix in ("dailymotion.com", "dmcdn.net", "dai.ly")
        )
        if (
            not allowed
            or parsed.scheme not in {"https", "http"}
            or parsed.username
            or parsed.password
            or parsed.port not in {None, 80, 443}
        ):
            raise ValueError("The provider returned an unsupported media destination.")
        return super().urlopen(request)


def formats(info: dict) -> list[dict]:
    return [
        fmt
        for fmt in info.get("formats", [])
        if fmt.get("vcodec") != "none"
        and fmt.get("url")
        and display_quality(fmt)
        and not fmt.get("has_drm")
        and fmt.get("ext") == "mp4"
    ]


def summary(info: dict, url: str) -> dict:
    choices = sorted({display_quality(fmt) for fmt in formats(info)}, reverse=True)
    if not choices:
        raise ValueError(
            "No supported MP4 streams are available. The video may be restricted."
        )
    subtitles = {}
    for automatic, key in ((False, "subtitles"), (True, "automatic_captions")):
        for language, tracks in (info.get(key) or {}).items():
            if tracks:
                subtitles.setdefault(
                    language,
                    {
                        "language": language,
                        "name": tracks[0].get("name") or language,
                        "automatic": automatic or language.endswith("-auto"),
                    },
                )
    thumbnail = info.get("thumbnail") or ""
    host = (urlsplit(thumbnail).hostname or "").lower()
    if not host.endswith(
        (".dmcdn.net", ".dailymotion.com")
    ) or not thumbnail.startswith("https://"):
        thumbnail = ""
    return {
        "id": info["id"],
        "title": info.get("title") or info["id"],
        "duration": info.get("duration") or 0,
        "channel": info.get("uploader") or "",
        "source_url": url,
        "thumbnail": thumbnail,
        "qualities": choices,
        "subtitles": list(subtitles.values()),
    }


def select_format(info: dict, preference: str) -> tuple[str, int]:
    candidates = formats(info)
    if not candidates:
        raise ValueError("No supported video streams are available.")
    levels = sorted({display_quality(fmt) for fmt in candidates})
    if preference == "best":
        selected = levels[-1]
    elif preference == "worst":
        selected = levels[0]
    else:
        target = int(preference)
        selected = max((q for q in levels if q <= target), default=levels[0])
    matching = [fmt for fmt in candidates if display_quality(fmt) == selected]
    fmt = max(
        matching,
        key=lambda f: (f.get("acodec") not in {"none", None}, f.get("tbr") or 0),
    )
    identifier = fmt["format_id"]
    if not re.fullmatch(r"[A-Za-z0-9_.-]+", identifier):
        raise ValueError("The provider returned an unsupported format identifier.")
    if fmt.get("acodec") == "none":
        identifier += "+bestaudio[ext=m4a]"
    return identifier, selected


def execute(request: dict, emit) -> dict:
    url = canonical_url(request["url"])
    action = request["action"]
    if action not in {"extract", "download"}:
        raise ValueError("Unsupported operation.")
    logger = QuietLogger()
    options = {
        "quiet": True,
        "no_warnings": True,
        "logger": logger,
        "noplaylist": True,
        "socket_timeout": 20,
        "retries": request.get("retries", 2),
        "fragment_retries": request.get("retries", 2),
        "extractor_retries": 2,
        "cachedir": False,
        "noprogress": True,
        "windowsfilenames": True,
        "hls_prefer_native": True,
        "concurrent_fragment_downloads": 1,
        "skip_unavailable_fragments": False,
        "overwrites": False,
        "merge_output_format": "mp4",
        "fixup": "detect_or_warn",
    }
    with DailymotionDL(options, auto_init=False) as ydl:
        ydl.add_info_extractor(DailymotionIE())
        emit({"type": "progress", "stage": "extracting", "percent": None})
        info = ydl.extract_info(url, download=False)
        if info.get("is_live"):
            raise ValueError("Live streams are not supported; use a completed video.")
        video = summary(info, url)
        if action == "extract":
            return {"video": video, "warnings": logger.warnings}
        if not shutil.which("ffmpeg") or not shutil.which("ffprobe"):
            raise ValueError(
                "FFmpeg and ffprobe are required. Install them and add them to PATH."
            )
        max_duration = request.get("max_duration", 0)
        if max_duration and video["duration"] > max_duration:
            raise ValueError("This video exceeds the configured duration limit.")
        preference = quality_value(request.get("quality", "best"))
        selector, selected_quality = select_format(info, preference)
        languages = subtitle_languages(request.get("subtitles", []))
        available = {track["language"] for track in video["subtitles"]}
        if languages == ["all"]:
            languages = sorted(available)
        if any(language not in available for language in languages):
            raise ValueError(
                "A selected subtitle language is no longer available. Extract the video again."
            )
        if request.get("subtitles") and not languages:
            logger.warning("No subtitles are available for this video.")
        output = Path(request["output"]).resolve()
        output.mkdir(parents=True, exist_ok=True)
        max_bytes = request.get("max_bytes", 0)

        def progress(data):
            downloaded = data.get("downloaded_bytes") or 0
            total = data.get("total_bytes") or data.get("total_bytes_estimate") or 0
            if max_bytes and (downloaded > max_bytes or total > max_bytes):
                raise ValueError("The video exceeds the configured file size limit.")
            emit(
                {
                    "type": "progress",
                    "stage": "downloading"
                    if data["status"] == "downloading"
                    else "processing",
                    "percent": min(99, round(downloaded * 100 / total, 1))
                    if total
                    else None,
                    "downloaded_bytes": downloaded,
                    "total_bytes": total,
                    "speed": data.get("speed"),
                    "eta": data.get("eta"),
                }
            )

        ydl.params.update(
            {
                "format": selector,
                "outtmpl": {"default": str(output / "video.%(ext)s")},
                "writesubtitles": bool(languages),
                "writeautomaticsub": bool(languages),
                "subtitleslangs": languages,
                "subtitlesformat": "vtt/best",
                "max_filesize": max_bytes or None,
            }
        )
        ydl.format_selector = ydl.build_format_selector(selector)
        ydl.add_progress_hook(progress)
        # Reprocess the already extracted information to avoid a second extraction
        # and use yt-dlp's handling of relative HLS URIs and separate audio tracks.
        ydl.process_ie_result(info, download=True)
        media = output / "video.mp4"
        if not media.is_file() or media.stat().st_size == 0:
            raise ValueError("No completed video file was produced.")
        if max_bytes and media.stat().st_size > max_bytes:
            raise ValueError("The video exceeds the configured file size limit.")
        video["selected_quality"] = selected_quality
        if request.get("metadata", False):
            (output / "metadata.json").write_text(
                json.dumps(video, ensure_ascii=False, indent=2), encoding="utf-8"
            )
        artifacts = [
            p.name
            for p in output.iterdir()
            if p.is_file() and p.suffix not in {".part", ".ytdl", ".tmp"}
        ]
        return {"video": video, "files": sorted(artifacts), "warnings": logger.warnings}
