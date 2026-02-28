"""Headless browser automation using Playwright."""

from __future__ import annotations

import asyncio
from typing import Any

from shannon.config import BrowserConfig
from shannon.core.auth import PermissionLevel
from shannon.tools.base import BaseTool, ToolResult
from shannon.utils.logging import get_logger

log = get_logger(__name__)


class BrowserTool(BaseTool):
    """Browse the web: navigate, read content, interact with elements, take screenshots."""

    def __init__(self, config: BrowserConfig | None = None) -> None:
        self._config = config or BrowserConfig()
        self._playwright: Any = None
        self._browser: Any = None
        self._context: Any = None
        self._page: Any = None
        self._initialized = False

    @property
    def name(self) -> str:
        return "browser"

    @property
    def description(self) -> str:
        return (
            "Browse the web: navigate to URLs, read page content, search Google, "
            "take screenshots, click elements, type into inputs, and extract data."
        )

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["navigate", "search", "screenshot", "click", "type", "extract", "pdf"],
                    "description": "The browser action to perform.",
                },
                "url": {
                    "type": "string",
                    "description": "URL to navigate to (for 'navigate' action).",
                },
                "query": {
                    "type": "string",
                    "description": "Search query (for 'search' action).",
                },
                "selector": {
                    "type": "string",
                    "description": "CSS selector for element interaction.",
                },
                "text": {
                    "type": "string",
                    "description": "Text to type (for 'type' action).",
                },
                "output_path": {
                    "type": "string",
                    "description": "File path for screenshot/PDF output.",
                },
            },
            "required": ["action"],
        }

    @property
    def required_permission(self) -> PermissionLevel:
        return PermissionLevel.TRUSTED

    async def _ensure_initialized(self) -> None:
        if self._initialized:
            return
        try:
            from playwright.async_api import async_playwright
        except ImportError:
            raise RuntimeError(
                "Playwright not installed. Run: pip install playwright && playwright install chromium"
            )

        self._playwright = await async_playwright().start()

        launch_kwargs: dict[str, Any] = {"headless": self._config.headless}
        browser_type = self._config.browser

        if browser_type == "firefox":
            self._browser = await self._playwright.firefox.launch(**launch_kwargs)
        elif browser_type == "webkit":
            self._browser = await self._playwright.webkit.launch(**launch_kwargs)
        else:
            self._browser = await self._playwright.chromium.launch(**launch_kwargs)

        self._context = await self._browser.new_context(
            user_agent="Shannon/0.1 (automated browser)",
        )
        self._context.set_default_timeout(self._config.default_timeout)
        self._page = await self._context.new_page()
        self._initialized = True
        log.info("browser_initialized", browser=browser_type, headless=self._config.headless)

    async def execute(self, **kwargs: Any) -> ToolResult:
        action = kwargs.get("action", "")

        try:
            await self._ensure_initialized()
        except RuntimeError as e:
            return ToolResult(success=False, error=str(e))

        try:
            if action == "navigate":
                return await self._navigate(kwargs.get("url", ""))
            elif action == "search":
                return await self._search(kwargs.get("query", ""))
            elif action == "screenshot":
                return await self._screenshot(kwargs.get("output_path"))
            elif action == "click":
                return await self._click(kwargs.get("selector", ""))
            elif action == "type":
                return await self._type_text(kwargs.get("selector", ""), kwargs.get("text", ""))
            elif action == "extract":
                return await self._extract(kwargs.get("selector"))
            elif action == "pdf":
                return await self._pdf(kwargs.get("output_path"))
            else:
                return ToolResult(success=False, error=f"Unknown action: {action}")
        except Exception as e:
            log.exception("browser_action_error", action=action)
            return ToolResult(success=False, error=str(e))

    async def _navigate(self, url: str) -> ToolResult:
        if not url:
            return ToolResult(success=False, error="URL is required")
        assert self._page is not None
        response = await self._page.goto(url, wait_until="domcontentloaded")
        title = await self._page.title()
        # Extract readable text content
        text = await self._page.evaluate("""
            () => {
                const article = document.querySelector('article') || document.body;
                return article.innerText.substring(0, 8000);
            }
        """)
        status = response.status if response else "unknown"
        return ToolResult(
            success=True,
            output=f"Title: {title}\nStatus: {status}\n\n{text}",
            data={"title": title, "url": url, "status": status},
        )

    async def _search(self, query: str) -> ToolResult:
        if not query:
            return ToolResult(success=False, error="Search query is required")
        assert self._page is not None
        url = f"https://www.google.com/search?q={query}"
        await self._page.goto(url, wait_until="domcontentloaded")
        # Extract search results
        results = await self._page.evaluate("""
            () => {
                const items = document.querySelectorAll('div.g');
                return Array.from(items).slice(0, 10).map(el => {
                    const title = el.querySelector('h3')?.innerText || '';
                    const link = el.querySelector('a')?.href || '';
                    const snippet = el.querySelector('.VwiC3b')?.innerText || '';
                    return `${title}\\n${link}\\n${snippet}`;
                }).join('\\n\\n');
            }
        """)
        return ToolResult(
            success=True,
            output=f"Search results for: {query}\n\n{results}" if results else f"No results found for: {query}",
        )

    async def _screenshot(self, output_path: str | None) -> ToolResult:
        assert self._page is not None
        path = output_path or "screenshot.png"
        await self._page.screenshot(path=path, full_page=False)
        return ToolResult(success=True, output=f"Screenshot saved to {path}", data={"path": path})

    async def _click(self, selector: str) -> ToolResult:
        if not selector:
            return ToolResult(success=False, error="CSS selector is required")
        assert self._page is not None
        await self._page.click(selector)
        await self._page.wait_for_load_state("domcontentloaded")
        title = await self._page.title()
        return ToolResult(success=True, output=f"Clicked '{selector}'. Page title: {title}")

    async def _type_text(self, selector: str, text: str) -> ToolResult:
        if not selector:
            return ToolResult(success=False, error="CSS selector is required")
        assert self._page is not None
        await self._page.fill(selector, text)
        return ToolResult(success=True, output=f"Typed into '{selector}'")

    async def _extract(self, selector: str | None) -> ToolResult:
        assert self._page is not None
        if selector:
            elements = await self._page.query_selector_all(selector)
            texts = []
            for el in elements:
                texts.append(await el.inner_text())
            output = "\n---\n".join(texts) if texts else "No elements found"
        else:
            output = await self._page.evaluate("() => document.body.innerText.substring(0, 10000)")
        return ToolResult(success=True, output=output)

    async def _pdf(self, output_path: str | None) -> ToolResult:
        assert self._page is not None
        path = output_path or "page.pdf"
        await self._page.pdf(path=path)
        return ToolResult(success=True, output=f"PDF saved to {path}", data={"path": path})

    async def cleanup(self) -> None:
        if self._context:
            await self._context.close()
        if self._browser:
            await self._browser.close()
        if self._playwright:
            await self._playwright.stop()
        self._initialized = False
