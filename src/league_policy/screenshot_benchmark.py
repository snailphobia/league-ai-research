"""Rendering, annotation scoring, and variance summaries for static-image trials."""

import hashlib
import math
from collections import Counter
from statistics import mean, pstdev

from PIL import Image, ImageDraw


def render(image, variant):
    """Fit the source into a constant 960x540 viewport; preserve aspect ratio."""
    if variant not in {"full", "small", "grid"}:
        raise ValueError("unknown variant")
    fitted = image.convert("RGB").copy()
    fitted.thumbnail((960, 540), Image.Resampling.LANCZOS)
    canvas = Image.new("RGB", (960, 540), "black")
    canvas.paste(fitted, ((960 - fitted.width) // 2, (540 - fitted.height) // 2))
    # The small condition downsamples the captured Frame before inference; the
    # native display stays at the same geometry as full for a paired comparison.
    if variant == "grid":
        draw = ImageDraw.Draw(canvas)
        for n in range(100, 1000, 100):
            x, y = n * 960 // 1000, n * 540 // 1000
            draw.line((x, 0, x, 539), fill=(110, 110, 110), width=1)
            draw.line((0, y, 959, y), fill=(110, 110, 110), width=1)
            draw.text((x + 2, 2), str(n), fill="white", stroke_width=1, stroke_fill="black")
            draw.text((2, y + 2), str(n), fill="white", stroke_width=1, stroke_fill="black")
    return canvas


def grade(decision, annotation, task):
    if decision is None:
        return {"correct": False, "failures": ["invalid_decision"]}
    failures = []
    if decision.screen_state not in annotation["states"]:
        failures.append("wrong_state")
    expected_health = annotation.get("health", [])
    health_correct = not expected_health or decision.health in expected_health
    if task == "decide":
        if decision.action not in annotation["actions"]:
            failures.append("action_constraint")
        if decision.target is not None and decision.action in {"move", "attack", "cast"}:
            # This checks battlefield-vs-HUD grounding, not tactical optimality.
            x, y = decision.target
            if y >= 850 or x < 15 or x > 985:
                failures.append("aimed_at_hud_or_edge")
    else:
        box = annotation.get("health_box")
        if box is None:
            if decision.action != "wait":
                failures.append("hallucinated_player_hud")
        elif decision.action != "click" or decision.target is None:
            failures.append("missing_grounding_click")
        elif not (
            box[0] <= decision.target[0] <= box[2] and box[1] <= decision.target[1] <= box[3]
        ):
            failures.append("health_bar_mislocalized")
    return {
        "correct": not failures,
        "failures": failures,
        "health_correct": health_correct,
        "overconfident_error": bool(failures) and decision.confidence >= 0.8,
    }


def distribution(values):
    if not values:
        return None
    ordered = sorted(values)
    return {
        "n": len(values),
        "mean": mean(values),
        "std": pstdev(values),
        "p50": ordered[len(ordered) // 2],
        "p95": ordered[min(len(ordered) - 1, int(len(ordered) * 0.95))],
        "min": min(values),
        "max": max(values),
    }


def summarize(rows):
    groups = {}
    for row in rows:
        key = (row["scenario"], row["variant"], row["task"])
        groups.setdefault(key, []).append(row)
    summaries = []
    for (scenario, variant, task), samples in sorted(groups.items()):
        decisions = [r["model"].get("decision") for r in samples]
        decisions = [d for d in decisions if d]
        actions = Counter(d["action"] for d in decisions)
        entropy = -sum(n / len(decisions) * math.log2(n / len(decisions)) for n in actions.values())
        points = [d["target"] for d in decisions if d["target"] is not None]
        center = None
        if points:
            cx, cy = mean(p[0] for p in points), mean(p[1] for p in points)
            center = {
                "x": cx,
                "y": cy,
                "rms_normalized": math.sqrt(
                    mean((p[0] - cx) ** 2 + (p[1] - cy) ** 2 for p in points)
                ),
            }
        summaries.append(
            {
                "scenario": scenario,
                "variant": variant,
                "task": task,
                "trials": len(samples),
                "valid": len(decisions),
                "correct": sum(r["grade"]["correct"] for r in samples),
                "health_correct": sum(r["grade"].get("health_correct", False) for r in samples),
                "delivery_verified": sum(r.get("delivery_verified", False) for r in samples),
                "actions": dict(actions),
                "action_entropy_bits": entropy,
                "coordinate_scatter": center,
                "api_ms": distribution(
                    [r["model"]["api_ms"] for r in samples if "api_ms" in r["model"]]
                ),
                "failures": dict(Counter(f for r in samples for f in r["grade"]["failures"])),
            }
        )
    return {
        "trials": len(rows),
        "semantic_correct": sum(r["grade"]["correct"] for r in rows),
        "valid_decisions": sum(bool(r["model"].get("decision")) for r in rows),
        "state_correct": sum(
            bool(r["model"].get("decision")) and "wrong_state" not in r["grade"]["failures"]
            for r in rows
        ),
        "health_correct": sum(r["grade"].get("health_correct", False) for r in rows),
        "delivery_verified": sum(r.get("delivery_verified", False) for r in rows),
        "overconfident_errors": sum(r["grade"].get("overconfident_error", False) for r in rows),
        "api_ms": distribution([r["model"]["api_ms"] for r in rows if "api_ms" in r["model"]]),
        "end_to_end_ms": distribution([r["end_to_end_ms"] for r in rows if r.get("end_to_end_ms")]),
        "deadline_250ms_misses": sum(r["model"].get("api_ms", 0) > 250 for r in rows),
        "failures": dict(Counter(f for r in rows for f in r["grade"]["failures"])),
        "groups": summaries,
        "limitations": [
            "Static public screenshots; no live game or gameplay outcome validation.",
            "Semantic labels are single-reviewer constraints, not expert-optimal action labels.",
            "Repeated trials share source images and are not independent gameplay samples.",
            "Coordinate scatter combines target actions; inspect action histograms too.",
            "API timings include network, scheduling and generation on a shared endpoint.",
        ],
    }


def image_digest(image):
    return hashlib.sha256(image.tobytes()).hexdigest()
