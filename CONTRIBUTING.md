# Contributing

Use a virtual environment and install `python -m pip install -e ".[dev]"`.
Run `python -m unittest discover -s tests -v` and `python -m ruff check src tests` before submitting a change. Build with `python -m build`.

Add regression coverage for behavior changes. Keep ordinary tests offline; report any live-provider verification separately with its date, engine version and result. Never commit cookies, authentication headers, signed media URLs, downloaded videos or local environments.

When reporting a bug, include your operating system, Python version, application version, yt-dlp version, reproduction steps and a public video URL when appropriate. Redact personal paths and credentials. Do not imply that restricted content is supported.

Keep this repository independently installable. Changes must not add imports or path manipulation pointing to the sibling DailyDL project.
