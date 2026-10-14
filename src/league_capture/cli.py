"""Explicit screenshot, stream benchmark, and observation recording commands."""

import argparse
import json
import time
from pathlib import Path

from . import FrameStream, Region, ScreenCapture
from .recording import TrajectoryRecorder
from .types import finite_seconds


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    for name in ["grab", "benchmark", "record"]:
        p = commands.add_parser(name)
        p.add_argument("--monitor", type=int, default=1, help="0: entire desktop; 1..N: monitors")
        p.add_argument("--region", type=int, nargs=4, metavar=("LEFT", "TOP", "WIDTH", "HEIGHT"))
        p.add_argument("--max-width", type=int, default=640)
        p.add_argument("--max-height", type=int, default=360)
        if name == "grab":
            p.add_argument("--output", type=Path, required=True)
        else:
            p.add_argument("--fps", type=float, default=20)
            p.add_argument("--seconds", type=float, default=3)
        if name == "record":
            p.add_argument("--directory", type=Path, required=True)
    args = parser.parse_args()
    region = Region(*args.region) if args.region else None
    if args.max_width < 1 or args.max_height < 1:
        parser.error("image size limits must be positive")
    if args.command == "grab":
        if args.output.suffix.lower() != ".png":
            parser.error("grab output must use a .png extension")
        with ScreenCapture() as capture:
            frame = capture.grab(monitor=args.monitor, region=region)
        view = frame.resize(args.max_width, args.max_height)
        args.output.write_bytes(view.png())
        metadata = {**view.metadata(), "image": str(args.output)}
        args.output.with_suffix(".json").write_text(json.dumps(metadata, indent=2) + "\n")
        print(json.dumps(metadata))
        return 0

    seconds = finite_seconds(args.seconds, "seconds")
    if seconds == 0:
        parser.error("seconds must be positive")
    recorder = TrajectoryRecorder(args.directory) if args.command == "record" else None
    count, capture_ms, resize_ms, skipped = 0, 0.0, 0.0, 0
    first_finished, last_finished = None, None
    try:
        with FrameStream(fps=args.fps, monitor=args.monitor, region=region) as stream:
            deadline = time.perf_counter() + seconds
            previous = -1
            while not count or time.perf_counter() < deadline:
                frame = stream.next(after_sequence=previous)
                skipped += max(0, frame.sequence - previous - 1)
                previous = frame.sequence
                start = time.perf_counter_ns()
                view = frame.resize(args.max_width, args.max_height)
                resize_ms += (time.perf_counter_ns() - start) / 1e6
                if recorder:
                    recorder.record_frame(view)
                count += 1
                capture_ms += (frame.finished_ns - frame.started_ns) / 1e6
                if first_finished is None:
                    first_finished = frame.finished_ns
                last_finished = frame.finished_ns
    finally:
        if recorder:
            recorder.close()
    elapsed = (last_finished - first_finished) / 1e9 if count > 1 else 0
    result = {
        "target_hz": args.fps,
        "observations": count,
        "observed_hz": (count - 1) / elapsed if elapsed else 0,
        "skipped_by_consumer": skipped,
        "mean_capture_ms": capture_ms / count,
        "mean_resize_ms": resize_ms / count,
        "last_observation": view.metadata(),
        "includes_model_inference": False,
    }
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
