# -*- coding: utf-8 -*-
"""Исчерпание попыток переподключения уведомляет ОДИН раз — и уведомление доезжает.

До 2026-08-12 «сдались» не логировалось вообще: ``_note_reconnect_failed``
выставляло флаги и возвращало ``False`` молча. На живом стенде оператор видел
россыпь одинаковых WARNING от попыток, а затем тишину — и не мог отличить
«перестали пробовать» от «наладилось».

Второе свойство здесь важнее первого: **запись обязана доехать до писателя.**
У драйверов подмешан ``ObservableMixin``, но слоты ``logger``/``error``/``stats``
им никто не регистрирует (ни одного ``register_manager`` во всём
``Services/device_hub``), поэтому ``self._log_warning`` тихо возвращает ``None``
и считает отказ в ``manager_call_failures``. Уведомление, написанное через
миксин, ушло бы в никуда — и тест, проверяющий «метод позван», был бы зелёным.
Поэтому тест ловит **запись на root-логгере**, а не вызов метода.
"""

from __future__ import annotations

import logging
from typing import List, Tuple

from Services.device_hub.drivers.base import BaseDeviceDriver


class _Entry:
    """Минимальная запись реестра устройств (форма, а не импорт схемы)."""

    def __init__(self, dev_id: str, transport: dict) -> None:
        self.id = dev_id
        self.transport = transport


class _Driver(BaseDeviceDriver):
    """Драйвер-пустышка: живая база, заглушённая периферия."""

    kind = "test"

    def initialize(self) -> bool:
        self.is_initialized = True
        return True

    def shutdown(self) -> bool:
        self.is_initialized = False
        return True

    def connect(self) -> bool:
        return False

    def disconnect(self) -> None:
        pass

    @property
    def is_connected(self) -> bool:
        return False

    def tick(self, stop_event=None):  # noqa: ANN001, ANN201 — форма базы
        return None

    def call(self, op: str, args: dict) -> dict:
        return {}


class _Capture(logging.Handler):
    def __init__(self) -> None:
        super().__init__()
        self.seen: List[Tuple[str, str]] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.seen.append((record.levelname, record.getMessage()))


def _driver(max_attempts: int, transport: dict | None = None) -> _Driver:
    entry = _Entry(
        "robot_main",
        transport if transport is not None else {"type": "tcp", "host": "192.168.1.7", "port": 502, "unit_id": 2},
    )
    driver = _Driver(entry)
    driver.max_reconnect_attempts = max_attempts
    return driver


def _capture():
    handler = _Capture()
    root = logging.getLogger()
    root.addHandler(handler)
    root.setLevel(logging.DEBUG)
    return handler, root


def test_exhaustion_notifies_exactly_once() -> None:
    """Три попытки при лимите 3 → ровно ОДНА громкая строка, на последней."""
    driver = _driver(3)
    handler, root = _capture()
    try:
        results = [driver._note_reconnect_failed() for _ in range(3)]  # noqa: SLF001
    finally:
        root.removeHandler(handler)

    assert results == [True, True, False], results
    notices = [(lvl, msg) for lvl, msg in handler.seen if "сдались" in msg]
    assert len(notices) == 1, f"уведомлений {len(notices)}, ожидалась ровно одна: {notices}"
    assert notices[0][0] == "WARNING", notices[0]


def test_notice_names_device_address_and_attempts() -> None:
    """Строка отвечает на «кто, куда и сколько раз» — иначе она бесполезна."""
    driver = _driver(2)
    handler, root = _capture()
    try:
        driver._note_reconnect_failed()  # noqa: SLF001
        driver._note_reconnect_failed()  # noqa: SLF001
    finally:
        root.removeHandler(handler)

    text = next(msg for lvl, msg in handler.seen if "сдались" in msg)
    assert "robot_main" in text
    assert "192.168.1.7" in text and "502" in text and "unit2" in text
    assert "после 2 попыток" in text


def test_no_notice_while_attempts_remain() -> None:
    """Пока лимит не исчерпан — тишина: уведомление про итог, а не про попытку."""
    driver = _driver(5)
    handler, root = _capture()
    try:
        for _ in range(4):
            driver._note_reconnect_failed()  # noqa: SLF001
    finally:
        root.removeHandler(handler)

    assert [msg for _, msg in handler.seen if "сдались" in msg] == []


def test_unlimited_mode_never_notifies() -> None:
    """max_reconnect_attempts<=0 — прежнее бесконечное поведение, без уведомлений."""
    driver = _driver(0)
    handler, root = _capture()
    try:
        results = [driver._note_reconnect_failed() for _ in range(10)]  # noqa: SLF001
    finally:
        root.removeHandler(handler)

    assert results == [True] * 10
    assert [msg for _, msg in handler.seen if "сдались" in msg] == []


def test_reset_restores_a_full_limit_and_a_second_notice() -> None:
    """После ручного «Подключить» серия начинается заново — и уведомит снова."""
    driver = _driver(2)
    handler, root = _capture()
    try:
        driver._note_reconnect_failed()  # noqa: SLF001
        driver._note_reconnect_failed()  # noqa: SLF001
        driver.reset_reconnect()
        driver._note_reconnect_failed()  # noqa: SLF001
        driver._note_reconnect_failed()  # noqa: SLF001
    finally:
        root.removeHandler(handler)

    assert len([msg for _, msg in handler.seen if "сдались" in msg]) == 2


def test_serial_address_is_named_too() -> None:
    """RTU-устройство: в строке порт, а не «адрес неизвестен»."""
    driver = _driver(1, {"type": "rtu", "serial_port": "COM7"})
    handler, root = _capture()
    try:
        driver._note_reconnect_failed()  # noqa: SLF001
    finally:
        root.removeHandler(handler)

    text = next(msg for lvl, msg in handler.seen if "сдались" in msg)
    assert "COM7" in text


def test_broken_transport_does_not_raise() -> None:
    """Кривой transport не роняет драйвер: уведомление — не место для падения."""
    driver = _driver(1, {})
    driver.entry.transport = "не словарь"
    handler, root = _capture()
    try:
        driver._note_reconnect_failed()  # noqa: SLF001
    finally:
        root.removeHandler(handler)

    text = next(msg for lvl, msg in handler.seen if "сдались" in msg)
    assert "адрес неизвестен" in text


def test_mixin_slot_is_still_unwired() -> None:
    """Страж посылки: у драйвера НЕТ зарегистрированного logger-слота.

    Если однажды разъём драйверов подключат по-настоящему, этот тест покраснеет —
    и напомнит перевести уведомление обратно на ``self._log_warning``, а не
    оставить два писателя. Проверка посылки, а не поведения.
    """
    driver = _driver(1)
    assert driver._registry.get("logger") is None, (  # noqa: SLF001
        "слот logger у драйвера появился — уведомление пора вернуть на разъём миксина"
    )
