from typing import Protocol

type OrderData = dict[str, str | int]


class Storage(Protocol):
    def save_order(self, order_id: int, data: OrderData) -> bool: ...
    def get_order(self, order_id: int) -> OrderData | None: ...


class Notifier(Protocol):
    def send(self, order_id: int, data: OrderData) -> None: ...


class OrderService:
    def __init__(self, storage: Storage, notifier: Notifier) -> None:
        self.storage = storage
        self.notifier = notifier

    def place_order(self, order_id: int, data: OrderData) -> bool:
        if not self.storage.save_order(order_id, data):
            return False
        self.notifier.send(order_id, data)
        return True

    def get_order(self, order_id: int) -> OrderData | None:
        return self.storage.get_order(order_id)
