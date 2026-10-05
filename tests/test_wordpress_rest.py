"""WordPress REST publisher against a tiny fake /wp-json/wp/v2 server."""
import base64
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from research_blog_agent.publishers import BlogPost, WordPressRestPublisher


@pytest.fixture
def fake_wp():
    calls = []

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def do_POST(self):
            body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            auth = base64.b64decode(self.headers["Authorization"].split()[1]).decode()
            calls.append((self.path, body, auth))
            status = body.get("status", "draft")
            out = {"id": 7, "status": status, "link": "http://wp.test/?p=7"}
            data = json.dumps(out).encode()
            self.send_response(201 if self.path.endswith("/posts") else 200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

    srv = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{srv.server_address[1]}", calls
    srv.shutdown()


def test_rest_creates_draft_then_publishes(fake_wp, monkeypatch):
    url, calls = fake_wp
    monkeypatch.setenv("WP_USER", "editor")
    monkeypatch.setenv("WP_APP_PASSWORD", "abcd efgh ijkl")
    pub = WordPressRestPublisher(url)
    draft = pub.create_draft(BlogPost("Hello", "<p>Body</p>", "Body"))
    assert draft.status == "draft" and draft.post_id == "7"
    assert calls[0] == ("/wp-json/wp/v2/posts", {"title": "Hello", "content": "<p>Body</p>", "status": "draft"},
                        "editor:abcd efgh ijkl")
    done = pub.publish(draft)
    assert done.status == "publish" and calls[1][0] == "/wp-json/wp/v2/posts/7"
