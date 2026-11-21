from playwright.sync_api import Page, expect


def test_flaky(authed_page: Page) -> None:
    authed_page.get_by_placeholder("Что нужно сделать?").fill("Купить молоко")
    authed_page.get_by_role("button", name="Добавить").click()
    authed_page.wait_for_timeout(300)
    assert authed_page.get_by_test_id("todo-item").count() == 1


def test_stable(authed_page: Page) -> None:
    authed_page.get_by_placeholder("Что нужно сделать?").fill("Купить молоко")
    authed_page.get_by_role("button", name="Добавить").click()
    expect(authed_page.get_by_test_id("todo-title")).to_have_text(["Купить молоко"])
