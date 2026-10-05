"""WordPress (Gutenberg) publisher driven through the user's logged-in browser."""
from __future__ import annotations

import logging
import time
from typing import Callable

from ..errors import AgentError, NotLoggedIn
from ..fallback import ScreenshotFallback
from ..locate import Resolver
from .base import BlogPost, DraftRef, Publisher

log = logging.getLogger("agent.wordpress")

# Gutenberg handles paste events itself (HTML -> blocks). Dispatching a synthetic
# ClipboardEvent with a DataTransfer is a real "paste" without touching the OS clipboard.
_PASTE_JS = """
([html, text]) => {
  const el = document.activeElement;
  if (!el || !el.isContentEditable) return false;
  const dt = new DataTransfer();
  dt.setData('text/html', html);
  dt.setData('text/plain', text);
  el.dispatchEvent(new ClipboardEvent('paste', {clipboardData: dt, bubbles: true, cancelable: true}));
  return true;
}
"""

_WP_DATA_JS = """
(html) => {
  const wp = window.wp;
  if (!wp || !wp.data || !wp.blocks) return false;
  wp.data.dispatch('core/block-editor').resetBlocks(wp.blocks.rawHandler({ HTML: html }));
  return true;
}
"""

_READ_JS = "el => (el.value !== undefined ? el.value : el.innerText).trim()"


class WordPressBrowserPublisher(Publisher):
    name = "wordpress"

    def __init__(self, new_page: Callable[[], object], selectors: dict, new_post_url: str,
                 fallback: ScreenshotFallback | None = None, timeout_ms: int = 15_000):
        self._new_page = new_page
        self.selectors = selectors
        self.new_post_url = new_post_url
        self.fallback = fallback
        self.timeout_ms = timeout_ms
        self.page = None

    def _page(self):
        if self.page is None:
            self.page = self._new_page()
        return self.page

    def _resolver(self) -> Resolver:
        return Resolver(self.page, self.selectors, self.fallback, self.timeout_ms)

    def _canvas(self):
        name = self.selectors.get("wordpress", {}).get("editor_frame_name")
        frame = self.page.frame(name=name) if name else None
        return frame or self.page

    def _content_len(self, r: Resolver, scope) -> int:
        area = r.all("wordpress.content_area", scope=scope)
        return len(area.first.inner_text()) if area.count() else 0

    # -------------------------------------------------------------------
    def create_draft(self, post: BlogPost) -> DraftRef:
        page = self._page()
        log.info("opening editor %s", self.new_post_url)
        page.goto(self.new_post_url, wait_until="domcontentloaded")
        if "wp-login.php" in page.url:
            raise NotLoggedIn("WordPress is not logged in in this browser profile.")
        r = self._resolver()

        modal = r.find("wordpress.dismiss_modal", timeout_ms=3_000, required=False)
        if modal is not None:
            modal.click()
            log.info("dismissed editor welcome dialog")

        scope = self._canvas()
        r.click("wordpress.title", scope=scope, timeout_ms=30_000)
        page.keyboard.insert_text(post.title)

        body = r.find("wordpress.body", scope=scope, timeout_ms=3_000, required=False)
        if body is not None:
            body.click()
        else:
            page.keyboard.press("Enter")  # Enter in the title creates + focuses a paragraph block

        method = self._paste(r, scope, post)
        log.info("body inserted via %s", method)

        r.click("wordpress.save_draft")
        r.find("wordpress.saved_indicator", timeout_ms=30_000)

        readback = self._readback(r, scope)
        ok = readback["title"] == post.title.strip() and readback["body_chars"] > 0
        (log.info if ok else log.warning)("read-back check: %s", readback)
        return DraftRef(self.name, "draft", url=page.url,
                        extra={"paste_method": method, "readback": readback, "verified": ok})

    def _paste(self, r: Resolver, scope, post: BlogPost) -> str:
        before = self._content_len(r, scope)
        if scope.evaluate(_PASTE_JS, [post.html, post.text]):
            deadline = time.monotonic() + 5
            while time.monotonic() < deadline:
                if self._content_len(r, scope) > before:
                    return "synthetic-paste"
                time.sleep(0.2)
        if self.page.evaluate(_WP_DATA_JS, post.html):
            return "wp-data-api"
        self.page.keyboard.insert_text(post.text)
        return "keyboard-text"

    def _readback(self, r: Resolver, scope) -> dict:
        title_el = r.find("wordpress.title", scope=scope, timeout_ms=2_000, required=False)
        title = title_el.evaluate(_READ_JS) if title_el is not None else ""
        return {"title": title, "body_chars": self._content_len(r, scope)}

    def publish(self, draft: DraftRef) -> DraftRef:
        page = self._page()
        if draft.url and page.url != draft.url:
            page.goto(draft.url, wait_until="domcontentloaded")
        r = self._resolver()
        r.click("wordpress.publish_button")
        confirm = r.find("wordpress.publish_confirm", timeout_ms=10_000, required=False)
        if confirm is not None:
            confirm.click()
        if r.find("wordpress.published_indicator", timeout_ms=30_000, required=False) is None:
            raise AgentError("Publish clicked but no confirmation appeared; check the editor.")
        return DraftRef(self.name, "publish", url=page.url, extra=draft.extra)
