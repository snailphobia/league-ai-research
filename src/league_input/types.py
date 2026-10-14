"""Platform-independent input descriptions. Physical keys and text are distinct."""

import math
from dataclasses import dataclass
from enum import StrEnum


class InputError(RuntimeError):
    """An input event could not be submitted or verified as requested."""


class UnsupportedPlatformError(InputError):
    """The native backend needs a Windows interactive desktop."""


class Button(StrEnum):
    LEFT = "left"
    RIGHT = "right"
    MIDDLE = "middle"
    X1 = "x1"
    X2 = "x2"


@dataclass(frozen=True)
class Key:
    """A native key: scan code, virtual key, or internal UTF-16 unit."""

    kind: str
    code: int
    extended: bool = False

    def __post_init__(self):
        if self.kind not in {"scan", "vk", "unicode"}:
            raise ValueError("key kind must be scan, vk, or unicode")
        if isinstance(self.code, bool) or not isinstance(self.code, int):
            raise ValueError("key code must be an integer")
        if not isinstance(self.extended, bool):
            raise ValueError("extended must be a boolean")
        low, high = {"scan": (1, 255), "vk": (1, 254), "unicode": (0, 65535)}[self.kind]
        if not low <= self.code <= high:
            raise ValueError(f"{self.kind} code must be in {low}..{high}")
        if self.kind == "unicode" and self.extended:
            raise ValueError("Unicode units do not have an extended flag")

    @classmethod
    def scan(cls, code: int, *, extended: bool = False):
        return cls("scan", code, extended)

    @classmethod
    def vk(cls, code: int, *, extended: bool = False):
        return cls("vk", code, extended)


@dataclass(frozen=True)
class Desktop:
    left: int
    top: int
    width: int
    height: int

    @property
    def right(self):
        return self.left + self.width - 1

    @property
    def bottom(self):
        return self.top + self.height - 1

    def contains(self, x: int, y: int):
        return self.left <= x <= self.right and self.top <= y <= self.bottom


def integer(value, name):
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{name} must be an integer")
    return value


def seconds(value, name):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{name} must be a finite non-negative number")
    if not math.isfinite(value) or value < 0:
        raise ValueError(f"{name} must be a finite non-negative number")
    return float(value)
