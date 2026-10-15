"""Evaluate frozen policy and exact-red baseline on seed-disjoint scenes."""

import argparse
import json
import platform
import time
from importlib.metadata import version
from pathlib import Path
from statistics import mean

from league_capture import Frame, Region
from league_policy import VisualPolicy, red_baseline
from league_policy.playground import HEIGHT, WIDTH, make_scene


def observation(image, index=0):
    now = time.perf_counter_ns()
    region = Region(0, 0, WIDTH, HEIGHT)
    return Frame(
        str(index), str(index), index, region, WIDTH, HEIGHT, image.tobytes(), now, now, (region,)
    )


def summarize(values):
    values = sorted(values)
    return {
        "mean": mean(values),
        "p50": values[len(values) // 2],
        "p95": values[min(len(values) - 1, int(len(values) * 0.95))],
        "max": max(values),
    }


def evaluate(policy, *, split, count):
    reports = {}
    for condition in ["nominal", "palette", "background", "combined"]:
        rows, timings = [], []
        for i in range(count):
            scene = make_scene(i, split=split, condition=condition)
            frame = observation(scene.image, i)
            started = time.perf_counter_ns()
            decision = policy.predict(frame)
            timings.append((time.perf_counter_ns() - started) / 1e6)
            point = None if decision.point is None else decision.view.to_desktop(*decision.point)
            baseline = red_baseline(frame)
            rows.append(
                {
                    "index": i,
                    "target": scene.target,
                    "point": point,
                    "score": decision.score,
                    "correct": scene.hit(point),
                    "baseline_point": baseline,
                    "baseline_correct": scene.hit(baseline),
                }
            )
        present = [row for row in rows if row["target"] is not None]
        absent = [row for row in rows if row["target"] is None]
        reports[condition] = {
            "examples": count,
            "target_present": len(present),
            "target_absent": len(absent),
            "learned_correct": sum(r["correct"] for r in rows),
            "learned_hits": sum(r["correct"] for r in present),
            "learned_false_clicks": sum(r["point"] is not None for r in absent),
            "baseline_correct": sum(r["baseline_correct"] for r in rows),
            "baseline_hits": sum(r["baseline_correct"] for r in present),
            "baseline_false_clicks": sum(r["baseline_point"] is not None for r in absent),
            "preprocess_and_inference_ms": summarize(timings),
            "trials": rows,
        }
    return reports


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--split", choices=["validation", "test"], default="test")
    parser.add_argument("--count", type=int, default=256)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.count < 1:
        parser.error("count must be positive")
    policy = VisualPolicy()
    # Warm up once; cold startup isn't mixed into steady-state timings.
    policy.predict(observation(make_scene(0, split="validation").image))
    reports = evaluate(policy, split=args.split, count=args.count)
    result = {
        "model_sha256": policy.sha256,
        "threshold": policy.threshold,
        "split": args.split,
        "seed_namespaces": "league_policy.playground.SPLITS",
        "platform": platform.platform(),
        "python": platform.python_version(),
        "inference_threads": 1,
        "onnxruntime": version("onnxruntime"),
        "numpy": version("numpy"),
        "pillow": version("Pillow"),
        "reports": reports,
        "limitations": "Synthetic stationary target task; no game or temporal policy evidence.",
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    for condition, report in reports.items():
        print(condition, json.dumps({k: v for k, v in report.items() if k != "trials"}))


if __name__ == "__main__":
    main()
