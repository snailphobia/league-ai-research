import json
import time

import pytest
from PIL import Image

from league_capture import Frame, Region
from league_policy.screenshot_benchmark import grade, render, summarize
from league_policy.screenshot_policy import from_pixel_coordinates, input_plan, parse_decision


def decision(**changes):
    return {
        "screen_state": "playing",
        "health": "healthy",
        "action": "click",
        "target": [500, 955],
        "key": None,
        "confidence": 0.85,
        "reason": "The player's HUD health bar is at the bottom.",
    } | changes


@pytest.mark.parametrize(
    "changes",
    [
        {"target": [-1, 500]},
        {"target": [1001, 500]},
        {"target": [True, 500]},
        {"target": [10.1, 500]},
        {"action": "wait"},
        {"key": "f4"},
        {"confidence": float("nan")},
        {"confidence": True},
        {"action": "cast", "key": "win"},
        {"screen_state": "unrecognized"},
    ],
)
def test_untrusted_model_output_cannot_create_unbounded_input(changes):
    with pytest.raises(ValueError):
        parse_decision(json.dumps(decision(**changes)))


def test_normalized_plan_preserves_negative_desktop_geometry_and_aimed_cast():
    region = Region(-960, -100, 960, 540)
    now = time.perf_counter_ns()
    frame = Frame("same", "same", 0, region, 960, 540, bytes(960 * 540 * 3), now, now, (region,))
    predicted = parse_decision(json.dumps(decision(action="cast", key="q", target=[1000, 0])))
    plan = input_plan(predicted, frame.resize(384, 216))
    assert plan == [{"action": "move_to", "x": -2, "y": -99}, {"action": "press", "key": "q"}]


def test_grounding_grade_rejects_mana_and_spectator_hud_hallucinations():
    annotation = {"states": ["playing"], "actions": ["move"], "health_box": [365, 936, 638, 960]}
    hp = parse_decision(json.dumps(decision()))
    assert grade(hp, annotation, "ground")["correct"]
    mana = parse_decision(json.dumps(decision(target=[500, 980])))
    assert grade(mana, annotation, "ground")["failures"] == ["health_bar_mislocalized"]
    spectator = {"states": ["spectator"], "actions": ["wait"], "health_box": None}
    errors = grade(hp, spectator, "ground")
    assert errors["failures"] == ["wrong_state", "hallucinated_player_hud"]
    assert errors["overconfident_error"]


def test_source_aspect_ratio_and_negative_control_survive_rendering():
    image = Image.new("RGB", (600, 415), (13, 17, 23))
    full, small = render(image, "full"), render(image, "small")
    assert full.size == (960, 540) and full.tobytes() == small.tobytes()
    assert full.getpixel((0, 0)) == (0, 0, 0)
    assert full.getpixel((480, 270)) == (13, 17, 23)


def test_invalid_api_responses_are_failures_not_successful_abstentions():
    row = {
        "scenario": "blank",
        "variant": "full",
        "task": "decide",
        "model": {"error": "HTTP 500", "api_ms": 400},
        "grade": grade(None, {"states": ["unknown"], "actions": ["wait"]}, "decide"),
        "delivery_verified": False,
    }
    summary = summarize([row])
    assert summary["semantic_correct"] == 0
    assert summary["valid_decisions"] == 0
    assert summary["delivery_verified"] == 0
    assert summary["deadline_250ms_misses"] == 1


def test_pixel_contract_checks_actual_image_bounds_before_converting():
    region = Region(-960, -100, 960, 540)
    now = time.perf_counter_ns()
    frame = Frame("same", "same", 0, region, 960, 540, bytes(960 * 540 * 3), now, now, (region,))
    view = frame.resize(384, 216)
    correct = from_pixel_coordinates(parse_decision(json.dumps(decision(target=[383, 215]))), view)
    assert input_plan(correct, view) == [{"action": "click", "x": -2, "y": 438, "button": "left"}]
    with pytest.raises(ValueError, match="outside"):
        from_pixel_coordinates(parse_decision(json.dumps(decision(target=[500, 500]))), view)
