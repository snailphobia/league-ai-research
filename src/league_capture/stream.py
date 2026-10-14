"""A bounded recent-frame buffer: slow consumers never build a stale FIFO."""

import threading
import time
from collections import deque

from .capture import ScreenCapture
from .types import CaptureError, finite_seconds, positive


class FrameStream:
    def __init__(self, *, fps=20, history=4, monitor=1, region=None, factory=ScreenCapture):
        fps = finite_seconds(fps, "fps")
        if fps == 0:
            raise ValueError("fps must be positive")
        positive(history, "history")
        self._period = 1 / fps
        self._frames = deque(maxlen=history)
        self._monitor, self._region, self._factory = monitor, region, factory
        self._condition = threading.Condition()
        self._stop = threading.Event()
        self._thread = None
        self._error = None
        self._terminal = False

    def start(self):
        with self._condition:
            if self._thread is not None or self._terminal:
                raise CaptureError("A frame stream can only be started once")
            self._thread = threading.Thread(target=self._run, name="screen-capture", daemon=True)
            self._thread.start()
        return self

    def _run(self):
        try:
            # The worker creates and closes its own native capture resources.
            with self._factory() as capture:
                deadline = time.perf_counter()
                while not self._stop.is_set():
                    frame = capture.grab(monitor=self._monitor, region=self._region)
                    with self._condition:
                        self._frames.append(frame)
                        self._condition.notify_all()
                    deadline += self._period
                    now = time.perf_counter()
                    if deadline < now:
                        # Skip missed scheduling slots instead of trying to catch up in a burst.
                        deadline += (int((now - deadline) / self._period) + 1) * self._period
                    self._stop.wait(max(0, deadline - now))
        except Exception as error:
            with self._condition:
                self._error = error
        finally:
            with self._condition:
                self._terminal = True
                self._condition.notify_all()

    def next(self, *, after_sequence=-1, timeout=2, max_age=None):
        timeout = finite_seconds(timeout, "timeout")
        deadline = time.perf_counter() + timeout
        with self._condition:
            if self._thread is None:
                raise CaptureError("Start the frame stream before reading it")
            while True:
                if self._error is not None:
                    raise CaptureError("Capture worker failed") from self._error
                if self._terminal or self._stop.is_set():
                    raise CaptureError("The capture stream has stopped")
                if self._frames and self._frames[-1].sequence > after_sequence:
                    frame = self._frames[-1]
                    return frame if max_age is None else frame.require_fresh(max_age)
                remaining = deadline - time.perf_counter()
                if remaining <= 0:
                    raise TimeoutError("No newer captured frame arrived before the deadline")
                self._condition.wait(remaining)

    def recent(self):
        with self._condition:
            if self._error is not None:
                raise CaptureError("Capture worker failed") from self._error
            return tuple(self._frames)

    def close(self, *, timeout=5):
        timeout = finite_seconds(timeout, "timeout")
        self._stop.set()
        with self._condition:
            if self._thread is None:
                self._terminal = True
            self._condition.notify_all()
        if self._thread is not None:
            self._thread.join(timeout)
            if self._thread.is_alive():
                raise CaptureError("Native capture has not stopped within the timeout")

    def __enter__(self):
        return self.start()

    def __exit__(self, *_):
        self.close()
