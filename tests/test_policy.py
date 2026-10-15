import time
from dataclasses import replace

import pytest

from league_capture import Frame, Region, StaleFrameError
from league_policy import Decision, VisualPolicy, act
from league_policy.playground import make_scene


def frame_for(scene):
    region = Region(-500, -100, 384, 256)
    now = time.perf_counter_ns()
    return Frame("test", "view", 0, region, 384, 256, scene.image.tobytes(), now, now, (region,))


class Clicks:
    def __init__(self):
        self.points = []

    def click(self, *point):
        self.points.append(point)


def test_packaged_checkpoint_generalizes_on_seed_disjoint_scenes():
    policy = VisualPolicy()
    correct, absent_clicks = 0, 0
    for index in range(40):
        scene = make_scene(index, split="validation", condition="combined")
        frame = frame_for(scene)
        decision = policy.predict(frame)
        point = None if decision.point is None else decision.view.to_desktop(*decision.point)
        local = (
            None if point is None else (point[0] - frame.region.left, point[1] - frame.region.top)
        )
        correct += scene.hit(local)
        absent_clicks += scene.target is None and point is not None
    assert correct >= 36
    assert absent_clicks <= 1


def test_stale_observation_never_calls_model_or_input():
    class MustNotRun:
        def predict(self, frame):
            raise AssertionError("stale frame reached inference")

    frame = replace(frame_for(make_scene(0)), started_ns=0, finished_ns=0)
    adapter = Clicks()
    with pytest.raises(StaleFrameError):
        act(adapter, frame, MustNotRun())
    assert not adapter.points


def test_inference_overrun_prevents_input():
    frame = frame_for(make_scene(0))

    class Slow:
        def predict(self, original):
            time.sleep(0.02)
            now = time.perf_counter_ns()
            return Decision(original, (20, 20), 0.9, now, now, now)

    adapter = Clicks()
    with pytest.raises(StaleFrameError):
        act(adapter, frame, Slow(), max_age=0.01)
    assert not adapter.points


def test_absent_target_abstains_and_valid_prediction_maps_to_negative_desktop():
    policy = VisualPolicy()
    adapter = Clicks()
    empty = make_scene(7, split="validation", present=False)
    _, point, _ = act(adapter, frame_for(empty), policy, max_age=2)
    assert point is None and not adapter.points
    scene = make_scene(7, split="validation", present=True)
    frame = frame_for(scene)
    _, point, _ = act(adapter, frame, policy, max_age=2)
    assert point is not None and point[0] < 0
    assert scene.hit((point[0] - frame.region.left, point[1] - frame.region.top))
    assert adapter.points == [point]
