"""Audit native screenshot traces and create a private interactive review report."""

import argparse
import hashlib
import json
from pathlib import Path

from PIL import Image

from league_policy.screenshot_benchmark import summarize
from league_policy.screenshot_policy import parse_decision


def load_run(directory):
    rows = []
    for path in directory.glob("*.json"):
        obj = json.loads(path.read_text(encoding="utf-8"))
        if "trial_id" in obj:
            rows.append(obj)
    rows.sort(key=lambda r: r["before"]["started_ns"])
    return rows


def audit(directory, rows):
    manifest = json.loads((directory / "manifest.json").read_text())
    context = json.loads((directory / "run.json").read_text())
    ids = {s["id"] for s in manifest["scenes"]}
    seen = set()
    for row in rows:
        assert row["scenario"] in ids
        key = (row["scenario"], row["variant"], row["task"], row["repetition"])
        assert key not in seen, key
        seen.add(key)
        for name in ["before", "model_input", "stable_before_action", "after"]:
            frame = row[name]
            file = directory / Path(frame["image"].replace("\\", "/"))
            assert file.is_relative_to(directory) and ".." not in file.parts
            data = file.read_bytes()
            assert hashlib.sha256(data).hexdigest() == frame["png_sha256"]
            with Image.open(file) as image:
                assert image.mode == "RGB" and image.size == (frame["width"], frame["height"])
                assert hashlib.sha256(image.tobytes()).hexdigest() == frame["rgb_sha256"]
        assert row["before"]["rgb_sha256"] == row["stable_before_action"]["rgb_sha256"]
        assert row["model_input"]["capture_id"] == row["before"]["capture_id"]
        trace = row["model"]
        if trace.get("decision"):
            assert trace["input_png_sha256"] == row["model_input"]["png_sha256"]
            parse_decision(json.dumps(trace["decision"]))
            assert row["before"]["started_ns"] <= trace["started_ns"] <= trace["finished_ns"]
            assert trace["finished_ns"] <= row["input_started_ns"] <= row["submitted_ns"]
        assert row["submitted_ns"] <= row["after"]["started_ns"] <= row["after"]["finished_ns"]
        for event in row["native_events"]:
            assert row["input_started_ns"] <= event["received_ns"] <= row["after"]["finished_ns"]
    assert len(rows) == context["planned_trials"], (len(rows), context["planned_trials"])
    return {
        "trials": len(rows),
        "unique_cells": len(seen),
        "png_hashes_and_geometry": True,
        "model_input_binding": True,
        "timestamp_causality": True,
        "complete_planned_matrix": True,
    }


HTML = (Path(__file__).parent / "templates/static-report.html").read_text(encoding="utf-8")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run", type=Path)
    parser.add_argument("--public", type=Path)
    args = parser.parse_args()
    rows = load_run(args.run)
    proof = audit(args.run, rows)
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
