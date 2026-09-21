from typing import Any
from urllib.parse import urlparse
import webbrowser
import queue
import threading

from arqen.tools.base import Tool


class _BrowserState:
    url = "about:blank"
    last_links: list[tuple[str, str]] = []
    controller = None


STATE = _BrowserState()


class _PersistentBrowser:
    def __init__(self) -> None:
        self.jobs: queue.Queue = queue.Queue()
        self.ready = threading.Event()
        self.error: Exception | None = None
        self.thread = threading.Thread(target=self._run, daemon=True, name="arqen-browser")
        self.thread.start()
        self.ready.wait(timeout=30)
        if self.error:
            raise RuntimeError(str(self.error))

    def _run(self) -> None:
        try:
            from playwright.sync_api import sync_playwright
            playwright = sync_playwright().start()
            browser = playwright.chromium.launch(headless=False, args=["--start-maximized"])
            context = browser.new_context(no_viewport=True)
            page = context.new_page()
            self.page = page
            self.ready.set()
            while True:
                job = self.jobs.get()
                if job is None:
                    break
                action, result, done = job
                try:
                    result.append(action(page))
                except Exception as exc:
                    result.append(exc)
                finally:
                    done.set()
            browser.close()
            playwright.stop()
        except Exception as exc:
            self.error = exc
            self.ready.set()

    def call(self, action):
        if self.error:
            raise RuntimeError(str(self.error))
        result: list[Any] = []
        done = threading.Event()
        self.jobs.put((action, result, done))
        done.wait(timeout=40)
        if not result:
            raise RuntimeError("Browser operation timed out")
        if isinstance(result[0], Exception):
            raise result[0]
        return result[0]


def _get_browser() -> _PersistentBrowser:
    if STATE.controller is None:
        STATE.controller = _PersistentBrowser()
    return STATE.controller


def _browser_call(action):
    """Run an action and recreate a manually closed browser once."""
    for attempt in range(2):
        controller = _get_browser()
        try:
            return controller.call(action)
        except Exception as exc:
            message = str(exc).lower()
            closed = any(part in message for part in ("browser has been closed", "target page", "target closed", "context has been closed"))
            if not closed or attempt == 1:
                raise
            STATE.controller = None


def _start_browser():
    try:
        from playwright.sync_api import sync_playwright
    except ImportError as exc:
        raise RuntimeError("Browser automation requires the playwright package") from exc
    playwright = sync_playwright().start()
    try:
        browser = playwright.chromium.launch(headless=False)
    except Exception as exc:
        playwright.stop()
        raise RuntimeError("Playwright browser is not installed. Run: playwright install chromium") from exc
    return playwright, browser, browser.new_page()


class BrowserNavigateTool(Tool):
    name = "browser_navigate"
    description = "Navigates the Arqen browser to a public URL."
    requires_confirmation = False
    arguments_schema = {"url": str}

    def run(self, arguments: dict[str, Any]) -> str:
        url = arguments["url"].strip()
        if not url.startswith(("http://", "https://")):
            url = f"https://{url}"
        if urlparse(url).scheme not in {"http", "https"}:
            raise ValueError("URL must use http or https")
        def navigate(page):
            page.goto(url, wait_until="domcontentloaded", timeout=30_000)
            return page.url
        final_url = _browser_call(navigate)
        STATE.url = final_url
        return f"Browser navigated to: {final_url}"


class BrowserReadPageTool(Tool):
    name = "browser_read_page"
    description = "Reads the title and visible text from the current Arqen browser page."
    requires_confirmation = False
    arguments_schema = {"section": str}

    def run(self, arguments: dict[str, Any]) -> str:
        def read(page):
            if page.url.startswith("about:blank") and STATE.url.startswith(("http://", "https://")):
                page.goto(STATE.url, wait_until="domcontentloaded", timeout=30_000)
            text = " ".join(page.locator("body").inner_text().split())
            section = str(arguments.get("section", "")).strip().lower()
            if section:
                upper = text.upper()
                start = upper.rfind(section.upper())
                if start >= 0:
                    markers = ["RIGHT NOW", "SAMIDA ©", "FOOTER"]
                    ends = [upper.find(marker, start + len(section)) for marker in markers]
                    ends = [value for value in ends if value >= 0]
                    text = text[start:min(ends) if ends else len(text)]
            return f"Title: {page.title()}\nURL: {page.url}\n\n{text[:20_000]}"
        return _browser_call(read)


class BrowserListLinksTool(Tool):
    name = "browser_list_links"
    description = "Lists links from the current browser page."
    requires_confirmation = False

    def run(self, arguments: dict[str, Any]) -> str:
        def list_links(page):
            links = page.locator("a").evaluate_all(
                "els => els.map(a => ({text: (a.innerText || a.textContent || '').trim(), href: a.href}))"
            )
            STATE.last_links = [
                (item["text"] or "(unnamed link)", item["href"])
                for item in links
                if item.get("href", "").startswith(("http://", "https://"))
            ][:50]
            return "\n".join(f"{index}. {text} -> {href}" for index, (text, href) in enumerate(STATE.last_links, 1)) or "No links found."
        return _browser_call(list_links)


class BrowserClickLinkTool(Tool):
    name = "browser_click_link"
    description = "Clicks a link by visible text on the current browser page."
    requires_confirmation = False
    arguments_schema = {"text": str}

    def run(self, arguments: dict[str, Any]) -> str:
        wanted = arguments["text"].strip()
        def click(page):
            if page.url.startswith("about:blank") and STATE.url.startswith(("http://", "https://")):
                page.goto(STATE.url, wait_until="domcontentloaded", timeout=30_000)
            link = page.get_by_role("link", name=wanted, exact=True).first
            if link.count() == 0:
                raise ValueError(f"No link found with text: {wanted}")
            href = link.get_attribute("href")
            if not href:
                raise ValueError(f"Link has no URL: {wanted}")
            target = page.locator("a").filter(has_text=wanted).first.get_attribute("href") or href
            from urllib.parse import urljoin
            if target.startswith("#"):
                page.evaluate("hash => { window.location.hash = hash; }", target)
                page.wait_for_timeout(150)
                STATE.url = page.url
                return f"Clicked link '{wanted}' and opened: {page.url}"
            # Use the page's real current URL. STATE.url can still be
            # about:blank after a browser restart or manual navigation.
            target = urljoin(page.url, target)
            STATE.url = target
            page.goto(target, wait_until="domcontentloaded", timeout=30_000)
            return f"Clicked link '{wanted}' and opened: {page.url}"
        return _browser_call(click)


class BrowserBackTool(Tool):
    name = "browser_back"
    description = "Navigates back one page in the current Arqen browser tab."
    requires_confirmation = False

    def run(self, arguments: dict[str, Any]) -> str:
        def back(page):
            page.go_back(wait_until="domcontentloaded", timeout=30_000)
            return page.url
        final_url = _browser_call(back)
        STATE.url = final_url or STATE.url
        return f"Browser navigated back to: {STATE.url}"


class BrowserForwardTool(Tool):
    name = "browser_forward"
    description = "Navigates forward one page in the current Arqen browser tab."
    requires_confirmation = False

    def run(self, arguments: dict[str, Any]) -> str:
        def forward(page):
            page.go_forward(wait_until="domcontentloaded", timeout=30_000)
            return page.url
        final_url = _browser_call(forward)
        STATE.url = final_url or STATE.url
        return f"Browser navigated forward to: {STATE.url}"
