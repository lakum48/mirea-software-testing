from unittest.mock import Mock, call, create_autospec

import pytest

from order_service import Notifier, OrderData, OrderService, Storage


@pytest.fixture
def components() -> tuple[OrderService, Mock, Mock]:
    storage = create_autospec(Storage, instance=True, spec_set=True)
    notifier = create_autospec(Notifier, instance=True, spec_set=True)
    return OrderService(storage, notifier), storage, notifier


@pytest.mark.parametrize(
    ("order_id", "data"),
    [(1, {"item": "Бумага", "price": 500}), (7, {"item": "Кабель", "price": 125}), (99, {"item": "Лампа", "qty": 3})],
    ids=["paper", "cable", "lamp"],
)
def test_saved_order_notifies_once(components: tuple, order_id: int, data: OrderData) -> None:
    service, storage, notifier = components
    trace = Mock()
    trace.attach_mock(storage.save_order, "save")
    trace.attach_mock(notifier.send, "notify")
    storage.save_order.return_value = True

    result = service.place_order(order_id, data)

    assert result is True
    storage.save_order.assert_called_once_with(order_id, data)
    notifier.send.assert_called_once_with(order_id, data)
    assert trace.mock_calls == [call.save(order_id, data), call.notify(order_id, data)]


def test_rejected_order_sends_nothing(components: tuple) -> None:
    service, storage, notifier = components
    data = {"item": "Папка"}
    storage.save_order.return_value = False

    assert service.place_order(1, data) is False
    storage.save_order.assert_called_once_with(1, data)
    notifier.send.assert_not_called()


def test_storage_exception_reaches_caller(components: tuple) -> None:
    service, storage, notifier = components
    error = OSError("storage unavailable")
    storage.save_order.side_effect = error
    data = {"item": "Папка"}

    with pytest.raises(OSError) as raised:
        service.place_order(5, data)

    assert raised.value is error
    storage.save_order.assert_called_once_with(5, data)
    notifier.send.assert_not_called()


@pytest.mark.parametrize("stored", [{"item": "Папка"}, None], ids=["found", "missing"])
def test_read_returns_storage_result(components: tuple, stored: OrderData | None) -> None:
    service, storage, notifier = components
    storage.get_order.return_value = stored

    assert service.get_order(5) == stored
    storage.get_order.assert_called_once_with(5)
    notifier.send.assert_not_called()
