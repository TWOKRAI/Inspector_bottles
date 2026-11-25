# -*- coding: utf-8 -*-
# ruff: noqa: F811
"""Слепые приёмочные тесты W1-b: живая запись режима съёмки (триггера) считывателя SDK.

Purpose: закрепить контракт «правка trigger_mode / trigger_source / trigger_period_ms в регистре
доходит до прибора»: поля объявлены `apply == "restart"`, `CodeReaderSdkPlugin` перезапускает захват,
отказ узла или перезапуска не выдаётся за «применено», строки журнала и `last_error` названы литералами.

Написаны ДО реализации, по DESIGN брифа W1-b (plans/2026-11-25_multicam-observability), без чтения
`plugin/sdk_plugin.py`, `plugin/sdk_registers.py`, `core/sdk_reader.py`.

Проводка настоящая, как в `Services/camera_device/tests/test_live_apply_wiring.py`: `RegistersManager` +
`PluginOrchestrator._on_register_update` (поток «системы») -> колбэк подписки плагина -> читатель ->
`FakeNodeApi` (из `test_sdk_trigger.py`). Фейком остаются только прибор и менеджер воркеров процесса.

ПРЕДПОЛОЖЕНО (не задано брифом дословно):
  * имя регистра в `RegistersManager` — `code_reader_sdk` (= `CodeReaderSdkPlugin.name`; так плагин
    берёт managed-регистр через `ctx.registers.get_register(self.name)`);
  * «событие last_error» — значение, которое плагин публикует в дерево состояния (`last_error`) или
    отдаёт командой `get_status`; тест принимает любое из двух (достаточно одного);
  * журнал плагина читается из `MockProcessServices.logs` (уровни `INFO` / `ERROR`).
"""

from __future__ import annotations

import functools
import threading
import time

import pytest

from Services.code_reader.sdk.errors import SdkError
from Services.code_reader.tests.test_sdk_plugin import (  # noqa: F401
    PROCESS_NAME,
    RecordingProxy,
    _bounded,
    _cmd,
    _status,
)
from Services.code_reader.tests.test_sdk_reader import make_reader, wait_until  # noqa: F401
from Services.code_reader.tests.test_sdk_trigger import M, S, FakeNodeApi, _refused

from multiprocess_framework.modules.process_module.generic.plugin_orchestrator import PluginOrchestrator
from multiprocess_framework.modules.process_module.plugins.base import PluginContext
from multiprocess_framework.modules.process_module.plugins.testing import MockProcessServices
from multiprocess_framework.modules.registers_module import RegistersManager

__all__ = []

REG = "code_reader_sdk"
RID = "id_a"
PREFIX = f"CodeReaderSdkPlugin[{RID}]: apply field="
RESTART_TRIGGER_MODE = f"{PREFIX}trigger_mode policy=restart"
WAIT_S = 4.0

_BUSY_MSG = "режим съёмки меняется только при остановленном захвате"


# --------------------------------------------------------------------------
# Фейк прибора: «второе открытие отказывает, третье разрешено»
# --------------------------------------------------------------------------


class _RefuseOpenNApi(FakeNodeApi):
    """`FakeNodeApi`, отказывающий в открытии с номером из `refuse_open_numbers` (нумерация с 1).

    Отказанное открытие попадает в журнал `calls` (как `open` с отказом в базовом фейке), поэтому
    `count("open")` считает и его.
    """

    def __init__(self, *args, refuse_open_numbers=(2,), **kwargs):
        super().__init__(*args, **kwargs)
        self.refuse_open_numbers = set(refuse_open_numbers)
        self.open_number = 0

    def open(self, entry):
        self.open_number += 1
        if self.open_number in self.refuse_open_numbers:
            self.log.append((entry.handle, ("open",)))
            raise SdkError(0x80020001, "MV_CODEREADER_OpenDevice")
        return super().open(entry)


# --------------------------------------------------------------------------
# Стенд: настоящие плагин + RegistersManager + PluginOrchestrator
# --------------------------------------------------------------------------


class _Rig:
    """Настоящий `CodeReaderSdkPlugin` + `RegistersManager` + `PluginOrchestrator` + читатель на `FakeNodeApi`."""

    def __init__(self, monkeypatch, api, **cfg) -> None:
        from Services.code_reader.core.sdk_reader import SdkCodeReader
        from Services.code_reader.plugin.sdk_plugin import CodeReaderSdkPlugin
        from Services.code_reader.plugin.sdk_registers import CodeReaderSdkRegisters

        self.api = api
        monkeypatch.setattr(CodeReaderSdkPlugin, "reader_factory", functools.partial(SdkCodeReader, api=api))
        config = {"auto_start": False, "reader_id": RID, "timeout_ms": 20, **cfg}
        self.proxy = RecordingProxy()
        self.services = MockProcessServices(name=PROCESS_NAME, config=config, state_proxy=self.proxy)
        self.rm = RegistersManager(registers={REG: CodeReaderSdkRegisters()})
        self.ctx = PluginContext(services=self.services, config=config, registers=self.rm, plugin_name=REG)
        self.orch = PluginOrchestrator(self.services)
        self.orch._registers_manager = self.rm
        self.plugin = CodeReaderSdkPlugin()
        self.plugin.configure(self.ctx)
        self.plugin.start(self.ctx)
        self.down = False

    def register_update(self, field: str, value) -> dict:
        """`register_update` как из системного потока процесса: отдельный daemon-поток, ответ обработчика."""
        box: dict = {}

        def system_thread() -> None:
            box["result"] = self.orch._on_register_update({"data": {"register": REG, "field": field, "value": value}})

        thread = threading.Thread(target=system_thread, name="system_sim", daemon=True)
        thread.start()
        thread.join(10.0)
        assert not thread.is_alive(), "обработчик register_update не вернулся за 10 с"
        assert "result" in box, "обработчик register_update упал без ответа"
        return box["result"]

    def opens(self) -> int:
        return self.api.count("open")

    def apply_msgs(self, level: str | None = None) -> list[str]:
        """Сообщения журнала плагина с префиксом строки применения (опционально только одного уровня)."""
        return [
            str(rec["msg"])
            for rec in list(self.services.logs)
            if str(rec["msg"]).startswith(PREFIX) and (level is None or rec["level"] == level)
        ]

    def last_errors_seen(self) -> set[str]:
        """Все значения `last_error`, дошедшие до дерева состояния, плюс текущее из `get_status`."""
        self.plugin.produce()
        seen = {v for v in self.proxy.seen("last_error") if v}
        current = _status(self).get("last_error")
        if current:
            seen.add(current)
        return seen

    def shutdown(self) -> None:
        if self.down:
            return
        self.down = True
        thread = threading.Thread(target=self.plugin.shutdown, args=(self.ctx,), daemon=True)
        thread.start()
        thread.join(15.0)


@pytest.fixture
def make_rig(monkeypatch):
    built: list[_Rig] = []

    def factory(api, **cfg) -> _Rig:
        rig = _Rig(monkeypatch, api, **cfg)
        built.append(rig)
        return rig

    yield factory
    for rig in built:
        rig.shutdown()


def _wait(predicate, what: str, timeout: float = WAIT_S) -> None:
    assert wait_until(predicate, timeout), f"за {timeout} с не случилось: {what}"


def _held(rig: _Rig) -> bool:
    return _status(rig).get("device_held") is True


def _grabbing_rig(make_rig, api, **cfg) -> _Rig:
    """Стенд с `auto_start True`, дождаться: прибор взят (открытие 1) и захват идёт."""
    rig = make_rig(api, auto_start=True, **cfg)
    _wait(lambda: rig.opens() >= 1 and _held(rig), "захват идёт: прибор открыт и удерживается")
    assert rig.opens() == 1
    return rig


# --------------------------------------------------------------------------
# 1. Контракт регистра
# --------------------------------------------------------------------------


def test_trigger_fields_declare_apply_restart():
    from Services.code_reader.plugin.sdk_registers import CodeReaderSdkRegisters

    meta = CodeReaderSdkRegisters.get_all_fields_meta()
    assert {name: meta[name].apply for name in ("trigger_mode", "trigger_source", "trigger_period_ms")} == {
        "trigger_mode": "restart",
        "trigger_source": "restart",
        "trigger_period_ms": "restart",
    }
    assert meta["timeout_ms"].apply != "restart"


# --------------------------------------------------------------------------
# 2. Правка при идущем захвате доходит до прибора
# --------------------------------------------------------------------------


def test_live_write_while_grabbing_restarts_and_reaches_device(make_rig):
    api = FakeNodeApi()
    rig = _grabbing_rig(make_rig, api)

    result = rig.register_update("trigger_mode", "On")

    assert result["success"] is True, result
    _wait(lambda: rig.opens() == 2 and ("set_enum_str", M, "On") in api.calls, "второе открытие и запись TriggerMode")
    calls = api.calls
    second_open = [i for i, c in enumerate(calls) if c == ("open",)][1]
    assert ("set_enum_str", M, "On") in calls[second_open:], "запись TriggerMode не после второго открытия"
    _wait(lambda: len(rig.apply_msgs("INFO")) == 1, "одна INFO-строка применения")
    assert rig.apply_msgs("INFO") == [f"{RESTART_TRIGGER_MODE} restarted=True applied=True"]
    _wait(lambda: _status(rig).get("device_held") is True, "прибор снова удерживается")
    assert _status(rig)["device_held"] is True
    assert rig.opens() == 2


# --------------------------------------------------------------------------
# 3. Отказ узла прибора — не «применено»
# --------------------------------------------------------------------------


def _refused_node_rig(make_rig) -> _Rig:
    """Захват идёт (открытие 1), затем `trigger_mode "On"` -> отказ узла -> откат; ждём конец перезапуска."""
    api = FakeNodeApi(fail=_refused(M))
    rig = _grabbing_rig(make_rig, api)
    result = rig.register_update("trigger_mode", "On")
    assert result["success"] is True, result
    _wait(lambda: rig.opens() == 3 and len(rig.apply_msgs("ERROR")) == 1, "перезапуск, откат и ERROR-строка")
    return rig


def test_refused_node_write_is_not_reported_as_applied(make_rig):
    rig = _refused_node_rig(make_rig)

    assert rig.opens() == 3  # 1 исходное, 2 с отказом узла, 3 откат на прежний режим
    errors = rig.apply_msgs("ERROR")
    assert len(errors) == 1, errors
    assert errors[0].startswith(f"{RESTART_TRIGGER_MODE} restarted=True applied=False param_errors=TriggerMode: ")
    assert errors[0].endswith(" fallback=old ok=True")
    assert [m for m in rig.apply_msgs("INFO") if "applied=True" in m] == []
    expected = "trigger apply: field=trigger_mode applied=False"
    _wait(lambda: expected in rig.last_errors_seen(), f"last_error == {expected!r}")


def test_return_to_old_value_after_node_refusal_keeps_reader_on_old_mode(make_rig):
    rig = _refused_node_rig(make_rig)
    api = rig.api
    assert rig.opens() == 3

    result = rig.register_update("trigger_mode", "")

    assert result["success"] is True, result
    unchanged = f"{RESTART_TRIGGER_MODE} restarted=False: значение не изменило режим"
    _wait(lambda: unchanged in rig.apply_msgs("INFO"), "INFO «значение не изменило режим»")
    assert rig.opens() == 3, "возврат к прежнему значению не должен перезапускать захват"

    assert _cmd(rig, "release_device")["released"] is True
    assert _cmd(rig, "take_device")["status"] == "ok"
    assert api.count("open") == 4
    fourth_open = [i for i, c in enumerate(api.calls) if c == ("open",)][3]
    node_writes = [c for c in api.calls[fourth_open:] if c[0].startswith("set_") and c[1] == M]
    assert node_writes == [], "читатель держит режим «On» вместо прежнего"


# --------------------------------------------------------------------------
# 4. Неудачный перезапуск -> откат на прежний режим
# --------------------------------------------------------------------------


def test_failed_restart_falls_back_to_old_trigger(make_rig):
    api = _RefuseOpenNApi(refuse_open_numbers=(2,))
    rig = _grabbing_rig(make_rig, api)

    result = rig.register_update("trigger_mode", "On")

    assert result["success"] is True, result
    _wait(lambda: rig.opens() == 3 and len(rig.apply_msgs("ERROR")) == 1, "отказ второго открытия и откат (открытие 3)")
    assert rig.opens() == 3
    errors = rig.apply_msgs("ERROR")
    assert len(errors) == 1, errors
    assert errors[0].startswith(f"{RESTART_TRIGGER_MODE} restarted=False error=")
    assert errors[0].endswith(" fallback=old ok=True")
    expected = "trigger apply: field=trigger_mode restarted=False; прежний режим идёт"
    _wait(lambda: expected in rig.last_errors_seen(), f"last_error == {expected!r}")


# --------------------------------------------------------------------------
# 5. То же значение — без перезапуска
# --------------------------------------------------------------------------


def test_same_value_does_not_restart(make_rig):
    api = FakeNodeApi()
    rig = _grabbing_rig(make_rig, api, trigger_mode="On")

    result = rig.register_update("trigger_mode", "On")

    assert result["success"] is True, result
    unchanged = f"{RESTART_TRIGGER_MODE} restarted=False: значение не изменило режим"
    _wait(lambda: unchanged in rig.apply_msgs("INFO"), "INFO «значение не изменило режим»")
    assert rig.opens() == 1, "то же значение перезапустило захват"


# --------------------------------------------------------------------------
# 6. Правка без захвата входит в следующий take_device
# --------------------------------------------------------------------------


def test_live_write_while_stopped_applies_on_next_take(make_rig):
    api = FakeNodeApi(pre_written={M})  # камера уже в режиме On: источник доступен для записи
    rig = make_rig(api, auto_start=False)
    assert rig.opens() == 0

    result = rig.register_update("trigger_source", "SelfTrigger")

    assert result["success"] is True, result
    assert rig.opens() == 0, "правка без захвата открыла прибор"
    assert _cmd(rig, "take_device")["status"] == "ok"
    assert api.count("open") == 1
    assert ("set_enum_str", S, "SelfTrigger") in api.calls
    assert api.values[101][S] == 7  # SelfTrigger на приборе


# --------------------------------------------------------------------------
# 7. SdkCodeReader.set_trigger при идущем захвате
# --------------------------------------------------------------------------


def test_set_trigger_refused_while_running(make_reader):
    api = FakeNodeApi()
    r = make_reader(api, timeout_ms=20)
    assert _bounded(r.reader.start, 10.0) is True

    with pytest.raises(RuntimeError) as info:
        r.reader.set_trigger({"trigger_mode": "On"})
    assert str(info.value) == _BUSY_MSG
    assert api.node_calls() == [], "отказанный set_trigger тронул узлы прибора"

    _bounded(r.reader.stop, 10.0)
    r.reader.set_trigger({"trigger_mode": "On"})  # после stop() не бросает
    assert _bounded(r.reader.start, 10.0) is True
    assert ("set_enum_str", M, "On") in api.calls  # режим вошёл в следующий старт


# --------------------------------------------------------------------------
# 8. shutdown снимает подписку
# --------------------------------------------------------------------------


def test_shutdown_unsubscribes(make_rig):
    api = FakeNodeApi()
    rig = make_rig(api, auto_start=False)

    # Подписка жива до shutdown: правка без захвата оставляет строку применения.
    assert rig.register_update("trigger_mode", "On")["success"] is True
    stopped_line = f"{RESTART_TRIGGER_MODE} restarted=False: захват не идёт, значение войдёт в следующий take_device"
    _wait(lambda: stopped_line in rig.apply_msgs(), "подписка не отозвалась на правку до shutdown")
    before = rig.apply_msgs()

    rig.shutdown()
    opens_after_shutdown = rig.opens()

    assert rig.register_update("trigger_mode", "Off")["success"] is True
    time.sleep(0.3)  # «ничего не случилось» нельзя дождаться событием; окно для запоздавшего колбэка

    assert rig.opens() == opens_after_shutdown == 0
    assert rig.apply_msgs() == before, "подписка пережила shutdown"
