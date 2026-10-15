"""Live model -> bounded SDK actions -> independent native receipt on static images.

Run only on a disposable Windows desktop. Raw web images and screen recordings
belong in a private output directory, not public repository artifacts.
"""

import argparse
import concurrent.futures as futures
import hashlib
import json
import platform
import random
import sys
import time
from importlib.metadata import version
from pathlib import Path
from uuid import uuid4

from PIL import Image

from league_capture import Region, ScreenCapture
from league_input import InputAdapter
from league_input.cli import execute
from league_policy.screenshot_benchmark import grade, image_digest, render, summarize
from league_policy.screenshot_policy import ScreenshotPolicy, input_plan


class Record:
    def __init__(self, directory):
        self.directory = directory
        (directory / "observations").mkdir(parents=True)
        self.output = (directory / "events.jsonl").open("x", encoding="utf-8")

    def event(self, event):
        self.output.write(json.dumps(event, allow_nan=False) + "\n")
        self.output.flush()

    def frame(self, frame):
        data = frame.png()
        digest = hashlib.sha256(data).hexdigest()
        path = self.directory / "observations" / (digest + ".png")
        if not path.exists():
            path.write_bytes(data)
        info = {
            **frame.metadata(),
            "image": str(path.relative_to(self.directory)),
            "png_sha256": digest,
            "rgb_sha256": hashlib.sha256(frame.rgb).hexdigest(),
        }
        self.event({"type": "observation", **info})
        return info


def predict(policy, frame, task, temperature):
    started = time.perf_counter_ns()
    try:
        return policy.predict(frame, task=task, temperature=temperature)
    except Exception as error:
        return None, {
            "error": type(error).__name__ + ": " + str(error)[:300],
            "api_ms": (time.perf_counter_ns() - started) / 1e6,
            "finished_ns": time.perf_counter_ns(),
            "task": task,
        }


def delivered(plan, events):
    if not plan:
        return not events
    for command in plan:
        if command["action"] == "move_to":
            continue
        if command["action"] == "click":
            message = 0x202 if command["button"] == "left" else 0x205
            if not any(
                e["kind"] == "mouse"
                and e["message"] == message
                and abs(e["x"] - command["x"]) <= 1
                and abs(e["y"] - command["y"]) <= 1
                for e in events
            ):
                return False
        else:
            vk = 0x1B if command["key"] == "escape" else ord(command["key"].upper())
            if not any(
                e["kind"] == "key" and e["message"] == 0x101 and e["vk"] == vk for e in events
            ):
                return False
    return True


def benchmark(args, progress=None):
    if sys.platform != "win32":
        raise RuntimeError("Native screenshot benchmark requires a Windows desktop")
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tests"))
    from windows_screenshot_viewer import RECEIPT, ScreenshotViewer

    manifest = json.loads(args.manifest.read_text())
    settings = json.loads(args.client.read_text())
    policy = ScreenshotPolicy(**settings)
    args.output.mkdir(parents=True, exist_ok=False)
    log = Record(args.output)
    region = Region(32, 32, 960, 540)
    full_region = Region(32, 32, 960, 576)
    viewer = ScreenshotViewer().start()
    scenes = manifest["scenes"][: args.max_scenarios]
    variants = args.variants or manifest["variants"]
    reps = args.repetitions or manifest["repetitions"]
    rows = []
    planned = len(scenes) * len(variants) * reps * len(manifest["tasks"])
    context = {
        "model": policy.model,
        "coordinate_system": policy.coordinate_system,
        "manifest_sha256": hashlib.sha256(args.manifest.read_bytes()).hexdigest(),
        "platform": platform.platform(),
        "python": sys.version,
        "pillow": version("Pillow"),
        "mss": version("mss"),
        "viewport": [960, 540],
        "input_sizes": {"full": [960, 540], "small": [384, 216], "grid": [960, 540]},
        "repetitions": reps,
        "variants": variants,
        "concurrency": args.concurrency,
        "planned_trials": planned,
        "temperature": manifest["temperature"],
        "clock": "perf_counter_ns on the Windows observer/action process",
    }
    (args.output / "run.json").write_text(json.dumps(context, indent=2) + "\n")
    (args.output / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    try:
        with (
            ScreenCapture() as capture,
            InputAdapter() as adapter,
            futures.ThreadPoolExecutor(max_workers=args.concurrency) as pool,
        ):
            for scene in scenes:
                path = args.corpus / scene["local_file"]
                assert hashlib.sha256(path.read_bytes()).hexdigest() == scene["rgb_png_sha256"]
                source = Image.open(path).convert("RGB")
                for variant in variants:
                    image = render(source, variant)
                    expected = image_digest(image)
                    viewer.present(image)
                    jobs = [
                        (task, repetition)
                        for repetition in range(reps)
                        for task in manifest["tasks"]
                    ]
                    random.Random(42).shuffle(jobs)
                    pending = {}

                    def enqueue(jobs=jobs, expected=expected, variant=variant, pending=pending):
                        task, repetition = jobs.pop()
                        limit = time.perf_counter() + 3
                        while True:
                            frame = capture.grab(region=region)
                            if hashlib.sha256(frame.rgb).hexdigest() == expected:
                                break
                            if time.perf_counter() > limit:
                                raise RuntimeError(
                                    "Screenshot presentation did not reach captured pixels"
                                )
                            time.sleep(0.005)
                        view = frame.resize(384, 216) if variant == "small" else frame
                        future = pool.submit(predict, policy, view, task, manifest["temperature"])
                        pending[future] = (task, repetition, frame, view)

                    while jobs and len(pending) < args.concurrency:
                        enqueue()
                    while pending:
                        done, _ = futures.wait(pending, return_when=futures.FIRST_COMPLETED)
                        for future in done:
                            task, repetition, before, model_view = pending.pop(future)
                            decision, trace = future.result()
                            trial_id = uuid4().hex
                            # Reset only receipt state. Re-capture and prove the
                            # observed image is unchanged before emitting input.
                            viewer.present(image)
                            stable = capture.grab(region=region)
                            unchanged = stable.rgb == before.rgb
                            plan = [] if decision is None else input_plan(decision, model_view)
                            started_input = time.perf_counter_ns()
                            if decision is not None and unchanged:
                                for command in plan:
                                    log.event(
                                        {
                                            "type": "action_start",
                                            "trial_id": trial_id,
                                            "capture_id": before.capture_id,
                                            "view_id": model_view.view_id,
                                            "command": command,
                                            "started_ns": time.perf_counter_ns(),
                                        }
                                    )
                                    execute(adapter, command)
                                    log.event(
                                        {
                                            "type": "action_end",
                                            "trial_id": trial_id,
                                            "status": "submitted",
                                            "finished_ns": time.perf_counter_ns(),
                                        }
                                    )
                            submitted = time.perf_counter_ns()
                            deadline = time.perf_counter() + 0.75
                            while True:
                                after = capture.grab(region=full_region)
                                visible = after.pixel(5, 550) == RECEIPT
                                received = delivered(plan, viewer.events)
                                if (
                                    not plan
                                    or (visible and received)
                                    or time.perf_counter() > deadline
                                ):
                                    break
                                time.sleep(0.002)
                            events = list(viewer.events)
                            verified = (
                                decision is not None
                                and unchanged
                                and received
                                and (visible if plan else not visible)
                            )
                            assessment = grade(decision, scene["annotation"], task)
                            if not unchanged:
                                assessment["correct"] = False
                                assessment["failures"].append("image_changed_before_input")
                            row = {
                                "trial_id": trial_id,
                                "scenario": scene["id"],
                                "variant": variant,
                                "task": task,
                                "repetition": repetition,
                                "model": trace,
                                "grade": assessment,
                                "plan": plan,
                                "native_events": events,
                                "image_unchanged_before_input": unchanged,
                                "delivery_verified": verified,
                                "visible_receipt": visible,
                                "input_started_ns": started_input,
                                "submitted_ns": submitted,
                                "input_ms": (submitted - started_input) / 1e6,
                                "observation_to_submit_ms": (submitted - before.started_ns) / 1e6,
                                "end_to_end_ms": (after.finished_ns - before.started_ns) / 1e6,
                                "source_page": scene["page_url"],
                                "before": log.frame(before),
                                "model_input": log.frame(model_view),
                                "stable_before_action": log.frame(stable),
                                "after": log.frame(after),
                            }
                            if decision is not None and not verified:
                                row["grade"]["correct"] = False
                                row["grade"]["failures"].append("delivery_failed")
                            log.event({"type": "trial", **row})
                            (args.output / (trial_id + ".json")).write_text(
                                json.dumps(row, indent=2) + "\n"
                            )
                            rows.append(row)
                            print(
                                json.dumps(
                                    {
                                        "completed": len(rows),
                                        "planned": planned,
                                        "scenario": scene["id"],
                                        "task": task,
                                        "correct": assessment["correct"],
                                        "delivered": verified,
                                    }
                                ),
                                flush=True,
                            )
                            if progress and (len(rows) % 10 == 0 or len(rows) == planned):
                                progress(
                                    {
                                        "completed": len(rows),
                                        "planned": planned,
                                        "correct": sum(r["grade"]["correct"] for r in rows),
                                        "last": scene["id"],
                                    }
                                )
                            if jobs:
                                enqueue()
    finally:
        viewer.close()
        log.output.close()
        (args.output / "summary.json").write_text(json.dumps(summarize(rows), indent=2) + "\n")
    return rows


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--corpus", type=Path, required=True)
    parser.add_argument("--client", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--repetitions", type=int)
    parser.add_argument("--max-scenarios", type=int, default=10_000)
    parser.add_argument("--variants", nargs="+", choices=["full", "small", "grid"])
    parser.add_argument("--concurrency", type=int, default=2)
    args = parser.parse_args()
    if args.concurrency not in {1, 2} or (args.repetitions is not None and args.repetitions < 1):
        parser.error("use concurrency 1 or 2 and positive repetitions")
    benchmark(args)


if __name__ == "__main__":
    main()
