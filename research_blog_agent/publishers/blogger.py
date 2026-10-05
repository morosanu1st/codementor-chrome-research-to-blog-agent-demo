"""Blogger publisher - stubbed in this demo.

Two ways to finish it:
  * Browser: add a `blogger:` section to config/selectors.yaml (title box,
    compose body, "Save"/"Publish" buttons) and reuse the WordPressBrowserPublisher
    flow (open editor -> fill title -> synthetic paste -> save -> human confirm).
  * API: Blogger API v3 `posts.insert(blogId, isDraft=True)` with OAuth, then
    `posts.publish` after confirmation.
"""
from __future__ import annotations

from ..errors import AgentError
from .base import BlogPost, DraftRef, Publisher


class BloggerPublisher(Publisher):
    name = "blogger"

    def __init__(self, blog_id: str | None = None):
        self.blog_id = blog_id

    def create_draft(self, post: BlogPost) -> DraftRef:
        raise AgentError("Blogger publisher is a documented stub in this demo; use --platform wordpress "
                         "or wordpress-rest (see research_blog_agent/publishers/blogger.py).")

    def publish(self, draft: DraftRef) -> DraftRef:  # pragma: no cover
        raise AgentError("Blogger publisher is a stub.")
