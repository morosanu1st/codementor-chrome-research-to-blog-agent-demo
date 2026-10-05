#!/usr/bin/env python3
"""One command -> ChatGPT Deep Research -> blog post -> draft in your blog -> "Publish?".

    python agent.py "research best SEO tools 2026 and post a blog"
    python agent.py --dry-run "research best SEO tools 2026 and post a blog"
"""
from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from research_blog_agent.command import CommandError, parse_command
from research_blog_agent.errors import AgentError
from research_blog_agent.pipeline import Agent, RunState
from research_blog_agent.settings import Settings

STEPS = ["open_chatgpt", "start_deep_research", "wait_research", "extract_research",
         "write_blog", "create_draft", "confirm_publish"]


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("command", nargs="?", help='e.g. "research best SEO tools 2026 and post a blog"')
    mode = ap.add_mutually_exclusive_group()
    mode.add_argument("--launch", action="store_true",
                      help="launch Chrome with a persistent profile instead of attaching via CDP")
    mode.add_argument("--dry-run", "--mock", dest="mock", action="store_true",
                      help="run the whole pipeline against the local mock pages (no accounts)")
    ap.add_argument("--cdp-url", default="http://127.0.0.1:9222")
    ap.add_argument("--user-data-dir", type=Path, help="profile dir for --launch")
    ap.add_argument("--chromium", action="store_true", help="--launch bundled Chromium instead of Chrome")
    ap.add_argument("--headed", action="store_true", help="show the browser in --dry-run")
    ap.add_argument("--platform", choices=["wordpress", "wordpress-rest", "blogger"])
    ap.add_argument("--wp-url", default="http://localhost:8080", help="test WordPress site URL")
    ap.add_argument("--max-wait-min", type=float, default=35.0, help="max Deep Research wait (minutes)")
    ap.add_argument("--no-deep-research", action="store_true", help="plain prompt (faster, for testing)")
    ap.add_argument("--extract", choices=["dom", "copy"], default="dom",
                    help="read the answer from the DOM (default) or via the Copy button + clipboard")
    ap.add_argument("--selectors", type=Path, help="alternative selectors YAML")
    ap.add_argument("--runs-dir", type=Path)
    ap.add_argument("--resume", type=Path, metavar="RUN_DIR", help="continue a previous run")
    ap.add_argument("--stop-after", choices=STEPS)
    ap.add_argument("-v", "--verbose", action="store_true")
    return ap


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO,
                        format="%(asctime)s %(message)s", datefmt="%H:%M:%S")
    logging.getLogger("agent").setLevel(logging.DEBUG if args.verbose else logging.INFO)

    state = RunState.load(args.resume) if args.resume else None
    raw = state["command"] if state else args.command
    if not raw:
        build_parser().error("a command is required (or --resume RUN_DIR)")
    try:
        cmd = parse_command(raw)
    except CommandError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    s = Settings(mode="mock" if args.mock else "launch" if args.launch else "cdp",
                 cdp_url=args.cdp_url, headless=args.mock and not args.headed,
                 wp_url=args.wp_url, deep_research=not args.no_deep_research, extract=args.extract,
                 selectors_path=args.selectors, chrome_channel=None if args.chromium else "chrome")
    if args.user_data_dir:
        s.user_data_dir = args.user_data_dir
    if args.runs_dir:
        s.runs_dir = args.runs_dir
    if args.platform:
        s.platform = args.platform
    s.research_wait.max_wait_s = args.max_wait_min * 60

    print(f'Topic: "{cmd.topic}"  blog: {cmd.wants_blog}  platform: {cmd.platform or s.platform}  mode: {s.mode}', flush=True)
    try:
        result = Agent(s, cmd, state=state, stop_after=args.stop_after).run()
    except AgentError as exc:
        print(f"\nFAILED: {exc}", file=sys.stderr)
        return 1
    print(f"\nDone. status={result.status}  run={result.run_dir}")
    if result.draft:
        print(f"Draft: {result.draft.get('url')}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
