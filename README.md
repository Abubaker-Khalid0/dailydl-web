# DailyDL Web

**A local, Arabic-first workspace for downloading Dailymotion videos.** Choose a quality, add subtitles or metadata, follow progress, and save the completed file.

![DailyDL Web desktop interface](docs/screenshot-desktop.jpg)

Built with [Flask](https://flask.palletsprojects.com/), [yt-dlp](https://github.com/yt-dlp/yt-dlp), [Waitress](https://docs.pylonsproject.org/projects/waitress/en/stable/), and [FFmpeg](https://ffmpeg.org/). DailyDL provides the UI, validation, job lifecycle and download delivery; yt-dlp handles provider extraction.

## Features

- Responsive Arabic / RTL interface with keyboard-accessible quality controls.
- Background downloads with progress, cancellation and reload recovery for active jobs.
- MP4 downloads; optional subtitles and metadata are delivered together in a ZIP.
- Browser download streaming without loading a whole video into a JavaScript Blob.
- Session-owned jobs, CSRF protection, strict URL validation and local-only hosting.
- Independent temporary directories, cancellation cleanup and automatic expiry.
- No frontend build step, external fonts, analytics or database.

## Requirements and installation

- CPython 3.10 or newer. Verified locally on Windows with Python 3.13.
- FFmpeg and ffprobe on `PATH` for downloading.

Inside this repository:

```sh
python -m venv .venv
```

Windows PowerShell:

```powershell
.\.venv\Scripts\Activate.ps1
```

macOS / Linux:

```sh
source .venv/bin/activate
```

Install and run:

```sh
python -m pip install -e .
dailydl-web
```

Open **http://127.0.0.1:5000**. To choose another port, run `dailydl-web --port 5050`. The alternative command is `python -m dailydl_web`.

This repository is standalone; it does not import anything from DailyDL CLI. For the dependency versions used in release verification, install `requirements.lock` before installing the project:

```sh
python -m pip install -r requirements.lock
python -m pip install -e .
```

## Using the app

1. Paste a Dailymotion URL or video ID and select **استخراج الفيديو**.
2. Choose the quality. Enable metadata or subtitles if needed.
3. Select **تحضير التحميل**, then follow the progress or cancel.
4. When ready, select **حفظ الملف على الجهاز**.

Video-only downloads are MP4. If additional files are produced, the response is a ZIP containing `video.mp4`, optional subtitle tracks and optional `metadata.json`. Automatic subtitles are labeled. Metadata does not contain signed CDN URLs.

The displayed quality uses the shorter dimension for portrait video. If the provider removes a requested resolution between extraction and download, the engine selects the nearest lower resolution, or the smallest available if none is lower. The final filename reports the actual quality.

Completed files are kept for **15 minutes** if uncollected. They are removed after their streamed response closes, including interrupted downloads. Start a new job if you need another copy. Active jobs resume polling after a page reload in the same browser tab. Restarting the application invalidates the session and in-memory job history.

## Resource limits and security model

This is a **personal, local application**, not a public multi-user download service. Waitress binds to `127.0.0.1`; debug mode is disabled. There is no account system or public deployment preset.

- Maximum two simultaneous extraction/download operations.
- Maximum 20 retained job records, including completed/failed jobs until expiry.
- Downloads have a 10-minute wall-clock deadline; extraction has a 60-second deadline.
- Web downloads are limited to two-hour videos and a 2 GiB video file. Temporary subtitle, merge and ZIP files can use additional disk space; this is not a filesystem quota.
- The client submits only a Dailymotion URL, validated quality, subtitle languages and a metadata flag. It cannot supply a raw media URL, filename or output path.
- Job status, cancellation and file delivery are bound to the initiating session.
- POST requests require a CSRF token, and untrusted Host / Origin values are rejected.
- No permissive CORS; security headers and a restrictive content security policy are enabled.

The adapter restricts initial outbound requests to Dailymotion/CDN domains. These checks are defense in depth, not a replacement for network egress controls against compromised upstream services or redirects. See [SECURITY.md](SECURITY.md) before adapting it for any network-facing deployment.

Temporary directories are removed on normal shutdown. A forced process termination or power loss may leave an OS temporary directory named `dailydl-web-*`; remove stale directories only after stopping the application.

## Development

```sh
python -m pip install -e ".[dev]"
python -m unittest discover -s tests -v
python -m ruff check src tests
python -m build
```

The tests exercise request validation, session isolation, CSRF, path traversal rejection, stream cleanup, ZIP output, expiry, capacity, cancellation and real subprocess deadlines. Live Dailymotion access is not required. GitHub Actions includes Windows/Ubuntu and Python 3.10/3.13 checks; the included workflow will run after the repository is pushed.

```text
src/dailydl_web/
  app.py              # Flask factory, validated routes, security headers
  jobs.py             # bounded jobs, ownership, expiry, streamed cleanup
  engine.py           # Dailymotion-only yt-dlp adapter
  runner.py           # supervised subprocess with deadline and cancellation
  worker.py           # private worker protocol
  model.py            # public input validation
  templates/          # accessible Arabic markup
  static/             # CSS, JavaScript, local icon
tests/
```

Provider changes can affect extraction. Update `yt-dlp[curl-cffi]`, rerun the tests and verify a live download before refreshing `requirements.lock`.

## License and attribution

Application code is MIT licensed. Dependencies keep their own licenses; see [THIRD_PARTY.md](THIRD_PARTY.md). Not affiliated with Dailymotion. Download only content you are authorized to save. Live, private, password-protected and DRM-protected videos are not supported by this application's workflow.
