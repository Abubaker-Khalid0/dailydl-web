"""Local web application with strict inputs and session-owned downloads."""

import atexit
import hmac
import secrets
import shutil
from urllib.parse import urlsplit

from flask import Flask, Response, jsonify, render_template, request, session
from werkzeug.exceptions import HTTPException

from . import __version__
from .jobs import BusyError, JobManager
from .model import canonical_url, quality_value, subtitle_languages
from .runner import OperationError


def create_app(config=None):
    app = Flask(__name__)
    app.config.update(
        SECRET_KEY=secrets.token_hex(32),
        MAX_CONTENT_LENGTH=8192,
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Strict",
        TRUSTED_HOSTS=["localhost", "127.0.0.1", "[::1]"],
        JOB_TIMEOUT=600,
        JOB_RETENTION=900,
        JOB_LIMIT=2,
        TEMP_ROOT=None,
    )
    if config:
        app.config.update(config)
    manager = JobManager(
        root=app.config["TEMP_ROOT"],
        timeout=app.config["JOB_TIMEOUT"],
        retention=app.config["JOB_RETENTION"],
        limit=app.config["JOB_LIMIT"],
        **({"operation": app.config["OPERATION"]} if "OPERATION" in app.config else {}),
    )
    app.extensions["jobs"] = manager
    atexit.register(manager.close)

    @app.before_request
    def protect():
        # Reading request.host invokes Flask's trusted-host validation.
        host = request.host
        if request.method not in {"GET", "HEAD", "OPTIONS"}:
            origin = request.headers.get("Origin")
            if origin and urlsplit(origin).netloc != host:
                return jsonify(error="Cross-origin requests are not allowed."), 403
            expected = session.get("csrf", "")
            supplied = request.headers.get("X-CSRF-Token", "")
            if not expected or not hmac.compare_digest(expected, supplied):
                return jsonify(
                    error="Session expired. Reload the page and try again."
                ), 403

    @app.after_request
    def security_headers(response):
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; script-src 'self'; style-src 'self'; "
            "img-src 'self' https://*.dmcdn.net https://*.dailymotion.com; "
            "connect-src 'self'; object-src 'none'; base-uri 'none'; frame-ancestors 'none'; form-action 'self'"
        )
        if request.path.startswith("/api/") or request.path == "/":
            response.headers["Cache-Control"] = "no-store"
        return response

    @app.errorhandler(HTTPException)
    def http_error(error):
        return jsonify(error=error.description), error.code

    @app.errorhandler(BusyError)
    def busy(error):
        response = jsonify(error=str(error))
        response.headers["Retry-After"] = "5"
        return response, 429

    @app.errorhandler(OperationError)
    def operation_error(error):
        return jsonify(error=str(error)), 502

    @app.errorhandler(ValueError)
    def invalid(error):
        return jsonify(error=str(error)), 400

    @app.errorhandler(KeyError)
    def missing(error):
        return jsonify(error="This download does not exist or has expired."), 404

    @app.errorhandler(Exception)
    def unexpected(error):
        app.logger.exception("Unexpected request failure")
        return jsonify(error="An unexpected error occurred. Please try again."), 500

    def body(allowed):
        data = request.get_json()
        if not isinstance(data, dict) or set(data) - allowed:
            raise ValueError("Invalid request fields.")
        return data

    def owner():
        return session.get("owner", "")

    @app.get("/")
    def index():
        session.setdefault("csrf", secrets.token_urlsafe(32))
        session.setdefault("owner", secrets.token_urlsafe(32))
        return render_template("index.html", version=__version__, csrf=session["csrf"])

    @app.get("/api/health")
    def health():
        return jsonify(
            version=__version__,
            ffmpeg=bool(shutil.which("ffmpeg")),
            ffprobe=bool(shutil.which("ffprobe")),
        )

    @app.post("/api/extract")
    def extract():
        data = body({"url"})
        return jsonify(manager.extract(canonical_url(data.get("url"))))

    @app.post("/api/jobs")
    def start():
        data = body({"url", "quality", "subtitles", "metadata"})
        metadata = data.get("metadata", False)
        if not isinstance(metadata, bool):
            raise ValueError("Metadata must be a boolean.")
        payload = {
            "url": canonical_url(data.get("url")),
            "quality": quality_value(data.get("quality", "best")),
            "subtitles": subtitle_languages(data.get("subtitles", [])),
            "metadata": metadata,
        }
        if not shutil.which("ffmpeg") or not shutil.which("ffprobe"):
            return jsonify(
                error="Install FFmpeg and ffprobe on the server before downloading."
            ), 503
        identifier = manager.start(owner(), payload)
        return jsonify(id=identifier), 202

    @app.get("/api/jobs/<identifier>")
    def status(identifier):
        return jsonify(manager.status(identifier, owner()))

    @app.post("/api/jobs/<identifier>/cancel")
    def cancel(identifier):
        body(set())
        manager.cancel(identifier, owner())
        return jsonify(success=True), 202

    @app.get("/api/jobs/<identifier>/file")
    def download(identifier):
        stream, filename, size = manager.open_download(identifier, owner())
        response = Response(
            stream,
            mimetype="application/zip" if filename.endswith(".zip") else "video/mp4",
            direct_passthrough=True,
        )
        response.headers.set(
            "Content-Disposition",
            "attachment",
            filename=filename.encode("ascii", "ignore").decode() or "download.mp4",
        )
        from urllib.parse import quote

        response.headers["Content-Disposition"] += "; filename*=UTF-8''" + quote(
            filename
        )
        response.content_length = size
        return response

    return app
