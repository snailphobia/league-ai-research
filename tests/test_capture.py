import io
import json
import sys
import threading
import time
from dataclasses import replace

import pytest
from PIL import Image

from league_capture import (
    CaptureError,
    FrameStream,
    Region,
    ScreenCapture,
    StaleFrameError,
    TrajectoryRecorder,
)


class Pixels:
    def __init__(self, monitors=None):
        self.geometry = (Region(-4, -2, 4, 4), Region(0, 0, 4, 4)) if monitors is None else monitors
        self.grabs = []
        self.closed = False

    def monitors(self):
        return self.geometry

    def grab(self, region):
        self.grabs.append(region)
        return bytes([11, 22, 33]) * (region.width * region.height)

    def close(self):
        self.closed = True


def observation():
    with ScreenCapture(Pixels()) as capture:
        return capture.grab(monitor=0)


def test_native_rgb_geometry_clock_and_snapshot_are_preserved():
    pixels = Pixels()
    ticks = iter([100, 200, 300, 400])
    with ScreenCapture(pixels, clock=lambda: next(ticks)) as capture:
        first, second = capture.grab(monitor=0), capture.grab(monitor=1)
    assert first.region == Region(-4, -2, 8, 6)
    assert first.pixel(0, 0) == (11, 22, 33)
    assert (first.started_ns, first.finished_ns) == (100, 200)
    assert first.capture_id != second.capture_id
    assert (first.sequence, second.sequence) == (0, 1)
    assert pixels.closed
    assert Image.open(io.BytesIO(first.png())).getpixel((0, 0)) == (11, 22, 33)


def test_resized_view_retains_source_coordinates_and_capture_identity():
    frame = observation()
    view = frame.resize(4, 3)
    assert (view.width, view.height) == (4, 3)
    assert view.capture_id == frame.capture_id and view.view_id != frame.view_id
    assert view.region == frame.region and view.started_ns == frame.started_ns
    assert view.to_desktop(0, 0) == (-3, -1)
    assert view.to_desktop(3, 2) == (3, 3)
    with pytest.raises(ValueError, match="gap"):
        view.to_desktop(0, 2)
    assert frame.resize(100, 100) is frame


@pytest.mark.parametrize("point", [(-1, 0), (8, 0), (0, 6), (True, 0), (0.2, 0)])
def test_image_coordinates_must_be_valid_pixels(point):
    with pytest.raises(ValueError):
        observation().to_desktop(*point)


@pytest.mark.parametrize(
    "kwargs",
    [
        {"monitor": -1},
        {"monitor": 3},
        {"monitor": True},
        {"region": Region(-5, 0, 2, 2)},
        {"region": (0, 0, 2, 2)},
    ],
)
def test_invalid_capture_requests_never_reach_the_backend(kwargs):
    pixels = Pixels()
    with ScreenCapture(pixels) as capture, pytest.raises(ValueError):
        capture.grab(**kwargs)
    assert pixels.grabs == []


def test_capture_refreshes_monitor_geometry_and_rejects_closed_source():
    pixels = Pixels()
    capture = ScreenCapture(pixels)
    capture.grab()
    pixels.geometry = (Region(100, 200, 2, 3),)
    assert capture.grab().region == pixels.geometry[0]
    capture.close()
    capture.close()
    with pytest.raises(CaptureError):
        capture.grab()


def test_frame_age_includes_capture_time():
    frame = replace(observation(), started_ns=1_000_000_000, finished_ns=1_200_000_000)
    assert frame.age(now_ns=1_250_000_000) == 0.25
    frame.require_fresh(0.3, now_ns=1_250_000_000)
    with pytest.raises(StaleFrameError):
        frame.require_fresh(0.1, now_ns=1_250_000_000)


def test_stream_keeps_bounded_history_and_skips_old_observations():
    owners = []

    def factory():
        owners.append(threading.get_ident())
        return ScreenCapture(Pixels())

    with FrameStream(fps=200, history=3, factory=factory) as stream:
        first = stream.next()
        time.sleep(0.04)  # Deliberately model a slower consumer.
        latest = stream.next(after_sequence=first.sequence)
        assert latest.sequence > first.sequence + 1
        assert len(stream.recent()) == 3
        assert owners[0] != threading.get_ident()
        history = stream.recent()
        assert [f.sequence for f in history] == sorted(f.sequence for f in history)
    with pytest.raises(CaptureError):
        stream.next()


def test_capture_failure_is_reported_to_waiting_consumers():
    class Broken(Pixels):
        def grab(self, region):
            raise RuntimeError("capture device lost")

    backend = Broken()
    with FrameStream(factory=lambda: ScreenCapture(backend)) as stream:
        with pytest.raises(CaptureError) as error:
            stream.next()
        assert isinstance(error.value.__cause__, RuntimeError)
    assert backend.closed


class Commands:
    def __init__(self):
        self.events = []

    def click(self, **kwargs):
        self.events.append(kwargs)

    def release_all(self):
        self.events.append("release_all")


def test_trajectory_records_images_and_action_timing(tmp_path):
    frame, commands = observation(), Commands()
    with TrajectoryRecorder(tmp_path) as recorder:
        recorder.run_action(commands, frame, {"action": "click", "x": 1, "y": 2}, max_age=5)
    events = [json.loads(line) for line in (tmp_path / "events.jsonl").read_text().splitlines()]
    assert [e["type"] for e in events] == ["episode", "observation", "action_start", "action_end"]
    assert commands.events == [{"x": 1, "y": 2}]
    assert events[2]["view_id"] == frame.view_id
    assert events[2]["started_ns"] <= events[3]["finished_ns"]
    assert events[3]["status"] == "submitted"
    assert Image.open(tmp_path / events[1]["image"]).size == (frame.width, frame.height)
    with pytest.raises(FileExistsError):
        TrajectoryRecorder(tmp_path)


def test_stale_observation_cannot_emit_an_action_and_releases_held_input(tmp_path):
    frame = replace(observation(), started_ns=0, finished_ns=0)
    commands = Commands()
    with TrajectoryRecorder(tmp_path) as recorder, pytest.raises(StaleFrameError):
        recorder.run_action(commands, frame, {"action": "click", "x": 1, "y": 2})
    assert commands.events == ["release_all"]


def test_recording_delay_does_not_hide_stale_input(tmp_path, monkeypatch):
    frame, commands = observation(), Commands()
    with TrajectoryRecorder(tmp_path) as recorder:
        original = recorder.record_frame

        def slow_record(value):
            original(value)
            time.sleep(0.02)

        monkeypatch.setattr(recorder, "record_frame", slow_record)
        with pytest.raises(StaleFrameError):
            recorder.run_action(commands, frame, {"action": "click"}, max_age=0.01)
    assert commands.events == ["release_all"]


def test_default_capture_is_lazy_and_windows_only():
    if sys.platform != "win32":
        with pytest.raises(CaptureError, match="Windows"):
            ScreenCapture()
