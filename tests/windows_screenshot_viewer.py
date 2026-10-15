"""Independent image viewer and native input witness. No policy or adapter imports.

Screenshots stay static. A separate footer changes color only after the window
receives a button/key release. The footer confirms input delivery, not gameplay.
"""

import ctypes as C
import threading
import time
from ctypes import wintypes as W

from PIL import Image
from windows_policy_scene import BitmapHeader
from windows_receiver import WNDPROC, K, U, signature
from windows_visual_scene import G, Paint

signature(U, "SendMessageW", [W.HWND, W.UINT, W.WPARAM, W.LPARAM], C.c_ssize_t)
signature(U, "GetCursorPos", [C.POINTER(W.POINT)], W.BOOL)
RECEIPT = (30, 220, 80)


class ScreenshotViewer:
    def __init__(self, left=32, top=32):
        self.left, self.top = left, top
        self.width, self.height = 960, 576
        self.image = Image.new("RGB", (960, 540), "black")
        self.events = []
        self.failure = None
        self.ready = threading.Event()
        self.thread = threading.Thread(target=self._run, daemon=True)

    def start(self):
        self.thread.start()
        if not self.ready.wait(10):
            raise RuntimeError("Screenshot viewer did not initialize")
        if self.failure:
            raise self.failure
        return self

    def present(self, image):
        if image.size != (960, 540) or image.mode != "RGB":
            raise ValueError("viewer expects 960x540 RGB images")
        self.image = image.copy()
        U.SendMessageW(self.hwnd, 0x8001, 0, 0)
        if self.failure:
            raise self.failure

    def _run(self):
        hwnd, original = None, None
        try:
            self.thread_id = K.GetCurrentThreadId()
            U.SetThreadDpiAwarenessContext(C.c_void_p(-4))
            header = BitmapHeader(C.sizeof(BitmapHeader), self.width, -self.height, 1, 24)
            self.surface = Image.new("RGB", (self.width, self.height), "black")
            self.surface.paste(self.image, (0, 0))
            self.bits = self.surface.tobytes("raw", "BGR")
            hwnd = U.CreateWindowExW(
                8,
                "STATIC",
                "League screenshot research viewer",
                0x90000100,
                self.left,
                self.top,
                self.width,
                self.height,
                None,
                None,
                K.GetModuleHandleW(None),
                None,
            )
            if not hwnd:
                raise C.WinError(C.get_last_error())
            self.hwnd = hwnd

            def repaint():
                self.bits = self.surface.tobytes("raw", "BGR")
                U.InvalidateRect(hwnd, None, False)
                U.UpdateWindow(hwnd)

            def procedure(window, message, wparam, lparam):
                try:
                    if message == 0x8001:
                        self.events = []
                        self.surface = Image.new("RGB", (self.width, self.height), "black")
                        self.surface.paste(self.image, (0, 0))
                        repaint()
                        U.SetForegroundWindow(hwnd)
                        U.SetFocus(hwnd)
                        return 0
                    if message == 0xF:
                        paint = Paint()
                        dc = U.BeginPaint(window, C.byref(paint))
                        try:
                            if not G.SetDIBitsToDevice(
                                dc,
                                0,
                                0,
                                self.width,
                                self.height,
                                0,
                                0,
                                0,
                                self.height,
                                self.bits,
                                C.byref(header),
                                0,
                            ):
                                raise RuntimeError("Screenshot paint failed")
                        finally:
                            U.EndPaint(window, C.byref(paint))
                        return 0
                    if message == 0x14:
                        return 1
                    if message == 0x84:
                        return 1
                    if message in {0x201, 0x202, 0x203, 0x204, 0x205, 0x206}:
                        x = C.c_short(lparam & 0xFFFF).value + self.left
                        y = C.c_short((lparam >> 16) & 0xFFFF).value + self.top
                        self.events.append(
                            {
                                "kind": "mouse",
                                "message": message,
                                "x": x,
                                "y": y,
                                "received_ns": time.perf_counter_ns(),
                            }
                        )
                    if message in {0x100, 0x101}:
                        cursor = W.POINT()
                        U.GetCursorPos(C.byref(cursor))
                        self.events.append(
                            {
                                "kind": "key",
                                "message": message,
                                "vk": int(wparam),
                                "x": cursor.x,
                                "y": cursor.y,
                                "received_ns": time.perf_counter_ns(),
                            }
                        )
                    if message in {0x202, 0x205, 0x101}:
                        self.surface.paste(RECEIPT, (0, 540, self.width, self.height))
                        repaint()
                        return 0
                    if message in {0x201, 0x203, 0x204, 0x206, 0x100}:
                        return 0
                except BaseException as error:
                    self.failure = error
                    return 0
                return U.CallWindowProcW(original, window, message, wparam, lparam)

            self._callback = WNDPROC(procedure)
            original = U.SetWindowLongPtrW(hwnd, -4, C.cast(self._callback, C.c_void_p))
            if not original:
                raise C.WinError(C.get_last_error())
            U.SetForegroundWindow(hwnd)
            U.SetFocus(hwnd)
            U.InvalidateRect(hwnd, None, False)
            U.UpdateWindow(hwnd)
            self.ready.set()
            message = W.MSG()
            while U.GetMessageW(C.byref(message), None, 0, 0) > 0:
                U.TranslateMessage(C.byref(message))
                U.DispatchMessageW(C.byref(message))
        except BaseException as error:
            self.failure = error
            self.ready.set()
        finally:
            if hwnd:
                if original:
                    U.SetWindowLongPtrW(hwnd, -4, original)
                U.DestroyWindow(hwnd)

    def close(self):
        if self.thread.is_alive():
            U.PostThreadMessageW(self.thread_id, 0x12, 0, 0)
            self.thread.join(5)
        if self.thread.is_alive():
            raise RuntimeError("Screenshot viewer failed to stop")
