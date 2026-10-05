"""Seven-step, resumable state machine: research in ChatGPT -> blog draft -> human confirm."""
from __future__ import annotations

import json
import logging
import sys
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Callable

from .browser import BrowserSession
from .chatgpt import ChatGPT, Extracted
from .command import Command
from .errors import AgentError, StepFailed
from .fallback import ScreenshotFallback, VisionLocator
from .locate import Resolver, load_selectors
from .publishers import (BloggerPublisher, BlogPost, DraftRef, Publisher,
                         WordPressBrowserPublisher, WordPressRestPublisher)
from .settings import Settings
from .wait import wait_for_completion

log = logging.getLogger("agent")


@dataclass
class Step:
    name: str
    title: str
    fn: Callable[[], None]
    retries: int = 2
    blog_only: bool = False


class RunState:
    """JSON file under runs/<id>/state.json; rewritten atomically after every step."""

    def __init__(self, run_dir: Path, data: dict):
        self.dir = Path(run_dir)
        self.data = data

    @classmethod
    def create(cls, runs_dir: Path, command: Command) -> "RunState":
        run_dir = Path(runs_dir) / time.strftime("%Y%m%d-%H%M%S")
        run_dir.mkdir(parents=True, exist_ok=True)
        st = cls(run_dir, {"command": command.raw, "topic": command.topic,
                           "wants_blog": command.wants_blog, "completed": []})
        st.save()
        return st

    @classmethod
    def load(cls, run_dir: Path) -> "RunState":
        run_dir = Path(run_dir)
        return cls(run_dir, json.loads((run_dir / "state.json").read_text(encoding="utf-8")))

    def save(self) -> None:
        tmp = self.dir / "state.json.tmp"
        tmp.write_text(json.dumps(self.data, indent=2), encoding="utf-8")
        tmp.replace(self.dir / "state.json")

    def done(self, step: str) -> None:
        self.data["completed"].append(step)
        self.save()

    def __getitem__(self, k):
        return self.data[k]

    def __setitem__(self, k, v):
        self.data[k] = v
        self.save()

    def get(self, k, default=None):
        return self.data.get(k, default)


@dataclass
class RunResult:
    run_dir: Path
    status: str
    completed: list[str] = field(default_factory=list)
    title: str | None = None
    draft: dict | None = None


def ask_publish(preview: str) -> bool:
    print(preview)
    if not sys.stdin.isatty():
        print("Non-interactive session -> leaving the post as a draft.")
        return False
    return input("Publish? [y/N] ").strip().lower() in ("y", "yes")


class Agent:
    def __init__(self, settings: Settings, command: Command, *, state: RunState | None = None,
                 confirm: Callable[[str], bool] = ask_publish, vision: VisionLocator | None = None,
                 stop_after: str | None = None):
        self.s = settings
        self.cmd = command
        self.state = state or RunState.create(settings.runs_dir, command)
        self.confirm = confirm
        self.stop_after = stop_after
        self.selectors = load_selectors(settings.selectors_path)
        self.fallback = ScreenshotFallback(self.state.dir / "screenshots", vision)
        self.session: BrowserSession | None = None
        self._chat: ChatGPT | None = None
        self._publisher: Publisher | None = None
        self.steps = [
            Step("open_chatgpt", "Open ChatGPT in your Chrome", self.step_open_chatgpt),
            Step("start_deep_research", "Start Deep Research on the topic", self.step_start_research),
            Step("wait_research", "Wait for Deep Research to finish", self.step_wait_research, retries=0),
            Step("extract_research", "Copy the full research result", self.step_extract_research),
            Step("write_blog", "Ask for a blog post and copy it", self.step_write_blog, blog_only=True),
            Step("create_draft", "Paste title + body into a new draft", self.step_create_draft, blog_only=True),
            Step("confirm_publish", "Ask 'Publish?' before the final click", self.step_confirm, retries=0,
                 blog_only=True),
        ]
        self._attach_file_log()

    def _attach_file_log(self) -> None:
        fh = logging.FileHandler(self.state.dir / "run.log", encoding="utf-8")
        fh.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
        logging.getLogger("agent").addHandler(fh)
        self._file_handler = fh

    # ------------------------------------------------------------------ driver
    def run(self) -> RunResult:
        try:
            with BrowserSession(self.s) as session:
                self.session = session
                total = len(self.steps)
                for i, step in enumerate(self.steps, 1):
                    if step.name in self.state["completed"]:
                        log.info("[%d/%d] %s - already done, skipping", i, total, step.name)
                        continue
                    if step.blog_only and not self.state["wants_blog"]:
                        log.info("[%d/%d] %s - no blog requested, skipping", i, total, step.name)
                        continue
                    self._run_step(i, total, step)
                    if self.stop_after == step.name:
                        log.info("stopping after %s (resume with --resume %s)", step.name, self.state.dir)
                        break
        finally:
            logging.getLogger("agent").removeHandler(self._file_handler)
            self._file_handler.close()
        return RunResult(self.state.dir, self.state.get("final_status", "incomplete"),
                         list(self.state["completed"]), (self.state.get("blog") or {}).get("title"),
                         self.state.get("draft"))

    def _run_step(self, i: int, total: int, step: Step) -> None:
        retries = min(step.retries, self.s.step_retries)
        for attempt in range(1, retries + 2):
            log.info("[%d/%d] %s: %s%s", i, total, step.name, step.title,
                     f" (attempt {attempt})" if attempt > 1 else "")
            t0 = time.monotonic()
            try:
                step.fn()
                self.state.done(step.name)
                log.info("[%d/%d] %s ok (%.1fs)", i, total, step.name, time.monotonic() - t0)
                return
            except Exception as exc:
                page = self._chat.page if self._chat else None
                if page is not None:
                    self.fallback.capture(page, f"fail-{step.name}-{attempt}")
                retryable = getattr(exc, "retryable", True)
                log.error("[%d/%d] %s failed: %s", i, total, step.name, exc)
                if not retryable or attempt > retries:
                    raise StepFailed(f"step '{step.name}' failed: {exc}. "
                                     f"Fix and re-run with --resume {self.state.dir}") from exc
                if page is not None:
                    try:
                        page.keyboard.press("Escape")
                    except Exception:
                        pass
                time.sleep(self.s.retry_backoff_s * attempt)

    # ------------------------------------------------------------------ helpers
    def chat(self) -> ChatGPT:
        if self._chat is None:
            page = self.session.new_page()
            chat = ChatGPT(page, Resolver(page, self.selectors, self.fallback, self.s.action_timeout_ms),
                           self.selectors)
            try:
                # On resume, reopen the same conversation; Deep Research keeps running server-side.
                saved = self.state.get("chat_url") if self.s.mode != "mock" else None
                chat.open(saved or self.s.chatgpt_url)
            except Exception:
                self.fallback.capture(page, "open-chatgpt")
                page.close()
                raise
            self._chat = chat
        return self._chat

    def publisher(self) -> Publisher:
        if self._publisher is None:
            platform = self.cmd.platform or self.s.platform
            if platform == "wordpress":
                self._publisher = WordPressBrowserPublisher(self.session.new_page, self.selectors,
                                                            self.s.new_post_url, self.fallback,
                                                            self.s.action_timeout_ms)
            elif platform == "wordpress-rest":
                self._publisher = WordPressRestPublisher(self.s.wp_url)
            elif platform == "blogger":
                self._publisher = BloggerPublisher(self.s.blogger_blog_id)
            else:
                raise AgentError(f"unknown platform {platform}")
        return self._publisher

    def _extract(self) -> Extracted:
        chat = self.chat()
        if self.s.extract == "copy":
            try:
                return chat.copy_last()
            except Exception as exc:
                log.warning("copy-button path failed (%s); falling back to DOM", exc)
        return chat.extract_last()

    def _write(self, name: str, content: str) -> str:
        path = self.state.dir / name
        path.write_text(content, encoding="utf-8")
        return str(path)

    def _post(self) -> BlogPost:
        b = self.state["blog"]
        return BlogPost(b["title"], Path(b["html_file"]).read_text(encoding="utf-8"),
                        Path(b["text_file"]).read_text(encoding="utf-8"))

    # ------------------------------------------------------------------ steps 1-7
    def step_open_chatgpt(self) -> None:
        self.chat()

    def step_start_research(self) -> None:
        chat = self.chat()
        if not self.state.get("research_prompt_sent"):
            self.state["research_baseline"] = chat.assistant_count()
            if self.s.deep_research:
                chat.enable_deep_research()
            chat.send(self.s.research_prompt.format(topic=self.state["topic"]))
            self.state["research_prompt_sent"] = True   # never re-send on retry
        chat.wait_started(self.state["research_baseline"])
        self.state["chat_url"] = chat.page.url

    def step_wait_research(self) -> None:
        chat = self.chat()

        def on_clarify(_question: str) -> int:
            baseline = chat.assistant_count()
            chat.send(self.s.clarify_reply)
            self.state["research_baseline"] = baseline
            return baseline

        res = wait_for_completion(chat, self.state["research_baseline"], self.s.research_wait,
                                  label="Deep Research", on_clarify=on_clarify)
        self.state["research_chars"] = len(res.text)
        self.state["chat_url"] = chat.page.url

    def step_extract_research(self) -> None:
        ex = self._extract()
        if not ex.text:
            raise AgentError("research result is empty")
        self.state["research"] = {"text_file": self._write("research.md", ex.text),
                                  "html_file": self._write("research.html", ex.html),
                                  "chars": len(ex.text), "via": ex.source}
        log.info("research captured: %d chars via %s", len(ex.text), ex.source)

    def step_write_blog(self) -> None:
        chat = self.chat()
        if not self.state.get("blog_prompt_sent"):
            self.state["blog_baseline"] = chat.assistant_count()
            chat.disable_deep_research()
            chat.send(self.s.blog_prompt)
            self.state["blog_prompt_sent"] = True
        wait_for_completion(chat, self.state["blog_baseline"], self.s.blog_wait, label="Blog post")
        ex = self._extract()
        title, text = ex.title, ex.text
        if not title:
            first, _, rest = text.partition("\n")
            title, text = first.lstrip("# ").strip(), rest
        lines = text.strip().splitlines()
        if lines and lines[0].lstrip("# ").strip() == title:   # drop a duplicated title line
            lines = lines[1:]
        body_text = "\n".join(lines).strip()
        self.state["blog"] = {"title": title, "text_file": self._write("blog.md", body_text),
                              "html_file": self._write("blog.html", ex.html)}
        log.info("blog captured: '%s' (%d words)", title, len(body_text.split()))

    def step_create_draft(self) -> None:
        draft = self.publisher().create_draft(self._post())
        self.state["draft"] = asdict(draft)
        log.info("draft saved: %s", draft.url)

    def step_confirm(self) -> None:
        post, draft = self._post(), DraftRef(**self.state["draft"])
        if self.confirm(self.publisher().preview(post, draft)):
            published = self.publisher().publish(draft)
            self.state["draft"] = asdict(published)
            self.state["final_status"] = "published"
            log.info("published: %s", published.url)
        else:
            self.state["final_status"] = "draft"
            log.info("left as draft (nothing published): %s", draft.url)
