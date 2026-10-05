"""Screenshot fallback hook.

The agent reads apps through the DOM / accessibility tree first. Only when every
configured strategy for a key fails does it fall back to pixels:

1. a full-page screenshot is saved to ``runs/<id>/screenshots/<key>.png``
   (useful for debugging and for patching ``config/selectors.yaml``), and
2. an optional ``VisionLocator`` is asked for click coordinates.

The demo ships without a vision model (``vision=None``) so a missing element is
a clean, logged failure. To plug one in, implement ``VisionLocator.locate`` (e.g.
send the PNG plus the key/description to a vision model and parse x/y) and pass
it to ``Agent(..., vision=MyVision())``.
"""
from __future__ import annotations

import logging
import re
import time
from pathlib import Path
from typing import Protocol

log = logging.getLogger("agent.fallback")


class VisionLocator(Protocol):
    def locate(self, screenshot: Path, target: str) -> tuple[float, float] | None:
        """Return viewport (x, y) of `target` in the screenshot, or None."""


class ScreenshotFallback:
    def __init__(self, out_dir: Path, vision: VisionLocator | None = None):
        self.out_dir = Path(out_dir)
        self.vision = vision

    def capture(self, page, label: str) -> Path | None:
        self.out_dir.mkdir(parents=True, exist_ok=True)
        safe = re.sub(r"[^a-zA-Z0-9_.-]+", "_", label)
        path = self.out_dir / f"{time.strftime('%H%M%S')}-{safe}.png"
        try:
            page.screenshot(path=str(path))
            return path
        except Exception as exc:  # pragma: no cover - best effort
            log.warning("screenshot failed: %s", exc)
            return None

    def locate(self, page, key: str, specs: list[dict]) -> tuple[float, float] | None:
        path = self.capture(page, key)
        log.warning("DOM lookup failed for '%s' (%d strategies); screenshot: %s", key, len(specs), path)
        if self.vision is None or path is None:
            return None
        point = self.vision.locate(path, key)
        if point:
            log.warning("vision fallback located '%s' at %s", key, point)
        return point
