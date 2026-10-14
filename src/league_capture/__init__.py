"""Screen observations and bounded temporal streams; imports do not capture input."""

from .capture import ScreenCapture
from .recording import TrajectoryRecorder
from .stream import FrameStream
from .types import CaptureError, Frame, Region, StaleFrameError

__all__ = [
    "CaptureError",
    "Frame",
    "FrameStream",
    "Region",
    "ScreenCapture",
    "StaleFrameError",
    "TrajectoryRecorder",
]
