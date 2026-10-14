"""Independent native GDI scene: clicks turn painted red targets green.

No capture or input adapter is imported here. The test policy locates targets
from captured pixels; expected target coordinates stay inside this witness.
"""

import ctypes as C
import threading
from ctypes import wintypes as W

from windows_receiver import WNDPROC, K, U, signature

BACKGROUND = (11, 22, 33)
TARGET = (230, 40, 70)
ACCEPTED = (30, 220, 80)
G = C.WinDLL("gdi32", use_last_error=True)


class Paint(C.Structure):
    _fields_ = [
        ("dc", W.HDC),
        ("erase", W.BOOL),
        ("rect", W.RECT),
        ("restore", W.BOOL),
        ("update", W.BOOL),
        ("reserved", W.BYTE * 32),
    ]


signature(U, "BeginPaint", [W.HWND, C.POINTER(Paint)], W.HDC)
signature(U, "EndPaint", [W.HWND, C.POINTER(Paint)], W.BOOL)
signature(U, "FillRect", [W.HDC, C.POINTER(W.RECT), W.HBRUSH], C.c_int)
signature(U, "InvalidateRect", [W.HWND, C.POINTER(W.RECT), W.BOOL], W.BOOL)
signature(U, "UpdateWindow", [W.HWND], W.BOOL)
signature(G, "CreateSolidBrush", [W.DWORD], W.HBRUSH)
signature(G, "DeleteObject", [W.HANDLE], W.BOOL)


class VisualScene:
    def __init__(self):
        self.ready = threading.Event()
        self.failure = None
        self.clicks = []
        self.thread = threading.Thread(target=self._run, daemon=True)

    def start(self):
        self.thread.start()
        if not self.ready.wait(10):
            raise RuntimeError("Native visual scene did not initialize")
        if self.failure:
            raise self.failure
        return self

    def _run(self):
        hwnd, original, brushes = None, None, []
        try:
            self.thread_id = K.GetCurrentThreadId()
            U.SetThreadDpiAwarenessContext(C.c_void_p(-4))
            self.left, self.top = U.GetSystemMetrics(76), U.GetSystemMetrics(77)
            self.width, self.height = U.GetSystemMetrics(78), U.GetSystemMetrics(79)
            rects = []
            from windows_receiver import MONITORPROC

            def monitor(handle, dc, pointer, data):
                r = pointer.contents
                rects.append((r.left, r.top, r.right, r.bottom))
                return True

            callback = MONITORPROC(monitor)
            U.EnumDisplayMonitors(None, None, callback, 0)
            self.targets = []
            for left, top, right, bottom in rects:
                x, y = (left + right) // 2 - self.left, (top + bottom) // 2 - self.top
                self.targets.append(W.RECT(x - 32, y - 32, x + 32, y + 32))
            accepted = set()
            for color in [BACKGROUND, TARGET, ACCEPTED]:
                brush = G.CreateSolidBrush(color[0] | color[1] << 8 | color[2] << 16)
                if not brush:
                    raise C.WinError(C.get_last_error())
                brushes.append(brush)
            hwnd = U.CreateWindowExW(
                8,
                "STATIC",
                "Visual capture test",
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

            def procedure(window, message, wparam, lparam):
                if message == 0xF:  # WM_PAINT
                    paint = Paint()
                    dc = U.BeginPaint(window, C.byref(paint))
                    whole = W.RECT(0, 0, self.width, self.height)
                    U.FillRect(dc, C.byref(whole), brushes[0])
                    for i, target in enumerate(self.targets):
                        U.FillRect(dc, C.byref(target), brushes[2 if i in accepted else 1])
                    U.EndPaint(window, C.byref(paint))
                    return 0
                if message == 0x14:  # WM_ERASEBKGND
                    return 1
                if message == 0x84:  # WM_NCHITTEST: this native scene owns its pixels.
                    return 1
                if message == 0x202:  # WM_LBUTTONUP
                    x, y = (
                        C.c_short(lparam & 0xFFFF).value,
                        C.c_short((lparam >> 16) & 0xFFFF).value,
                    )
                    for i, rect in enumerate(self.targets):
                        if rect.left <= x < rect.right and rect.top <= y < rect.bottom:
                            accepted.add(i)
                            self.clicks.append((x + self.left, y + self.top))
                            U.InvalidateRect(window, None, False)
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
            for brush in brushes:
                G.DeleteObject(brush)

    def close(self):
        if self.thread.is_alive():
            U.PostThreadMessageW(self.thread_id, 0x12, 0, 0)
            self.thread.join(5)
        if self.thread.is_alive():
            raise RuntimeError("Native visual scene failed to stop")
