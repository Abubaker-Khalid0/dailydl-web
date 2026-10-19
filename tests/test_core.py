import json
import subprocess
import sys
import threading
import time
import unittest
from unittest.mock import patch

from dailydl_web import engine, runner
from dailydl_web.model import (
    canonical_url,
    quality_value,
    safe_name,
    subtitle_languages,
)


class InputTests(unittest.TestCase):
    def test_supported_urls(self):
        for value in (
            "xalfjry",
            "https://dai.ly/xalfjry",
            "https://www.dailymotion.com/video/xalfjry?x=1",
            "https://www.dailymotion.com/embed/video/xalfjry",
            "https://geo.dailymotion.com/player.html?video=xalfjry",
        ):
            with self.subTest(value=value):
                self.assertEqual(
                    canonical_url(value), "https://www.dailymotion.com/video/xalfjry"
                )

    def test_rejects_untrusted_and_malformed_urls(self):
        for value in (
            None,
            10,
            [],
            "",
            "https://notdailymotion.com/video/xalfjry",
            "file:///tmp/test",
            "http://127.0.0.1/video/xalfjry",
            "https://dailymotion.com@localhost/video/xalfjry",
            "https://www.dailymotion.com:5000/video/xalfjry",
            "https://dai.ly/xalfjry/extra",
        ):
            with self.subTest(value=value), self.assertRaises(ValueError):
                canonical_url(value)

    def test_quality_validation(self):
        self.assertEqual(quality_value("720"), "720")
        self.assertEqual(quality_value("best"), "best")
        for value in ("/../../escape", 720, "x", "-1", "9999", None):
            with self.subTest(value=value), self.assertRaises(ValueError):
                quality_value(value)

    def test_subtitle_validation(self):
        self.assertEqual(subtitle_languages(["en", "ar-auto", "en"]), ["en", "ar-auto"])
        for value in ("en", ["../../file"], [None], ["en"] * 21):
            with self.subTest(value=value), self.assertRaises(ValueError):
                subtitle_languages(value)

    def test_safe_windows_and_unicode_names(self):
        self.assertEqual(safe_name("CON"), "video")
        self.assertEqual(safe_name(".."), "video")
        self.assertIn("تجربة", safe_name("تجربة: فيديو/جديد"))
        self.assertNotIn("/", safe_name("../danger"))
        self.assertLessEqual(len(safe_name("A" * 500)), 70)


class EngineTests(unittest.TestCase):
    def setUp(self):
        self.info = {
            "id": "xalfjry",
            "title": "Test",
            "duration": 5,
            "formats": [
                {
                    "format_id": "hls-low",
                    "url": "https://a.dmcdn.net/low.m3u8",
                    "width": 360,
                    "height": 640,
                    "vcodec": "h264",
                    "acodec": "aac",
                    "ext": "mp4",
                },
                {
                    "format_id": "hls-high",
                    "url": "https://a.dmcdn.net/high.m3u8",
                    "width": 720,
                    "height": 1280,
                    "vcodec": "h264",
                    "acodec": "aac",
                    "ext": "mp4",
                },
            ],
            "subtitles": {"en": [{"name": "English"}]},
        }

    def test_portrait_quality_and_fallback(self):
        self.assertEqual(engine.select_format(self.info, "best"), ("hls-high", 720))
        self.assertEqual(engine.select_format(self.info, "480"), ("hls-low", 360))
        self.assertEqual(engine.select_format(self.info, "144"), ("hls-low", 360))

    def test_separate_audio_is_included(self):
        self.info["formats"][1]["acodec"] = "none"
        self.assertEqual(
            engine.select_format(self.info, "best")[0], "hls-high+bestaudio[ext=m4a]"
        )

    def test_public_metadata_does_not_expose_media_urls(self):
        result = engine.summary(self.info, "https://www.dailymotion.com/video/xalfjry")
        self.assertEqual(result["qualities"], [720, 360])
        self.assertNotIn("dmcdn", json.dumps(result))

    def test_network_guard_rejects_arbitrary_hosts(self):
        with engine.DailymotionDL({"quiet": True}, auto_init=False) as client:
            for url in (
                "http://127.0.0.1/private",
                "file:///etc/passwd",
                "https://dmcdn.net.evil.example/x",
                "https://a.dmcdn.net:444/x",
                "https://user:pass@a.dmcdn.net/x",
            ):
                with self.subTest(url=url), self.assertRaises(ValueError):
                    client.urlopen(url)

    def test_errors_redact_signed_urls(self):
        self.assertNotIn(
            "secret",
            engine.public_error(Exception("Failed https://cdn.example/x?token=secret")),
        )


class RunnerTests(unittest.TestCase):
    def run_child(self, code, **kwargs):
        original = subprocess.Popen

        def launch(command, **options):
            if command[0] == sys.executable and "-m" in command:
                return original([sys.executable, "-c", code], **options)
            return original(command, **options)

        with patch.object(runner.subprocess, "Popen", side_effect=launch):
            return runner.run_operation(
                {"action": "extract", "url": "xalfjry"}, **kwargs
            )

    def test_real_process_timeout(self):
        started = time.monotonic()
        with self.assertRaisesRegex(runner.OperationError, "timed out"):
            self.run_child("import time; time.sleep(60)", timeout=0.2)
        self.assertLess(time.monotonic() - started, 8)

    def test_cancellation_terminates_process(self):
        event = threading.Event()
        event.set()
        with self.assertRaises(runner.OperationCancelled):
            self.run_child("import time; time.sleep(60)", cancel=event)

    def test_worker_exit_is_not_success(self):
        with self.assertRaises(runner.OperationError):
            self.run_child("raise SystemExit(2)", timeout=5)

    def test_result_and_progress_protocol(self):
        events = []
        code = "import json; print(json.dumps({'type':'progress','percent':50}), flush=True); print(json.dumps({'type':'result','result':{'ok':True}}), flush=True)"
        self.assertEqual(
            self.run_child(code, timeout=5, on_progress=events.append), {"ok": True}
        )
        self.assertEqual(events[0]["percent"], 50)


if __name__ == "__main__":
    unittest.main()
