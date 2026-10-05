"""End-to-end: the full 7-step pipeline against the local mock pages, headless."""
import json

from research_blog_agent.command import parse_command
from research_blog_agent.fallback import ScreenshotFallback
from research_blog_agent.locate import PointTarget, Resolver, load_selectors
from research_blog_agent.browser import BrowserSession
from research_blog_agent.pipeline import Agent, RunState
from research_blog_agent.settings import Settings

CMD = "research best SEO tools 2026 and post a blog"


def mock_settings(tmp_path):
    return Settings(mode="mock", headless=True, runs_dir=tmp_path / "runs")


def test_full_pipeline_publish_after_confirmation(tmp_path):
    previews = []
    result = Agent(mock_settings(tmp_path), parse_command(CMD),
                   confirm=lambda p: previews.append(p) or True).run()

    assert result.status == "published"
    assert result.completed == ["open_chatgpt", "start_deep_research", "wait_research",
                                "extract_research", "write_blog", "create_draft", "confirm_publish"]
    state = json.loads((result.run_dir / "state.json").read_text())
    research = (result.run_dir / "research.md").read_text()
    assert "Research report: best SEO tools 2026" in research and len(research) > 400
    assert result.title == "Best SEO Tools 2026: A Practical Guide"
    assert state["draft"]["status"] == "publish"
    assert state["draft"]["extra"]["paste_method"] == "synthetic-paste"
    assert state["draft"]["extra"]["readback"]["title"] == result.title
    assert result.title in previews[0] and "words" in previews[0]
    assert "WP_APP_PASSWORD" not in json.dumps(state)


def test_default_answer_leaves_draft(tmp_path):
    result = Agent(mock_settings(tmp_path), parse_command(CMD), confirm=lambda p: False).run()
    assert result.status == "draft"
    assert result.draft["status"] == "draft"
    assert result.draft["url"].endswith("?post=42&action=edit")


def test_resume_skips_completed_steps(tmp_path):
    s = mock_settings(tmp_path)
    first = Agent(s, parse_command(CMD), stop_after="extract_research").run()
    assert first.status == "incomplete" and first.completed[-1] == "extract_research"

    state = RunState.load(first.run_dir)
    second = Agent(mock_settings(tmp_path), parse_command(CMD), state=state, confirm=lambda p: False).run()
    assert second.status == "draft"
    assert second.completed[:4] == first.completed  # research steps were not re-run


def test_screenshot_fallback_hook(tmp_path):
    class FakeVision:
        def __init__(self, point):
            self.point, self.calls = point, []

        def locate(self, screenshot, target):
            self.calls.append((screenshot, target))
            return self.point

    s = mock_settings(tmp_path)
    with BrowserSession(s) as session:
        page = session.new_page()
        page.goto(s.chatgpt_url)
        box = page.get_by_test_id("composer-plus-btn").bounding_box()
        vision = FakeVision((box["x"] + box["width"] / 2, box["y"] + box["height"] / 2))
        selectors = {"broken": {"plus": [{"css": "#renamed-by-a-ui-update"}]}}
        r = Resolver(page, selectors, ScreenshotFallback(tmp_path / "shots", vision), 500)

        target = r.click("broken.plus")
        assert isinstance(target, PointTarget)
        assert page.get_by_role("menu").is_visible()
        assert vision.calls and vision.calls[0][0].exists()
        assert vision.calls[0][1] == "broken.plus"


def test_copy_button_extraction_path(tmp_path):
    s = mock_settings(tmp_path)
    s.extract = "copy"
    result = Agent(s, parse_command(CMD), stop_after="write_blog").run()
    state = json.loads((result.run_dir / "state.json").read_text())
    assert state["research"]["via"] == "copy"
    assert (result.run_dir / "research.md").read_text().startswith("# Research report:")
    assert result.title == "Best SEO Tools 2026: A Practical Guide"
