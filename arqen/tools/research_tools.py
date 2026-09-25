"""Web research that holds up when a site pushes back.

Reddit often refuses plain page fetches, and busy services answer 429 or 5xx
now and then.  This module retries those with a short backoff, reads Reddit
through its JSON (then RSS) feeds, and gives research a set of sources that
answer reliably: Hacker News, GitHub and a project's own release notes.
Every source is capped, so one long page or thread cannot crowd out the rest
of the model's context, and every result carries its address for citing.
"""

from __future__ import annotations

import html
import json
import re
import time
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import quote, quote_plus, urlparse
from urllib.request import Request, urlopen

from arqen.tools.base import Tool

BROWSER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/130 Safari/537.36"
# Reddit asks API clients for a descriptive agent and throttles browser-like ones.
RESEARCH_AGENT = "Arqen/1.0 (local research assistant)"
PAGE_LIMIT = 12_000
PER_SOURCE = 5
_RETRY_STATUS = {429, 500, 502, 503, 504}
_BACKOFF = (1.0, 2.5)
_MAX_WAIT = 5.0
_sleep = time.sleep  # replaced in tests


class FetchError(RuntimeError):
    """A source could not be read; the message says why, without guessing."""


def fetch(url: str, *, accept: str = "*/*", agent: str = BROWSER_AGENT, timeout: float = 10,
          max_bytes: int = 2_000_000, headers: dict[str, str] | None = None) -> tuple[bytes, str]:
    """GET ``url`` with retries for rate limits, server errors and timeouts.

    Returns the body and its charset.  Other errors (403, 404, ...) fail at
    once: asking again would only get the same answer.
    """
    for attempt in range(len(_BACKOFF) + 1):
        try:
            request = Request(url, headers={"User-Agent": agent, "Accept": accept, **(headers or {})})
            with urlopen(request, timeout=timeout) as response:
                charset = response.headers.get_content_charset() if response.headers else None
                return response.read(max_bytes), charset or "utf-8"
        except HTTPError as exc:
            if exc.code not in _RETRY_STATUS or attempt == len(_BACKOFF):
                raise FetchError(f"HTTP {exc.code}") from None
            wait = _retry_after(exc) or _BACKOFF[attempt]
        except (URLError, TimeoutError, ConnectionError) as exc:
            if attempt == len(_BACKOFF):
                reason = getattr(exc, "reason", exc)
                raise FetchError(f"could not connect ({type(reason).__name__})") from None
            wait = _BACKOFF[attempt]
        _sleep(min(wait, _MAX_WAIT))
    raise FetchError("no answer")  # not reached


def _retry_after(exc: HTTPError) -> float | None:
    value = (exc.headers or {}).get("Retry-After") if exc.headers else None
    try:
        return float(value) if value is not None else None
    except ValueError:
        return None


def fetch_json(url: str, **options) -> Any:
    body, charset = fetch(url, accept="application/json", **options)
    try:
        return json.loads(body.decode(charset, errors="replace"))
    except json.JSONDecodeError:
        raise FetchError("the answer was not JSON (probably a block page)") from None


def clip(text: str | None, limit: int) -> str:
    text = (text or "").strip()
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


def _day(value) -> str:
    """A date from an ISO string or a Unix timestamp, as YYYY-MM-DD."""
    if isinstance(value, (int, float)):
        return datetime.fromtimestamp(value, tz=timezone.utc).strftime("%Y-%m-%d")
    return str(value or "")[:10]


# --- Reddit --------------------------------------------------------------------

def is_reddit(url: str) -> bool:
    host = urlparse(url).netloc.casefold()
    return host == "redd.it" or host == "reddit.com" or host.endswith(".reddit.com")


def _reddit_feed(url: str, suffix: str) -> str:
    """The same Reddit page as JSON or RSS, on www.reddit.com."""
    parsed = urlparse(url)
    path = parsed.path.rstrip("/") or "/"
    if parsed.netloc.casefold() == "redd.it":
        path = f"/comments{path}"
    params = parsed.query
    if suffix == ".json":
        # raw_json keeps "&" and "<" as they were typed instead of HTML-escaped.
        params = f"{params}&raw_json=1" if params else "raw_json=1"
    return f"https://www.reddit.com{path}{suffix}" + (f"?{params}" if params else "")


def _reddit_post_line(post: dict) -> str:
    return (f"- {post.get('title', '')} ({post.get('score', 0)} points, {post.get('num_comments', 0)} comments, "
            f"r/{post.get('subreddit', '?')}, {_day(post.get('created_utc'))})\n"
            f"  https://www.reddit.com{post.get('permalink', '')}")


def _reddit_from_json(data) -> str:
    if isinstance(data, list) and data:
        # A thread: [post listing, comment listing].
        post = data[0]["data"]["children"][0]["data"]
        lines = [f"Reddit thread: {post.get('title', '')}",
                 f"r/{post.get('subreddit', '?')} · u/{post.get('author', '?')} · {post.get('score', 0)} points · "
                 f"{_day(post.get('created_utc'))}",
                 f"https://www.reddit.com{post.get('permalink', '')}", ""]
        if post.get("selftext"):
            lines += [clip(post["selftext"], 3000), ""]
        comments = [child["data"] for child in (data[1]["data"]["children"] if len(data) > 1 else [])
                    if child.get("kind") == "t1"]
        comments.sort(key=lambda item: item.get("score", 0), reverse=True)
        if comments:
            lines.append("Top comments:")
            lines += [f"- u/{item.get('author', '?')} ({item.get('score', 0)}): {clip(item.get('body'), 600)}"
                      for item in comments[:8]]
        return "\n".join(lines)
    posts = [child["data"] for child in (data.get("data", {}).get("children", []) if isinstance(data, dict) else [])
             if child.get("kind") == "t3"]
    if not posts:
        return "Reddit returned no posts."
    return "Reddit posts:\n" + "\n".join(_reddit_post_line(post) for post in posts[:15])


_ATOM = "{http://www.w3.org/2005/Atom}"
# Reddit refuses its JSON feed to unauthenticated clients much of the time.
# After a refusal Arqen goes straight to RSS for a while, which halves the
# requests and keeps it under Reddit's rate limit.
_JSON_PAUSE = 3600.0
_json_refused_at: float | None = None


def _reddit_json_allowed() -> bool:
    return _json_refused_at is None or time.monotonic() - _json_refused_at > _JSON_PAUSE


def _reddit_json(url: str):
    global _json_refused_at
    try:
        return fetch_json(url, agent=RESEARCH_AGENT)
    except FetchError as exc:
        if str(exc) == "HTTP 403":
            _json_refused_at = time.monotonic()
        raise


def _rss_entries(body: bytes, limit: int) -> tuple[str, list[str]]:
    """The feed's title and up to ``limit`` entries as result lines."""
    try:
        root = ET.fromstring(body)
    except ET.ParseError:
        raise FetchError("the RSS feed could not be read") from None
    lines = []
    for entry in root.findall(f"{_ATOM}entry")[:limit]:
        link = entry.find(f"{_ATOM}link")
        content = re.sub(r"<[^>]+>", " ", html.unescape(entry.findtext(f"{_ATOM}content", "")))
        lines.append(f"- {entry.findtext(f'{_ATOM}title', '')} ({_day(entry.findtext(f'{_ATOM}updated', ''))})\n"
                     f"  {link.get('href') if link is not None else ''}\n  {clip(' '.join(content.split()), 400)}")
    return root.findtext(f"{_ATOM}title", ""), lines


def _reddit_from_rss(body: bytes) -> str:
    title, lines = _rss_entries(body, 15)
    return f"Reddit (RSS): {title}\n" + "\n".join(lines) if lines else "Reddit returned no posts."


def read_reddit(url: str) -> str:
    """A Reddit page through its JSON feed, then its RSS feed."""
    problems = []
    if _reddit_json_allowed():
        try:
            return _reddit_from_json(_reddit_json(_reddit_feed(url, ".json")))
        except (FetchError, KeyError, IndexError, TypeError) as exc:
            problems.append(f"JSON: {exc}")
    try:
        body, _ = fetch(_reddit_feed(url, ".rss"), accept="application/atom+xml", agent=RESEARCH_AGENT)
        return _reddit_from_rss(body)
    except FetchError as exc:
        problems.append(f"RSS: {exc}")
    raise FetchError(
        "Reddit refused the request (" + "; ".join(problems) + "). Use search_tech_news for Hacker News and "
        "GitHub, or the project's official site and release notes, instead."
    )


# --- Research sources -----------------------------------------------------------

def hacker_news(query: str) -> list[str]:
    data = fetch_json(f"https://hn.algolia.com/api/v1/search?query={quote_plus(query)}&tags=story&hitsPerPage={PER_SOURCE}")
    return [
        f"- {hit.get('title', '')} ({hit.get('points') or 0} points, {hit.get('num_comments') or 0} comments, "
        f"{_day(hit.get('created_at'))})\n  https://news.ycombinator.com/item?id={hit.get('objectID')}"
        + (f"\n  {hit['url']}" if hit.get("url") else "")
        for hit in (data.get("hits") or [])[:PER_SOURCE]
    ]


def reddit_search(query: str) -> list[str]:
    url = f"https://www.reddit.com/search.json?q={quote_plus(query)}&sort=relevance&t=year&limit={PER_SOURCE}&raw_json=1"
    json_problem = "skipped after an earlier refusal"
    if _reddit_json_allowed():
        try:
            data = _reddit_json(url)
            posts = [child["data"] for child in data.get("data", {}).get("children", []) if child.get("kind") == "t3"]
            return [_reddit_post_line(post) for post in posts[:PER_SOURCE]]
        except (FetchError, KeyError, TypeError, AttributeError) as exc:
            json_problem = str(exc)
    try:
        body, _ = fetch(f"https://www.reddit.com/search.rss?q={quote_plus(query)}&sort=relevance&t=year",
                        accept="application/atom+xml", agent=RESEARCH_AGENT)
    except FetchError as rss_problem:
        raise FetchError(f"blocked (JSON: {json_problem}; RSS: {rss_problem})") from None
    return _rss_entries(body, PER_SOURCE)[1]


def _github_headers() -> dict[str, str]:
    # A connected GitHub token raises the rate limit; research works without one.
    from arqen.connectors.store import load_credentials

    token = load_credentials("github").get("token", "")
    headers = {"Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28"}
    return {**headers, "Authorization": f"Bearer {token}"} if token else headers


def github_repos(query: str) -> list[str]:
    data = fetch_json(f"https://api.github.com/search/repositories?q={quote_plus(query)}&sort=stars&per_page={PER_SOURCE}",
                      agent=RESEARCH_AGENT, headers=_github_headers())
    return [
        f"- {repo.get('full_name')} (★{repo.get('stargazers_count', 0)}, last push {_day(repo.get('pushed_at'))}): "
        f"{clip(repo.get('description'), 200) or 'no description'}\n  {repo.get('html_url')}"
        for repo in (data.get("items") or [])[:PER_SOURCE]
    ]


class SearchTechNewsTool(Tool):
    name = "search_tech_news"
    description = (
        "Searches Hacker News, Reddit and GitHub at once for discussions, news and projects "
        "(nyheter, diskussioner, forum) about a technical topic; at most 5 results per source. "
        "A source that is blocked is reported and the others still answer."
    )
    arguments_schema = {"query": str}

    def run(self, arguments: dict[str, Any]) -> str:
        query = str(arguments["query"]).strip()
        if not query:
            raise ValueError("Search query cannot be empty")
        sections = []
        for title, search in (("Hacker News", hacker_news), ("Reddit", reddit_search), ("GitHub", github_repos)):
            try:
                lines = search(query)
                sections.append(f"## {title}\n" + ("\n".join(lines) if lines else "No results."))
            except FetchError as exc:
                sections.append(f"## {title}\nUnavailable: {exc}")
        return "\n\n".join(sections) + "\n\nOpen a result with fetch_webpage for its full text."


def _repo(value: str) -> str:
    text = str(value).strip()
    match = re.search(r"github\.com/([\w.-]+/[\w.-]+)", text)
    repo = (match.group(1) if match else text).strip("/").removesuffix(".git")
    if repo.count("/") != 1 or not all(repo.split("/")):
        raise ValueError(f"Use owner/name for the repository, got: {value}")
    return repo


class GitHubReleaseNotesTool(Tool):
    name = "github_release_notes"
    description = (
        "Reads the official release notes (versioner, ändringslogg, changelog) of a GitHub project: "
        "the 5 latest releases, or its latest tags when it publishes no releases. "
        "Repository as owner/name or a github.com address."
    )
    arguments_schema = {"repo": str}

    def run(self, arguments: dict[str, Any]) -> str:
        repo = _repo(arguments["repo"])
        base = f"https://api.github.com/repos/{quote(repo, safe='/')}"
        try:
            releases = fetch_json(f"{base}/releases?per_page={PER_SOURCE}", agent=RESEARCH_AGENT, headers=_github_headers())
        except FetchError as exc:
            if "404" in str(exc):
                raise ValueError(f"No public GitHub repository {repo}.") from None
            raise
        if releases:
            parts = [f"Release notes for {repo} (newest first):"]
            for release in releases[:PER_SOURCE]:
                parts.append(
                    f"\n### {release.get('name') or release.get('tag_name')} ({release.get('tag_name')}, "
                    f"{_day(release.get('published_at'))}{', pre-release' if release.get('prerelease') else ''})\n"
                    f"{release.get('html_url')}\n{clip(release.get('body'), 1500) or '(no notes)'}"
                )
            return "\n".join(parts)
        tags = fetch_json(f"{base}/tags?per_page={PER_SOURCE}", agent=RESEARCH_AGENT, headers=_github_headers())
        if not tags:
            return f"{repo} publishes no releases or tags. Look for a CHANGELOG file or the project's own site."
        return (f"{repo} publishes no GitHub releases. Latest tags: "
                + ", ".join(tag.get("name", "") for tag in tags[:PER_SOURCE])
                + f"\nhttps://github.com/{repo}/tags — a CHANGELOG file in the repository may have the notes.")
