# -*- coding: utf-8 -*-
# ruff: noqa: F811
"""Слепые приёмочные тесты Task 2.2a: режим съёмки (триггер) считывателя SDK.

Написаны ДО реализации, только по брифу (строки приёмки 1-17), без чтения кода
``core/sdk_reader.py`` и ``plugin/sdk_*.py``.

Контракт, который проверяется:
  * ``SdkCodeReader(..., trigger={"trigger_mode", "trigger_source", "trigger_period_ms"})``;
  * при ``start()`` между ``open`` и ``start_grabbing`` пишутся узлы
    ``TriggerMode`` -> ``TriggerSource`` -> ``TriggerSelfTriggerPeriod`` (перед записью узел читается);
  * при остановке (после ``stop_grabbing``, до ``close``) возвращаются прежние значения в обратном порядке;
  * отказ узла — не ошибка сессии: ``stats()["param_errors"]`` (узел -> текст), ``errors``/``last_error`` не растут;
  * плагин: ключи конфига ``trigger_*``, ``param_errors`` в register, ``get_status`` и дереве состояния.

Фейк ``FakeNodeApi`` ниже хранит состояние прибора (значения узлов по handle) и ведёт себя как
камера 1: потомок (источник, период) недоступен (0x80020106), пока родитель не записан; запись любого
узла при идущем захвате — 0x80020106; период вне [20, 10000] — 0x80020102; ``set_enum_str`` кодирует
строки в ASCII, как настоящий ``MvCodeReaderApi`` (не-ASCII -> ``UnicodeEncodeError``).

ПРЕДПОЛОЖЕНО о публичном API (одно место правки — константы и хелперы ниже):
  * плагин называется ``CodeReaderSdkPlugin`` (так в реальном дереве, не ``SdkCodeReaderPlugin``);
  * команды плагина — через ``plugin.commands[<имя>]`` (как в test_sdk_plugin.py);
  * register-поле ``param_errors`` — строка ``"узел: текст; узел: текст"``, порядок узлов M, S, P;
  * «пропущен» в тексте пропущенных потомков — с маленькой буквы, в начале текста.
"""

from __future__ import annotations

import threading
import time
from types import SimpleNamespace

import pytest

from Services.code_reader.sdk.errors import E_GC_ACCESS, E_GC_RANGE, SdkError
from Services.code_reader.tests.test_sdk_plugin import (  # noqa: F401 — make_plugin это pytest-фикстура
    PROCESS_NAME,
    RecordingProxy,
    _bounded,
    _cmd,
    _status,
    make_plugin,
)
from Services.code_reader.tests.test_sdk_reader import make_reader, wait_until  # noqa: F401

from multiprocess_framework.modules.process_module.plugins.base import PluginContext
from multiprocess_framework.modules.process_module.plugins.testing import MockProcessServices

M = "TriggerMode"
S = "TriggerSource"
P = "TriggerSelfTriggerPeriod"

FULL = {"trigger_mode": "On", "trigger_source": "SelfTrigger", "trigger_period_ms": 40}

# Исходные значения камеры 1: Off=0, Line0=0, период 300 (литералы из брифа).
START_FULL = [
    ("open",),
    ("get_enum", M),
    ("set_enum_str", M, "On"),
    ("get_enum", S),
    ("set_enum_str", S, "SelfTrigger"),
    ("get_int", P),
    ("set_int", P, 40),
    ("start_grabbing",),
]
STOP_FULL = [
    ("stop_grabbing",),
    ("set_int", P, 300),
    ("set_enum", S, 0),
    ("set_enum", M, 0),
    ("close",),
]

_ENUM_STR = {"Off": 0, "On": 1, "Line0": 0, "SelfTrigger": 7}
_PARENT = {S: M, P: S}
_PERIOD_MIN, _PERIOD_MAX = 20, 10000


# --------------------------------------------------------------------------
# Фейк прибора: пара «FakeNodeApi + _entry»
# --------------------------------------------------------------------------


def _entry(ip: str, handle: int) -> SimpleNamespace:
    return SimpleNamespace(ip=ip, model="MV-ID3013PM", serial=f"S{handle}", info=object(), handle=handle)


class FakeNodeApi:
    """Фейк ``MvCodeReaderApi`` с состоянием узлов и журналом вызовов.

    ``calls`` — журнал кортежей БЕЗ handle (``enum_devices`` и ``get_frame`` в него не входят);
    ``calls_of(h)`` — то же для одного handle. ``fail`` — отказы: ключ ``(метод, узел)`` или
    ``(handle, метод, узел)``, значение — исключение (для ``open``/``start_grabbing`` узел ``""``).
    ``pre_written`` — узлы, считающиеся записанными с момента ``open`` (камера уже в нужном режиме).
    """

    def __init__(self, entries=None, initial=None, *, fail=None, pre_written=(), delay_s: float = 0.0):
        self.entries = list(entries) if entries is not None else [_entry("10.0.0.1", 101)]
        self.values = {e.handle: {M: 0, S: 0, P: 300} for e in self.entries}
        for handle, vals in (initial or {}).items():
            self.values[handle].update(vals)
        self.fail = dict(fail or {})
        self.pre_written = set(pre_written)
        self.delay_s = delay_s
        self.log: list[tuple[int, tuple]] = []
        self._written = {e.handle: set() for e in self.entries}
        self._grabbing = {e.handle: False for e in self.entries}

    # --- наблюдение ---
    @property
    def calls(self) -> list[tuple]:
        return [c for _, c in list(self.log)]

    def calls_of(self, handle: int) -> list[tuple]:
        return [c for h, c in list(self.log) if h == handle]

    def count(self, name: str) -> int:
        return [c[0] for c in self.calls].count(name)

    def node_calls(self) -> list[tuple]:
        return [c for c in self.calls if c[0].startswith(("get_", "set_"))]

    # --- внутреннее ---
    def _enter(self, h, method: str, name: str = "", *args) -> None:
        self.log.append((h, (method, name, *args) if name else (method,)))
        if self.delay_s:
            time.sleep(self.delay_s)
        exc = self.fail.get((h, method, name)) or self.fail.get((method, name))
        if exc is not None:
            raise exc

    def _access(self, h, name: str, *, write: bool) -> None:
        if write and self._grabbing[h]:
            raise SdkError(E_GC_ACCESS, f"MV_CODEREADER_SetValue[{name}]")
        parent = _PARENT.get(name)
        if parent is not None and parent not in self._written[h]:
            raise SdkError(E_GC_ACCESS, f"MV_CODEREADER_Node[{name}]")

    def _store(self, h, name: str, value: int) -> None:
        self.values[h][name] = value
        self._written[h].add(name)

    # --- API ---
    def enum_devices(self):
        return list(self.entries)

    def open(self, entry):
        h = entry.handle
        self._enter(h, "open")
        self._written[h] = set(self.pre_written)
        self._grabbing[h] = False
        return h

    def get_enum(self, h, name):
        self._enter(h, "get_enum", name)
        self._access(h, name, write=False)
        return {"cur": self.values[h][name], "supported": [0, 1, 7]}

    def get_int(self, h, name):
        self._enter(h, "get_int", name)
        self._access(h, name, write=False)
        return {"cur": self.values[h][name], "min": _PERIOD_MIN, "max": _PERIOD_MAX, "inc": 1}

    def set_enum_str(self, h, name, value):
        self._enter(h, "set_enum_str", name, value)
        name.encode("ascii")
        value.encode("ascii")  # как настоящий api: не-ASCII -> UnicodeEncodeError
        self._access(h, name, write=True)
        if value not in _ENUM_STR:
            raise SdkError(E_GC_RANGE, f"MV_CODEREADER_SetEnumValueByString[{name}]")
        self._store(h, name, _ENUM_STR[value])

    def set_enum(self, h, name, value):
        self._enter(h, "set_enum", name, value)
        self._access(h, name, write=True)
        self._store(h, name, value)

    def set_int(self, h, name, value):
        self._enter(h, "set_int", name, value)
        self._access(h, name, write=True)
        if not _PERIOD_MIN <= value <= _PERIOD_MAX:
            raise SdkError(E_GC_RANGE, f"MV_CODEREADER_SetIntValue[{name}]")
        self._store(h, name, value)

    def start_grabbing(self, h):
        self._enter(h, "start_grabbing")
        self._grabbing[h] = True

    def stop_grabbing(self, h):
        self._enter(h, "stop_grabbing")
        self._grabbing[h] = False

    def close(self, h):
        self._enter(h, "close")

    def get_frame(self, h, timeout_ms):
        time.sleep(0.005)  # «кадра за таймаут не было»
        return None


# --------------------------------------------------------------------------
# Хелперы теста
# --------------------------------------------------------------------------


def _start(r) -> bool:
    return _bounded(r.reader.start, 10.0)


def _stop(r) -> None:
    _bounded(r.reader.stop, 10.0)


def _pe(r) -> dict:
    return r.reader.stats()["param_errors"]


def _refused(name: str, method: str = "set_enum_str", code: int = E_GC_RANGE) -> dict:
    return {(method, name): SdkError(code, f"MV_CODEREADER_X[{name}]")}


# --------------------------------------------------------------------------
# Строка 1. Без полей режима прибор не трогаем
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "trigger",
    [{}, {"trigger_mode": "", "trigger_source": "", "trigger_period_ms": 0}],
    ids=["empty-mapping", "empty-values"],
)
def test_empty_trigger_fields_touch_no_node(make_reader, trigger):
    api = FakeNodeApi()
    r = make_reader(api, trigger=trigger, timeout_ms=20)
    assert _start(r) is True
    _stop(r)
    assert api.node_calls() == []
    assert api.calls == [("open",), ("start_grabbing",), ("stop_grabbing",), ("close",)]
    assert _pe(r) == {}


class _KwReader:
    """Читатель-заглушка: фиксирует, с чем его создала фабрика плагина."""

    def __init__(self, on_frame, on_error, **kw):
        self.kw = kw

    def stats(self):
        return {
            "frames": 0,
            "ok": 0,
            "no_code": 0,
            "bad_code": 0,
            "errors": 0,
            "state": "stopped",
            "last_error": None,
            "device": None,
            "device_held": False,
            "param_errors": {},
        }

    def start(self):
        return True

    def stop(self, timeout: float = 2.0):
        return None


def _configure(config: dict):
    """Плагин, сконфигурированный по текущему ``reader_factory`` класса (без start)."""
    from Services.code_reader.plugin.sdk_plugin import CodeReaderSdkPlugin

    services = MockProcessServices(name=PROCESS_NAME, config=config, state_proxy=RecordingProxy())
    ctx = PluginContext(services=services, config=config)
    plugin = CodeReaderSdkPlugin()
    plugin.configure(ctx)
    return plugin


@pytest.mark.parametrize(
    "extra",
    [{}, {"trigger_mode": "", "trigger_source": "", "trigger_period_ms": 0}],
    ids=["absent", "empty-values"],
)
def test_plugin_without_trigger_fields_gives_factory_no_trigger_kwarg(monkeypatch, extra):
    from Services.code_reader.plugin.sdk_plugin import CodeReaderSdkPlugin

    monkeypatch.setattr(CodeReaderSdkPlugin, "reader_factory", _KwReader)
    plugin = _configure({"auto_start": False, **extra})
    assert "trigger" not in plugin._reader.kw
    # Поля режима есть в register и пусты по умолчанию.
    assert plugin._reg.trigger_mode == ""
    assert plugin._reg.trigger_source == ""
    assert plugin._reg.trigger_period_ms == 0
    assert plugin._reg.param_errors == ""


# --------------------------------------------------------------------------
# Строка 2. Порядок записи при start()
# --------------------------------------------------------------------------


def test_all_three_fields_written_in_order_between_open_and_start_grabbing(make_reader):
    api = FakeNodeApi()
    r = make_reader(api, trigger=FULL, timeout_ms=20)
    assert _start(r) is True
    assert api.calls == START_FULL
    # Эффект на приборе: записано то, что просили (On=1, SelfTrigger=7, период 40).
    assert api.values[101] == {M: 1, S: 7, P: 40}
    assert _pe(r) == {}


# --------------------------------------------------------------------------
# Строка 3. Возврат при stop() в обратном порядке, между stop_grabbing и close
# --------------------------------------------------------------------------


def test_stop_restores_original_values_in_reverse_order_including_zero(make_reader):
    api = FakeNodeApi()
    r = make_reader(api, trigger=FULL, timeout_ms=20)
    assert _start(r) is True
    _stop(r)
    assert api.calls == START_FULL + STOP_FULL
    assert api.values[101] == {M: 0, S: 0, P: 300}  # прибор вернулся в исходное


# --------------------------------------------------------------------------
# Строка 4. Исходные зависимых узлов читаются после записи родителя
# --------------------------------------------------------------------------


def test_dependent_originals_are_read_after_parent_write_and_restored(make_reader):
    api = FakeNodeApi(initial={101: {S: 5, P: 123}})
    r = make_reader(api, trigger=FULL, timeout_ms=20)
    assert _start(r) is True
    assert _pe(r) == {}  # чтение до записи родителя дало бы 0x80020106 и запись в param_errors
    _stop(r)
    assert api.calls[len(START_FULL) :] == [
        ("stop_grabbing",),
        ("set_int", P, 123),
        ("set_enum", S, 5),
        ("set_enum", M, 0),
        ("close",),
    ]
    assert api.values[101] == {M: 0, S: 5, P: 123}


# --------------------------------------------------------------------------
# Строка 5. Исходное зависимого узла не прочиталось
# --------------------------------------------------------------------------


def test_unreadable_source_original_skips_write_and_descendants(make_reader):
    api = FakeNodeApi(fail=_refused(S, "get_enum", E_GC_ACCESS))
    r = make_reader(api, trigger=FULL, timeout_ms=20)
    assert _start(r) is True
    pe = _pe(r)
    assert set(pe) == {S, P}
    assert "0x80020106" in pe[S]
    assert pe[P].startswith("пропущен")
    _stop(r)
    assert api.calls == [
        ("open",),
        ("get_enum", M),
        ("set_enum_str", M, "On"),
        ("get_enum", S),
        ("start_grabbing",),
        ("stop_grabbing",),
        ("set_enum", M, 0),  # возврат остальных идёт
        ("close",),
    ]


def test_unreadable_period_original_skips_only_period_write(make_reader):
    api = FakeNodeApi(fail=_refused(P, "get_int", E_GC_ACCESS))
    r = make_reader(api, trigger=FULL, timeout_ms=20)
    assert _start(r) is True
    pe = _pe(r)
    assert set(pe) == {P}
    assert "0x80020106" in pe[P]
    _stop(r)
    assert api.calls == [
        ("open",),
        ("get_enum", M),
        ("set_enum_str", M, "On"),
        ("get_enum", S),
        ("set_enum_str", S, "SelfTrigger"),
        ("get_int", P),
        ("start_grabbing",),
        ("stop_grabbing",),
        ("set_enum", S, 0),
        ("set_enum", M, 0),
        ("close",),
    ]


# --------------------------------------------------------------------------
# Строка 6. Отказ записи режима: потомки не трогаются, захват идёт
# --------------------------------------------------------------------------


def test_mode_write_refused_skips_children_and_capture_runs(make_reader):
    api = FakeNodeApi(fail=_refused(M, "set_enum_str", E_GC_RANGE))
    r = make_reader(api, trigger=FULL, timeout_ms=20)
    assert _start(r) is True
    assert r.reader.stats()["state"] == "running"
    assert api.calls == [("open",), ("get_enum", M), ("set_enum_str", M, "On"), ("start_grabbing",)]
    pe = _pe(r)
    assert set(pe) == {M, S, P}
    assert "0x80020102" in pe[M]
    assert pe[S].startswith("пропущен")
    assert pe[P].startswith("пропущен")
    _stop(r)
    assert api.calls[4:] == [("stop_grabbing",), ("close",)]  # возвратов нет: ничего не записано


# --------------------------------------------------------------------------
# Строка 7. Задан только источник
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "trigger",
    [
        {"trigger_source": "SelfTrigger"},
        {"trigger_mode": "", "trigger_source": "SelfTrigger", "trigger_period_ms": 0},
    ],
    ids=["only-key", "empty-others"],
)
def test_source_without_mode_is_still_tried(make_reader, trigger):
    api = FakeNodeApi(pre_written={M})  # камера уже в режиме On: источник доступен
    r = make_reader(api, trigger=trigger, timeout_ms=20)
    assert _start(r) is True
    assert api.calls == [
        ("open",),
        ("get_enum", S),
        ("set_enum_str", S, "SelfTrigger"),
        ("start_grabbing",),
    ]
    assert api.values[101][S] == 7
    _stop(r)
    assert api.calls[4:] == [("stop_grabbing",), ("set_enum", S, 0), ("close",)]


# --------------------------------------------------------------------------
# Строка 9. Не-ASCII в имени режима
# --------------------------------------------------------------------------


def test_non_ascii_mode_is_contained_close_not_lost_and_text_is_type_only(make_reader):
    api = FakeNodeApi()
    r = make_reader(api, trigger={"trigger_mode": "Вкл"}, timeout_ms=20)
    assert _start(r) is True
    text = _pe(r)[M]
    assert text
    assert "Вкл" not in text
    assert "UnicodeEncodeError" in text
    _stop(r)
    assert api.count("open") == 1
    assert api.count("close") == 1


# --------------------------------------------------------------------------
# Строка 10. Отказ узла — не ошибка сессии
# --------------------------------------------------------------------------


def test_node_refusal_is_not_a_session_error(make_reader):
    api = FakeNodeApi(fail=_refused(S, "set_enum_str", E_GC_RANGE))
    r = make_reader(api, trigger=FULL, timeout_ms=20)
    assert _start(r) is True
    assert _pe(r)  # отказ зафиксирован
    s = r.reader.stats()
    assert s["last_error"] is None
    assert s["errors"] == 0
    _stop(r)
    s = r.reader.stats()
    assert s["last_error"] is None
    assert s["errors"] == 0
    assert r.errors == []  # on_error не вызван


# --------------------------------------------------------------------------
# Строка 11. Отказ возврата одного узла
# --------------------------------------------------------------------------


def test_restore_failure_of_one_node_does_not_block_others_or_close(make_reader):
    api = FakeNodeApi()
    r = make_reader(api, trigger=FULL, timeout_ms=20)
    assert _start(r) is True
    api.fail[("set_enum", S)] = RuntimeError("boom")
    errors_before = r.reader.stats()["errors"]
    callbacks_before = len(r.errors)
    _stop(r)
    assert api.calls[len(START_FULL) :] == STOP_FULL  # попытка по источнику была, остальные и close идут
    assert api.values[101][M] == 0
    assert api.values[101][P] == 300
    assert r.reader.stats()["errors"] == errors_before + 1
    assert len(r.errors) == callbacks_before + 1
    assert api.count("close") == 1


# --------------------------------------------------------------------------
# Строка 12. Отказ start_grabbing после записи
# --------------------------------------------------------------------------


def test_start_grabbing_failure_restores_in_reverse_and_closes_once(make_reader):
    api = FakeNodeApi(fail={("start_grabbing", ""): SdkError(0x80020001, "MV_CODEREADER_StartGrabbing")})
    r = make_reader(api, trigger=FULL, timeout_ms=20)
    assert _start(r) is False
    assert api.calls == START_FULL + [
        ("set_int", P, 300),
        ("set_enum", S, 0),
        ("set_enum", M, 0),
        ("close",),
    ]
    assert api.values[101] == {M: 0, S: 0, P: 300}
    _stop(r)
    assert api.count("close") == 1  # повторный stop() второго close не даёт


# --------------------------------------------------------------------------
# Строка 13. Перезапуск
# --------------------------------------------------------------------------


def test_start_stop_start_repeats_same_sequence(make_reader):
    api = FakeNodeApi()
    r = make_reader(api, trigger=FULL, timeout_ms=20)
    assert _start(r) is True
    _stop(r)
    assert _start(r) is True
    _stop(r)
    one = START_FULL + STOP_FULL
    assert api.calls == one + one


def test_clean_restart_clears_param_errors_of_refused_first_run(make_reader):
    api = FakeNodeApi(fail=_refused(S, "set_enum_str", E_GC_RANGE))
    r = make_reader(api, trigger=FULL, timeout_ms=20)
    assert _start(r) is True
    assert set(_pe(r)) == {S, P}  # первый запуск с отказом
    _stop(r)
    api.fail.clear()
    n = len(api.calls)
    assert _start(r) is True
    assert _pe(r) == {}
    _stop(r)
    assert api.calls[n:] == START_FULL + STOP_FULL


# --------------------------------------------------------------------------
# Строка 14. stats()["param_errors"]: копия и безопасность при параллельном опросе
# --------------------------------------------------------------------------


def test_stats_param_errors_is_a_copy(make_reader):
    api = FakeNodeApi(fail=_refused(M, "set_enum_str", E_GC_RANGE))
    r = make_reader(api, trigger=FULL, timeout_ms=20)
    assert _start(r) is True
    first = _pe(r)
    snapshot = dict(first)
    assert set(snapshot) == {M, S, P}
    first["junk"] = "x"
    first[M] = "изменено снаружи"
    first.pop(S)
    assert _pe(r) == snapshot


def test_stats_polled_in_loop_during_start_does_not_raise(make_reader):
    api = FakeNodeApi(delay_s=0.03)  # start() идёт ~0.3 с: опрос заведомо попадает внутрь
    r = make_reader(api, trigger=FULL, timeout_ms=20)
    seen: list = []
    failures: list[BaseException] = []
    done = threading.Event()

    def poll() -> None:
        while not done.is_set():
            try:
                seen.append(r.reader.stats()["param_errors"])
            except BaseException as exc:  # noqa: BLE001 — собираем для проверки в потоке теста
                failures.append(exc)

    poller = threading.Thread(target=poll, daemon=True)
    poller.start()
    try:
        ok = _bounded(r.reader.start, 10.0)
    finally:
        done.set()
        poller.join(5.0)
    assert not poller.is_alive(), "опрос stats() завис"
    assert failures == []
    assert ok is True
    assert seen, "опрос не успел ни разу"
    assert all(isinstance(x, dict) and set(x) <= {M, S, P} for x in seen)
    assert _pe(r) == {}


# --------------------------------------------------------------------------
# Строка 15. Два читателя на одном фейке
# --------------------------------------------------------------------------

_TWO = [_entry("10.0.0.1", 101), _entry("10.0.0.2", 102)]
_FULL_B = {"trigger_mode": "On", "trigger_source": "SelfTrigger", "trigger_period_ms": 50}


def test_two_readers_restore_their_own_original_values(make_reader):
    api = FakeNodeApi(entries=_TWO, initial={102: {M: 1, S: 2, P: 77}})
    a = make_reader(api, device_ip="10.0.0.1", trigger=FULL, timeout_ms=20)
    b = make_reader(api, device_ip="10.0.0.2", trigger=_FULL_B, timeout_ms=20)
    assert _start(a) is True
    assert _start(b) is True
    _stop(a)
    _stop(b)
    assert api.calls_of(101) == START_FULL + STOP_FULL
    assert api.calls_of(102) == [
        ("open",),
        ("get_enum", M),
        ("set_enum_str", M, "On"),
        ("get_enum", S),
        ("set_enum_str", S, "SelfTrigger"),
        ("get_int", P),
        ("set_int", P, 50),
        ("start_grabbing",),
        ("stop_grabbing",),
        ("set_int", P, 77),
        ("set_enum", S, 2),
        ("set_enum", M, 1),
        ("close",),
    ]
    assert api.values[101] == {M: 0, S: 0, P: 300}
    assert api.values[102] == {M: 1, S: 2, P: 77}


def test_two_readers_have_independent_param_errors(make_reader):
    api = FakeNodeApi(entries=_TWO, fail={(102, "set_enum_str", M): SdkError(E_GC_RANGE, "x")})
    a = make_reader(api, device_ip="10.0.0.1", trigger=FULL, timeout_ms=20)
    b = make_reader(api, device_ip="10.0.0.2", trigger=FULL, timeout_ms=20)
    assert _start(a) is True
    assert _start(b) is True
    assert _pe(a) == {}
    assert set(_pe(b)) == {M, S, P}
    assert "0x80020102" in _pe(b)[M]
    _stop(a)
    _stop(b)
    assert _pe(a) == {}


# --------------------------------------------------------------------------
# Строка 16. Плагин: передача в читатель, register, статус, дерево
# --------------------------------------------------------------------------


def test_plugin_passes_trigger_mapping_to_factory(monkeypatch):
    from Services.code_reader.plugin.sdk_plugin import CodeReaderSdkPlugin

    monkeypatch.setattr(CodeReaderSdkPlugin, "reader_factory", _KwReader)
    plugin = _configure({"auto_start": False, **FULL})
    assert dict(plugin._reader.kw["trigger"]) == FULL
    assert plugin._reg.trigger_mode == "On"
    assert plugin._reg.trigger_source == "SelfTrigger"
    assert plugin._reg.trigger_period_ms == 40


def _synced(w, pred, timeout: float = 3.0) -> bool:
    """Ждёт, пока register/дерево догонят читателя (статус и produce() обновляют их из stats())."""

    def check() -> bool:
        _status(w)
        w.plugin.produce()
        return pred()

    return wait_until(check, timeout)


def test_plugin_node_refusal_reaches_register_status_and_tree(make_plugin):
    api = FakeNodeApi(fail=_refused(M, "set_enum_str", E_GC_RANGE))
    w = make_plugin(api, timeout_ms=20, **FULL)
    assert _cmd(w, "take_device")["status"] == "ok"

    assert _synced(w, lambda: "0x80020102" in w.plugin._reg.param_errors)
    status = _status(w)["param_errors"]
    assert "0x80020102" in status
    parts = status.split("; ")
    assert [p.split(": ", 1)[0] for p in parts] == [M, S, P]  # формат «узел: текст; …»
    assert w.plugin._reg.param_errors == status
    assert wait_until(lambda: any("0x80020102" in v for v in w.proxy.seen("param_errors")), 3.0)
    assert "0x80020102" in w.proxy.tree()["param_errors"]


def test_plugin_clean_run_has_empty_param_errors_everywhere(make_plugin):
    api = FakeNodeApi()
    w = make_plugin(api, timeout_ms=20, **FULL)
    assert _cmd(w, "take_device")["status"] == "ok"
    assert api.calls == START_FULL
    assert _status(w)["param_errors"] == ""
    assert w.plugin._reg.param_errors == ""
    assert all(v == "" for v in w.proxy.seen("param_errors"))


def test_plugin_clean_rerun_clears_previous_param_errors_in_tree(make_plugin):
    api = FakeNodeApi(fail=_refused(M, "set_enum_str", E_GC_RANGE))
    w = make_plugin(api, timeout_ms=20, **FULL)
    assert _cmd(w, "take_device")["status"] == "ok"
    assert _synced(w, lambda: "0x80020102" in w.plugin._reg.param_errors)

    assert _cmd(w, "release_device")["released"] is True
    api.fail.clear()
    assert _cmd(w, "take_device")["status"] == "ok"

    assert _status(w)["param_errors"] == ""
    assert _synced(w, lambda: w.plugin._reg.param_errors == "")
    assert wait_until(lambda: w.proxy.seen("param_errors")[-1:] == [""], 3.0), w.proxy.seen("param_errors")


# --------------------------------------------------------------------------
# Строка 8. Период ниже допустимого для камеры: register строится, отказ — в param_errors
# --------------------------------------------------------------------------


def test_plugin_period_below_camera_range_is_accepted_by_register_and_refused_by_device(make_plugin):
    api = FakeNodeApi()
    w = make_plugin(api, timeout_ms=20, trigger_mode="On", trigger_source="SelfTrigger", trigger_period_ms=10)
    assert w.plugin._reg.trigger_period_ms == 10  # configure прошёл, register не отверг 10
    assert _cmd(w, "take_device")["status"] == "ok"
    assert ("set_int", P, 10) in api.calls
    assert _synced(w, lambda: "0x80020102" in w.plugin._reg.param_errors)
    assert "0x80020102" in _status(w)["param_errors"]
    assert api.values[101][P] == 300  # прибор значение не принял


# --------------------------------------------------------------------------
# Строка 16 (связка). Настоящие плагин и читатель на фейковом api: конфиг -> записи в прибор
# --------------------------------------------------------------------------


def test_real_plugin_and_real_reader_write_recipe_config_to_device(make_plugin):
    api = FakeNodeApi(entries=[_entry("192.168.1.10", 101)])
    w = make_plugin(
        api,
        device_ip="192.168.1.10",
        reader_id="id3013-sdk-1",
        timeout_ms=20,
        trigger_mode="On",
        trigger_source="SelfTrigger",
        trigger_period_ms=40,
    )
    assert _cmd(w, "take_device")["status"] == "ok"
    assert api.calls == START_FULL
    assert api.values[101] == {M: 1, S: 7, P: 40}
    assert _cmd(w, "release_device")["released"] is True
    assert api.calls == START_FULL + STOP_FULL
    assert api.values[101] == {M: 0, S: 0, P: 300}
