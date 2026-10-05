from __future__ import annotations

import textwrap
from abc import ABC, abstractmethod
from dataclasses import dataclass, field


@dataclass
class BlogPost:
    title: str
    html: str
    text: str

    @property
    def word_count(self) -> int:
        return len(self.text.split())


@dataclass
class DraftRef:
    platform: str
    status: str                     # "draft" | "publish"
    url: str | None = None
    post_id: str | None = None
    extra: dict = field(default_factory=dict)


class Publisher(ABC):
    """Every target (browser editor, REST API, ...) implements the same 2-phase contract:
    create_draft() is safe and reversible; publish() is only called after a human says yes."""

    name = "base"

    @abstractmethod
    def create_draft(self, post: BlogPost) -> DraftRef: ...

    @abstractmethod
    def publish(self, draft: DraftRef) -> DraftRef: ...

    def preview(self, post: BlogPost, draft: DraftRef) -> str:
        body = textwrap.shorten(" ".join(post.text.split()), width=600, placeholder=" …")
        return "\n".join([
            "-" * 72,
            f"Platform : {draft.platform}   status: {draft.status}",
            f"Draft    : {draft.url or '(n/a)'}",
            f"Title    : {post.title}",
            f"Length   : {post.word_count} words",
            "-" * 72,
            textwrap.fill(body, width=72),
            "-" * 72,
        ])
