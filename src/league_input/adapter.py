"""Keyboard/mouse API with ordered chords and cleanup of owned input."""

import time
from contextlib import contextmanager
from threading import RLock

from .backend import Backend
from .types import Button, InputError, Key, integer, seconds


class InputAdapter:
    def __init__(self, backend: Backend | None = None, *, sleep=time.sleep):
        if backend is None:
            from .windows import WindowsBackend

            backend = WindowsBackend()
        self._backend = backend
        self._sleep = sleep
        self._owned: dict[tuple[str, Key | Button], None] = {}
        self._lock = RLock()
        self._closed = False

    def _open(self):
        if self._closed:
            raise InputError("This input adapter is closed")

    @property
    def held_keys(self):
        return tuple(k for kind, k in self._owned if kind == "key")

    @property
    def held_buttons(self):
        return tuple(b for kind, b in self._owned if kind == "button")

    def available_keys(self):
        return self._backend.keys()

    def _down(self, kind, value):
        self._open()
        token = kind, value
        if token in self._owned:
            return False
        # Track before submission: a partially inserted input still needs release.
        self._owned[token] = None
        if kind == "key":
            self._backend.key_event(value, True)
        else:
            self._backend.button_event(value, True)
        return True

    def _up(self, kind, value):
        token = kind, value
        if token not in self._owned:
            return False
        if kind == "key":
            self._backend.key_event(value, False)
        else:
            self._backend.button_event(value, False)
        del self._owned[token]  # Preserve ownership if release fails, for a retry.
        return True

    def key_down(self, key: str | Key):
        with self._lock:
            return self._down("key", self._backend.resolve(key))

    def key_up(self, key: str | Key):
        with self._lock:
            return self._up("key", self._backend.resolve(key))

    def mouse_down(self, button: str | Button = Button.LEFT):
        with self._lock:
            return self._down("button", Button(button))

    def mouse_up(self, button: str | Button = Button.LEFT):
        with self._lock:
            return self._up("button", Button(button))

    def _release_tokens(self, tokens):
        errors = []
        for kind, value in reversed(tokens):
            try:
                self._up(kind, value)
            except Exception as error:
                errors.append(error)
        if errors:
            raise ExceptionGroup("Some owned inputs could not be released", errors)

    @contextmanager
    def hold(self, *keys: str | Key, buttons=()):
        resolved = [self._backend.resolve(key) for key in keys]
        resolved_buttons = [Button(button) for button in buttons]
        requested = [("key", key) for key in resolved] + [("button", b) for b in resolved_buttons]
        acquired = []
        with self._lock:
            self._open()
            try:
                for token in requested:
                    if token not in self._owned:
                        acquired.append(token)
                        self._down(*token)
                yield self
            finally:
                self._release_tokens(acquired)

    def hotkey(self, *keys: str | Key, duration: float = 0.0):
        duration = seconds(duration, "duration")
        if not keys:
            raise ValueError("A hotkey needs at least one key")
        with self.hold(*keys):
            self._sleep(duration)

    def press(self, key: str | Key, *, count=1, interval=0.0, duration=0.0):
        integer(count, "count")
        if count < 1:
            raise ValueError("count must be positive")
        interval, duration = seconds(interval, "interval"), seconds(duration, "duration")
        resolved = self._backend.resolve(key)
        with self._lock:
            self._open()
            if ("key", resolved) in self._owned:
                raise InputError("press cannot tap a key already held; release it or use key_down")
            for index in range(count):
                if index:
                    self._sleep(interval)
                self.hotkey(resolved, duration=duration)

    def type_text(self, text: str, *, interval=0.0):
        if not isinstance(text, str):
            raise ValueError("text must be a string")
        interval = seconds(interval, "interval")
        text.encode("utf-16-le")  # Validate the entire string before any input.
        with self._lock:
            self._open()
            for index, char in enumerate(text):
                if index:
                    self._sleep(interval)
                data = char.encode("utf-16-le")
                units = [
                    Key("unicode", int.from_bytes(data[i : i + 2], "little"))
                    for i in range(0, len(data), 2)
                ]
                with self.hold(*units):
                    pass

    def position(self):
        with self._lock:
            self._open()
            return self._backend.position()

    def desktop(self):
        with self._lock:
            self._open()
            return self._backend.desktop()

    def _point(self, x, y):
        integer(x, "x")
        integer(y, "y")
        if not self._backend.contains(x, y):
            raise ValueError(f"({x}, {y}) is not on an attached monitor")

    def move_to(self, x: int, y: int, *, duration=0.0):
        duration = seconds(duration, "duration")
        with self._lock:
            self._open()
            self._point(x, y)
            self._backend.move_to(x, y, duration)

    def move_by(self, dx: int, dy: int, *, duration=0.0):
        integer(dx, "dx")
        integer(dy, "dy")
        with self._lock:
            x, y = self.position()
            self.move_to(x + dx, y + dy, duration=duration)

    def move_relative(self, dx: int, dy: int):
        integer(dx, "dx")
        integer(dy, "dy")
        with self._lock:
            self._open()
            self._backend.move_relative(dx, dy)

    def click(self, x=None, y=None, *, button=Button.LEFT, count=1, interval=0.0, duration=0.0):
        button = Button(button)
        integer(count, "count")
        if count < 1:
            raise ValueError("count must be positive")
        interval, duration = seconds(interval, "interval"), seconds(duration, "duration")
        if (x is None) != (y is None):
            raise ValueError("Specify both x and y, or neither")
        with self._lock:
            self._open()
            if ("button", button) in self._owned:
                raise InputError("click cannot tap a mouse button already held")
            if x is not None:
                self.move_to(x, y)
            for index in range(count):
                if index:
                    self._sleep(interval)
                with self.hold(buttons=[button]):
                    self._sleep(duration)

    def drag_to(self, x: int, y: int, *, button=Button.LEFT, duration=0.25):
        button = Button(button)
        duration = seconds(duration, "duration")
        with self._lock:
            self._open()
            self._point(x, y)
            with self.hold(buttons=[button]):
                self.move_to(x, y, duration=duration)

    def scroll(self, ticks: int, *, horizontal=False):
        integer(ticks, "ticks")
        if not isinstance(horizontal, bool):
            raise ValueError("horizontal must be a boolean")
        if not -(2**31) <= ticks * 120 < 2**31:
            raise ValueError("wheel delta exceeds Windows' signed 32-bit range")
        with self._lock:
            self._open()
            self._backend.scroll(ticks, horizontal)

    def release_all(self):
        with self._lock:
            self._release_tokens(list(self._owned))

    def close(self):
        with self._lock:
            self.release_all()
            self._closed = True

    def __enter__(self):
        self._open()
        return self

    def __exit__(self, *_):
        self.close()
