"""Capture pixels through MSS; keep physical geometry in the same space as input."""

import ctypes
import sys
import time
from contextlib import contextmanager
from importlib.metadata import version
from threading import RLock
from uuid import uuid4

from .types import CaptureError, Frame, Region, integer


class MSSBackend:
    def __init__(self):
        if sys.platform != "win32":
            raise CaptureError("The default capture backend requires Windows")
        if version("mss") != "10.2.0":
            raise CaptureError("Install the pinned capture extra: league-input[capture]")
        from ctypes import wintypes as W

        from mss import MSS

        self.user32 = ctypes.WinDLL("user32", use_last_error=True)
        self.user32.SetThreadDpiAwarenessContext.argtypes = [ctypes.c_void_p]
        self.user32.SetThreadDpiAwarenessContext.restype = ctypes.c_void_p
        self._monitor_proc = ctypes.WINFUNCTYPE(
            W.BOOL, W.HANDLE, W.HDC, ctypes.POINTER(W.RECT), W.LPARAM
        )
        self.user32.EnumDisplayMonitors.argtypes = [
            W.HDC,
            ctypes.POINTER(W.RECT),
            self._monitor_proc,
            W.LPARAM,
        ]
        self.user32.EnumDisplayMonitors.restype = W.BOOL
        with self._dpi():
            self._capture = MSS(backend="gdi", with_cursor=False)

    @contextmanager
    def _dpi(self):
        previous = self.user32.SetThreadDpiAwarenessContext(ctypes.c_void_p(-4))
        if not previous:
            raise CaptureError("Cannot enable physical-pixel coordinates for capture")
        try:
            yield
        finally:
            self.user32.SetThreadDpiAwarenessContext(previous)

    def monitors(self):
        # Public Win32 enumeration refreshes geometry on every grab. MSS caches its
        # own monitor list; we pass explicit rectangles to its capture API instead.
        result = []

        def collect(handle, hdc, pointer, data):
            r = pointer.contents
            result.append(Region(r.left, r.top, r.right - r.left, r.bottom - r.top))
            return True

        callback = self._monitor_proc(collect)
        with self._dpi():
            if not self.user32.EnumDisplayMonitors(None, None, callback, 0) or not result:
                raise CaptureError("Cannot enumerate attached monitors")
        return tuple(result)

    def grab(self, region):
        from PIL import Image

        with self._dpi():
            shot = self._capture.grab(
                {
                    "left": region.left,
                    "top": region.top,
                    "width": region.width,
                    "height": region.height,
                }
            )
            # Ignore the unused GDI alpha byte. Copy before the native DIB is reused.
            return Image.frombytes(
                "RGB", (region.width, region.height), shot.bgra, "raw", "BGRX"
            ).tobytes()

    def close(self):
        self._capture.close()


class ScreenCapture:
    def __init__(self, backend=None, *, clock=time.perf_counter_ns):
        self._backend = MSSBackend() if backend is None else backend
        self._clock = clock
        self._sequence = 0
        self._closed = False
        self._lock = RLock()

    def _open(self):
        if self._closed:
            raise CaptureError("This capture source is closed")

    def monitors(self):
        with self._lock:
            self._open()
            return self._backend.monitors()

    def grab(self, *, monitor=1, region=None):
        """Monitor 0 is the virtual desktop; 1..N follow Windows enumeration order."""
        integer(monitor, "monitor")
        if region is not None and not isinstance(region, Region):
            raise ValueError("region must be a Region")
        with self._lock:
            self._open()
            started = self._clock()
            monitors = self._backend.monitors()
            if not monitors:
                raise CaptureError("No monitors are attached")
            left, top = min(m.left for m in monitors), min(m.top for m in monitors)
            desktop = Region(
                left,
                top,
                max(m.right for m in monitors) - left + 1,
                max(m.bottom for m in monitors) - top + 1,
            )
            if region is None:
                if not 0 <= monitor <= len(monitors):
                    raise ValueError("monitor index is outside the attached monitor list")
                region = desktop if monitor == 0 else monitors[monitor - 1]
            if not desktop.contains_region(region):
                raise ValueError("capture region extends outside the virtual desktop")
            rgb = self._backend.grab(region)
            finished = self._clock()
            identity = uuid4().hex
            frame = Frame(
                identity,
                identity,
                self._sequence,
                region,
                region.width,
                region.height,
                rgb,
                started,
                finished,
                tuple(monitors),
            )
            self._sequence += 1
            return frame

    def close(self):
        with self._lock:
            if not self._closed:
                self._backend.close()
                self._closed = True

    def __enter__(self):
        self._open()
        return self

    def __exit__(self, *_):
        self.close()
