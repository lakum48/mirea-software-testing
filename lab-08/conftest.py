import os
import threading
from collections.abc import Iterator
from http.server import ThreadingHTTPServer

import pytest
from playwright.sync_api import Browser, BrowserContext, Page, expect

from app import server
from pages import TodoPage


@pytest.fixture(scope="session")
def base_url() -> Iterator[str]:
    server.TEST_MODE = True
    server.DELAY_MS = int(os.getenv("TODO_DELAY_MS", "0"))
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), server.Handler)
    worker = threading.Thread(target=httpd.serve_forever, daemon=True)
    worker.start()
    try:
        yield f"http://127.0.0.1:{httpd.server_port}"
    finally:
        httpd.shutdown()
        httpd.server_close()
        worker.join()


@pytest.fixture(scope="session")
def user_state(browser: Browser, base_url: str) -> dict:
    context = browser.new_context(base_url=base_url)
    try:
        response = context.request.post("/api/login", data={"username": "user", "password": "user123"})
        assert response.ok
        return context.storage_state()
    finally:
        context.close()


@pytest.fixture(autouse=True)
def clean_server(page: Page, base_url: str) -> None:
    assert page.request.post(base_url + "/api/test/reset").status == 204


@pytest.fixture
def authed_page(page: Page, context: BrowserContext, base_url: str, user_state: dict) -> Page:
    context.add_cookies(user_state["cookies"])
    page.goto(base_url + "/")
    expect(page.get_by_text("Задач пока нет", exact=True)).to_be_visible()
    return page


@pytest.fixture
def todo(authed_page: Page) -> TodoPage:
    return TodoPage(authed_page)
