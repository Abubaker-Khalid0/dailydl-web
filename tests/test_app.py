import io
import json
import tempfile
import time
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

from dailydl_web.app import create_app
from dailydl_web.runner import OperationCancelled


VIDEO = {
    "id": "xalfjry",
    "title": "<script>Title</script>",
    "duration": 10,
    "channel": "Channel",
    "qualities": [360],
    "subtitles": [],
    "selected_quality": 360,
}


def operation(request, **kwargs):
    if request["action"] == "extract":
        return {"video": VIDEO}
    output = Path(request["output"])
    (output / "video.mp4").write_bytes(b"test-video")
    files = ["video.mp4"]
    if request.get("metadata"):
        (output / "metadata.json").write_text(json.dumps(VIDEO), encoding="utf-8")
        files.append("metadata.json")
    return {"video": VIDEO, "files": files, "warnings": []}


class WebTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.app = create_app(
            {"TESTING": True, "TEMP_ROOT": self.temporary.name, "OPERATION": operation}
        )
        self.manager = self.app.extensions["jobs"]
        self.client = self.app.test_client()
        self.client.get("/")
        with self.client.session_transaction() as session:
            self.headers = {"X-CSRF-Token": session["csrf"]}
            self.owner = session["owner"]
        self.ffmpeg = patch("dailydl_web.app.shutil.which", return_value="ffmpeg")
        self.ffmpeg.start()

    def tearDown(self):
        self.ffmpeg.stop()
        self.manager.close()
        self.temporary.cleanup()

    def post(self, route, payload, **kwargs):
        return self.client.post(route, json=payload, headers=self.headers, **kwargs)

    def start(self, **options):
        response = self.post("/api/jobs", {"url": "xalfjry", **options})
        self.assertEqual(response.status_code, 202, response.json)
        identifier = response.json["id"]
        self.manager.jobs[identifier]["thread"].join(timeout=3)
        return identifier

    def test_home_and_security_headers(self):
        response = self.client.get("/")
        self.assertEqual(response.status_code, 200)
        self.assertIn("script-src 'self'", response.headers["Content-Security-Policy"])
        self.assertNotIn("Access-Control-Allow-Origin", response.headers)

    def test_csrf_and_cross_origin_requests_rejected(self):
        self.assertEqual(
            self.client.post("/api/extract", json={"url": "xalfjry"}).status_code, 403
        )
        headers = {**self.headers, "Origin": "https://untrusted.example"}
        self.assertEqual(
            self.client.post(
                "/api/extract", json={"url": "xalfjry"}, headers=headers
            ).status_code,
            403,
        )

    def test_dns_rebinding_host_rejected(self):
        response = self.client.get("/", headers={"Host": "evil.example"})
        self.assertEqual(response.status_code, 400)

    def test_invalid_inputs_return_json_400(self):
        for payload in (
            [],
            {"url": None},
            {"url": 42},
            {"url": "http://127.0.0.1/private"},
            {"url": "xalfjry", "unexpected": True},
        ):
            with self.subTest(payload=payload):
                response = self.post("/api/extract", payload)
                self.assertEqual(response.status_code, 400)
                self.assertTrue(response.is_json)

    def test_raw_stream_and_path_traversal_rejected(self):
        for payload in (
            {"stream_url": "http://127.0.0.1/private"},
            {"url": "xalfjry", "quality": "/../../escape"},
            {"url": "xalfjry", "metadata": "yes"},
            {"url": "xalfjry", "subtitles": ["../../escape"]},
        ):
            with self.subTest(payload=payload):
                self.assertEqual(self.post("/api/jobs", payload).status_code, 400)
        self.assertEqual(list(self.manager.root.iterdir()), [])

    def test_payload_size_is_bounded(self):
        self.assertEqual(
            self.post("/api/extract", {"url": "x" * 9000}).status_code, 413
        )

    def test_ownership_is_enforced(self):
        identifier = self.start()
        other = self.app.test_client()
        other.get("/")
        self.assertEqual(other.get(f"/api/jobs/{identifier}").status_code, 404)
        self.assertEqual(other.get(f"/api/jobs/{identifier}/file").status_code, 404)

    def test_download_stream_closes_then_cleans(self):
        identifier = self.start()
        directory = self.manager.jobs[identifier]["directory"]
        response = self.client.get(f"/api/jobs/{identifier}/file", buffered=False)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data, b"test-video")
        response.close()
        self.assertFalse(directory.exists())
        self.assertEqual(
            self.client.get(f"/api/jobs/{identifier}").json["status"], "downloaded"
        )

    def test_response_closed_without_consumption_cleans(self):
        identifier = self.start()
        response = self.client.get(f"/api/jobs/{identifier}/file", buffered=False)
        response.close()
        self.assertFalse(self.manager.jobs[identifier]["directory"].exists())

    def test_optional_metadata_is_in_zip(self):
        identifier = self.start(metadata=True)
        response = self.client.get(f"/api/jobs/{identifier}/file", buffered=True)
        with zipfile.ZipFile(io.BytesIO(response.data)) as archive:
            self.assertEqual(set(archive.namelist()), {"video.mp4", "metadata.json"})
        response.close()

    def test_jobs_with_same_title_are_isolated(self):
        first, second = self.start(), self.start()
        self.assertNotEqual(
            self.manager.jobs[first]["directory"],
            self.manager.jobs[second]["directory"],
        )

    def test_expired_downloads_are_removed(self):
        identifier = self.start()
        directory = self.manager.jobs[identifier]["directory"]
        self.manager.jobs[identifier]["finished"] = time.monotonic() - 1000
        self.manager.cleanup()
        self.assertFalse(directory.exists())
        self.assertEqual(self.client.get(f"/api/jobs/{identifier}").status_code, 404)

    def test_cancellation_and_capacity(self):
        def blocked(request, *, cancel, **kwargs):
            cancel.wait(5)
            raise OperationCancelled("Cancelled")

        self.manager.operation = blocked
        identifiers = []
        for _ in range(2):
            response = self.post("/api/jobs", {"url": "xalfjry"})
            self.assertEqual(response.status_code, 202)
            identifiers.append(response.json["id"])
        self.assertEqual(self.post("/api/jobs", {"url": "xalfjry"}).status_code, 429)
        for identifier in identifiers:
            self.assertEqual(
                self.post(f"/api/jobs/{identifier}/cancel", {}).status_code, 202
            )
            self.manager.jobs[identifier]["thread"].join(timeout=3)
            self.assertEqual(
                self.client.get(f"/api/jobs/{identifier}").json["status"], "cancelled"
            )
            self.assertFalse(self.manager.jobs[identifier]["directory"].exists())


if __name__ == "__main__":
    unittest.main()
