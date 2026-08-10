# -*- coding: utf-8 -*-
"""D7 — мост stdlib-логгера pymodbus в наш разъём (АВТОРСКИЕ тесты механизма).

Свойства, которые мост обязан держать и которые он держал БЕЗ единого теста
(находка координатора при приёмке D7):

  1. запись библиотеки доезжает до нашего разъёма — иначе третий формат в
     консоли остаётся, а задача считается закрытой;
  2. **ровно один раз.** С обработчиком на stdlib-root запись выходила ДВАЖДЫ:
     мостом и оригиналом, поднявшимся до root'а. Пока у root'а хендлеров нет,
     дубля не видно — но это свойство окружения, а не гарантия: один
     `logging.basicConfig()` в прикладном коде возвращает второй формат;
  3. мост не зацикливается. Он пишет через ``get_std_logger(record.name)``, и
     если бы вид писал в stdlib-логгер с ТЕМ ЖЕ именем, запись вернулась бы в
     мост — рекурсия ровно в момент, когда связь уже потеряна. Вид пишет в
     ``mpf.<имя>``, и это проверяется, а не предполагается;
  4. установка идемпотентна: второй импорт не удваивает строки.
"""

from __future__ import annotations

import logging
from typing import List

import pytest

pytest.importorskip("pymodbus", reason="мост существует только при установленном pymodbus")

from Services.modbus.sdk.client import (  # noqa: E402 — после importorskip
    PYMODBUS_LOGGER_NAMES,
    _PymodbusChannelBridge,
    install_pymodbus_bridge,
)

_LIB_LOGGER = "pymodbus.logging"


class _Capture(logging.Handler):
    """Сборщик записей: смотрим ИМЯ и текст, а не факт вызова какого-то метода."""

    def __init__(self) -> None:
        super().__init__()
        self.seen: List[str] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.seen.append(f"{record.name}|{record.getMessage()}")


@pytest.fixture
def root_capture() -> _Capture:
    """Обработчик на root — им и ловится наш вид (`mpf.*`), и утечка оригинала."""
    handler = _Capture()
    root = logging.getLogger()
    root.addHandler(handler)
    previous_level = root.level
    root.setLevel(logging.DEBUG)
    try:
        yield handler
    finally:
        root.removeHandler(handler)
        root.setLevel(previous_level)


def test_library_record_reaches_our_connector(root_capture: _Capture) -> None:
    """Запись pymodbus доезжает до разъёма — под именем вида, а не библиотеки."""
    logging.getLogger(_LIB_LOGGER).error("Connection to (127.0.0.1, 502) failed: timed out")

    ours = [line for line in root_capture.seen if line.startswith("mpf.")]
    assert ours, f"мост не доставил запись: {root_capture.seen}"
    assert "timed out" in ours[0]


def test_library_record_is_delivered_exactly_once(root_capture: _Capture) -> None:
    """Ни дубля от оригинала, ни второго прохода моста.

    Литерал 1, а не «не меньше одного»: «доехало хотя бы раз» согласилось бы и
    с двумя строками — тем самым вторым форматом, ради которого задача заведена.
    """
    logging.getLogger(_LIB_LOGGER).error("МАРКЕР-D7-однократность")

    marked = [line for line in root_capture.seen if "МАРКЕР-D7-однократность" in line]
    assert len(marked) == 1, f"запись вышла {len(marked)} раз(а): {marked}"


def test_bridge_does_not_feed_itself(root_capture: _Capture) -> None:
    """Вид пишет в ``mpf.<имя>``, а не в имя библиотеки — иначе рекурсия.

    Проверяется наблюдаемое имя записи, а не реализация вида: если однажды
    ``get_std_logger`` начнёт писать в логгер того же имени, запись вернётся в
    мост и тест покраснеет здесь, а не подвесит прогон в проде.
    """
    logging.getLogger(_LIB_LOGGER).error("МАРКЕР-D7-рекурсия")

    names = {line.split("|", 1)[0] for line in root_capture.seen if "МАРКЕР-D7-рекурсия" in line}
    assert names == {f"mpf.{_LIB_LOGGER}"}, f"неожиданные имена записей: {names}"


def test_install_is_idempotent() -> None:
    """Повторная установка не добавляет второй мост — иначе строки удвоятся."""
    before = {
        name: sum(1 for h in logging.getLogger(name).handlers if isinstance(h, _PymodbusChannelBridge))
        for name in PYMODBUS_LOGGER_NAMES
    }
    assert install_pymodbus_bridge() == 0, "мост уже стоял — установка обязана вернуть 0"

    after = {
        name: sum(1 for h in logging.getLogger(name).handlers if isinstance(h, _PymodbusChannelBridge))
        for name in PYMODBUS_LOGGER_NAMES
    }
    assert after == before == dict.fromkeys(PYMODBUS_LOGGER_NAMES, 1)


def test_library_logger_does_not_propagate() -> None:
    """Подъём к root'у отключён — «один писатель» держится структурно."""
    for name in PYMODBUS_LOGGER_NAMES:
        assert logging.getLogger(name).propagate is False, name
