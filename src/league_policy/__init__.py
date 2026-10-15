"""Small pixel-only research policies; importing this package never emits input."""

from .policy import Decision, VisualPolicy, act, red_baseline

__all__ = ["Decision", "VisualPolicy", "act", "red_baseline"]
