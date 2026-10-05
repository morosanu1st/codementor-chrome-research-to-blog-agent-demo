from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from .wait import WaitConfig

ROOT = Path(__file__).resolve().parent.parent

BLOG_PROMPT = ("Turn this into a blog post. Start with a single H1 title, then an intro, "
               "H2 sections and a short conclusion, in Markdown.")
CLARIFY_REPLY = ("No further clarification needed - use your best judgment on scope and "
                 "proceed with the full research now.")


@dataclass
class Settings:
    mode: str = "cdp"                       # cdp | launch | mock
    cdp_url: str = "http://127.0.0.1:9222"
    user_data_dir: Path = Path.home() / ".research-blog-agent" / "chrome-profile"
    chrome_channel: str | None = "chrome"   # installed Google Chrome (None = bundled Chromium)
    headless: bool = False

    chatgpt_url: str = "https://chatgpt.com/"
    deep_research: bool = True
    research_prompt: str = "{topic}"
    blog_prompt: str = BLOG_PROMPT
    clarify_reply: str = CLARIFY_REPLY
    extract: str = "dom"                    # dom | copy

    platform: str = "wordpress"             # wordpress | wordpress-rest | blogger
    wp_url: str = "http://localhost:8080"   # a TEST WordPress site
    editor_url: str | None = None           # override the new-post URL (mock mode)
    blogger_blog_id: str | None = None

    selectors_path: Path | None = None
    runs_dir: Path = ROOT / "runs"
    action_timeout_ms: int = 15_000
    step_retries: int = 2
    retry_backoff_s: float = 3.0

    research_wait: WaitConfig = field(default_factory=WaitConfig)
    blog_wait: WaitConfig = field(default_factory=lambda: WaitConfig(
        max_wait_s=6 * 60, poll_s=2, stable_s=6, min_chars=300, idle_accept_s=30, auto_clarify=False))

    @property
    def new_post_url(self) -> str:
        return self.editor_url or f"{self.wp_url.rstrip('/')}/wp-admin/post-new.php"

    def apply_mock(self, base_url: str) -> None:
        """Point everything at the local mock pages and shrink the timings."""
        self.chatgpt_url = f"{base_url}/chat.html?tick=8&research_ms=1200"
        self.editor_url = f"{base_url}/editor.html"
        self.platform = "wordpress"
        self.retry_backoff_s = 0.2
        self.research_wait = WaitConfig(max_wait_s=90, poll_s=0.2, stable_s=0.8, min_chars=400,
                                        progress_every_s=1.0, clarify_max_chars=600)
        self.blog_wait = WaitConfig(max_wait_s=60, poll_s=0.2, stable_s=0.8, min_chars=200,
                                    idle_accept_s=5, progress_every_s=1.0, auto_clarify=False)
