"""Native mechanics for the research viewer; live VLM benchmark is a separate run."""

import json
import os
import sys
import time
from pathlib import Path

import pytest
from PIL import Image

from league_capture import Region, ScreenCapture
from league_input import InputAdapter
from league_input.cli import execute
from league_policy.screenshot_policy import input_plan, parse_decision

pytestmark = [
    pytest.mark.windows,
    pytest.mark.skipif(
        sys.platform != "win32" or os.environ.get("LEAGUE_INPUT_NATIVE_TESTS") != "1",
        reason="Requires opt-in on a disposable Windows interactive desktop",
    ),
]


def test_static_viewer_witnesses_buttons_and_keys_without_changing_model_pixels():
    from windows_screenshot_viewer import RECEIPT, ScreenshotViewer

    image = Image.new("RGB", (960, 540), (11, 22, 33))
    viewer = ScreenshotViewer().start()
    try:
        with ScreenCapture() as capture, InputAdapter() as adapter:
            for action, key in [("move", None), ("close_overlay", None), ("cast", "q")]:
                viewer.present(image)
                time.sleep(0.05)
                frame = capture.grab(region=Region(32, 32, 960, 540))
                assert frame.rgb == image.tobytes()
                decision = parse_decision(
                    json.dumps(
                        {
                            "screen_state": "playing",
                            "health": "healthy",
                            "action": action,
                            "key": key,
                            "target": [500, 500] if action in {"move", "cast"} else None,
                            "confidence": 0.9,
                            "reason": "Synthetic transport acceptance only.",
                        }
                    )
                )
                for command in input_plan(decision, frame):
                    execute(adapter, command)
                deadline = time.perf_counter() + 2
                while time.perf_counter() < deadline:
                    after = capture.grab(region=Region(32, 32, 960, 576))
                    if after.pixel(5, 550) == RECEIPT:
                        break
                assert after.pixel(5, 550) == RECEIPT
                assert capture.grab(region=Region(32, 32, 960, 540)).rgb == frame.rgb
                if action == "move":
                    assert any(
                        e["message"] == 0x205 and e["x"] == 512 and e["y"] == 302
                        for e in viewer.events
                    )
                else:
                    vk = 0x1B if action == "close_overlay" else ord("Q")
                    assert any(e["message"] == 0x101 and e.get("vk") == vk for e in viewer.events)
    finally:
        viewer.close()


def test_static_viewer_records_rapid_clicks_and_double_click_messages():
    from windows_screenshot_viewer import ScreenshotViewer

    viewer = ScreenshotViewer().start()
    report = {}
    try:
        with InputAdapter() as adapter:
            for button, down, up, double in [
                ("left", 0x201, 0x202, 0x203),
                ("right", 0x204, 0x205, 0x206),
            ]:
                viewer.present(Image.new("RGB", (960, 540), (11, 22, 33)))
                adapter.click(512, 302, button=button, count=3, interval=0.01)
                deadline = time.perf_counter() + 2
                while len(viewer.events) < 6 and time.perf_counter() < deadline:
                    time.sleep(0.01)
                events = list(viewer.events)
                report[button] = events
                assert len(events) == 6
                assert sum(e["message"] == up for e in events) == 3
                assert sum(e["message"] in {down, double} for e in events) == 3
                assert any(e["message"] == double for e in events)
    finally:
        viewer.close()
        root = Path(os.environ.get("LEAGUE_POLICY_EVIDENCE", "artifacts/policy"))
        root.mkdir(parents=True, exist_ok=True)
        (root / "screenshot-viewer-doubleclick.json").write_text(
            json.dumps(report, indent=2) + "\n"
        )
