# -*- coding: utf-8 -*-
"""Недоступное устройство уведомляет ОДИН раз, а не на каждой попытке.

Основание — живой стенд 2026-08-12 (`webcam_sketch`, робота в сети нет):
на одно недоступное устройство пришло **12 строк** — четыре попытки по три
(`connect →` INFO, `Connection … failed: timed out` ERROR от библиотеки,
`connect FAILED` WARNING), — а про итог («сдались, больше не пробуем») не было
**ни одной**. Требование владельца: уведомить один раз.

Три свойства, каждое своим тестом:

1. **громкая строка одна на серию** — повторы уходят в DEBUG и считаются;
2. **счёт не теряется** — при смене сообщения печатается, сколько раз повторилось
   предыдущее (потеря громкости со счётом и голосом, а не молчание);
3. **восстановление видно числом** — успешный connect после серии называет,
   сколько попыток было неудачных.

Судим по **уровню и тексту доехавшей записи**, а не по факту вызова метода:
спай на имени метода сторожил бы имя, а не свойство «оператор видит одну строку».
"""

from __future__ import annotations

import logging
from typing import Any, List, Tuple

import pytest

pytest.importorskip("pymodbus", reason="клиент существует только при установленном pymodbus")

from Services.modbus.core.config import ModbusConfig  # noqa: E402 — после importorskip
from Services.modbus.sdk.client import ModbusSdkClient, _PymodbusChannelBridge  # noqa: E402
from Services.modbus.sdk.errors import ModbusConnectionError  # noqa: E402

_LIB_LOGGER = "pymodbus.logging"


class _Capture(logging.Handler):
    """Сборщик (уровень, текст) — судим наблюдаемое, а не вызовы."""

    def __init__(self) -> None:
        super().__init__()
        self.seen: List[Tuple[str, str]] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.seen.append((record.levelname, record.getMessage()))

    def texts(self, needle: str) -> List[Tuple[str, str]]:
        return [(lvl, msg) for lvl, msg in self.seen if needle in msg]


@pytest.fixture
def capture() -> _Capture:
    handler = _Capture()
    root = logging.getLogger()
    root.addHandler(handler)
    previous = root.level
    root.setLevel(logging.DEBUG)
    try:
        yield handler
    finally:
        root.removeHandler(handler)
        root.setLevel(previous)


class _FakeClient:
    """Дубль pymodbus-клиента. Обязан УМЕТЬ отказывать — иначе он не дубль."""

    def __init__(self, results: List[bool]) -> None:
        self._results = list(results)
        self.calls = 0

    def connect(self) -> bool:
        self.calls += 1
        return self._results.pop(0) if self._results else False

    def close(self) -> None:  # pragma: no cover — не участвует в этих сценариях
        pass


def _client(results: List[bool]) -> Tuple[ModbusSdkClient, _FakeClient]:
    cfg = ModbusConfig(host="10.0.0.9", port=502, unit_id=2)
    client = ModbusSdkClient(cfg)
    fake = _FakeClient(results)
    client._client = fake  # noqa: SLF001 — подмена транспорта, публичной точки нет
    return client, fake


def _try_connect(client: ModbusSdkClient) -> None:
    with pytest.raises(ModbusConnectionError):
        client.connect()


# =============================================================================
# Свойство 1: громкая строка одна на серию
# =============================================================================


def test_first_failure_is_loud_and_repeats_are_quiet(capture: _Capture) -> None:
    """Первый отказ — WARNING, четыре следующих — DEBUG. Ровно как на стенде."""
    client, _ = _client([False] * 5)

    for _ in range(5):
        _try_connect(client)

    failures = capture.texts("connect FAILED")
    levels = [lvl for lvl, _ in failures]
    assert levels == ["WARNING", "DEBUG", "DEBUG", "DEBUG", "DEBUG"], levels
    assert "10.0.0.9" in failures[0][1], "громкая строка обязана называть адрес"
    assert "#2 подряд" in failures[1][1] or "попытка #2" in failures[1][1], failures[1][1]


def test_attempt_line_is_not_repeated_loudly(capture: _Capture) -> None:
    """Строка «пробуем» на серии тоже одна: она удваивала объём, не добавляя фактов."""
    client, _ = _client([False] * 4)

    for _ in range(4):
        _try_connect(client)

    attempts = capture.texts("connect →")
    levels = [lvl for lvl, _ in attempts]
    assert levels == ["INFO", "DEBUG", "DEBUG", "DEBUG"], levels


# =============================================================================
# Свойство 2: счёт не теряется (мост библиотеки)
# =============================================================================


def test_bridge_downgrades_identical_repeats_with_a_counter(capture: _Capture) -> None:
    """Одинаковое сообщение библиотеки: первое на своём уровне, повторы — DEBUG."""
    lib = logging.getLogger(_LIB_LOGGER)
    for _ in range(3):
        lib.error("МАРКЕР-шум Connection to (10.0.0.9, 502) failed: timed out")

    seen = capture.texts("МАРКЕР-шум")
    levels = [lvl for lvl, _ in seen]
    assert levels == ["ERROR", "DEBUG", "DEBUG"], levels
    assert "повтор #1" in seen[1][1] and "повтор #2" in seen[2][1], seen


def test_bridge_reports_how_many_repeats_were_muted(capture: _Capture) -> None:
    """Смена сообщения печатает счёт заглушённых — молчания без числа не остаётся."""
    lib = logging.getLogger(_LIB_LOGGER)
    for _ in range(4):
        lib.error("МАРКЕР-серия одно и то же")
    lib.error("МАРКЕР-другое сообщение")

    tail = capture.texts("МАРКЕР-другое сообщение")
    assert tail, "запись после серии не доехала"
    assert "повторилось ещё 3 раз" in tail[0][1], tail[0][1]
    assert tail[0][0] == "ERROR", "новое сообщение обязано вернуть громкость"


def test_bridge_state_is_per_message_not_global(capture: _Capture) -> None:
    """Разные устройства не глушат друг друга: ключ — (логгер, текст)."""
    lib = logging.getLogger(_LIB_LOGGER)
    lib.error("МАРКЕР-устройство-A недоступно")
    lib.error("МАРКЕР-устройство-B недоступно")

    a = capture.texts("МАРКЕР-устройство-A")
    b = capture.texts("МАРКЕР-устройство-B")
    assert [lvl for lvl, _ in a] == ["ERROR"], a
    assert [lvl for lvl, _ in b] == ["ERROR"], b


# =============================================================================
# Свойство 3: восстановление видно числом
# =============================================================================


def test_recovery_names_how_many_attempts_failed(capture: _Capture) -> None:
    """Успех после серии печатает её длину — иначе восстановление неотличимо."""
    client, _ = _client([False, False, True])

    _try_connect(client)
    _try_connect(client)
    assert client.connect() is True

    connected = capture.texts("connected")
    assert connected, "успешный connect не доехал"
    assert "после 2 неудачных попыток" in connected[0][1], connected[0][1]


def test_streak_resets_after_success(capture: _Capture) -> None:
    """После успеха следующая неудача снова громкая — серия закрыта, а не забыта."""
    client, _ = _client([False, True, False])

    _try_connect(client)
    client.connect()
    capture.seen.clear()
    _try_connect(client)

    failures = capture.texts("connect FAILED")
    assert [lvl for lvl, _ in failures] == ["WARNING"], failures


def test_bridge_handler_is_a_single_instance() -> None:
    """Счёт повторов живёт на handler'е — их обязан быть ровно один на логгер."""
    handlers = [h for h in logging.getLogger("pymodbus").handlers if isinstance(h, _PymodbusChannelBridge)]
    assert len(handlers) == 1, f"мостов {len(handlers)} — счёт повторов раздвоится"


def test_fake_can_actually_refuse() -> None:
    """Проверка самого дубля: он умеет отказывать, иначе тесты выше вакуумны."""
    _, fake = _client([False])
    assert fake.connect() is False
    assert fake.calls == 1


def _unused(_: Any) -> None:  # pragma: no cover — держит импорт Any осмысленным
    pass
