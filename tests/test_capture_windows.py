"""Native pixel fidelity and a screenshot -> input -> screenshot feedback loop."""

import json
import os
import platform
import sys
import time
from importlib.metadata import version
from pathlib import Path
from statistics import mean, median

import pytest
from PIL import Image

from league_capture import FrameStream, ScreenCapture, TrajectoryRecorder
from league_input import InputAdapter

pytestmark = [
    pytest.mark.windows,
    pytest.mark.skipif(
        sys.platform != "win32" or os.environ.get("LEAGUE_INPUT_NATIVE_TESTS") != "1",
        reason="Requires opt-in on a disposable Windows interactive desktop",
    ),
]


@pytest.fixture(scope="module")
def scene():
    from windows_visual_scene import VisualScene

    witness = VisualScene().start()
    try:
        yield witness
    finally:
        witness.close()


def locate(frame, color):
    # Deliberately inspect only screenshot pixels, not the witness's target positions.
    image = Image.frombytes("RGB", (frame.width, frame.height), frame.rgb)
    found = [
        (i % frame.width, i // frame.width)
        for i, pixel in enumerate(image.getdata())
        if pixel == color
    ]
    if not found:
        return None
    return (
        (min(x for x, _ in found) + max(x for x, _ in found)) // 2,
        (min(y for _, y in found) + max(y for _, y in found)) // 2,
    )


def wait_for(capture, *, monitor, color, timeout=4):
    deadline = time.perf_counter() + timeout
    while time.perf_counter() < deadline:
        raw = capture.grab(monitor=monitor)
        view = raw.resize(640, 360)
        position = locate(view, color)
        if position is not None:
            return raw, view, position
        time.sleep(0.02)
    raise AssertionError(f"Native scene color {color} did not reach captured pixels")


def evidence_directory():
    return Path(os.environ.get("LEAGUE_CAPTURE_EVIDENCE", "artifacts/capture"))


def test_native_pixels_roundtrip_and_visual_click_on_every_monitor(scene):
    from windows_visual_scene import ACCEPTED, BACKGROUND, TARGET

    root = evidence_directory()
    root.mkdir(parents=True, exist_ok=True)
    reports = []
    with ScreenCapture() as capture, InputAdapter() as adapter:
        monitors = capture.monitors()
        for index, monitor in enumerate(monitors, 1):
            before, view, point = wait_for(capture, monitor=index, color=TARGET)
            assert before.pixel(5, 5) == BACKGROUND  # Detect RGB/BGR swaps and incorrect offsets.
            native_point = view.to_desktop(*point)
            assert monitor.contains(*native_point)
            episode = root / f"monitor-{index}-{before.capture_id}"
            with TrajectoryRecorder(episode) as recorder:
                recorder.record_frame(before)
                recorder.run_action(
                    adapter,
                    view,
                    {"action": "click", "x": native_point[0], "y": native_point[1]},
                    max_age=3,
                )
                after, _, _ = wait_for(capture, monitor=index, color=ACCEPTED)
                recorder.record_frame(after)
            assert native_point in scene.clicks  # Independent application receipt.
            assert locate(after, TARGET) is None
            reports.append(
                {
                    "monitor": index,
                    "episode": episode.name,
                    "region": before.metadata()["region"],
                    "clicked": native_point,
                    "before": before.metadata(),
                    "after": after.metadata(),
                    "application_received": True,
                }
            )
    (root / "visual-loop.json").write_text(
        json.dumps(
            {
                "windows": platform.platform(),
                "python": sys.version,
                "mss": version("mss"),
                "pillow": version("Pillow"),
                "reports": reports,
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )


def test_native_twenty_hz_capture_stream_measures_its_actual_rate(scene):
    samples = []
    with FrameStream(fps=20, monitor=0, history=4) as stream:
        deadline = time.perf_counter() + 2
        previous = -1
        while time.perf_counter() < deadline:
            frame = stream.next(after_sequence=previous)
            assert frame.sequence > previous
            assert frame.finished_ns >= frame.started_ns
            previous = frame.sequence
            samples.append(frame)
        assert len(stream.recent()) <= 4
    assert len(samples) >= 2
    elapsed = (samples[-1].finished_ns - samples[0].finished_ns) / 1e9
    latencies = sorted((f.finished_ns - f.started_ns) / 1e6 for f in samples)
    result = {
        "target_hz": 20,
        "observations": len(samples),
        "observed_hz": (len(samples) - 1) / elapsed,
        "capture_ms": {
            "mean": mean(latencies),
            "median": median(latencies),
            "p95": latencies[min(len(latencies) - 1, int(len(latencies) * 0.95))],
        },
        "geometry": samples[0].metadata(),
        "includes_model_inference": False,
    }
    root = evidence_directory()
    root.mkdir(parents=True, exist_ok=True)
    (root / "benchmark.json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
