"""Export scientific plots from audited native screenshot runs (requires matplotlib)."""

import argparse
import json
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
from matplotlib.patches import Rectangle
from report_screenshots import load_run


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--normalized", type=Path, required=True)
    parser.add_argument("--pixels", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    first = load_run(args.normalized)
    second = load_run(args.pixels) if args.pixels else []
    manifest = json.loads((args.normalized / "manifest.json").read_text())
    names = [s["id"] for s in manifest["scenes"]]
    conditions = [("N/full", first, "full"), ("N/small", first, "small"), ("N/grid", first, "grid")]
    if second:
        conditions += [("P/full", second, "full"), ("P/small", second, "small")]
    matrix = np.zeros((len(names), len(conditions)))
    for i, name in enumerate(names):
        for j, (_, rows, variant) in enumerate(conditions):
            subset = [
                r
                for r in rows
                if r["scenario"] == name and r["variant"] == variant and r["task"] == "ground"
            ]
            matrix[i, j] = sum(r["grade"]["correct"] for r in subset) / len(subset)
    fig, ax = plt.subplots(figsize=(8, 8.5), layout="constrained")
    im = ax.imshow(matrix, vmin=0, vmax=1, cmap="RdYlGn", aspect="auto")
    ax.set_xticks(range(len(conditions)), [c[0] for c in conditions])
    ax.set_yticks(range(len(names)), [n.replace("_", " ") for n in names])
    ax.set_title(
        "Player-HUD grounding: hits or correct abstentions\n"
        "N = normalized contract; P = pixel contract; five repeats per cell"
    )
    for i in range(len(names)):
        for j in range(len(conditions)):
            ax.text(j, i, f"{int(matrix[i, j] * 100)}%", ha="center", va="center", color="black")
    fig.colorbar(im, ax=ax, label="Fraction satisfying state and pointer constraints", shrink=0.7)
    for suffix in ["png", "svg"]:
        fig.savefig(args.output / ("grounding-matrix." + suffix), dpi=180)
    plt.close(fig)

    annotation = next(s["annotation"] for s in manifest["scenes"] if s["id"] == "legacy_lane")
    box = annotation["health_box"]
    fig, axes = plt.subplots(1, 2, figsize=(11, 5), layout="constrained")
    ax = axes[0]
    ax.add_patch(
        Rectangle(
            (box[0], box[1]),
            box[2] - box[0],
            box[3] - box[1],
            facecolor="#65c89b",
            alpha=0.35,
            edgecolor="#128556",
            label="Frozen health-bar ROI",
        )
    )
    for label, rows, variant in conditions:
        points = [
            r["model"]["decision"]["target"]
            for r in rows
            if r["scenario"] == "legacy_lane"
            and r["variant"] == variant
            and r["task"] == "ground"
            and r["model"].get("decision")
            and r["model"]["decision"]["target"] is not None
        ]
        if points:
            ax.scatter([p[0] for p in points], [p[1] for p in points], s=65, label=label, alpha=0.8)
    ax.set(
        xlim=(0, 1000),
        ylim=(1000, 0),
        xlabel="Canonical normalized x",
        ylabel="Canonical normalized y",
        title="Same healthy lane: emitted target scatter",
    )
    ax.legend(loc="upper left", fontsize=8)
    axes[1].boxplot(
        [
            [r["model"]["api_ms"] / 1000 for r in rows if r["variant"] == variant]
            for _, rows, variant in conditions
        ],
        tick_labels=[c[0] for c in conditions],
        showfliers=True,
    )
    axes[1].set(
        ylabel="API response time (seconds)", title="Client-observed latency on shared endpoint"
    )
    axes[1].grid(axis="y", alpha=0.2)
    for suffix in ["png", "svg"]:
        fig.savefig(args.output / ("variance-and-latency." + suffix), dpi=180)
    plt.close(fig)
    (args.output / "plot-context.json").write_text(
        json.dumps(
            {
                "matplotlib": matplotlib.__version__,
                "conditions": [c[0] for c in conditions],
                "normalized_manifest_sha256": json.loads(
                    (args.normalized / "run.json").read_text()
                )["manifest_sha256"],
                "pixels_manifest_sha256": json.loads((args.pixels / "run.json").read_text())[
                    "manifest_sha256"
                ]
                if args.pixels
                else None,
                "note": "Convenience images; repeated trials are not independent gameplay samples. "
                "Follow-up is post-observation and timing is not isolated from shared load.",
            },
            indent=2,
        )
        + "\n"
    )


if __name__ == "__main__":
    main()
