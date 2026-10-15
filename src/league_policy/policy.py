"""ONNX CPU inference and a bounded observation -> click step.

The checkpoint recognizes the synthetic playground's plus-marked target only.
There is no game knowledge, hidden-state input, or baseline fallback.
"""

import hashlib
import math
import time
from dataclasses import dataclass
from importlib.resources import files

from league_capture import Frame
from league_capture.types import finite_seconds


@dataclass(frozen=True)
class Decision:
    view: Frame
    point: tuple[int, int] | None
    score: float
    started_ns: int
    prepared_ns: int
    finished_ns: int


class VisualPolicy:
    def __init__(self, model=None, *, threshold=0.99):
        import onnxruntime as ort

        if isinstance(threshold, bool) or not math.isfinite(threshold) or not 0 < threshold < 1:
            raise ValueError("threshold must be finite and between zero and one")
        blob = (
            files("league_policy").joinpath("models/target.onnx").read_bytes()
            if model is None
            else model.read_bytes()
        )
        self.sha256 = hashlib.sha256(blob).hexdigest()
        self.threshold = threshold
        options = ort.SessionOptions()
        options.intra_op_num_threads = 1
        options.inter_op_num_threads = 1
        self.session = ort.InferenceSession(
            blob, sess_options=options, providers=["CPUExecutionProvider"]
        )

    def predict(self, frame):
        import numpy as np
        from PIL import Image

        started = time.perf_counter_ns()
        # This first experiment has a fixed 3:2 crop. Reject unsupported shapes
        # instead of silently distorting the observation/coordinate transform.
        view = frame.resize(96, 64)
        if (view.width, view.height) != (96, 64):
            raise ValueError("policy requires a crop with 3:2 aspect ratio, at least 96x64")
        # Grayscale removes an irrelevant color shortcut; geometry is learned.
        gray = Image.frombytes("RGB", (96, 64), view.rgb).convert("L")
        tensor = np.asarray(gray, dtype=np.float32)[None, None] / 255
        prepared = time.perf_counter_ns()
        logits = self.session.run(["heatmap"], {"pixels": tensor})[0]
        finished = time.perf_counter_ns()
        if logits.shape != (1, 1, 64, 96) or not np.isfinite(logits).all():
            raise ValueError("model returned an invalid target heatmap")
        index = int(logits.argmax())
        value = float(logits.reshape(-1)[index])
        score = 1 / (1 + math.exp(-max(-80, min(80, value))))
        point = (index % 96, index // 96) if score >= self.threshold else None
        return Decision(view, point, score, started, prepared, finished)


def act(adapter, frame, policy, *, max_age=0.25):
    """Infer from this observation and submit at most one click if still fresh.

    Caller owns capture, pacing, recording, and application feedback. The return
    value proves submission only. No input is emitted on an abstention/error.
    """
    finite_seconds(max_age, "max_age")
    frame.require_fresh(max_age)
    decision = policy.predict(frame)
    if decision.view.capture_id != frame.capture_id:
        raise ValueError("decision is associated with a different observation")
    if not math.isfinite(decision.score) or not 0 <= decision.score <= 1:
        raise ValueError("invalid decision score")
    frame.require_fresh(max_age)
    point = None
    if decision.point is not None:
        point = decision.view.to_desktop(*decision.point)
        frame.require_fresh(max_age)
        adapter.click(*point)
    return decision, point, time.perf_counter_ns()


def red_baseline(frame):
    """Previous exact-red bounding-box rule, evaluated on the same resized pixels."""
    import numpy as np

    view = frame.resize(96, 64)
    pixels = np.frombuffer(view.rgb, dtype=np.uint8).reshape(view.height, view.width, 3)
    ys, xs = np.where(np.all(pixels == (230, 40, 70), axis=2))
    if not len(xs):
        return None
    return view.to_desktop(int((xs.min() + xs.max()) // 2), int((ys.min() + ys.max()) // 2))
