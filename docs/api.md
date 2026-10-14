# Input API

Importing league_input is safe on another platform. Constructing the default InputAdapter requires Windows 10 or newer and an interactive desktop. A custom backend can be injected for portable orchestration tests.

| Method | Behavior |
| --- | --- |
| available_keys() | List named keys and aliases supported by the backend |
| key_down(key), key_up(key) | Hold/release an adapter-owned key; repeats are idempotent |
| hold(*keys, buttons=()) | Context manager; press in order and release new acquisitions in reverse |
| hotkey(*keys, duration=0) | Arbitrary ordered chord, with bounded hold duration |
| press(key, count=1, interval=0, duration=0) | Repeated complete key taps |
| type_text(text, interval=0) | Layout-independent UTF-16 input, including surrogate pairs |
| desktop(), position() | Virtual desktop bounds and current physical-pixel pointer coordinates |
| move_to(x, y, duration=0) | Absolute movement on any attached monitor |
| move_by(dx, dy, duration=0) | Exact pixel offset from current pointer position |
| move_relative(dx, dy) | Native relative counts; Windows acceleration can affect displacement |
| mouse_down(button), mouse_up(button) | Hold/release left, right, middle, X1, or X2 |
| click(x=None, y=None, button='left', count=1, interval=0, duration=0) | Optional movement followed by complete button clicks |
| drag_to(x, y, button='left', duration=0.25) | Hold a button while moving to a target |
| scroll(ticks, horizontal=False) | Signed wheel ticks; one tick is 120 Windows wheel units |
| release_all(), close() | Release only owned input; close makes the adapter unusable |

All timing values are seconds. Coordinates and wheel ticks are integers. Validate a full chord before emitting its first key. Negative coordinates are valid when a monitor occupies that part of the virtual desktop; gaps between monitors are not target pixels. Invalid points are rejected before a drag or click starts.

Keys may be named strings, Key.scan(code, extended=False), or Key.vk(code, extended=False). Scan codes are 1..255, with the extended flag for E0-prefixed keys. Windows virtual-key codes are 1..254; unassigned codes do not create nonexistent hardware functionality. Uppercase letters identify the same physical key as lowercase letters. Use explicit modifiers for key combinations and type_text for Unicode text.

Hold contexts preserve keys/buttons already owned by an outer context. Tapping a key or button already held is rejected instead of silently releasing it. Windows virtual keys are mapped to physical scan-code identities for ownership, so equivalent named/raw representations share a hold. Release uses the original event channel and retains an exact descriptor's identity across a calling-thread layout change. Named physical keys remain based on US QWERTY positions; Unicode text is the layout-independent text interface.

Input errors preserve uncertain ownership until a release succeeds, so cleanup can be retried. Cleanup attempts every owned release even when an earlier release fails, and reports failures as an ExceptionGroup. Use a with block or explicit try/finally. Forcibly killing the process prevents Python cleanup.

The JSON Lines CLI exposes the same methods. Each line is an object with an action field and that method's arguments. Hotkeys use a keys list. A raw key is an object with kind, code, and an optional extended boolean:

```json
{"action":"hotkey","keys":["ctrl",{"kind":"vk","code":65}],"duration":0.05}
```

One process keeps held input across lines and releases it at EOF or the first error. Each command is validated before its own execution. Output reports submitted input, not application acceptance; queries additionally return their values. An error is written to stderr with a nonzero exit code.

Ctrl+Alt+Delete, the secure desktop, and higher-integrity targets are governed by separate Windows facilities. Application-specific acceptance must be checked on that application's actual input path. This adapter provides ordinary operating system input, not guarantees about games or anti-cheat systems.
