from html.parser import HTMLParser
from typing import Any
import re
from urllib.parse import parse_qs, quote, quote_plus, unquote, urlparse, urlunparse
from urllib.request import Request, urlopen
import webbrowser

from arqen.tools.base import Tool


class _TextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.title = ""
        self.parts: list[str] = []
        self.in_title = False
        self.skip = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "title":
            self.in_title = True
        if tag in {"script", "style", "noscript"}:
            self.skip += 1

    def handle_endtag(self, tag: str) -> None:
        if tag == "title":
            self.in_title = False
        if tag in {"script", "style", "noscript"} and self.skip:
            self.skip -= 1

    def handle_data(self, data: str) -> None:
        text = " ".join(data.split())
        if not text or self.skip:
            return
        if self.in_title:
            self.title += text
        else:
            self.parts.append(text)


def _safe_url(url: str) -> str:
    parsed = urlparse(url)
    return urlunparse((
        parsed.scheme,
        parsed.netloc.encode("idna").decode("ascii"),
        quote(parsed.path, safe="/%:@-._~!$&'()*+,;="),
        parsed.params,
        quote(parsed.query, safe="=&%:@-._~!$'()*+,;/?"),
        quote(parsed.fragment, safe="/?=&%:@-._~!$'()*+,;"),
    ))


KNOWN_DOMAIN_CORRECTIONS = {
    "samrida.dev": "samida.dev",
    "semrida.dev": "samida.dev",
}


def _normalize_known_domain(url: str) -> str:
    value = url.strip()
    prefix = ""
    if not value.startswith(("http://", "https://")):
        prefix, value = "https://", value
    parsed = urlparse(value)
    corrected = KNOWN_DOMAIN_CORRECTIONS.get(parsed.netloc.casefold(), parsed.netloc)
    if corrected != parsed.netloc:
        value = urlunparse((parsed.scheme, corrected, parsed.path, parsed.params, parsed.query, parsed.fragment))
    return prefix + value if prefix else value


class FetchWebpageTool(Tool):
    name = "fetch_webpage"
    description = "Fetches the title and readable text from a public web page."
    requires_confirmation = False
    arguments_schema = {"url": str}

    def run(self, arguments: dict[str, Any]) -> str:
        url = arguments["url"].strip()
        if not url.startswith(("http://", "https://")):
            url = f"https://{url}"
        url = _safe_url(url)
        parsed = urlparse(url)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise ValueError("URL must start with http:// or https://")
        request = Request(url, headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/130 Safari/537.36"})
        with urlopen(request, timeout=8) as response:
            raw = response.read(2_000_000)
            charset = response.headers.get_content_charset() or "utf-8"
        parser = _TextExtractor()
        parser.feed(raw.decode(charset, errors="replace"))
        text = " ".join(parser.parts)
        return f"Title: {parser.title or '(untitled)'}\nURL: {url}\n\n{text[:20_000]}"


class OpenWebpageTool(Tool):
    name = "open_webpage"
    description = "Opens a public URL in the computer's default web browser."
    requires_confirmation = True
    arguments_schema = {"url": str}

    def normalize_arguments(self, arguments: dict[str, Any]) -> dict[str, Any]:
        normalized = dict(arguments)
        normalized["url"] = _normalize_known_domain(str(normalized.get("url", "")))
        return normalized

    def run(self, arguments: dict[str, Any]) -> str:
        url = arguments["url"].strip()
        if not url.startswith(("http://", "https://")):
            url = f"https://{url}"
        parsed = urlparse(url)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise ValueError("URL must start with http:// or https://")
        if not webbrowser.open(url, new=0):
            raise RuntimeError("Could not open the default web browser")
        # Keep the URL available if the user follows up with an Arqen-browser
        # action such as clicking an in-page hash link.
        try:
            from arqen.tools.browser_tools import STATE
            STATE.url = url
            from arqen.tools.browser_tools import _browser_call
            _browser_call(lambda page: page.goto(url, wait_until="domcontentloaded", timeout=30_000))
        except Exception:
            # Opening the user's default browser remains successful even if
            # the optional internal reader cannot be started.
            pass
        return f"Opened web page: {url}"


class SearchWebTool(Tool):
    name = "search_web"
    description = "Searches the public web and returns a short list of results."
    requires_confirmation = False
    arguments_schema = {"query": str}

    def __init__(self) -> None:
        self.last_results: list[tuple[str, str]] = []

    def run(self, arguments: dict[str, Any]) -> str:
        query = arguments["query"].strip()
        if not query:
            raise ValueError("Search query cannot be empty")
        url = f"https://html.duckduckgo.com/html/?q={quote_plus(query)}"
        request = Request(url, headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/130 Safari/537.36"})
        with urlopen(request, timeout=15) as response:
            html = response.read(2_000_000).decode("utf-8", errors="replace")
        parser = _SearchExtractor()
        parser.feed(html)
        if not parser.results:
            fallback_url = f"https://www.google.com/search?q={quote_plus(query)}"
            fallback_request = Request(
                fallback_url,
                headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/130 Safari/537.36"},
            )
            try:
                with urlopen(fallback_request, timeout=15) as response:
                    fallback_html = response.read(2_000_000).decode("utf-8", errors="replace")
                parser.feed(fallback_html)
            except OSError:
                pass
        direct_result: tuple[str, str] | None = None
        domain_match = re.search(r"\b(?:https?://)?([a-z0-9.-]+\.[a-z]{2,})(?:/[^\s]*)?\b", query, re.IGNORECASE)
        if domain_match:
            domain = domain_match.group(1).lower()
            direct_url = f"https://{domain}"
            try:
                with urlopen(Request(direct_url, headers={"User-Agent": "Mozilla/5.0"}), timeout=5) as response:
                    if 200 <= response.status < 400:
                        direct_result = (f"Direct site: {domain}", direct_url)
            except OSError:
                pass
        results = parser.results[:8]
        if direct_result and direct_result[1] not in {link for _, link in results}:
            results.insert(0, direct_result)
        self.last_results = results[:8]
        results = [f"{index}. {title}\n{link}" for index, (title, link) in enumerate(self.last_results, 1)]
        return "\n\n".join(results) or "Sökningen gav inga parsade resultat just nu. Försök igen eller öppna en sökmotor manuellt."


class _SearchExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.results: list[tuple[str, str]] = []
        self.current_title = ""
        self.current_href = ""
        self.in_result = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attributes = dict(attrs)
        if tag == "a" and "result__a" in attributes.get("class", ""):
            self.in_result = True
            self.current_title = ""
            href = attributes.get("href", "") or ""
            parsed = urlparse(href)
            self.current_href = unquote(parse_qs(parsed.query).get("uddg", [href])[0])

    def handle_data(self, data: str) -> None:
        if self.in_result:
            self.current_title += " ".join(data.split())

    def handle_endtag(self, tag: str) -> None:
        if tag == "a" and self.in_result:
            if self.current_title and self.current_href:
                self.results.append((self.current_title, self.current_href))
            self.in_result = False
