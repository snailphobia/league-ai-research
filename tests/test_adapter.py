import io
import math

import pytest

from league_input import Button, Desktop, InputAdapter, InputError, Key, UnsupportedPlatformError
from league_input.cli import run


class RecordingBackend:
    """Test input ownership and ordering independently of Windows."""

    names = {
        "ctrl": Key.scan(29),
        "control": Key.scan(29),
        "shift": Key.scan(42),
        "alt": Key.scan(56),
        "a": Key.scan(30),
        "b": Key.scan(48),
    }

    def __init__(self):
        self.events = []
        self.cursor = (50, 50)
        self.fail_down = None
        self.fail_up = None

    def resolve(self, key):
        if isinstance(key, Key):
            return key
        if key not in self.names:
            raise ValueError("Unknown key")
        return self.names[key]

    def key_event(self, key, down):
        self.events.append(("key", key, down))
        if key == (self.fail_down if down else self.fail_up):
            raise InputError("simulated native rejection")

    def button_event(self, button, down):
        self.events.append(("button", button, down))

    def move_to(self, x, y, duration):
        self.events.append(("move", x, y, duration))
        self.cursor = x, y

    def move_relative(self, dx, dy):
        self.events.append(("relative", dx, dy))

    def scroll(self, ticks, horizontal):
        self.events.append(("scroll", ticks, horizontal))

    def position(self):
        return self.cursor

    def desktop(self):
        return Desktop(-1280, -200, 3200, 1280)

    def contains(self, x, y):
        return self.desktop().contains(x, y)

    def keys(self):
        return tuple(self.names)


@pytest.fixture
def pair():
    backend = RecordingBackend()
    return InputAdapter(backend, sleep=lambda _: None), backend


def test_chord_order_and_reverse_release(pair):
    adapter, backend = pair
    adapter.hotkey("ctrl", "shift", "alt", "a")
    assert backend.events == [
        ("key", backend.names[k], True) for k in ("ctrl", "shift", "alt", "a")
    ] + [("key", backend.names[k], False) for k in ("a", "alt", "shift", "ctrl")]
    assert not adapter.held_keys


def test_whole_chord_validates_before_any_events(pair):
    adapter, backend = pair
    with pytest.raises(ValueError):
        adapter.hotkey("ctrl", "unknown")
    assert backend.events == []


def test_nested_hold_preserves_outer_input_and_alias_identity(pair):
    adapter, backend = pair
    with adapter.hold("ctrl"):
        with adapter.hold("control", "a"):
            assert adapter.held_keys == (backend.names["ctrl"], backend.names["a"])
        assert adapter.held_keys == (backend.names["ctrl"],)
    assert backend.events.count(("key", backend.names["ctrl"], True)) == 1
    assert backend.events.count(("key", backend.names["ctrl"], False)) == 1


def test_partial_chord_failure_releases_all_attempted_keys(pair):
    adapter, backend = pair
    backend.fail_down = backend.names["a"]
    with pytest.raises(InputError):
        adapter.hotkey("ctrl", "a")
    assert backend.events[-2:] == [
        ("key", backend.names["a"], False),
        ("key", backend.names["ctrl"], False),
    ]
    assert not adapter.held_keys


def test_cleanup_continues_after_one_release_fails_and_can_retry(pair):
    adapter, backend = pair
    adapter.key_down("ctrl")
    adapter.key_down("a")
    adapter.mouse_down("left")
    backend.fail_up = backend.names["a"]
    with pytest.raises(ExceptionGroup):
        adapter.release_all()
    assert adapter.held_keys == (backend.names["a"],)
    assert not adapter.held_buttons
    assert backend.events[-1] == ("key", backend.names["ctrl"], False)
    backend.fail_up = None
    adapter.close()
    assert not adapter.held_keys


def test_context_cleanup_after_exception_releases_owned_inputs_only(pair):
    adapter, backend = pair
    with pytest.raises(RuntimeError), adapter:
        adapter.key_down("ctrl")
        adapter.mouse_down("x2")
        raise RuntimeError("interrupted action")
    assert backend.events[-2:] == [
        ("button", Button.X2, False),
        ("key", backend.names["ctrl"], False),
    ]
    with pytest.raises(InputError):
        adapter.key_down("a")


def test_unicode_preserves_utf16_surrogate_order_and_releases(pair):
    adapter, backend = pair
    adapter.type_text("Ș😀")
    downs = [event[1].code for event in backend.events if event[2] is True]
    assert downs == [0x218, 0xD83D, 0xDE00]
    assert not adapter.held_keys


def test_invalid_unicode_validates_entire_string_before_emitting(pair):
    adapter, backend = pair
    with pytest.raises(UnicodeEncodeError):
        adapter.type_text("valid\ud800")
    assert backend.events == []


@pytest.mark.parametrize("value", [-1, math.inf, math.nan, True, "0"])
def test_invalid_timing_never_emits_input(pair, value):
    adapter, backend = pair
    with pytest.raises(ValueError):
        adapter.hotkey("ctrl", "a", duration=value)
    assert backend.events == []


@pytest.mark.parametrize("point", [(-1280, -200), (1919, 1079), (0, 0)])
def test_monitor_corners_and_negative_coordinates(pair, point):
    adapter, backend = pair
    adapter.click(*point, button="x1")
    assert backend.events[0] == ("move", *point, 0.0)
    assert backend.events[1:] == [("button", Button.X1, True), ("button", Button.X1, False)]


def test_invalid_target_does_not_press_drag_button(pair):
    adapter, backend = pair
    with pytest.raises(ValueError):
        adapter.drag_to(5000, 20)
    assert backend.events == []


def test_pixel_delta_and_raw_relative_input_have_distinct_contracts(pair):
    adapter, backend = pair
    adapter.move_by(-60, 20)
    adapter.move_relative(4, -3)
    assert backend.events == [("move", -10, 70, 0.0), ("relative", 4, -3)]


def test_repeated_clicks_and_both_wheel_axes(pair):
    adapter, backend = pair
    adapter.click(count=2, button="middle")
    adapter.scroll(-3)
    adapter.scroll(2, horizontal=True)
    assert backend.events == [
        ("button", Button.MIDDLE, True),
        ("button", Button.MIDDLE, False),
    ] * 2 + [("scroll", -3, False), ("scroll", 2, True)]


def test_tapping_owned_key_does_not_release_it(pair):
    adapter, backend = pair
    adapter.key_down("ctrl")
    with pytest.raises(InputError):
        adapter.press("control")
    assert adapter.held_keys == (backend.names["ctrl"],)


def test_jsonl_raw_keys_and_cleanup_at_eof(pair):
    adapter, backend = pair
    stream = io.StringIO(
        '{"action":"key_down","key":{"kind":"vk","code":65}}\n{"action":"move_to","x":-10,"y":50}\n'
    )
    output, errors = io.StringIO(), io.StringIO()
    assert run(stream, output, errors, factory=lambda: adapter) == 0
    assert not errors.getvalue()
    assert backend.events[-1] == ("key", Key.vk(65), False)
    assert len(output.getvalue().splitlines()) == 2


def test_jsonl_error_releases_previous_held_input(pair):
    adapter, backend = pair
    stream = io.StringIO('{"action":"key_down","key":"ctrl"}\n{"action":"unknown"}\n')
    assert run(stream, io.StringIO(), io.StringIO(), factory=lambda: adapter) == 2
    assert backend.events[-1] == ("key", backend.names["ctrl"], False)


def test_native_initialization_is_lazy_on_other_platforms():
    import sys

    if sys.platform != "win32":
        with pytest.raises(UnsupportedPlatformError):
            InputAdapter()
