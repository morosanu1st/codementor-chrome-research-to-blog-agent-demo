"""WordPress REST API publisher (Application Passwords; creates a draft)."""
from __future__ import annotations

import os

import requests

from ..errors import AgentError
from .base import BlogPost, DraftRef, Publisher


class WordPressRestPublisher(Publisher):
    name = "wordpress-rest"

    def __init__(self, site_url: str, user: str | None = None, app_password: str | None = None,
                 session: requests.Session | None = None, timeout_s: float = 30):
        self.site = site_url.rstrip("/")
        # Read from the environment at runtime; never written to run state or logs.
        self.user = user or os.environ.get("WP_USER")
        self.app_password = app_password or os.environ.get("WP_APP_PASSWORD")
        if not (self.user and self.app_password):
            raise AgentError("Set WP_USER and WP_APP_PASSWORD (a WordPress Application Password).")
        self.http = session or requests.Session()
        self.timeout_s = timeout_s

    def _post(self, path: str, payload: dict) -> dict:
        resp = self.http.post(f"{self.site}/wp-json/wp/v2/{path}", json=payload,
                              auth=(self.user, self.app_password), timeout=self.timeout_s)
        if resp.status_code >= 400:
            raise AgentError(f"WordPress REST {resp.status_code}: {resp.text[:300]}")
        return resp.json()

    def create_draft(self, post: BlogPost) -> DraftRef:
        data = self._post("posts", {"title": post.title, "content": post.html, "status": "draft"})
        pid = str(data["id"])
        return DraftRef(self.name, data.get("status", "draft"),
                        url=f"{self.site}/wp-admin/post.php?post={pid}&action=edit", post_id=pid,
                        extra={"preview": f"{self.site}/?p={pid}&preview=true"})

    def publish(self, draft: DraftRef) -> DraftRef:
        data = self._post(f"posts/{draft.post_id}", {"status": "publish"})
        return DraftRef(self.name, data.get("status", "publish"), url=data.get("link", draft.url),
                        post_id=draft.post_id)
