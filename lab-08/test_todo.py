import re

import pytest
from playwright.sync_api import Browser, Page, Route, expect

from pages import TodoPage


def enter(page: Page, base_url: str, name: str, password: str) -> None:
    page.goto(base_url + "/login")
    page.get_by_label("Логин").fill(name)
    page.get_by_label("Пароль").fill(password)
    page.get_by_role("button", name="Войти").click()


def test_login_success(page: Page, base_url: str) -> None:
    enter(page, base_url, "user", "user123")
    expect(page.get_by_role("heading", name="Список задач")).to_be_visible()


@pytest.mark.parametrize(
    ("user", "password"), [("user", "wrong"), ("unknown", "user123"), ("", "")],
    ids=["wrong-password", "wrong-user", "empty"],
)
def test_login_error(page: Page, base_url: str, user: str, password: str) -> None:
    enter(page, base_url, user, password)
    expect(page.get_by_role("alert")).to_have_text("Неверный логин или пароль")


def test_guest_redirect(page: Page, base_url: str) -> None:
    page.goto(base_url + "/")
    expect(page).to_have_url(base_url + "/login")


def test_logout(page: Page, base_url: str) -> None:
    enter(page, base_url, "user", "user123")
    page.get_by_role("button", name="Выйти").click()
    expect(page).to_have_url(base_url + "/login")
    page.goto(base_url + "/")
    expect(page).to_have_url(base_url + "/login")


def test_empty(todo: TodoPage) -> None:
    expect(todo.page.get_by_text("Задач пока нет", exact=True)).to_be_visible()
    expect(todo.items).to_have_count(0)


def test_add(todo: TodoPage) -> None:
    todo.add("Купить бумагу")
    expect(todo.titles).to_have_text(["Купить бумагу"])
    expect(todo.title).to_have_value("")


def test_insertion_order_and_counter(todo: TodoPage) -> None:
    for name in ["Печать", "Подпись", "Архив"]:
        todo.add(name)
        expect(todo.titles.filter(has_text=name)).to_be_visible()
    expect(todo.titles).to_have_text(["Печать", "Подпись", "Архив"])
    expect(todo.page.get_by_text("Осталось: 3", exact=True)).to_be_visible()


def test_complete(todo: TodoPage) -> None:
    todo.add("Проверить")
    todo.check("Проверить").check()
    expect(todo.items).to_have_class(re.compile(r"\bdone\b"))
    expect(todo.check("Проверить")).to_be_checked()
    expect(todo.page.get_by_text("Осталось: 0", exact=True)).to_be_visible()


def test_delete(todo: TodoPage) -> None:
    todo.add("Завершить")
    todo.remove("Завершить")
    expect(todo.items).to_have_count(0)
    expect(todo.page.get_by_text("Задач пока нет")).to_be_visible()


def test_reload_preserves_tasks(todo: TodoPage) -> None:
    todo.add("Сохранить")
    expect(todo.titles).to_have_text(["Сохранить"])
    todo.page.reload()
    expect(todo.titles).to_have_text(["Сохранить"])


def test_filters_and_pressed_state(todo: TodoPage) -> None:
    todo.seed("В работе")
    todo.seed("Готово", done=True)
    todo.page.reload()
    expect(todo.titles).to_have_count(2)
    for label, visible in [("Активные", ["В работе"]), ("Выполненные", ["Готово"]), ("Все", ["В работе", "Готово"])]:
        todo.filter(label).click()
        expect(todo.titles).to_have_text(visible)
        for candidate in ("Активные", "Выполненные", "Все"):
            expect(todo.filter(candidate)).to_have_attribute("aria-pressed", str(label == candidate).lower())


def test_counter_series(todo: TodoPage) -> None:
    todo.seed("Первая")
    todo.seed("Вторая")
    todo.page.reload()
    expect(todo.page.get_by_text("Осталось: 2", exact=True)).to_be_visible()
    todo.check("Первая").check()
    expect(todo.page.get_by_text("Осталось: 1", exact=True)).to_be_visible()
    todo.remove("Вторая")
    expect(todo.page.get_by_text("Осталось: 0", exact=True)).to_be_visible()


@pytest.mark.parametrize("value", ["", "   "], ids=["empty", "blank"])
def test_empty_title_rejected(todo: TodoPage, value: str) -> None:
    todo.add(value)
    expect(todo.error).to_have_text("Название не может быть пустым")
    expect(todo.items).to_have_count(0)


@pytest.mark.parametrize(
    ("existing", "entered", "result", "error"),
    [(None, "а"*100, "а"*100, None), (None, "а"*101, None, "Название не длиннее 100 символов"),
     (None, "  Книга  ", "Книга", None), ("купить хлеб", "КУПИТЬ ХЛЕБ", "купить хлеб", "Такая задача уже есть")],
    ids=["100", "101", "trim", "variant-5"],
)
def test_title_boundaries(todo: TodoPage, existing: str, entered: str, result: str, error: str) -> None:
    if existing:
        todo.add(existing)
        expect(todo.titles).to_have_text([existing])
    todo.add(entered)
    if error:
        expect(todo.error).to_have_text(error)
    expect(todo.titles).to_have_text([result] if result else [])


def test_case_insensitive_duplicate(todo: TodoPage) -> None:
    todo.add("купить хлеб")
    expect(todo.titles).to_have_text(["купить хлеб"])
    todo.add("КУПИТЬ ХЛЕБ")
    expect(todo.error).to_have_text("Такая задача уже есть")
    expect(todo.titles).to_have_text(["купить хлеб"])


def test_failed_load_502(todo: TodoPage) -> None:
    todo.page.route("**/api/todos", lambda route: route.fulfill(status=502, json={}))
    todo.page.reload()
    expect(todo.error).to_have_text("Не удалось загрузить задачи. Попробуйте ещё раз.")


@pytest.mark.parametrize(
    ("kind", "message"),
    [("server", "Ошибка сервера. Попробуйте ещё раз."), ("network", "Ошибка сети. Попробуйте ещё раз.")],
)
def test_failed_add_keeps_input(todo: TodoPage, kind: str, message: str) -> None:
    def answer(route: Route) -> None:
        if route.request.method != "POST":
            route.continue_()
        elif kind == "server":
            route.fulfill(status=503, json={})
        else:
            route.abort()

    todo.page.route("**/api/todos", answer)
    todo.add("Запомнить")
    expect(todo.error).to_have_text(message)
    expect(todo.title).to_have_value("Запомнить")
    expect(todo.items).to_have_count(0)


def test_api_created_data_visible(todo: TodoPage) -> None:
    todo.seed("Из API")
    todo.page.reload()
    expect(todo.titles).to_have_text(["Из API"])


def test_two_contexts(todo: TodoPage, browser: Browser, base_url: str, user_state: dict) -> None:
    second = browser.new_context(base_url=base_url, storage_state=user_state)
    try:
        other = TodoPage(second.new_page())
        other.page.goto(base_url + "/")
        expect(other.items).to_have_count(0)
        todo.add("Общая")
        expect(todo.titles).to_have_text(["Общая"])
        other.page.reload()
        expect(other.titles).to_have_text(["Общая"])
    finally:
        second.close()


def test_reopen_completed(todo: TodoPage) -> None:
    todo.seed("Готово", done=True)
    todo.page.reload()
    todo.check("Готово").uncheck()
    expect(todo.page.get_by_text("Осталось: 1", exact=True)).to_be_visible()
    expect(todo.check("Готово")).not_to_be_checked()


def test_clear_error_after_success(todo: TodoPage) -> None:
    todo.add(" ")
    expect(todo.error).to_be_visible()
    todo.add("Исправлено")
    expect(todo.titles).to_have_text(["Исправлено"])
    expect(todo.error).to_be_hidden()
