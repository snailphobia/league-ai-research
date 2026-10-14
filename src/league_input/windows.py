"""Reuse pinned PyDirectInput RGX with checked submission and raw VK support.

The few private RGX entry points used here are version-pinned and exercised by
the independent Windows receiver. RGX provides the Win32 ABI, key catalog,
pixel coordinate conversion, and movement implementation.
"""

import ctypes
import importlib
import sys
from contextlib import contextmanager
from importlib.metadata import version
from threading import RLock

from .types import Button, Desktop, InputError, Key, UnsupportedPlatformError

_LIBRARY_LOCK = RLock()

ALIASES = {
    "control": "ctrl",
    "lctrl": "ctrlleft",
    "rctrl": "ctrlright",
    "lshift": "shiftleft",
    "rshift": "shiftright",
    "lalt": "altleft",
    "ralt": "altright",
    "altgr": "altright",
    "lwin": "winleft",
    "rwin": "winright",
    "windows": "win",
    "numpad0": "num0",
    "numdecimal": "decimal",
    "numdivide": "divide",
    "nummultiply": "multiply",
    "numadd": "add",
    "numsubtract": "subtract",
}


class WindowsBackend:
    def __init__(self):
        if sys.platform != "win32":
            raise UnsupportedPlatformError("WindowsBackend requires Windows 10 or newer")
        if version("pydirectinput-rgx") != "2.1.3.1":
            raise InputError("Install the pinned pydirectinput-rgx==2.1.3.1 backend")
        self.lib = importlib.import_module("pydirectinput")
        self.user32 = ctypes.WinDLL("user32", use_last_error=True)
        self.user32.SetThreadDpiAwarenessContext.argtypes = [ctypes.c_void_p]
        self.user32.SetThreadDpiAwarenessContext.restype = ctypes.c_void_p
        self.lib.FAILSAFE = False  # Corners are valid targets. Cleanup is adapter-owned.
        self.lib.PAUSE = 0

    @contextmanager
    def _context(self):
        with _LIBRARY_LOCK:
            old_dpi = self.user32.SetThreadDpiAwarenessContext(ctypes.c_void_p(-4))
            if not old_dpi:
                raise InputError("Cannot enable physical-pixel coordinates for this thread")
            original_send = self.lib._send_input

            def checked_send(inputs):
                expected = 1 if isinstance(inputs, self.lib._INPUT) else len(inputs)
                inserted = original_send(inputs)
                if inserted != expected:
                    raise InputError(
                        f"SendInput inserted {inserted}/{expected} events; "
                        "check the desktop, target integrity level, and input acceptance"
                    )
                return inserted

            self.lib._send_input = checked_send
            try:
                yield
            finally:
                self.lib._send_input = original_send
                self.user32.SetThreadDpiAwarenessContext(old_dpi)

    def resolve(self, key):
        if isinstance(key, Key):
            return key
        if not isinstance(key, str) or not key:
            raise ValueError("key must be a key name or Key.scan/Key.vk")
        name = ALIASES.get(key.lower(), key.lower())
        # Pause's E1 sequence and PrintScreen's compound make code are not
        # ordinary E0 scan codes. Windows virtual keys express them correctly.
        if name == "pause":
            return Key.vk(0x13)
        if name in {"printscreen", "prntscrn", "prtsc", "prtscr"}:
            return Key.vk(0x2C)
        code = self.lib.KEYBOARD_MAPPING.get(name)
        if code is None:
            raise ValueError(f"Unknown key {key!r}; use Key.vk or Key.scan for other keys")
        if not isinstance(code, int) or code & 0x10000:
            raise ValueError("Use explicit Shift chords for symbols, or type_text for text")
        return Key.scan(code & 0xFF, extended=code >= 0xE000)

    def keys(self):
        names = [
            n
            for n, c in self.lib.KEYBOARD_MAPPING.items()
            if n == n.lower() and (isinstance(c, int) and not c & 0x10000 or n == "pause")
        ]
        return tuple(sorted(set(names) | set(ALIASES)))

    def identity(self, key):
        if key.kind != "vk":
            return key
        # MAPVK_VK_TO_VSC_EX preserves E0/E1 prefixes and left/right identity.
        code = self.lib._map_virtual_key(key.code, 4)
        if not code or code >> 8 == 0xE1:
            return key
        return Key.scan(code & 0xFF, extended=key.extended or code >> 8 == 0xE0)

    def key_event(self, key, down):
        flags = (0 if down else 2) | (1 if key.extended else 0)
        if key.kind == "vk":
            event = self.lib._create_keyboard_input(wVk=key.code, dwFlags=flags)
        else:
            flags |= 4 if key.kind == "unicode" else 8
            event = self.lib._create_keyboard_input(wScan=key.code, dwFlags=flags)
        with self._context():
            self.lib._send_input(event)

    def button_event(self, button, down):
        name = {Button.X1: "mouse4", Button.X2: "mouse5"}.get(button, button.value)
        with self._context():
            (self.lib.mouseDown if down else self.lib.mouseUp)(button=name, _pause=False)

    def move_to(self, x, y, duration):
        with self._context():
            self.lib.moveTo(
                x, y, duration=duration, virtual=True, attempt_pixel_perfect=True, _pause=False
            )

    def move_relative(self, dx, dy):
        with self._context():
            self.lib._send_input(self.lib._create_mouse_input(dx=dx, dy=dy, dwFlags=1))

    def scroll(self, ticks, horizontal):
        if ticks:
            with self._context():
                # WM_MOUSEWHEEL/WM_MOUSEHWHEEL expose a signed 16-bit delta.
                # Preserve large requested totals with bounded native packets.
                while ticks:
                    chunk = max(-273, min(273, ticks))
                    self.lib._send_input(
                        self.lib._create_mouse_input(
                            mouseData=chunk * 120, dwFlags=0x1000 if horizontal else 0x800
                        )
                    )
                    ticks -= chunk

    def position(self):
        with self._context():
            return self.lib.position()

    def desktop(self):
        with self._context():
            width, height, left, top = self.lib.virtual_size()
            return Desktop(left, top, width, height)

    def contains(self, x, y):
        with self._context():
            return self.lib.valid_screen_coordinates(x, y)
