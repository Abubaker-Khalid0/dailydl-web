# Security policy

DailyDL Web is designed for a single user's local workstation. The supported launcher binds to loopback, uses Waitress without the Flask debugger, and accepts only known local Host values.

## Boundaries

- Browser clients cannot choose a filesystem path or submit a raw stream URL.
- A download is re-extracted from a validated canonical Dailymotion video URL.
- Every job has a random ID, a session owner, a private directory, and an expiry time.
- The streamed file handle is closed before its directory is removed, including on Windows and interrupted responses.
- CSRF tokens protect POST requests. A restrictive CSP, no permissive CORS, and Host validation reduce attacks against the local service.
- Deadlines stop the supervised worker process tree. Download capacity and retained job counts are bounded.

This is not a general-purpose public download proxy. Upstream media manifests, redirects, DNS and media decoders remain trust boundaries. Domain checks on initial requests do not constitute comprehensive redirect/DNS isolation. Do not expose the service publicly by simply changing the bind address.

A network-facing adaptation needs explicit authentication, TLS, destination/IP enforcement at every network hop, egress isolation, per-user quotas, durable shared job storage, and deployment-specific review. Multiple web server processes are not supported by the current in-memory job manager.

Provider error messages are shortened and URL-redacted. Keep logs private and never publish cookies, signed media URLs or local credentials in issue reports. A forced shutdown can leave files in the OS temporary directory; inspect only stale `dailydl-web-*` directories after stopping the application.

## Reporting

Report suspected security issues privately through the repository's GitHub Security Advisories feature if enabled. Otherwise contact the repository owner privately before publishing a reproducible exploit. Include the affected version and minimal reproduction; omit other users' data and credentials. There is no promised response SLA.
