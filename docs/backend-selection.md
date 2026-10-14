# Backend selection

The adapter uses [PyDirectInput RGX 2.1.3.1](https://pypi.org/project/pydirectinput-rgx/2.1.3.1/), the maintained MIT-licensed fork of PyDirectInput. Its scan-code catalog, extended key support, UTF-16 input, virtual desktop coordinates, and mouse buttons cover the bulk of the requirements. The upstream repository includes Windows test utilities, but those do not substitute for this project's acceptance tests.

PyAutoGUI's primary-monitor focus and the original PyDirectInput's narrower key and mouse feature set make them less suitable for this adapter. Pynput is useful for general desktop automation, but the scan-code and pixel-position facilities needed here are already present in RGX.

The Windows backend reuses RGX's ABI structures, scan-code map, coordinate conversion, and movement implementation. A small version-pinned bridge adds arbitrary virtual keys, checked SendInput return counts, adapter-owned cleanup, and physical-pixel coordinates under per-thread DPI awareness. It temporarily wraps RGX's private input submission function under a process-wide lock, restoring it after every operation. Changes to the pinned dependency require rerunning Windows acceptance.

The input adapter exclusively owns its backend's calls. Do not call RGX concurrently outside the adapter in the same process: its configuration and input submission function are module globals. Multiple adapter objects also cannot establish ownership of the same Windows key independently; use one adapter per desktop and route producers through it.

Named keys identify physical positions on a US QWERTY keyboard. Use explicit Shift chords for shifted symbols, Unicode text for layout-independent characters, and raw virtual keys for layout-sensitive Windows keys or codes outside the named catalog. The Pause E1 sequence and PrintScreen are sent as virtual keys rather than treating them as ordinary extended scan codes.

Mouse movement uses the entire Windows virtual desktop. The pointer position and target coordinates are physical pixels, including monitors with negative offsets. The RGX corner fail-safe is disabled because corners are valid requested targets; the adapter instead exposes release-all and structured context-manager cleanup. This does not protect against a process being forcibly terminated before cleanup.

Ordinary injected input is subject to [Windows input restrictions](https://learn.microsoft.com/en-us/windows/win32/api/winuser/nf-winuser-sendinput). Firmware-only Fn keys and secure attention sequences are not regular Windows key events. The adapter does not install drivers, change application input policy, or alter Windows security policy.
