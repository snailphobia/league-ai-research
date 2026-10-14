"""Immutable observations, physical screen regions, and explicit view transforms."""

import io
import math
import time
from dataclasses import asdict, dataclass, replace
from uuid import uuid4


class CaptureError(RuntimeError):
    pass


class StaleFrameError(CaptureError):
    pass


def integer(value, name):
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{name} must be an integer")
    return value


def positive(value, name):
    integer(value, name)
    if value < 1:
        raise ValueError(f"{name} must be positive")
    return value


def finite_seconds(value, name):
    if isinstance(value, bool) or not isinstance(value, (float, int)):
        raise ValueError(f"{name} must be a finite non-negative number")
    if not math.isfinite(value) or value < 0:
        raise ValueError(f"{name} must be a finite non-negative number")
    return float(value)


@dataclass(frozen=True)
class Region:
    left: int
    top: int
    width: int
    height: int

    def __post_init__(self):
        integer(self.left, "left")
        integer(self.top, "top")
        positive(self.width, "width")
        positive(self.height, "height")
        if not all(-(2**31) <= v < 2**31 for v in (self.left, self.top, self.right, self.bottom)):
            raise ValueError("region coordinates exceed Windows' signed 32-bit range")

    @property
    def right(self):
        return self.left + self.width - 1

    @property
    def bottom(self):
        return self.top + self.height - 1

    def contains(self, x, y):
        return self.left <= x <= self.right and self.top <= y <= self.bottom

    def contains_region(self, other):
        return self.contains(other.left, other.top) and self.contains(other.right, other.bottom)


@dataclass(frozen=True)
class Frame:
    capture_id: str
    view_id: str
    sequence: int
    region: Region
    width: int
    height: int
    rgb: bytes
    started_ns: int
    finished_ns: int
    monitors: tuple[Region, ...]

    def __post_init__(self):
        positive(self.width, "width")
        positive(self.height, "height")
        integer(self.sequence, "sequence")
        integer(self.started_ns, "started_ns")
        integer(self.finished_ns, "finished_ns")
        if self.sequence < 0 or self.started_ns < 0 or self.finished_ns < self.started_ns:
            raise ValueError("invalid frame sequence or capture interval")
        if not isinstance(self.rgb, bytes) or len(self.rgb) != self.width * self.height * 3:
            raise ValueError("rgb must be immutable packed RGB bytes matching the image dimensions")
        if not isinstance(self.monitors, tuple) or not self.monitors:
            raise ValueError("a frame needs an immutable monitor geometry snapshot")
        if not self.capture_id or not self.view_id:
            raise ValueError("frame identifiers cannot be empty")

    def pixel(self, x, y):
        self._pixel(x, y)
        offset = (y * self.width + x) * 3
        return tuple(self.rgb[offset : offset + 3])

    def _pixel(self, x, y):
        integer(x, "x")
        integer(y, "y")
        if not (0 <= x < self.width and 0 <= y < self.height):
            raise ValueError("point is outside this image")

    def to_desktop(self, x, y):
        """Map an image pixel's center to its physical desktop pixel."""
        self._pixel(x, y)
        dx = self.region.left + (2 * x + 1) * self.region.width // (2 * self.width)
        dy = self.region.top + (2 * y + 1) * self.region.height // (2 * self.height)
        if not any(m.contains(dx, dy) for m in self.monitors):
            raise ValueError("image pixel maps to a gap between monitors")
        return dx, dy

    def age(self, *, now_ns=None):
        # Conservatively include the entire capture interval, not only time since return.
        now_ns = time.perf_counter_ns() if now_ns is None else now_ns
        return max(0, now_ns - self.started_ns) / 1e9

    def require_fresh(self, max_age, *, now_ns=None):
        max_age = finite_seconds(max_age, "max_age")
        if self.age(now_ns=now_ns) > max_age:
            raise StaleFrameError(f"observation is older than {max_age:g} seconds")
        return self

    def resize(self, max_width, max_height):
        """Fit inside a box without stretching or upscaling; retain native geometry."""
        from PIL import Image

        positive(max_width, "max_width")
        positive(max_height, "max_height")
        scale = min(1, max_width / self.width, max_height / self.height)
        if scale == 1:
            return self
        width, height = max(1, int(self.width * scale)), max(1, int(self.height * scale))
        image = Image.frombytes("RGB", (self.width, self.height), self.rgb)
        image = image.resize((width, height), Image.Resampling.BILINEAR)
        return replace(self, view_id=uuid4().hex, width=width, height=height, rgb=image.tobytes())

    def png(self):
        from PIL import Image

        output = io.BytesIO()
        Image.frombytes("RGB", (self.width, self.height), self.rgb).save(output, format="PNG")
        return output.getvalue()

    def metadata(self):
        return {
            "capture_id": self.capture_id,
            "view_id": self.view_id,
            "sequence": self.sequence,
            "region": asdict(self.region),
            "width": self.width,
            "height": self.height,
            "pixel_format": "RGB",
            "started_ns": self.started_ns,
            "finished_ns": self.finished_ns,
            "monitors": [asdict(m) for m in self.monitors],
        }
