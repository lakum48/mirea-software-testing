import logging
from collections.abc import Callable


class TemperatureSensor:
    def __init__(self, initial: float = 0.0) -> None:
        self._value = initial
        self._listeners: list[Callable[[float], None]] = []

    @property
    def temperature(self) -> float:
        return self._value

    def subscribe(self, callback: Callable[[float], None]) -> None:
        if callback not in self._listeners:
            self._listeners.append(callback)

    def unsubscribe(self, callback: Callable[[float], None]) -> None:
        if callback in self._listeners:
            self._listeners.remove(callback)

    def set_temperature(self, value: float) -> None:
        if value == self._value:
            return
        self._value = value
        for callback in tuple(self._listeners):
            try:
                callback(value)
            except Exception:  # Сбой внешнего подписчика не должен прерывать доставку остальным.
                logging.getLogger(__name__).exception("Не удалось доставить показание датчика")
