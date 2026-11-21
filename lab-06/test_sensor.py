from unittest.mock import Mock

import pytest

from sensor import TemperatureSensor


@pytest.fixture
def sensor() -> TemperatureSensor:
    return TemperatureSensor(initial=20)


def test_initial_state(sensor: TemperatureSensor) -> None:
    assert sensor.temperature == 20


@pytest.mark.parametrize("value", [0, -12, 20.5, 39], ids=["zero", "negative", "fraction", "positive"])
def test_change_emits_new_value(sensor: TemperatureSensor, value: float) -> None:
    listener = Mock()
    sensor.subscribe(listener)
    sensor.set_temperature(value)
    assert sensor.temperature == value
    listener.assert_called_once_with(value)


def test_same_value_does_not_emit(sensor: TemperatureSensor) -> None:
    listener = Mock()
    sensor.subscribe(listener)
    sensor.set_temperature(20)
    listener.assert_not_called()


def test_both_receive_reading(sensor: TemperatureSensor) -> None:
    first, second = Mock(), Mock()
    sensor.subscribe(first)
    sensor.subscribe(second)
    sensor.set_temperature(30)
    first.assert_called_once_with(30)
    second.assert_called_once_with(30)


def test_unsubscribe_only_removes_one_listener(sensor: TemperatureSensor) -> None:
    first, second = Mock(), Mock()
    sensor.subscribe(first)
    sensor.subscribe(second)
    sensor.unsubscribe(first)
    sensor.set_temperature(15)
    first.assert_not_called()
    second.assert_called_once_with(15)


def test_repeated_and_unknown_unsubscribe(sensor: TemperatureSensor) -> None:
    removed, foreign, active = Mock(), Mock(), Mock()
    sensor.subscribe(removed)
    sensor.subscribe(active)
    sensor.unsubscribe(removed)
    sensor.unsubscribe(removed)
    sensor.unsubscribe(foreign)
    sensor.set_temperature(28)
    removed.assert_not_called()
    foreign.assert_not_called()
    active.assert_called_once_with(28)


def test_failed_listener_does_not_interrupt_delivery(sensor: TemperatureSensor, caplog: pytest.LogCaptureFixture) -> None:
    failed, next_listener = Mock(side_effect=RuntimeError("offline")), Mock()
    sensor.subscribe(failed)
    sensor.subscribe(next_listener)
    sensor.set_temperature(25)
    failed.assert_called_once_with(25)
    next_listener.assert_called_once_with(25)
    assert "offline" in caplog.text


def test_subscribe_is_idempotent(sensor: TemperatureSensor) -> None:
    listener = Mock()
    sensor.subscribe(listener)
    sensor.subscribe(listener)
    sensor.set_temperature(9)
    listener.assert_called_once_with(9)
