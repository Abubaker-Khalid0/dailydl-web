"""Bounded background downloads with cancellation and disposable artifacts."""

import shutil
import tempfile
import threading
import time
import uuid
import zipfile
from pathlib import Path

from .model import safe_name
from .runner import OperationCancelled, run_operation


class BusyError(Exception):
    pass


class JobManager:
    def __init__(
        self, *, root=None, limit=2, retention=900, timeout=600, operation=run_operation
    ):
        self.root = Path(tempfile.mkdtemp(prefix="dailydl-web-", dir=root)).resolve()
        self.slots = threading.BoundedSemaphore(limit)
        self.retention = retention
        self.timeout = timeout
        self.operation = operation
        self.lock = threading.RLock()
        self.jobs = {}
        self.closing = threading.Event()
        self.cleaner = threading.Thread(target=self._sweep, daemon=True)
        self.cleaner.start()

    def _remove(self, path):
        resolved = Path(path).resolve()
        if resolved.parent != self.root:
            raise ValueError("Invalid artifact directory.")
        shutil.rmtree(resolved, ignore_errors=False) if resolved.exists() else None

    def cleanup(self):
        with self.lock:
            expired = [
                key
                for key, job in self.jobs.items()
                if job["status"] in {"done", "error", "cancelled", "downloaded"}
                and time.monotonic() - job["finished"] > self.retention
            ]
            for key in expired:
                self._remove(self.jobs[key]["directory"])
                del self.jobs[key]

    def _sweep(self):
        while not self.closing.wait(15):
            try:
                self.cleanup()
            except OSError:
                # Windows scanners may briefly hold a file. Retry on the next sweep.
                continue

    def extract(self, url):
        if not self.slots.acquire(blocking=False):
            raise BusyError("All download slots are busy. Try again shortly.")
        try:
            return self.operation(
                {"action": "extract", "url": url}, timeout=min(self.timeout, 60)
            )
        finally:
            self.slots.release()

    def start(self, owner, request):
        self.cleanup()
        with self.lock:
            if (
                self.closing.is_set()
                or len(self.jobs) >= 20
                or not self.slots.acquire(blocking=False)
            ):
                raise BusyError("The download queue is full. Try again shortly.")
            identifier = uuid.uuid4().hex
            directory = self.root / identifier
            try:
                directory.mkdir()
                job = {
                    "id": identifier,
                    "owner": owner,
                    "status": "running",
                    "stage": "extracting",
                    "percent": None,
                    "error": None,
                    "cancel": threading.Event(),
                    "directory": directory,
                    "finished": 0,
                    "warnings": [],
                }
                thread = threading.Thread(
                    target=self._run, args=(job, request), daemon=True
                )
                job["thread"] = thread
                self.jobs[identifier] = job
                thread.start()
                return identifier
            except Exception:
                self.jobs.pop(identifier, None)
                self._remove(directory)
                self.slots.release()
                raise

    def _run(self, job, request):
        try:

            def update(event):
                with self.lock:
                    for key in (
                        "stage",
                        "percent",
                        "downloaded_bytes",
                        "total_bytes",
                        "speed",
                        "eta",
                    ):
                        if key in event:
                            job[key] = event[key]

            result = self.operation(
                {
                    **request,
                    "action": "download",
                    "output": str(job["directory"]),
                    "max_bytes": 2 * 1024**3,
                    "max_duration": 7200,
                },
                timeout=self.timeout,
                on_progress=update,
                cancel=job["cancel"],
            )
            if job["cancel"].is_set():
                raise OperationCancelled("Download cancelled.")
            files = []
            for name in result["files"]:
                path = job["directory"] / name
                if (
                    path.resolve().parent != job["directory"]
                    or path.is_symlink()
                    or not path.is_file()
                ):
                    raise ValueError("Invalid download artifact.")
                files.append(path)
            if not files or not any(path.name == "video.mp4" for path in files):
                raise ValueError("No completed video file was produced.")
            video = result["video"]
            filename = f"{safe_name(video['title'])} [{video['id']}] {video['selected_quality']}p"
            artifact = job["directory"] / "video.mp4"
            extension = ".mp4"
            if len(files) > 1:
                artifact = job["directory"] / "download.zip"
                with zipfile.ZipFile(
                    artifact, "w", compression=zipfile.ZIP_STORED
                ) as bundle:
                    for path in files:
                        bundle.write(path, arcname=path.name)
                extension = ".zip"
            with self.lock:
                if job["cancel"].is_set():
                    raise OperationCancelled("Download cancelled.")
                job.update(
                    status="done",
                    stage="complete",
                    percent=100,
                    artifact=artifact,
                    filename=filename + extension,
                    size=artifact.stat().st_size,
                    warnings=result.get("warnings", []),
                    finished=time.monotonic(),
                )
        except Exception as error:
            with self.lock:
                job.update(
                    status="cancelled"
                    if isinstance(error, OperationCancelled)
                    else "error",
                    error=str(error),
                    finished=time.monotonic(),
                )
            try:
                self._remove(job["directory"])
            except OSError:
                pass  # The expiry sweep will retry; state is still retained.
        finally:
            self.slots.release()

    def get(self, identifier, owner):
        with self.lock:
            job = self.jobs.get(identifier)
            if not job or job["owner"] != owner:
                raise KeyError(identifier)
            return job

    def status(self, identifier, owner):
        self.cleanup()
        with self.lock:
            job = self.get(identifier, owner)
            return {
                key: job.get(key)
                for key in (
                    "id",
                    "status",
                    "stage",
                    "percent",
                    "error",
                    "downloaded_bytes",
                    "total_bytes",
                    "speed",
                    "eta",
                    "warnings",
                    "filename",
                    "size",
                )
            }

    def cancel(self, identifier, owner):
        with self.lock:
            job = self.get(identifier, owner)
            if job["status"] != "running":
                raise ValueError("This job is no longer running.")
            job["cancel"].set()
            job["stage"] = "cancelling"

    def open_download(self, identifier, owner):
        with self.lock:
            job = self.get(identifier, owner)
            if job["status"] != "done":
                raise ValueError(
                    "The download is not ready or has already been collected."
                )
            handle = job["artifact"].open("rb")
            job["status"] = "serving"

        def release():
            with self.lock:
                job.update(status="downloaded", finished=time.monotonic())
                try:
                    self._remove(job["directory"])
                except OSError:
                    pass

        return FileBody(handle, release), job["filename"], job["size"]

    def close(self):
        if self.closing.is_set():
            return
        self.closing.set()
        with self.lock:
            jobs = list(self.jobs.values())
            for job in jobs:
                job["cancel"].set()
        for job in jobs:
            job["thread"].join(timeout=15)
        self.cleaner.join(timeout=2)
        # Only this process's private temporary root is ever removed.
        shutil.rmtree(self.root, ignore_errors=True)


class FileBody:
    """WSGI iterable that closes the file BEFORE deleting its directory on Windows."""

    def __init__(self, handle, release):
        self.handle, self.release, self.closed = handle, release, False

    def __iter__(self):
        return self

    def __next__(self):
        if self.closed:
            raise StopIteration
        data = self.handle.read(256 * 1024)
        if not data:
            self.close()
            raise StopIteration
        return data

    def close(self):
        if not self.closed:
            self.closed = True
            self.handle.close()
            self.release()
