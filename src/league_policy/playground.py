"""Seeded synthetic labels/rendering, separate from the online policy.

Task: click the one colored disk bearing a white plus, or abstain when absent.
The learner never receives Scene objects, labels, seeds, or application state.
"""

import random
from dataclasses import dataclass

from PIL import Image, ImageDraw

WIDTH, HEIGHT = 384, 256
TRAIN_COLORS = [(230, 40, 70), (40, 180, 60), (50, 80, 210)]
SHIFT_COLORS = [(210, 90, 220), (220, 155, 20), (20, 180, 190)]
COMPLETE = (30, 220, 80)
SPLITS = {"train": 100_000, "validation": 200_000, "test": 300_000, "native": 400_000}


@dataclass(frozen=True)
class Scene:
    image: Image.Image
    target: tuple[int, int, int] | None

    def hit(self, point):
        if point is None:
            return self.target is None
        if self.target is None:
            return False
        x, y, radius = self.target
        return (point[0] - x) ** 2 + (point[1] - y) ** 2 <= radius**2


def make_scene(index, *, split="train", condition="nominal", present=None):
    if condition not in {"nominal", "palette", "background", "combined"}:
        raise ValueError("unknown visual condition")
    if split == "train" and condition != "nominal":
        raise ValueError("shifted conditions are reserved for evaluation")
    # Separate seed namespaces and separate conditions. No train/test seed overlap.
    rng = random.Random(
        SPLITS[split]
        + index * 17
        + ["nominal", "palette", "background", "combined"].index(condition) * 10_000_000
    )
    bright = condition in {"background", "combined"}
    background = tuple(rng.randint(95, 150) if bright else rng.randint(5, 65) for _ in range(3))
    image = Image.new("RGB", (WIDTH, HEIGHT), background)
    draw = ImageDraw.Draw(image)
    # Low-contrast panels introduce edges without becoming target cues.
    for _ in range(5):
        x, y = rng.randrange(WIDTH), rng.randrange(HEIGHT)
        color = tuple(max(0, min(180, v + rng.randint(-12, 12))) for v in background)
        draw.rectangle((x, y, min(WIDTH - 1, x + 80), min(HEIGHT - 1, y + 40)), fill=color)
    cells = [(x, y) for y in (40, 124, 208) for x in (40, 136, 232, 328)]
    rng.shuffle(cells)
    present = rng.random() >= 0.2 if present is None else present
    target = None
    for i, (cx, cy) in enumerate(cells[: rng.randint(4, 8)]):
        x, y = cx + rng.randint(-12, 12), cy + rng.randint(-10, 10)
        radius = rng.randint(18, 27)
        colors = SHIFT_COLORS if condition in {"palette", "combined"} else TRAIN_COLORS
        color = rng.choice(colors)
        if i == 0 and present:
            # Nominal cases preserve the old baseline's red target cue; training
            # includes other colors so the policy can learn the marker shape.
            if split != "train" and condition in {"nominal", "background"}:
                color = TRAIN_COLORS[0]
            target = (x, y, radius)
        elif split != "train" and condition == "nominal":
            color = rng.choice(TRAIN_COLORS[1:])
        draw.ellipse((x - radius, y - radius, x + radius, y + radius), fill=color)
        arm = rng.randint(9, 12)
        if i == 0 and present:
            draw.rectangle((x - 3, y - arm, x + 3, y + arm), fill="white")
            draw.rectangle((x - arm, y - 3, x + arm, y + 3), fill="white")
        else:
            kind = rng.choice(["blank", "bar", "x", "ring"])
            if kind == "bar":
                draw.rectangle((x - arm, y - 3, x + arm, y + 3), fill="white")
            elif kind == "x":
                draw.line((x - arm, y - arm, x + arm, y + arm), fill="white", width=6)
                draw.line((x - arm, y + arm, x + arm, y - arm), fill="white", width=6)
            elif kind == "ring":
                draw.ellipse((x - arm, y - arm, x + arm, y + arm), outline="white", width=4)
    return Scene(image, target)


def completed_image():
    return Image.new("RGB", (WIDTH, HEIGHT), COMPLETE)


def visible_completion(frame):
    """Independent response marker; never used for selecting the action."""
    return all(frame.pixel(x, y) == COMPLETE for x, y in [(2, 2), (10, 2), (2, 10)])
