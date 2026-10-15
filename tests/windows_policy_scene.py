"""Independent Win32 application witness for the learned synthetic policy.

It renders supplied images, hit-tests actual WM_LBUTTONUP messages, and paints
completion pixels. It imports neither the input adapter nor the learned policy.
"""

import ctypes as C
import threading
import time
from ctypes import wintypes as W

from windows_receiver import WNDPROC, K, U, signature
from windows_visual_scene import G, Paint


class BitmapHeader(C.Structure):
    _fields_ = [
        ("size", W.DWORD),
        ("width", W.LONG),
        ("height", W.LONG),
        ("planes", W.WORD),
        ("bits", W.WORD),
        ("compression", W.DWORD),
        ("image_size", W.DWORD),
        ("xppm", W.LONG),
        ("yppm", W.LONG),
        ("colors", W.DWORD),
        ("important", W.DWORD),
    ]


signature(
    G,
    "SetDIBitsToDevice",
    [
        W.HDC,
        C.c_int,
        C.c_int,
        W.DWORD,
        W.DWORD,
        C.c_int,
        C.c_int,
        W.UINT,
        W.UINT,
        C.c_void_p,
        C.c_void_p,
        W.UINT,
    ],
    C.c_int,
)
signature(U, "SendMessageW", [W.HWND, W.UINT, W.WPARAM, W.LPARAM], C.c_ssize_t)


class PolicyScene:
    def __init__(self, region, completion):
        self.region = region
        self.completion = completion
        self.ready = threading.Event()
        self.accepted = threading.Event()
        self.failure = None
        self.pending = self.scene = None
        self.clicks = []
        self.thread = threading.Thread(target=self._run, daemon=True)

    def start(self):
        self.thread.start()
        if not self.ready.wait(10):
            raise RuntimeError("Native policy scene did not initialize")
        if self.failure:
            raise self.failure
        return self

    def show(self, scene):
        self.pending = scene
        U.SendMessageW(self.hwnd, 0x8001, 0, 0)
        if self.failure:
            raise self.failure

    def _run(self):
        hwnd, original = None, None
        try:
            self.thread_id = K.GetCurrentThreadId()
            U.SetThreadDpiAwarenessContext(C.c_void_p(-4))
            r = self.region
            header = BitmapHeader(C.sizeof(BitmapHeader), r.width, -r.height, 1, 24)
            self.bits = self.completion.tobytes("raw", "BGR")
            hwnd = U.CreateWindowExW(
                8,
                "STATIC",
                "Synthetic policy playground",
                0x90000100,
                r.left,
                r.top,
                r.width,
                r.height,
                None,
                None,
                K.GetModuleHandleW(None),
                None,
            )
            if not hwnd:
                raise C.WinError(C.get_last_error())
            self.hwnd = hwnd

            def procedure(window, message, wparam, lparam):
                try:
                    if message == 0x8001:
                        self.scene = self.pending
                        self.accepted.clear()
                        self.clicks = []
                        self.received_ns = None
                        self.bits = self.scene.image.tobytes("raw", "BGR")
                        U.InvalidateRect(window, None, False)
                        U.UpdateWindow(window)
                        self.shown_ns = time.perf_counter_ns()
                        return 0
                    if message == 0xF:
                        paint = Paint()
                        dc = U.BeginPaint(window, C.byref(paint))
                        try:
                            result = G.SetDIBitsToDevice(
                                dc,
                                0,
                                0,
                                r.width,
                                r.height,
                                0,
                                0,
                                0,
                                r.height,
                                self.bits,
                                C.byref(header),
                                0,
                            )
                            if not result:
                                raise RuntimeError("Native image paint failed")
                        finally:
                            U.EndPaint(window, C.byref(paint))
                        return 0
                    if message == 0x14:
                        return 1
                    if message == 0x84:
                        return 1
                    if message == 0x202:
                        x = C.c_short(lparam & 0xFFFF).value
                        y = C.c_short((lparam >> 16) & 0xFFFF).value
                        self.clicks.append((x + r.left, y + r.top))
                        if self.scene and self.scene.target and self.scene.hit((x, y)):
                            self.received_ns = time.perf_counter_ns()
                            self.bits = self.completion.tobytes("raw", "BGR")
                            U.InvalidateRect(window, None, False)
                            U.UpdateWindow(window)
                            self.accepted.set()
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
            raise RuntimeError("Native policy scene failed to stop")
