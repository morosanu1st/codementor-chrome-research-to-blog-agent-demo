"""ChatGPT (web) driver: DOM-first, no clipboard dependency by default."""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass

from .errors import AgentError, NotLoggedIn
from .locate import Resolver

log = logging.getLogger("agent.chatgpt")

_EXTRACT_JS = """
(el, bodyCss) => {
  const root = el.querySelector(bodyCss) || el;
  const clone = root.cloneNode(true);
  clone.querySelectorAll('button, svg, [aria-hidden="true"]').forEach(n => n.remove());
  const heading = clone.querySelector('h1, h2');
  let title = '';
  if (heading) { title = heading.textContent.trim(); heading.remove(); }
  return { text: root.innerText, html: clone.innerHTML.trim(), title };
}
"""


@dataclass
class Extracted:
    text: str
    html: str
    title: str = ""
    source: str = "dom"


class ChatGPT:
    def __init__(self, page, resolver: Resolver, selectors: dict):
        self.page = page
        self.r = resolver
        self.body_css = selectors.get("chatgpt", {}).get("message_body_css", ".markdown")

    # -- navigation -------------------------------------------------------
    def open(self, url: str) -> None:
        log.info("opening %s", url)
        self.page.goto(url, wait_until="domcontentloaded")
        self.r.find("chatgpt.composer", timeout_ms=30_000)
        if self.r.visible("chatgpt.logged_out_markers"):
            raise NotLoggedIn("ChatGPT is not logged in in this Chrome profile. "
                              "Log in once in that window, then re-run (or --resume).")

    # -- composer ---------------------------------------------------------
    def enable_deep_research(self) -> None:
        if self.r.visible("chatgpt.deep_research_active"):
            log.info("Deep Research already selected")
            return
        self.r.click("chatgpt.tools_menu_button")
        self.r.click("chatgpt.deep_research_option")
        if self.r.find("chatgpt.deep_research_active", timeout_ms=5_000, required=False) is None:
            log.warning("could not confirm the Deep Research pill; continuing")
        else:
            log.info("Deep Research selected")

    def disable_deep_research(self) -> None:
        btn = self.r.find("chatgpt.deep_research_remove", timeout_ms=1_000, required=False)
        if btn is not None:
            btn.click()
            log.info("Deep Research mode cleared for follow-up prompt")

    def send(self, text: str) -> None:
        box = self.r.find("chatgpt.composer")
        box.click()
        self.page.keyboard.insert_text(text)
        btn = self.r.find("chatgpt.send_button", timeout_ms=5_000, required=False)
        if btn is not None:
            btn.click()
        else:
            self.page.keyboard.press("Enter")
        log.info("sent prompt (%d chars)", len(text))

    def wait_started(self, baseline: int, timeout_s: float = 60) -> None:
        deadline = time.monotonic() + timeout_s
        while time.monotonic() < deadline:
            if self.is_busy() or self.assistant_count() > baseline:
                return
            time.sleep(0.5)
        raise AgentError("ChatGPT did not start answering within %ds" % timeout_s)

    # -- ChatProbe ----------------------------------------------------------
    def is_busy(self) -> bool:
        return self.r.visible("chatgpt.busy_indicators")

    def _messages(self):
        return self.r.all("chatgpt.assistant_messages")

    def assistant_count(self) -> int:
        return self._messages().count()

    def last_assistant_text(self) -> str:
        msgs = self._messages()
        n = msgs.count()
        return msgs.nth(n - 1).inner_text() if n else ""

    # -- extraction -----------------------------------------------------------
    def extract_last(self) -> Extracted:
        msgs = self._messages()
        n = msgs.count()
        if not n:
            raise AgentError("no assistant message to extract")
        data = msgs.nth(n - 1).evaluate(_EXTRACT_JS, self.body_css)
        return Extracted(text=data["text"].strip(), html=data["html"], title=data["title"], source="dom")

    def copy_last(self) -> Extracted:
        """Alternative path: click the turn's Copy button and read the clipboard (Markdown)."""
        try:
            self.page.context.grant_permissions(["clipboard-read", "clipboard-write"])
        except Exception as exc:  # CDP default context may refuse; reading may still work
            log.debug("grant_permissions failed: %s", exc)
        buttons = self.r.all("chatgpt.copy_button")
        if buttons.count() == 0:
            raise AgentError("no copy button found")
        buttons.nth(buttons.count() - 1).click()
        md = self.page.evaluate("() => navigator.clipboard.readText()")
        import markdown as mdlib

        title, body_md = split_markdown_title(md)
        return Extracted(text=md.strip(), html=mdlib.markdown(body_md, extensions=["extra"]),
                         title=title, source="copy")


def split_markdown_title(md: str) -> tuple[str, str]:
    lines = md.strip().splitlines()
    for i, line in enumerate(lines):
        if line.strip():
            if line.lstrip().startswith("#"):
                return line.lstrip("# ").strip(), "\n".join(lines[i + 1:]).strip()
            return "", md.strip()
    return "", ""
