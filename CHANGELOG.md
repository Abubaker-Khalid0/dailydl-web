# Changelog

## 4.0.0 — 2026-10-17

- Split the web application into a standalone installable project.
- Introduce a responsive Arabic interface with live progress, cancellation and subtitle/metadata options.
- Replace client-supplied stream URLs and filenames with validated server-side extraction and isolated jobs.
- Add session ownership, CSRF protection, Host checks and local-only Waitress startup.
- Fix Windows file cleanup by closing streamed responses before deleting artifacts.
- Add deadline/capacity/expiry controls, regression tests, CI and packaging.
