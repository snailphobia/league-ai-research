"""Windows input API; native initialization occurs only on construction."""

from .adapter import InputAdapter
from .types import Button, Desktop, InputError, Key, UnsupportedPlatformError

__all__ = ["InputAdapter", "Button", "Desktop", "InputError", "Key", "UnsupportedPlatformError"]
