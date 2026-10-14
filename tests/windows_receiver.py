"""Independent Win32 witness: native hooks plus a real Unicode EDIT window.

This deliberately does not import the adapter or its input library. Run on a
disposable desktop: the topmost receiver covers the virtual desktop during tests.
"""

import ctypes as C
import sys
import threading
import time
from ctypes import wintypes as W

if sys.platform != "win32":
    raise RuntimeError("The independent receiver runs on Windows only")

U = C.WinDLL("user32", use_last_error=True)
K = C.WinDLL("kernel32", use_last_error=True)
LRESULT = C.c_ssize_t
PROC = C.WINFUNCTYPE(LRESULT, C.c_int, W.WPARAM, W.LPARAM)
WNDPROC = C.WINFUNCTYPE(LRESULT, W.HWND, W.UINT, W.WPARAM, W.LPARAM)


class KeyboardEvent(C.Structure):
    _fields_ = [
        ("vk", W.DWORD),
        ("scan", W.DWORD),
        ("flags", W.DWORD),
        ("time", W.DWORD),
        ("extra", C.c_size_t),
    ]


class MouseEvent(C.Structure):
    _fields_ = [
        ("point", W.POINT),
        ("data", W.DWORD),
        ("flags", W.DWORD),
        ("time", W.DWORD),
        ("extra", C.c_size_t),
    ]


def signature(dll, name, args, result):
    fn = getattr(dll, name)
    fn.argtypes, fn.restype = args, result
    return fn


signature(U, "SetWindowsHookExW", [C.c_int, PROC, W.HINSTANCE, W.DWORD], C.c_void_p)
signature(U, "CallNextHookEx", [C.c_void_p, C.c_int, W.WPARAM, W.LPARAM], LRESULT)
signature(U, "UnhookWindowsHookEx", [C.c_void_p], W.BOOL)
signature(U, "GetMessageW", [C.POINTER(W.MSG), W.HWND, W.UINT, W.UINT], W.BOOL)
signature(U, "TranslateMessage", [C.POINTER(W.MSG)], W.BOOL)
signature(U, "DispatchMessageW", [C.POINTER(W.MSG)], LRESULT)
signature(U, "PostThreadMessageW", [W.DWORD, W.UINT, W.WPARAM, W.LPARAM], W.BOOL)
signature(
    U,
    "CreateWindowExW",
    [
        W.DWORD,
        W.LPCWSTR,
        W.LPCWSTR,
        W.DWORD,
        C.c_int,
        C.c_int,
        C.c_int,
        C.c_int,
        W.HWND,
        W.HMENU,
        W.HINSTANCE,
        C.c_void_p,
    ],
    W.HWND,
)
signature(U, "SetWindowLongPtrW", [W.HWND, C.c_int, C.c_void_p], C.c_void_p)
signature(U, "CallWindowProcW", [C.c_void_p, W.HWND, W.UINT, W.WPARAM, W.LPARAM], LRESULT)
signature(U, "SetForegroundWindow", [W.HWND], W.BOOL)
signature(U, "SetFocus", [W.HWND], W.HWND)
signature(U, "GetWindowTextW", [W.HWND, W.LPWSTR, C.c_int], C.c_int)
signature(U, "SetWindowTextW", [W.HWND, W.LPCWSTR], W.BOOL)
signature(U, "DestroyWindow", [W.HWND], W.BOOL)
signature(U, "SetThreadDpiAwarenessContext", [C.c_void_p], C.c_void_p)
signature(K, "GetModuleHandleW", [W.LPCWSTR], W.HMODULE)
signature(K, "GetCurrentThreadId", [], W.DWORD)


class Receiver:
    def __init__(self):
        self.events = []
        self.window_events = []
        self.block_keys = True
        self.ready = threading.Event()
        self.failure = None
        self.hwnd = None
        self.thread = threading.Thread(target=self._run, daemon=True)

    def start(self):
        self.thread.start()
        if not self.ready.wait(10):
            raise RuntimeError("Win32 receiver did not initialize")
        if self.failure:
            raise self.failure
        time.sleep(0.1)
        return self

    def _run(self):
        hooks = []
        original_proc = None
        try:
            self.thread_id = K.GetCurrentThreadId()
            U.SetThreadDpiAwarenessContext(C.c_void_p(-4))
            left, top = U.GetSystemMetrics(76), U.GetSystemMetrics(77)
            width, height = U.GetSystemMetrics(78), U.GetSystemMetrics(79)
            self.geometry = dict(left=left, top=top, width=width, height=height)
            self.hwnd = U.CreateWindowExW(
                8,
                "EDIT",
                "",
                0x90000000 | 4 | 0x40,
                left,
                top,
                width,
                height,
                None,
                None,
                K.GetModuleHandleW(None),
                None,
            )
            if not self.hwnd:
                raise C.WinError(C.get_last_error())

            def window_proc(hwnd, message, wparam, lparam):
                if message in {
                    0x100,
                    0x101,
                    0x102,
                    0x104,
                    0x105,
                    0x201,
                    0x202,
                    0x204,
                    0x205,
                    0x207,
                    0x208,
                    0x20B,
                    0x20C,
                }:
                    self.window_events.append(dict(message=message, wparam=int(wparam)))
                if message == 0x7B:  # Suppress the EDIT context menu, not button delivery.
                    return 0
                return U.CallWindowProcW(original_proc, hwnd, message, wparam, lparam)

            self._wnd_callback = WNDPROC(window_proc)
            original_proc = U.SetWindowLongPtrW(
                self.hwnd, -4, C.cast(self._wnd_callback, C.c_void_p)
            )
            if not original_proc:
                raise C.WinError(C.get_last_error())

            def keyboard(code, message, pointer):
                if code >= 0:
                    data = C.cast(pointer, C.POINTER(KeyboardEvent)).contents
                    if data.flags & 0x10:  # Record only adapter-generated injected events.
                        self.events.append(
                            dict(
                                kind="key",
                                message=int(message),
                                vk=int(data.vk),
                                scan=int(data.scan),
                                flags=int(data.flags),
                            )
                        )
                        if self.block_keys:
                            return 1
                return U.CallNextHookEx(None, code, message, pointer)

            def mouse(code, message, pointer):
                if code >= 0:
                    data = C.cast(pointer, C.POINTER(MouseEvent)).contents
                    if data.flags & 1:
                        self.events.append(
                            dict(
                                kind="mouse",
                                message=int(message),
                                x=int(data.point.x),
                                y=int(data.point.y),
                                data=int(data.data),
                                flags=int(data.flags),
                            )
                        )
                return U.CallNextHookEx(None, code, message, pointer)

            self._key_callback, self._mouse_callback = PROC(keyboard), PROC(mouse)
            for kind, callback in ((13, self._key_callback), (14, self._mouse_callback)):
                handle = U.SetWindowsHookExW(kind, callback, K.GetModuleHandleW(None), 0)
                if not handle:
                    raise C.WinError(C.get_last_error())
                hooks.append(handle)
            U.SetForegroundWindow(self.hwnd)
            U.SetFocus(self.hwnd)
            self.ready.set()
            message = W.MSG()
            while U.GetMessageW(C.byref(message), None, 0, 0) > 0:
                U.TranslateMessage(C.byref(message))
                U.DispatchMessageW(C.byref(message))
        except BaseException as error:
            self.failure = error
            self.ready.set()
        finally:
            for hook in hooks:
                U.UnhookWindowsHookEx(hook)
            if self.hwnd:
                if original_proc:
                    U.SetWindowLongPtrW(self.hwnd, -4, original_proc)
                U.DestroyWindow(self.hwnd)

    def wait(self, predicate, timeout=3):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if self.failure:
                raise self.failure
            if predicate():
                return
            time.sleep(0.01)
        raise AssertionError(
            f"No expected received event within {timeout}s; tail={self.events[-12:]}"
        )

    def clear(self):
        time.sleep(0.05)
        self.events.clear()
        self.window_events.clear()

    def text(self):
        buffer = C.create_unicode_buffer(4096)
        U.GetWindowTextW(self.hwnd, buffer, len(buffer))
        return buffer.value

    def clear_text(self):
        U.SetWindowTextW(self.hwnd, "")

    def stop(self):
        if self.thread.is_alive():
            U.PostThreadMessageW(self.thread_id, 0x12, 0, 0)
            self.thread.join(5)
        if self.thread.is_alive():
            raise RuntimeError("Windows receiver failed to stop")
