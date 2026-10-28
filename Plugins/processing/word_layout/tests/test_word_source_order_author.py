"""C-37, тесты автора: внешняя запись регистра из другого потока (H1, H2).

Плагин не держит замков (ограничение 8(б) спеки): тесты проверяют, что при гонке записей
нет падений и итог сходится (регистр и раскладка не расходятся) — не что нет потерь.
Потоки daemon, ожидание с дедлайном: зависший поток не вешает прогон.
"""

from __future__ import annotations

import threading
import time
from collections.abc import Callable
from typing import Any, ClassVar

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
    """Smoke «нет исключений»: регистр пишет второй поток, порт «МИР» подаёт основной.

    Итоговое согласие регистра и раскладки следует из устройства кода и порядок записей не доказывает —
    порядок закреплён детерминированными тестами P3a/P3b ниже. Не проверяет отсутствие потерь.
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


# --- детерминированные тесты: отказ регистра и окна гонки (без потоков) -----------------------


class _RefusingRegisters(WordLayoutRegisters):
    """Регистр, чей ``update_field`` отказывает на ``target_word`` со значениями из ``refuse``."""

    refuse: ClassVar[set[str]] = set()

    def update_field(self, field_name: str, value: Any, access_level: int = 0) -> tuple[bool, str | None]:
        if field_name == "target_word" and value in type(self).refuse:
            return False, "отказ (инъекция)"
        return super().update_field(field_name, value, access_level)


class _HookedPlugin(WordLayoutPlugin):
    """Крючки вокруг записи порта: ``before`` — до ``update_field``, ``after`` — сразу после него."""

    before: Callable[[], None] | None = None
    after: Callable[[], None] | None = None

    def _write_word(self, w: str, log: bool = True) -> bool:
        if self.before is not None:
            hook, self.before = self.before, None
            hook()
        ok = super()._write_word(w, log)
        if self.after is not None:
            hook, self.after = self.after, None
            hook()
        return ok


def _make_with(
    plugin_cls: type[WordLayoutPlugin], reg_cls: type[WordLayoutRegisters], target_word: str = ""
) -> tuple[WordLayoutPlugin, MockProcessServices, RegistersManager]:
    cfg = {**_CFG, "target_word": target_word}
    services = MockProcessServices(name="layout", config=dict(cfg))
    rm = RegistersManager(registers={_REG: reg_cls()})
    plugin = plugin_cls()
    plugin.configure(PluginContext(services=services, config=dict(cfg), registers=rm))
    return plugin, services, rm


def _lines(services: MockProcessServices, mark: str) -> list[str]:
    return [e["msg"] for e in services.logs if mark in e["msg"]]


def _write(rm: RegistersManager, value: str) -> None:
    assert rm.set_field_value(_REG, "target_word", value) == (True, None)


def test_port_write_refused_keeps_register_word() -> None:
    """Регистр отказал порту: слово порта не применено, действует «РИМ», одна строка об отказе."""
    p, services, rm = _make_with(WordLayoutPlugin, _RefusingRegisters, "РИМ")
    p.process([{"predictions": []}])
    _RefusingRegisters.refuse = {"МИР"}
    try:
        p.process([{"signal_2": "МИР"}])
    finally:
        _RefusingRegisters.refuse = set()
    assert p._reg.word_norm == "РИМ"
    assert rm.get_register(_REG).target_word == "РИМ"
    assert len(_lines(services, "не записано в регистр")) == 1


def test_rollback_refused_logs_once_and_no_false_info() -> None:
    """Откат пустой записи отклонён: 5 пустых items дают одну строку об отказе и ни одной «не принято»."""
    p, services, rm = _make_with(WordLayoutPlugin, _RefusingRegisters)
    p.process([{"signal_2": "МИР"}])
    _write(rm, "")
    _RefusingRegisters.refuse = {"МИР"}
    try:
        for _ in range(5):
            p.process([{"predictions": []}])
    finally:
        _RefusingRegisters.refuse = set()
    assert p._reg.word_norm == "МИР"
    assert rm.get_register(_REG).target_word == ""
    assert len(_lines(services, "не записано в регистр")) == 1
    assert _lines(services, "пустое слово в регистре не принято") == []


def test_port_word_stored_raw() -> None:
    """Порт «мир» лежит в регистре как пришло, раскладка по нормализованному слову."""
    p, _, rm = _make_with(WordLayoutPlugin, WordLayoutRegisters)
    p.process([{"signal_2": "мир"}])
    assert rm.get_register(_REG).target_word == "мир"
    assert p._reg.word_norm == "МИР"


def test_p3a_external_write_after_port_update_is_next_arrival() -> None:
    """Ограничение (а): запись между update_field порта и ``_own_word = w`` принимается на следующем item."""
    p, services, rm = _make_with(_HookedPlugin, WordLayoutRegisters, "РИМ")
    p.process([{"predictions": []}])
    p.after = lambda: _write(rm, "ЛЕС")
    p.process([{"signal_2": "МИР"}])
    p.process([{"predictions": []}])
    assert p._reg.word_norm == "ЛЕС"
    assert rm.get_register(_REG).target_word == "ЛЕС"
    assert any("'МИР' → 'ЛЕС' (источник: регистр)" in m for m in _lines(services, "смена слова"))


def test_p3b_external_write_before_port_write_loses_to_port() -> None:
    """Ограничение (б): запись между проверкой регистра и записью порта того же item затёрта портом."""
    p, services, rm = _make_with(_HookedPlugin, WordLayoutRegisters, "РИМ")
    p.process([{"predictions": []}])
    p.before = lambda: _write(rm, "ЛЕС")
    p.process([{"signal_2": "МИР"}])
    p.process([{"predictions": []}])
    assert p._reg.word_norm == "МИР"
    assert rm.get_register(_REG).target_word == "МИР"
    assert _lines(services, "'ЛЕС'") == []
