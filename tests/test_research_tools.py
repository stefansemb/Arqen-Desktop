"""Web research: retries, Reddit feeds and the extra sources, without the network."""

import io
import json
from email.message import Message
from urllib.error import HTTPError, URLError

import pytest

from arqen.connectors import store
from arqen.tools import research_tools as research
from arqen.tools.web_tools import FetchWebpageTool, SearchWebTool


class FakeResponse:
    def __init__(self, body: bytes, charset: str = "utf-8") -> None:
        self._body = body
        self.headers = Message()
        self.headers["Content-Type"] = f"text/html; charset={charset}"

    def read(self, limit=None):
        return self._body if limit is None else self._body[:limit]

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def _http_error(code: int, retry_after: str | None = None) -> HTTPError:
    headers = Message()
    if retry_after is not None:
        headers["Retry-After"] = retry_after
    return HTTPError("https://example.com", code, "error", headers, io.BytesIO(b""))


@pytest.fixture
def web(monkeypatch):
    """Answer each request from a script keyed by URL fragment; a tuple is answered in turn."""
    seen: list[dict] = []
    answers: dict[str, object] = {}
    waits: list[float] = []

    def fake_urlopen(request, timeout=None):
        seen.append({"url": request.full_url, "headers": dict(request.header_items())})
        for fragment in sorted(answers, key=len, reverse=True):
            if fragment in request.full_url:
                answer = answers[fragment]
                if isinstance(answer, tuple):
                    answer = answer[0]
                    if len(answers[fragment]) > 1:
                        answers[fragment] = answers[fragment][1:]
                if isinstance(answer, Exception):
                    raise answer
                body = answer if isinstance(answer, bytes) else json.dumps(answer).encode("utf-8")
                return FakeResponse(body)
        raise _http_error(404)

    monkeypatch.setattr(research, "urlopen", fake_urlopen)
    monkeypatch.setattr(research, "_sleep", waits.append)
    monkeypatch.setattr(research, "_json_refused_at", None)
    return seen, answers, waits


# --- Retries -------------------------------------------------------------------

def test_rate_limits_and_server_errors_are_retried_with_backoff(web):
    seen, answers, waits = web
    answers["example.com"] = (_http_error(429, retry_after="3"), _http_error(503), b"<title>Hej</title><p>Text</p>")

    output = FetchWebpageTool().run({"url": "https://example.com/sida"})

    assert "Title: Hej" in output and len(seen) == 3
    assert waits == [3.0, 2.5]  # the server's own Retry-After first, then the backoff


def test_a_long_retry_after_is_capped(web):
    _, answers, waits = web
    answers["example.com"] = (_http_error(429, retry_after="120"), b"<p>ok</p>")
    FetchWebpageTool().run({"url": "example.com"})
    assert waits == [5.0]


def test_a_refusal_is_not_retried_and_points_elsewhere(web):
    seen, answers, waits = web
    answers["example.com"] = _http_error(403)
    with pytest.raises(RuntimeError, match="search_tech_news"):
        FetchWebpageTool().run({"url": "https://example.com"})
    assert len(seen) == 1 and waits == []


def test_connection_trouble_gives_up_after_three_tries(web):
    seen, answers, _ = web
    answers["example.com"] = URLError(TimeoutError())
    with pytest.raises(RuntimeError, match="could not connect"):
        FetchWebpageTool().run({"url": "https://example.com"})
    assert len(seen) == 3


def test_search_web_retries_a_rate_limited_search(web):
    seen, answers, _ = web
    answers["duckduckgo"] = (
        _http_error(429),
        b'<a class="result__a" href="https://arqen.dev/">Arqen</a>',
    )
    assert "https://arqen.dev/" in SearchWebTool().run({"query": "arqen"})
    assert len(seen) == 2


def test_pages_are_capped_per_source(web):
    _, answers, _ = web
    answers["example.com"] = ("<p>" + "ord " * 10_000 + "</p>").encode()
    output = FetchWebpageTool().run({"url": "https://example.com"})
    assert len(output) < research.PAGE_LIMIT + 200 and output.endswith("…")


# --- Reddit --------------------------------------------------------------------

THREAD = [
    {"data": {"children": [{"kind": "t3", "data": {
        "title": "Ollama vs LM Studio", "subreddit": "LocalLLaMA", "author": "anna", "score": 120,
        "created_utc": 1758800000, "permalink": "/r/LocalLLaMA/comments/abc/ollama/", "selftext": "Vilken är snabbast?",
    }}]}},
    {"data": {"children": [
        {"kind": "t1", "data": {"author": "bo", "score": 5, "body": "LM Studio."}},
        {"kind": "t1", "data": {"author": "cia", "score": 40, "body": "Ollama, utan tvekan."}},
        {"kind": "more", "data": {}},
    ]}},
]

RSS = b"""<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom"><title>LocalLLaMA</title>
<entry><title>Ny modell sl\xc3\xa4ppt</title><updated>2026-09-24T10:00:00+00:00</updated>
<link href="https://www.reddit.com/r/LocalLLaMA/comments/xyz/ny/"/>
<content type="html">&lt;p&gt;Den &amp;amp; den&lt;/p&gt;</content></entry></feed>"""


def test_reddit_threads_are_read_through_json(web):
    seen, answers, _ = web
    answers["/comments/abc/ollama.json"] = THREAD

    output = FetchWebpageTool().run({"url": "https://old.reddit.com/r/LocalLLaMA/comments/abc/ollama/"})

    assert seen[0]["url"] == "https://www.reddit.com/r/LocalLLaMA/comments/abc/ollama.json?raw_json=1"
    assert seen[0]["headers"]["User-agent"] == research.RESEARCH_AGENT
    assert "Reddit thread: Ollama vs LM Studio" in output and "Vilken är snabbast?" in output
    # Highest-voted comment first.
    assert output.index("Ollama, utan tvekan.") < output.index("LM Studio.")


def test_reddit_falls_back_to_rss_when_json_is_blocked(web):
    _, answers, _ = web
    answers[".json"] = _http_error(403)
    answers["/r/LocalLLaMA.rss"] = RSS

    output = FetchWebpageTool().run({"url": "https://www.reddit.com/r/LocalLLaMA"})

    assert "Reddit (RSS): LocalLLaMA" in output
    assert "Ny modell släppt (2026-09-24)" in output and "Den & den" in output


def test_a_fully_blocked_reddit_says_where_to_look_instead(web):
    _, answers, _ = web
    answers["reddit.com"] = _http_error(403)
    with pytest.raises(research.FetchError, match="search_tech_news"):
        FetchWebpageTool().run({"url": "https://www.reddit.com/r/LocalLLaMA"})


# --- Research sources ------------------------------------------------------------

def test_tech_news_searches_three_sources_and_survives_a_blocked_one(web):
    seen, answers, _ = web
    answers["hn.algolia.com"] = {"hits": [
        {"title": "Show HN: Arqen", "points": 88, "num_comments": 12, "created_at": "2026-09-20T08:00:00Z",
         "objectID": "4242", "url": "https://arqen.dev"},
    ] * 7}
    answers["reddit.com/search"] = _http_error(403)
    answers["api.github.com/search"] = {"items": [
        {"full_name": "stefansemb/Arqen-Desktop", "stargazers_count": 3, "pushed_at": "2026-09-25T20:00:00Z",
         "description": "Lokal AI-assistent", "html_url": "https://github.com/stefansemb/Arqen-Desktop"},
    ]}

    output = research.SearchTechNewsTool().run({"query": "arqen assistant"})

    hn, reddit, github = output.split("## ")[1:]
    assert hn.count("Show HN: Arqen") == research.PER_SOURCE  # capped per source
    assert "news.ycombinator.com/item?id=4242" in hn
    assert "Unavailable: blocked" in reddit
    assert "stefansemb/Arqen-Desktop (★3, last push 2026-09-25)" in github
    assert "Authorization" not in seen[-1]["headers"]  # no GitHub connection, no token


def test_github_research_uses_a_connected_token(web):
    seen, answers, _ = web
    store.save_credentials("github", {"token": "ghp_testtoken123"})
    answers["api.github.com"] = {"items": []}
    research.github_repos("arqen")
    assert seen[0]["headers"]["Authorization"] == "Bearer ghp_testtoken123"


def test_release_notes_come_newest_first_and_capped(web):
    seen, answers, _ = web
    answers["/releases"] = [
        {"name": "v2.0", "tag_name": "v2.0.0", "published_at": "2026-09-01T00:00:00Z", "prerelease": False,
         "html_url": "https://github.com/ollama/ollama/releases/tag/v2.0.0", "body": "Nytt: " + "x" * 3000},
    ]

    output = research.GitHubReleaseNotesTool().run({"repo": "https://github.com/ollama/ollama.git"})

    assert seen[0]["url"].startswith("https://api.github.com/repos/ollama/ollama/releases")
    assert "### v2.0 (v2.0.0, 2026-09-01)" in output
    assert len(output) < 1800


def test_a_project_without_releases_falls_back_to_tags(web):
    _, answers, _ = web
    answers["/releases"] = []
    answers["/tags"] = [{"name": "1.4.2"}, {"name": "1.4.1"}]
    output = research.GitHubReleaseNotesTool().run({"repo": "someone/tool"})
    assert "publishes no GitHub releases" in output and "1.4.2, 1.4.1" in output


def test_a_missing_repository_is_said_plainly(web):
    with pytest.raises(ValueError, match="No public GitHub repository"):
        research.GitHubReleaseNotesTool().run({"repo": "nobody/nothing"})


def test_after_a_refused_json_feed_reddit_goes_straight_to_rss(web):
    seen, answers, _ = web
    answers[".json"] = _http_error(403)
    answers[".rss"] = RSS

    FetchWebpageTool().run({"url": "https://www.reddit.com/r/LocalLLaMA"})
    FetchWebpageTool().run({"url": "https://www.reddit.com/r/Python"})

    assert [call["url"].split("?")[0].rsplit(".", 1)[-1] for call in seen] == ["json", "rss", "rss"]
