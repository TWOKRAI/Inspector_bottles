"""C-37, тесты автора: внешняя запись регистра из другого потока (H1, H2).

Плагин не держит замков (ограничение 8(б) спеки): тесты проверяют, что при гонке записей
нет падений и итог сходится (регистр и раскладка не расходятся) — не что нет потерь.
Потоки daemon, ожидание с дедлайном: зависший поток не вешает прогон.
"""

from __future__ import annotations

import threading
import time

from multiprocess_framework.modules.process_module.plugins.base import PluginContext
from multiprocess_framework.modules.process_module.plugins.testing import MockProcessServices
from multiprocess_framework.modules.registers_module import RegistersManager

from Plugins.processing.word_layout.plugin import WordLayoutPlugin
from Plugins.processing.word_layout.registers import WordLayoutRegisters

_REG = "word_layout"
_CFG = {"require_pick": False, "word_source": "signal_2", "settle_frames": 1, "target_word": ""}
_JOIN_S = 5.0
_N = 200
_MIN_ITEMS = 400  # основной поток обрабатывает не меньше стольких items — записи реально перемежаются


def _make() -> tuple[WordLayoutPlugin, RegistersManager]:
    services = MockProcessServices(name="layout", config=dict(_CFG))
    rm = RegistersManager(registers={_REG: WordLayoutRegisters()})
    plugin = WordLayoutPlugin()
    plugin.configure(PluginContext(services=services, config=dict(_CFG), registers=rm))
    return plugin, rm


def _disk(label: str, tid: object) -> dict:
    pred = {"label": label, "confidence": 0.9, "angle_deg": 0.0, "angle_valid": True}
    return {"predictions": [pred], "sidecar": {"track_id": tid}}


def _run_writer(target) -> tuple[threading.Thread, list[BaseException]]:
    """Запустить писателя в daemon-потоке; исключения потока собираются в список."""
    errors: list[BaseException] = []

    def _body() -> None:
        try:
            target()
        except BaseException as exc:  # noqa: BLE001 - тест фиксирует любое падение писателя
            errors.append(exc)

    t = threading.Thread(target=_body, daemon=True)
    t.start()
    return t, errors


def test_external_writes_from_other_thread() -> None:
    """200 внешних записей из второго потока, пока основной подаёт пустые items.

    Проверяет отсутствие падений и итог (последнее слово «РИМ» действует), не отсутствие потерь.
    """
    p, rm = _make()
    p.process([{"signal_2": "МИР"}])

    def writer() -> None:
        for i in range(_N):
            word = "МИР" if i % 2 == 0 else "РИМ"  # чётных 100: начинает «МИР», последняя (i=199) — «РИМ»
            rm.set_field_value(_REG, "target_word", word)
            time.sleep(0)  # отдать GIL основному потоку между записями

    t, errors = _run_writer(writer)
    for _ in range(_MIN_ITEMS):
        p.process([{"predictions": []}])
    t.join(timeout=_JOIN_S)
    assert not t.is_alive()
    assert errors == []

    out = p.process([_disk("Р", 1)])[0]
    assert out["robot_job"]["slot"] == 0  # «РИМ»: Р — ячейка 0
    assert rm.get_register(_REG).target_word == "РИМ"


def test_port_and_register_writers_race() -> None:
    """Регистр пишет второй поток, порт «МИР» подаёт основной: регистр и раскладка не расходятся.

    Проверяет отсутствие падений и согласие итога, не отсутствие потерь.
    """
    p, rm = _make()

    def writer() -> None:
        for i in range(_N):
            rm.set_field_value(_REG, "target_word", "РИМ" if i % 2 == 0 else "ЛЕС")
            time.sleep(0)

    t, errors = _run_writer(writer)
    for i in range(_MIN_ITEMS):
        p.process([{"signal_2": "МИР"} if i % 2 == 0 else {"predictions": []}])
    t.join(timeout=_JOIN_S)
    assert not t.is_alive()
    assert errors == []

    p.process([{"predictions": []}])
    reg = rm.get_register(_REG)
    assert " ".join(reg.target_word.upper().split()) == reg.word_norm
