import pytest

from research_blog_agent.command import CommandError, parse_command


@pytest.mark.parametrize("text,topic,blog,platform", [
    ("research best SEO tools 2026 and post a blog", "best SEO tools 2026", True, None),
    ("Research best SEO tools 2026 and post a blog.", "best SEO tools 2026", True, None),
    ("deep research the future of solar batteries, then publish a blog post on Blogger",
     "the future of solar batteries", True, "blogger"),
    ("research brand positioning for startups and write an article to wordpress",
     "brand positioning for startups", True, "wordpress"),
    ("research rust vs go for CLI tools", "rust vs go for CLI tools", False, None),
])
def test_parse(text, topic, blog, platform):
    cmd = parse_command(text)
    assert (cmd.topic, cmd.wants_blog, cmd.platform) == (topic, blog, platform)


@pytest.mark.parametrize("text", ["", "post a blog", "research"])
def test_rejects(text):
    with pytest.raises(CommandError):
        parse_command(text)
