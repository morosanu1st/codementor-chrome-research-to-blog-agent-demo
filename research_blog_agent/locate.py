"""Resolve keys from config/selectors.yaml into Playwright locators."""
from __future__ import annotations

import logging
import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml
from playwright.sync_api import Error as PWError

from .errors import LocatorNotFound
from .fallback import ScreenshotFallback

log = logging.getLogger("agent.locate")
DEFAULT_SELECTORS = Path(__file__).resolve().parent.parent / "config" / "selectors.yaml"


def load_selectors(path: str | Path | None = None) -> dict:
    with open(path or DEFAULT_SELECTORS, encoding="utf-8") as fh:
        return yaml.safe_load(fh)


def _pat(value: Any):
    if isinstance(value, str) and value.startswith("re:"):
        return re.compile(value[3:], re.IGNORECASE)
    return value


def build_locator(scope, spec: dict):
    base = scope.locator(spec["within"]) if "within" in spec else scope
    if "role" in spec:
        kwargs = {"name": _pat(spec["name"])} if "name" in spec else {}
        return base.get_by_role(spec["role"], **kwargs)
    if "test_id" in spec:
        return base.get_by_test_id(spec["test_id"])
    if "label" in spec:
        return base.get_by_label(_pat(spec["label"]))
    if "placeholder" in spec:
        return base.get_by_placeholder(_pat(spec["placeholder"]))
    if "text" in spec:
        return base.get_by_text(_pat(spec["text"]))
    if "css" in spec:
        return base.locator(spec["css"])
    raise ValueError(f"Unknown selector strategy: {spec}")


@dataclass
class PointTarget:
    """Click target produced by the vision fallback (coordinates, not DOM)."""

    page: Any
    x: float
    y: float
    key: str

    def click(self, **_):
        self.page.mouse.click(self.x, self.y)


class Resolver:
    def __init__(self, page, selectors: dict, fallback: ScreenshotFallback | None = None,
                 default_timeout_ms: int = 10_000):
        self.page = page
        self.selectors = selectors
        self.fallback = fallback
        self.default_timeout_ms = default_timeout_ms

    def specs(self, key: str) -> list[dict]:
        node: Any = self.selectors
        for part in key.split("."):
            if not isinstance(node, dict) or part not in node:
                raise KeyError(f"selector key '{key}' not in selectors config")
            node = node[part]
        return node if isinstance(node, list) else [node]

    def _first_visible(self, scope, spec: dict):
        try:
            loc = build_locator(scope, spec)
            for i in range(min(loc.count(), 10)):
                cand = loc.nth(i)
                if cand.is_visible():
                    return cand
        except PWError:
            return None
        return None

    def find(self, key: str, *, scope=None, timeout_ms: int | None = None, required: bool = True):
        scope = scope or self.page
        specs = self.specs(key)
        timeout = (self.default_timeout_ms if timeout_ms is None else timeout_ms) / 1000
        deadline = time.monotonic() + timeout
        while True:
            for spec in specs:
                hit = self._first_visible(scope, spec)
                if hit is not None:
                    return hit
            if time.monotonic() >= deadline:
                break
            time.sleep(0.25)
        if not required:
            return None
        if self.fallback is not None:
            point = self.fallback.locate(self.page, key, specs)
            if point:
                return PointTarget(self.page, point[0], point[1], key)
        raise LocatorNotFound(f"no visible element for '{key}' (tried {len(specs)} strategies)")

    def visible(self, key: str, *, scope=None) -> bool:
        scope = scope or self.page
        return any(self._first_visible(scope, s) is not None for s in self.specs(key))

    def all(self, key: str, *, scope=None):
        scope = scope or self.page
        specs = self.specs(key)
        for spec in specs:
            loc = build_locator(scope, spec)
            try:
                if loc.count() > 0:
                    return loc
            except PWError:
                continue
        return build_locator(scope, specs[0])

    def click(self, key: str, **kwargs):
        target = self.find(key, **kwargs)
        target.click()
        return target
