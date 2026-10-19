"""Supervise a worker and its FFmpeg children with a real wall-clock deadline."""

import json
import os
import queue
import signal
import subprocess
import sys
import threading
import time


class OperationError(Exception):
    pass


class OperationCancelled(OperationError):
    pass


def stop_process(process):
    if process.poll() is not None:
        return
    if os.name == "nt":
        try:
            subprocess.run(
                ["taskkill", "/PID", str(process.pid), "/T", "/F"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=5,
                creationflags=subprocess.CREATE_NO_WINDOW,
            )
        except (OSError, subprocess.TimeoutExpired):
            process.kill()
    else:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
    if process.poll() is None:
        process.kill()
    process.wait(timeout=10)


def run_operation(request, *, timeout=600, on_progress=None, cancel=None):
    if timeout <= 0:
        raise ValueError("Timeout must be positive.")
    flags = (
        {
            "creationflags": subprocess.CREATE_NEW_PROCESS_GROUP
            | subprocess.CREATE_NO_WINDOW
        }
        if os.name == "nt"
        else {"start_new_session": True}
    )
    environment = os.environ.copy()
    environment.update(PYTHONIOENCODING="utf-8", PYTHONDONTWRITEBYTECODE="1")
    process = subprocess.Popen(
        [sys.executable, "-m", f"{__package__}.worker"],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        text=True,
        encoding="utf-8",
        errors="replace",
        env=environment,
        **flags,
    )
    events = queue.Queue()

    def read_events():
        try:
            for line in process.stdout:
                try:
                    events.put(json.loads(line))
                except json.JSONDecodeError:
                    continue
        finally:
            events.put(None)

    reader = threading.Thread(target=read_events, daemon=True)
    reader.start()
    deadline = time.monotonic() + timeout
    try:
        process.stdin.write(json.dumps(request) + "\n")
        process.stdin.close()
        while True:
            if cancel is not None and cancel.is_set():
                raise OperationCancelled("Operation cancelled.")
            if time.monotonic() >= deadline:
                raise OperationError(f"Operation timed out after {timeout:g} seconds.")
            try:
                event = events.get(
                    timeout=min(0.1, max(0.001, deadline - time.monotonic()))
                )
            except queue.Empty:
                continue
            if event is None:
                raise OperationError("The download worker stopped unexpectedly.")
            if event.get("type") == "error":
                raise OperationError(event.get("error", "Download failed."))
            if event.get("type") == "result":
                return event["result"]
            if on_progress:
                on_progress(event)
    finally:
        try:
            process.wait(timeout=0.5)
        except subprocess.TimeoutExpired:
            stop_process(process)
        if not process.stdin.closed:
            process.stdin.close()
        reader.join(timeout=2)
        process.stdout.close()
