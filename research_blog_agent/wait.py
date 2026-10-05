"""Long-wait completion detection (Deep Research can run 5-30 minutes).

A reply is considered finished when ALL of these hold:
  * a new assistant message exists (count > baseline),
  * no busy indicator is visible (stop button, "Researching..." status),
  * the message text has not changed for `stable_s` seconds,
  * the text is at least `min_chars` long (so a short "starting research..."
    acknowledgement is never mistaken for the report).

Deep Research often first asks clarifying questions. If the idle message is
short and contains a question, `on_clarify` is called (once by default) to send
a "proceed with your best judgment" reply, and waiting continues.
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import Callable, Protocol

from .errors import WaitTimeout

log = logging.getLogger("agent.wait")


@dataclass
class WaitConfig:
    max_wait_s: float = 35 * 60
    poll_s: float = 5.0
    stable_s: float = 20.0
    min_chars: int = 1500
    idle_accept_s: float | None = None   # accept a short idle reply after N s (None = never)
    progress_every_s: float = 30.0
    auto_clarify: bool = True
    max_clarifications: int = 1
    clarify_max_chars: int = 1200


class ChatProbe(Protocol):
    def is_busy(self) -> bool: ...
    def assistant_count(self) -> int: ...
    def last_assistant_text(self) -> str: ...


@dataclass
class WaitResult:
    text: str
    baseline: int
    elapsed_s: float
    clarifications: int


def looks_like_clarification(text: str, max_chars: int) -> bool:
    t = text.strip()
    return 0 < len(t) <= max_chars and "?" in t


def wait_for_completion(
    probe: ChatProbe,
    baseline: int,
    cfg: WaitConfig,
    *,
    label: str = "reply",
    on_clarify: Callable[[str], int] | None = None,
    clock: Callable[[], float] = time.monotonic,
    sleep: Callable[[float], None] = time.sleep,
) -> WaitResult:
    start = clock()
    last_text: str | None = None
    last_change = start
    last_progress = start
    clarifications = 0

    while True:
        now = clock()
        busy = probe.is_busy()
        count = probe.assistant_count()
        text = probe.last_assistant_text() if count > baseline else ""
        if text != last_text:
            last_text, last_change = text, now
        stable_for = now - last_change

        if count > baseline and not busy and stable_for >= cfg.stable_s:
            if len(text) >= cfg.min_chars:
                log.info("%s complete: %d chars after %.0fs", label, len(text), now - start)
                return WaitResult(text, baseline, now - start, clarifications)
            if (on_clarify and cfg.auto_clarify and clarifications < cfg.max_clarifications
                    and looks_like_clarification(text, cfg.clarify_max_chars)):
                clarifications += 1
                log.info("%s asked a clarifying question; answering and continuing", label)
                baseline = on_clarify(text)
                last_text, last_change = None, clock()
                continue
            if cfg.idle_accept_s is not None and stable_for >= cfg.idle_accept_s:
                log.info("%s idle for %.0fs; accepting %d chars", label, stable_for, len(text))
                return WaitResult(text, baseline, now - start, clarifications)

        if now - start >= cfg.max_wait_s:
            raise WaitTimeout(
                f"{label} not finished after {cfg.max_wait_s / 60:.1f} min "
                f"(busy={busy}, chars={len(text)}). Re-run with --resume to keep waiting."
            )
        if now - last_progress >= cfg.progress_every_s:
            last_progress = now
            state = "working" if busy else ("settling" if count > baseline else "waiting")
            log.info("  … %s %s: %02d:%02d elapsed, %d chars so far", label, state,
                     int(now - start) // 60, int(now - start) % 60, len(text))
        sleep(cfg.poll_s)
