from playwright.sync_api import Locator, Page


class TodoPage:
    def __init__(self, page: Page) -> None:
        self.page = page
        self.title = page.get_by_placeholder("Что нужно сделать?")
        self.add_button = page.get_by_role("button", name="Добавить", exact=True)
        self.titles = page.get_by_test_id("todo-title")
        self.items = page.get_by_test_id("todo-item")
        self.error = page.get_by_role("alert")

    def add(self, title: str) -> None:
        self.title.fill(title)
        self.add_button.click()

    def check(self, title: str) -> Locator:
        return self.page.get_by_role("checkbox", name=f"Выполнено: {title}", exact=True)

    def remove(self, title: str) -> None:
        self.page.get_by_role("button", name=f"Удалить: {title}", exact=True).click()

    def filter(self, name: str) -> Locator:
        return self.page.get_by_role("button", name=name, exact=True)

    def seed(self, title: str, *, done: bool = False) -> None:
        response = self.page.request.post("/api/todos", data={"title": title})
        assert response.status == 201
        if done:
            updated = self.page.request.patch(f"/api/todos/{response.json()['id']}", data={"done": True})
            assert updated.ok
