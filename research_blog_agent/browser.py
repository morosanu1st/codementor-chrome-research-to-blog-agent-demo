"""Browser session: attach to the user's Chrome (CDP), launch a persistent profile, or mock."""
from __future__ import annotations

import functools
import http.server
import logging
import threading
from pathlib import Path

from playwright.sync_api import sync_playwright

from .errors import AgentError
from .settings import ROOT, Settings

log = logging.getLogger("agent.browser")
MOCK_DIR = ROOT / "mock"


class MockServer:
    """Serves mock/ (fake chat + fake editor) on 127.0.0.1 with a random port."""

    def __init__(self, directory: Path = MOCK_DIR):
        handler = functools.partial(_QuietHandler, directory=str(directory))
        self.httpd = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)

    @property
    def base_url(self) -> str:
        return f"http://127.0.0.1:{self.httpd.server_address[1]}"

    def start(self) -> "MockServer":
        self.thread.start()
        return self

    def stop(self) -> None:
        self.httpd.shutdown()
        self.httpd.server_close()


class _QuietHandler(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *args):  # noqa: D401
        pass


class BrowserSession:
    def __init__(self, settings: Settings):
        self.s = settings
        self._pw = self.browser = self.context = self._server = None

    def __enter__(self) -> "BrowserSession":
        self._pw = sync_playwright().start()
        mode = self.s.mode
        if mode == "mock":
            self._server = MockServer().start()
            self.s.apply_mock(self._server.base_url)
            self.browser = self._pw.chromium.launch(headless=self.s.headless)
            self.context = self.browser.new_context(viewport={"width": 1280, "height": 900})
            log.info("mock mode: %s", self._server.base_url)
        elif mode == "launch":
            Path(self.s.user_data_dir).mkdir(parents=True, exist_ok=True)
            self.context = self._pw.chromium.launch_persistent_context(
                str(self.s.user_data_dir), channel=self.s.chrome_channel, headless=False,
                no_viewport=True)
            log.info("launched Chrome with profile %s", self.s.user_data_dir)
        else:
            try:
                self.browser = self._pw.chromium.connect_over_cdp(self.s.cdp_url)
            except Exception as exc:
                self._pw.stop()
                raise AgentError(
                    f"Could not attach to Chrome at {self.s.cdp_url}. Start it with "
                    "scripts/start_chrome_debug.ps1 (Windows) or scripts/start_chrome_debug.sh, "
                    "or use --launch.") from exc
            self.context = self.browser.contexts[0] if self.browser.contexts else self.browser.new_context()
            log.info("attached to your Chrome via CDP (%s)", self.s.cdp_url)
        return self

    def new_page(self):
        page = self.context.new_page()
        page.set_default_timeout(self.s.action_timeout_ms)
        return page

    def __exit__(self, *exc) -> None:
        try:
            if self.s.mode == "mock":
                self.context.close()
                self.browser.close()
            elif self.s.mode == "launch":
                self.context.close()
            # CDP: leave the user's browser and tabs exactly as they are; just disconnect.
        finally:
            self._pw.stop()
            if self._server:
                self._server.stop()
