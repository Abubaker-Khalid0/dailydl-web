# Third-party components

DailyDL Web is an application built on existing open-source tools. The extractor is not an original DailyDL implementation.

| Component | Role | Upstream |
| --- | --- | --- |
| yt-dlp | Dailymotion extraction, HLS and subtitles | https://github.com/yt-dlp/yt-dlp |
| curl-cffi | Browser-compatible HTTP requests used by yt-dlp | https://github.com/lexiforest/curl_cffi |
| Flask / Werkzeug / Jinja | Web routes, request handling and templates | https://palletsprojects.com/ |
| Waitress | Local WSGI server | https://docs.pylonsproject.org/projects/waitress/en/stable/ |
| FFmpeg / ffprobe | Media processing and inspection; installed separately | https://ffmpeg.org/ |

Dependencies retain their upstream licenses and notices. The MIT license in this repository covers DailyDL application code. FFmpeg licensing depends on the selected build. The frontend uses local CSS, JavaScript and an SVG mark, without a bundled external font or frontend framework.

Documentation screenshots show the application; any source-video thumbnail or title visible in a verification screenshot belongs to its original publisher and is not a bundled demo video.
