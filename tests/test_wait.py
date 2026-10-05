import pytest

from research_blog_agent.errors import WaitTimeout
from research_blog_agent.wait import WaitConfig, wait_for_completion


class FakeClock:
    def __init__(self):
        self.t = 0.0

    def __call__(self):
        return self.t

    def sleep(self, s):
        self.t += s


class ScriptedChat:
    """Plays back a timeline of (until_t, busy, messages) to emulate a 20-minute Deep Research run."""

    def __init__(self, clock, timeline):
        self.clock, self.timeline, self.sent = clock, timeline, []

    def _now(self):
        for until, busy, msgs in self.timeline:
            if self.clock() < until:
                return busy, msgs
        return self.timeline[-1][1:]

    def is_busy(self):
        return self._now()[0]

    def assistant_count(self):
        return len(self._now()[1])

    def last_assistant_text(self):
        msgs = self._now()[1]
        return msgs[-1] if msgs else ""


CFG = WaitConfig(max_wait_s=35 * 60, poll_s=5, stable_s=20, min_chars=100, progress_every_s=60)
REPORT = "R" * 500


def test_long_research_with_clarification():
    clock = FakeClock()
    q = "Should I focus on free or paid tools?"
    chat = ScriptedChat(clock, [
        (30, True, [q[:10]]),               # streaming the question
        (60, False, [q]),                   # idle question -> agent must answer
        (20 * 60, True, [q]),               # researching for ~20 min (busy, no new message)
        (21 * 60, True, [q, REPORT[:200]]), # streaming the report
        (10 ** 9, False, [q, REPORT]),      # finished
    ])
    answered = []
    res = wait_for_completion(chat, 0, CFG, on_clarify=lambda t: answered.append(t) or 1,
                              clock=clock, sleep=clock.sleep)
    assert answered == [q]
    assert res.text == REPORT and res.clarifications == 1
    assert 21 * 60 <= res.elapsed_s < 22 * 60


def test_timeout_is_reported():
    clock = FakeClock()
    chat = ScriptedChat(clock, [(10 ** 9, True, [])])
    with pytest.raises(WaitTimeout):
        wait_for_completion(chat, 0, CFG, clock=clock, sleep=clock.sleep)
