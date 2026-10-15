"""Audit native screenshot traces and create a private interactive review report."""

import argparse
import hashlib
import json
from pathlib import Path

from PIL import Image

from league_policy.screenshot_benchmark import render, summarize
from league_policy.screenshot_policy import parse_decision


def load_run(directory):
    rows = []
    for path in directory.glob("*.json"):
        obj = json.loads(path.read_text(encoding="utf-8"))
        if "trial_id" in obj:
            rows.append(obj)
    rows.sort(key=lambda r: r["before"]["started_ns"])
    return rows


def audit(directory, rows, corpus=None):
    manifest = json.loads((directory / "manifest.json").read_text())
    context = json.loads((directory / "run.json").read_text())
    assert (
        hashlib.sha256((json.dumps(manifest, indent=2) + "\n").encode()).hexdigest()
        == context["manifest_sha256"]
    )
    ids = {s["id"] for s in manifest["scenes"]}
    seen = set()
    verified_images = set()
    rendered = {}
    scenes = {s["id"]: s for s in manifest["scenes"]}
    capture_ids = set()
    guarded = 0
    for row in rows:
        assert row["scenario"] in ids
        key = (row["scenario"], row["variant"], row["task"], row["repetition"])
        assert key not in seen, key
        seen.add(key)
        assert row["before"]["capture_id"] not in capture_ids
        capture_ids.add(row["before"]["capture_id"])
        for name in ["before", "model_input", "stable_before_action", "after"]:
            frame = row[name]
            file = directory / Path(frame["image"].replace("\\", "/"))
            assert file.is_relative_to(directory) and ".." not in file.parts
            data = file.read_bytes()
            identity = (frame["png_sha256"], frame["width"], frame["height"], frame["rgb_sha256"])
            if identity not in verified_images:
                assert hashlib.sha256(data).hexdigest() == frame["png_sha256"]
                with Image.open(file) as image:
                    assert image.mode == "RGB" and image.size == (frame["width"], frame["height"])
                    assert hashlib.sha256(image.tobytes()).hexdigest() == frame["rgb_sha256"]
                verified_images.add(identity)
        if corpus:
            key = (row["scenario"], row["variant"])
            if key not in rendered:
                source = corpus / scenes[row["scenario"]]["local_file"]
                assert (
                    hashlib.sha256(source.read_bytes()).hexdigest()
                    == scenes[row["scenario"]]["rgb_png_sha256"]
                )
                expected = render(Image.open(source), row["variant"])
                rendered[key] = hashlib.sha256(expected.tobytes()).hexdigest()
            assert row["before"]["rgb_sha256"] == rendered[key], key
        before_path = directory / Path(row["before"]["image"].replace("\\", "/"))
        with Image.open(before_path) as image:
            pixels = image.tobytes()
            if row["variant"] == "small":
                image = image.resize((384, 216), Image.Resampling.BILINEAR)
            assert hashlib.sha256(image.tobytes()).hexdigest() == row["model_input"]["rgb_sha256"]
        after_path = directory / Path(row["after"]["image"].replace("\\", "/"))
        with Image.open(after_path) as after:
            if row["image_unchanged_before_input"]:
                assert after.crop((0, 0, 960, 540)).tobytes() == pixels
            assert (after.getpixel((5, 550)) == (30, 220, 80)) == row["visible_receipt"]
        unchanged = row["before"]["rgb_sha256"] == row["stable_before_action"]["rgb_sha256"]
        assert unchanged == row["image_unchanged_before_input"]
        assert row["model_input"]["capture_id"] == row["before"]["capture_id"]
        trace = row["model"]
        if trace.get("decision"):
            assert trace["input_png_sha256"] == row["model_input"]["png_sha256"]
            parse_decision(json.dumps(trace["decision"]))
            assert row["before"]["started_ns"] <= trace["started_ns"] <= trace["finished_ns"]
            assert trace["finished_ns"] <= row["input_started_ns"] <= row["submitted_ns"]
            d = trace["decision"]
            events = row["native_events"]
            expected_count = 0
            for command in row["plan"] if unchanged else []:
                if command["action"] == "move_to":
                    continue
                expected_count += 2
                if command["action"] == "click":
                    messages = [0x201, 0x202] if command["button"] == "left" else [0x204, 0x205]
                    assert all(
                        any(
                            e["kind"] == "mouse"
                            and e["message"] == message
                            and abs(e["x"] - command["x"]) <= 1
                            and abs(e["y"] - command["y"]) <= 1
                            for e in events
                        )
                        for message in messages
                    )
                else:
                    vk = 0x1B if command["key"] == "escape" else ord(command["key"].upper())
                    assert all(
                        any(
                            e["kind"] == "key" and e["message"] == message and e["vk"] == vk
                            for e in events
                        )
                        for message in [0x100, 0x101]
                    )
            assert len(events) == expected_count
            if d["target"] is not None:
                image = row["model_input"]
                native = image["region"]
                x, y = d["target"]
                px = min(image["width"] - 1, x * image["width"] // 1000)
                py = min(image["height"] - 1, y * image["height"] // 1000)
                dx = native["left"] + (2 * px + 1) * native["width"] // (2 * image["width"])
                dy = native["top"] + (2 * py + 1) * native["height"] // (2 * image["height"])
                assert row["plan"][0]["x"] == dx and row["plan"][0]["y"] == dy
                if d["action"] == "cast" and unchanged:
                    assert all(abs(e["x"] - dx) <= 1 and abs(e["y"] - dy) <= 1 for e in events)
            if unchanged:
                assert row["delivery_verified"] and row["visible_receipt"] == bool(row["plan"])
            else:
                guarded += 1
                assert not events and not row["delivery_verified"] and not row["visible_receipt"]
                assert "image_changed_before_input" in row["grade"]["failures"]
        else:
            assert not row["plan"] and not row["native_events"] and not row["delivery_verified"]
        assert row["submitted_ns"] <= row["after"]["started_ns"] <= row["after"]["finished_ns"]
        for event in row["native_events"]:
            assert row["input_started_ns"] <= event["received_ns"] <= row["after"]["finished_ns"]
    assert len(rows) == context["planned_trials"], (len(rows), context["planned_trials"])
    expected = {
        (s["id"], variant, task, rep)
        for s in manifest["scenes"]
        for variant in context["variants"]
        for task in manifest["tasks"]
        for rep in range(context["repetitions"])
    }
    assert seen == expected
    return {
        "trials": len(rows),
        "unique_cells": len(seen),
        "png_hashes_and_geometry": True,
        "model_input_binding": True,
        "timestamp_causality": True,
        "complete_planned_matrix": True,
        "source_renderer_verified": corpus is not None,
        "input_downsampling_and_static_viewport_verified": True,
        "native_down_up_pairs_and_coordinates_verified": True,
        "changed_image_trials_safely_blocked": guarded,
    }


HTML = (Path(__file__).parent / "templates/static-report.html").read_text(encoding="utf-8")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run", type=Path)
    parser.add_argument("--public", type=Path)
    parser.add_argument("--corpus", type=Path)
    args = parser.parse_args()
    rows = load_run(args.run)
    proof = audit(args.run, rows, args.corpus)
    summary = summarize(rows)
    (args.run / "audit.json").write_text(json.dumps(proof, indent=2) + "\n")
    (args.run / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")
    payload = json.dumps({"summary": summary, "rows": rows}, ensure_ascii=False).replace(
        "<", "\\u003c"
    )
    (args.run / "report.html").write_text(HTML.replace("__DATA__", payload), encoding="utf-8")
    if args.public:
        args.public.mkdir(parents=True, exist_ok=True)
        for name in ["summary.json", "audit.json", "run.json"]:
            (args.public / name).write_bytes((args.run / name).read_bytes())
        with (args.public / "trials.jsonl").open("w", encoding="utf-8") as out:
            for row in rows:
                record = {
                    k: row[k]
                    for k in [
                        "trial_id",
                        "scenario",
                        "variant",
                        "task",
                        "repetition",
                        "grade",
                        "plan",
                        "native_events",
                        "delivery_verified",
                        "visible_receipt",
                        "image_unchanged_before_input",
                        "end_to_end_ms",
                        "source_page",
                    ]
                }
                record["decision"] = row["model"].get("decision")
                record["api_ms"] = row["model"].get("api_ms")
                record["response_sha256"] = hashlib.sha256(
                    json.dumps(row["model"].get("response"), sort_keys=True).encode()
                ).hexdigest()
                record["input_png_sha256"] = row["model"].get("input_png_sha256")
                record["before_rgb_sha256"] = row["before"]["rgb_sha256"]
                out.write(json.dumps(record, ensure_ascii=False) + "\n")
    print(json.dumps({k: v for k, v in summary.items() if k != "groups"}, indent=2))
    print("Report", args.run / "report.html")


if __name__ == "__main__":
    main()
