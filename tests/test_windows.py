"""Acceptance tests observe Windows events and real application effects.

Opt in on a disposable interactive desktop with LEAGUE_INPUT_NATIVE_TESTS=1.
"""

import itertools
import json
import os
import platform
import sys
import time
from importlib.metadata import version
from pathlib import Path

import pytest

from league_input import Button, InputAdapter, Key

pytestmark = [
    pytest.mark.windows,
    pytest.mark.skipif(
        sys.platform != "win32" or os.environ.get("LEAGUE_INPUT_NATIVE_TESTS") != "1",
        reason="Requires opt-in on a disposable Windows interactive desktop",
    ),
]


@pytest.fixture(scope="module")
def receiver():
    from windows_receiver import Receiver

    witness = Receiver().start()
    reports = []
    witness.reports = reports
    try:
        yield witness
    finally:
        path = Path(os.environ.get("LEAGUE_INPUT_EVIDENCE", "artifacts/windows-input.json"))
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(
                dict(
                    windows=platform.platform(),
                    python=sys.version,
                    library=version("pydirectinput-rgx"),
                    geometry=witness.geometry,
                    observations=reports,
                ),
                indent=2,
            ),
            encoding="utf-8",
        )
        witness.stop()


@pytest.fixture
def native(receiver):
    receiver.block_keys = True
    receiver.clear()
    with InputAdapter() as adapter:
        yield adapter
    time.sleep(0.05)


def record(receiver, name):
    receiver.reports.append(
        dict(
            test=name, events=list(receiver.events), application_events=list(receiver.window_events)
        )
    )


def key_events(receiver):
    return [e for e in receiver.events if e["kind"] == "key"]


def test_all_named_keys_reach_windows(native, receiver):
    # Deduplicate aliases, but test each distinct physical or special key.
    unique = {}
    for name in native.available_keys():
        unique.setdefault(native._backend.resolve(name), name)
    assert len(unique) >= 100
    for key, name in unique.items():
        receiver.clear()
        native.press(name)
        receiver.wait(lambda: len(key_events(receiver)) >= 2)
        observed = key_events(receiver)
        assert observed[0]["message"] in {0x100, 0x104}, (name, observed)
        assert observed[-1]["message"] in {0x101, 0x105}, (name, observed)
        if key.kind == "scan":
            assert observed[0]["scan"] == key.code, (name, observed)
            if key.code == 0x36 and not key.extended:
                # Windows marks VK_RSHIFT extended in the low-level witness,
                # although its physical make code is 0x36 without an E0 prefix.
                assert observed[0]["vk"] == 0xA1, (name, observed)
            else:
                assert bool(observed[0]["flags"] & 1) == key.extended, (name, observed)
        else:
            assert observed[0]["vk"] == key.code, (name, observed)
        record(receiver, f"named_key:{name}")


def test_modifier_combinations_reach_windows_in_order(native, receiver):
    modifiers = (
        "ctrlleft",
        "ctrlright",
        "shiftleft",
        "shiftright",
        "altleft",
        "altright",
        "winleft",
        "winright",
    )
    for count in range(1, 4):
        for combination in itertools.combinations(modifiers, count):
            receiver.clear()
            native.hotkey(*combination, "a")
            expected = count + 1
            receiver.wait(lambda expected=expected: len(key_events(receiver)) >= expected * 2)
            observed = key_events(receiver)
            assert len(observed) == expected * 2, (combination, observed)
            down = [e["scan"] for e in observed[:expected]]
            up = [e["scan"] for e in observed[expected:]]
            assert up == list(reversed(down)), (combination, observed)
            assert all(e["message"] in {0x100, 0x104} for e in observed[:expected])
            assert all(e["message"] in {0x101, 0x105} for e in observed[expected:])
            record(receiver, f"chord:{'+'.join(combination)}+a")


def test_long_chord_has_no_two_key_or_six_key_limit(native, receiver):
    keys = (
        "ctrlleft",
        "ctrlright",
        "shiftleft",
        "shiftright",
        "altleft",
        "altright",
        "winleft",
        "winright",
        "q",
        "w",
        "e",
        "r",
        "t",
        "y",
    )
    native.hotkey(*keys)
    receiver.wait(lambda: len(key_events(receiver)) == len(keys) * 2)
    events = key_events(receiver)
    assert [e["scan"] for e in events[len(keys) :]] == list(
        reversed([e["scan"] for e in events[: len(keys)]])
    )
    record(receiver, "long_chord_14_keys")


@pytest.mark.parametrize(
    "key,vk",
    [
        (Key.vk(0x41), 0x41),
        (Key.vk(0x7B), 0x7B),
        (Key.vk(0x87), 0x87),
        (Key.vk(0xAD), 0xAD),
        (Key.scan(0x1D, extended=True), 0xA3),
    ],
)
def test_raw_key_codes(native, receiver, key, vk):
    native.press(key)
    receiver.wait(lambda: len(key_events(receiver)) >= 2)
    assert key_events(receiver)[0]["vk"] == vk
    record(receiver, f"raw:{key}")


def test_unicode_is_received_by_real_edit_control(native, receiver):
    receiver.block_keys = False
    receiver.clear_text()
    text = "ASCII Șț漢字 😀"
    native.type_text(text, interval=0.01)
    receiver.wait(lambda: receiver.text() == text)
    assert any(e["message"] == 0x102 for e in receiver.window_events)
    record(receiver, "unicode_application_effect")


def test_application_receives_a_key_with_both_modifiers_held(native, receiver):
    receiver.block_keys = False
    native.hotkey("ctrl", "shift", "a", duration=0.01)
    receiver.wait(
        lambda: any(
            e["message"] == 0x100 and e["wparam"] == 0x41 and e["ctrl"] and e["shift"]
            for e in receiver.window_events
        )
    )
    record(receiver, "application_modifier_state")


def test_raw_and_named_modifier_holds_share_ownership(native, receiver):
    with native.hold(Key.vk(0x11)):
        with native.hold("ctrl", "a"):
            pass
        assert native.held_keys == (Key.vk(0x11),)
        native.press("b")
    receiver.wait(lambda: len(key_events(receiver)) == 6)
    events = key_events(receiver)
    assert [e["vk"] for e in events] == [0xA2, 0x41, 0x41, 0x42, 0x42, 0xA2]
    assert [e["message"] for e in events] == [0x100, 0x100, 0x101, 0x100, 0x101, 0x101]
    record(receiver, "mixed_raw_named_modifier_ownership")


def test_absolute_movement_all_desktop_corners(native, receiver):
    d = native.desktop()
    for point in (
        (d.left, d.top),
        (d.right, d.top),
        (d.left, d.bottom),
        (d.right, d.bottom),
        (d.left + d.width // 2, d.top + d.height // 2),
    ):
        native.move_to(*point)
        receiver.wait(lambda point=point: native.position() == point)
        assert native.position() == point
        receiver.clear()
        native.click(*point)
        receiver.wait(
            lambda: any(e["kind"] == "mouse" and e["message"] == 0x202 for e in receiver.events)
        )
        click = next(e for e in receiver.events if e["message"] == 0x201)
        assert (click["x"], click["y"]) == point
        record(receiver, f"corner_click:{point}")
    record(receiver, "absolute_corners")


def test_exact_pixel_delta_and_raw_motion(native, receiver):
    native.move_to(100, 100)
    native.move_by(37, 23)
    receiver.wait(lambda: native.position() == (137, 123))
    receiver.clear()
    native.move_relative(5, -2)
    receiver.wait(
        lambda: any(e["kind"] == "mouse" and e["message"] == 0x200 for e in receiver.events)
    )
    assert native.position() != (137, 123)
    record(receiver, "relative_motion")


def test_native_coordinate_overflow_is_rejected_before_input(native, receiver):
    with pytest.raises(ValueError):
        native.click(2**32 + 100, 100)
    with pytest.raises(ValueError):
        native.move_relative(2**31, 0)
    assert receiver.events == []
    record(receiver, "native_coordinate_overflow_rejected")


@pytest.mark.parametrize(
    "button,down,up",
    [
        (Button.LEFT, 0x201, 0x202),
        (Button.RIGHT, 0x204, 0x205),
        (Button.MIDDLE, 0x207, 0x208),
        (Button.X1, 0x20B, 0x20C),
        (Button.X2, 0x20B, 0x20C),
    ],
)
def test_all_buttons_received_by_windows_and_application(native, receiver, button, down, up):
    native.click(200, 200, button=button)
    receiver.wait(lambda: any(e["kind"] == "mouse" and e["message"] == up for e in receiver.events))
    mouse = [e for e in receiver.events if e["kind"] == "mouse" and e["message"] != 0x200]
    assert [e["message"] for e in mouse] == [down, up]
    if button in {Button.X1, Button.X2}:
        assert mouse[0]["data"] >> 16 == (1 if button == Button.X1 else 2)
    receiver.wait(lambda: any(e["message"] == down for e in receiver.window_events))
    record(receiver, f"button:{button.value}")


def test_both_scroll_axes_and_directions(native, receiver):
    for horizontal, message in ((False, 0x20A), (True, 0x20E)):
        for ticks in (3, -2):
            receiver.clear()
            native.scroll(ticks, horizontal=horizontal)
            receiver.wait(
                lambda message=message: any(
                    e["kind"] == "mouse" and e["message"] == message for e in receiver.events
                )
            )
            event = next(e for e in receiver.events if e["message"] == message)
            delta = (event["data"] >> 16) & 0xFFFF
            if delta >= 32768:
                delta -= 65536
            assert delta == ticks * 120
            record(receiver, f"wheel:{horizontal}:{ticks}")


@pytest.mark.parametrize("horizontal,ticks", [(False, 1000), (True, -1000)])
def test_large_wheel_delta_keeps_its_sign_and_total(native, receiver, horizontal, ticks):
    message = 0x20E if horizontal else 0x20A
    native.scroll(ticks, horizontal=horizontal)
    receiver.wait(lambda: len([e for e in receiver.events if e["message"] == message]) == 4)
    deltas = []
    for e in receiver.events:
        if e["message"] == message:
            raw = (e["data"] >> 16) & 0xFFFF
            deltas.append(raw - 65536 if raw >= 32768 else raw)
    assert sum(deltas) == ticks * 120
    assert all(delta * ticks > 0 for delta in deltas)
    record(receiver, f"large_wheel:{horizontal}:{ticks}")


def test_drag_and_exception_cleanup(native, receiver):
    native.move_to(250, 250)
    native.drag_to(350, 300, duration=0.1)
    receiver.wait(lambda: native.position() == (350, 300))
    buttons = [e["message"] for e in receiver.events if e["message"] in {0x201, 0x202}]
    assert buttons == [0x201, 0x202]
    receiver.clear()
    with pytest.raises(RuntimeError), native.hold("ctrl", buttons=["left"]):
        raise RuntimeError("simulated action cancellation")
    receiver.wait(
        lambda: (
            len(key_events(receiver)) == 2 and any(e["message"] == 0x202 for e in receiver.events)
        )
    )
    assert not native.held_keys and not native.held_buttons
    record(receiver, "drag_and_cleanup")
