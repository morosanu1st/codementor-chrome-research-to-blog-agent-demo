"""Parse a one-line natural command into a structured intent."""
from __future__ import annotations

import re
from dataclasses import dataclass

_PATTERN = re.compile(
    r"""^\s*(?:please\s+)?(?:do\s+)?(?:a\s+)?(?:deep\s+)?research(?:\s+on|\s+about)?\s+
        (?P<topic>.+?)
        (?P<blog>
          (?:\s*,\s*|\s+)(?:(?:and|then|&)\s+)*
          (?:post|publish|write|create|make|turn\s+it\s+into)\s+(?:it\s+)?(?:as\s+|to\s+|into\s+)?(?:an?\s+)?
          (?:blog(?:\s+post)?|post|article)
          (?:\s+(?:on|to)\s+(?P<platform>wordpress|blogger))?
        )?
        \s*[.!]?\s*$""",
    re.IGNORECASE | re.VERBOSE,
)


@dataclass(frozen=True)
class Command:
    raw: str
    topic: str
    wants_blog: bool
    platform: str | None = None


class CommandError(ValueError):
    pass


def parse_command(text: str) -> Command:
    m = _PATTERN.match(text or "")
    if not m:
        raise CommandError('Could not understand the command. Try: "research <topic> and post a blog"')
    topic = m.group("topic").strip().strip("\"'").strip()
    if not topic:
        raise CommandError("Topic is empty.")
    platform = m.group("platform").lower() if m.group("platform") else None
    return Command(raw=text, topic=topic, wants_blog=m.group("blog") is not None, platform=platform)
