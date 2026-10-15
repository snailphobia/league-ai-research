"""A learned prediction must cause native receipt AND later changed pixels."""

import json
import os
import platform
import sys
import time
from importlib.metadata import version
from pathlib import Path
from statistics import mean

import pytest

from league_capture import Region, ScreenCapture, TrajectoryRecorder
from league_input import InputAdapter
from league_policy import VisualPolicy, act, red_baseline
from league_policy.playground import completed_image, make_scene, visible_completion

pytestmark = [
    pytest.mark.windows,
    pytest.mark.skipif(
        sys.platform != "win32" or os.environ.get("LEAGUE_INPUT_NATIVE_TESTS") != "1",
        reason="Requires opt-in on a disposable Windows interactive desktop",
    ),
]


def summary(values):
    values = sorted(values)
    if not values:
        return None
    return {
        "mean": mean(values),
        "p50": values[len(values) // 2],
        "p95": values[min(len(values) - 1, int(len(values) * 0.95))],
        "max": max(values),
    }


def test_learned_policy_native_feedback_and_full_latency():
    from windows_policy_scene import PolicyScene

    root = Path(os.environ.get("LEAGUE_POLICY_EVIDENCE", "artifacts/policy"))
    root.mkdir(parents=True, exist_ok=True)
    policy = VisualPolicy()
    rows = []
    with ScreenCapture() as capture, InputAdapter() as adapter:
        for monitor_index, monitor in enumerate(capture.monitors(), 1):
            region = Region(monitor.left + 48, monitor.top + 48, 384, 256)
            witness = PolicyScene(region, completed_image()).start()
            try:
                for index in range(32):
                    condition = ["nominal", "palette", "background", "combined"][index % 4]
                    present = index % 5 != 0
                    task = make_scene(index, split="native", condition=condition, present=present)
                    witness.show(task)
                    # Test-only presentation barrier; the policy gets only the
                    # resulting screenshot, never task/labels/witness coordinates.
                    expected = task.image.tobytes()
                    deadline = time.perf_counter() + 3
                    while True:
                        before = capture.grab(region=region)
                        if before.rgb == expected:
                            break
                        if time.perf_counter() > deadline:
                            raise AssertionError("Synthetic scene was not visibly presented")
                        time.sleep(0.005)
                    decision, point, submitted = act(adapter, before, policy, max_age=0.25)
                    after = None
                    if point is not None:
                        deadline = time.perf_counter() + 0.5
                        while time.perf_counter() < deadline:
                            after = capture.grab(region=region)
                            if visible_completion(after):
                                break
                            time.sleep(0.002)
                    received = witness.accepted.is_set()
                    feedback = after is not None and visible_completion(after)
                    success = (received and feedback) if present else (point is None)
                    baseline = red_baseline(before)
                    local_baseline = (
                        None
                        if baseline is None
                        else (baseline[0] - region.left, baseline[1] - region.top)
                    )
                    row = {
                        "monitor": monitor_index,
                        "index": index,
                        "condition": condition,
                        "present": present,
                        "score": decision.score,
                        "point": point,
                        "capture_id": before.capture_id,
                        "view_id": decision.view.view_id,
                        "region": before.metadata()["region"],
                        "application_received": received,
                        "visible_feedback": feedback,
                        "success": success,
                        "baseline_correct": task.hit(local_baseline),
                        "timestamps_ns": {
                            "capture_started": before.started_ns,
                            "capture_finished": before.finished_ns,
                            "inference_started": decision.started_ns,
                            "preprocess_finished": decision.prepared_ns,
                            "inference_finished": decision.finished_ns,
                            "submitted": submitted,
                            "application_received": witness.received_ns,
                            "feedback_finished": after.finished_ns if feedback else None,
                        },
                        "capture_ms": (before.finished_ns - before.started_ns) / 1e6,
                        "preprocess_ms": (decision.prepared_ns - decision.started_ns) / 1e6,
                        "inference_ms": (decision.finished_ns - decision.prepared_ns) / 1e6,
                        "input_ms": (submitted - decision.finished_ns) / 1e6,
                        "observation_to_submit_ms": (submitted - before.started_ns) / 1e6,
                        "observation_to_feedback_ms": (
                            (after.finished_ns - before.started_ns) / 1e6 if feedback else None
                        ),
                    }
                    rows.append(row)
                    # Evidence encoding stays outside the measured action path.
                    # Save representatives and every failure, not private desktop pixels.
                    if index < 4 or not success:
                        episode = root / f"monitor-{monitor_index}-trial-{index}"
                        with TrajectoryRecorder(episode) as log:
                            log.record_frame(before)
                            log.record_frame(decision.view)
                            if after is not None:
                                log.record_frame(after)
                        # Times refer to the measured action, not a replay.
                        (episode / "policy.json").write_text(
                            json.dumps(row, indent=2) + "\n", encoding="utf-8"
                        )
            finally:
                witness.close()
    metrics = {
        field: summary([r[field] for r in rows if r[field] is not None])
        for field in [
            "capture_ms",
            "preprocess_ms",
            "inference_ms",
            "input_ms",
            "observation_to_submit_ms",
            "observation_to_feedback_ms",
        ]
    }
    report = {
        "model_sha256": policy.sha256,
        "threshold": policy.threshold,
        "windows": platform.platform(),
        "python": sys.version,
        "onnxruntime": version("onnxruntime"),
        "numpy": version("numpy"),
        "pillow": version("Pillow"),
        "mss": version("mss"),
        "inference_threads": 1,
        "crop": [384, 256],
        "model_input": [96, 64],
        "trials": len(rows),
        "successes": sum(r["success"] for r in rows),
        "baseline_correct": sum(r["baseline_correct"] for r in rows),
        "latency_ms": metrics,
        "reports": rows,
        "limitations": "Stationary synthetic cropped scenes on CPU; excludes frame-pacing wait.",
    }
    (root / "native-policy.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    assert report["successes"] >= len(rows) * 0.9, report
    assert all(r["point"] is None for r in rows if not r["present"]), report
