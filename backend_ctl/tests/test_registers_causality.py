# -*- coding: utf-8 -*-
"""Task 0.11 (B-3): проверенная запись = образ ДО + подтверждение хоста + образ ПОСЛЕ.

Блок 1 — ``set_register_verified`` и ``register_restore`` (``registers.py``).
Блок 2 — ``config_reload_verified`` и ``telemetry_set(verify=True)`` (``driver.py``):
причина отказа хоста называется вслух, а не подменяется ложной.

Ожидаемые значения — литералы: ни одно не выводится из проверяемого кода. Каждый тест
«хост отверг» сначала проверяет, что запись ушла, и только потом — что результат ложен:
иначе он был бы зелёным и для инструмента, который ничего не послал.
"""

from __future__ import annotations

import threading
from collections.abc import Callable
from typing import Any

import pytest

from backend_ctl.driver import BackendDriver


def _bounded[T](fn: Callable[[], T], limit: float = 5.0) -> T:
    """Вызов в daemon-потоке с дедлайном: зависший инструмент — красный тест, не зависший прогон."""
    box: dict[str, Any] = {}

    def run() -> None:
        try:
            box["res"] = fn()
        except BaseException as exc:  # noqa: BLE001 - пробрасываем в поток теста
            box["exc"] = exc

    t = threading.Thread(target=run, daemon=True)
    t.start()
    t.join(limit)
    assert not t.is_alive(), f"инструмент завис дольше {limit} с"
    if "exc" in box:
        raise box["exc"]
    return box["res"]


def _rejected(command: str) -> dict[str, Any]:
    return {"success": False, "error": f"No handler for {command}"}


# --------------------------------------------------------------------------
# Блок 1: регистры
# --------------------------------------------------------------------------


class _FakeRegisterHost:
    """Подставной хост регистров: журнал команд, применяет запись или отвергает её.

    ``unreadable_reads`` — номера (с 1) обращений к ``introspect.registers``, на которые
    хост отвечает таймаутом: образ прочитать не удалось. ``coerce_to_int`` — приёмник как
    Pydantic-регистр: строку-число приводит к int (MCP отдаёт скаляр строкой).

    Неизвестное поле: по умолчанию ack ``success True`` без эффекта (так отвечают старые
    дублёры, ``test_driver.py:1311``, и любой приёмник, принявший запись молча).
    ``unknown_field_refuses`` — текущий хост: ``set_field_value`` отвергает неизвестное поле
    (``registers_module/core/manager.py:197-201``, ``plugin_orchestrator.py:879-890``) ответом
    ``{"success": False, "register", "field", "error": "Поле ... не найдено ..."}``.
    ``foreign_write`` — запись, которую хост отверг, при этом всё равно попадает в регистр
    (чужой писатель успел поставить то же значение): образ после равен цели при отказе ack.
    """

    def __init__(
        self,
        registers: dict[str, dict[str, Any]],
        *,
        applies: bool,
        unreadable_reads: tuple[int, ...] = (),
        coerce_to_int: bool = False,
        unknown_field_refuses: bool = False,
        foreign_write: bool = False,
    ) -> None:
        self.registers = registers
        self.applies = applies
        self.unreadable_reads = unreadable_reads
        self.coerce_to_int = coerce_to_int
        self.unknown_field_refuses = unknown_field_refuses
        self.foreign_write = foreign_write
        self.commands: list[str] = []
        self.writes: list[dict[str, Any]] = []
        self._reads = 0

    def send(self, process, command, args=None, **kw):
        self.commands.append(command)
        if command == "register_update":
            self.writes.append(dict(args))
            reg = self.registers.get(args["register"], {})
            if not self.applies:
                if self.foreign_write and args["field"] in reg:
                    reg[args["field"]] = args["value"]  # чужой писатель, хост свою запись отверг
                return _rejected("register_update")
            if args["field"] not in reg:
                if self.unknown_field_refuses:
                    return {
                        "success": False,
                        "register": args["register"],
                        "field": args["field"],
                        "error": f"Поле '{args['field']}' не найдено в регистре '{args['register']}'",
                    }
                return {"success": True}  # ack без эффекта: поля нет, значение не записано
            value = args["value"]
            reg[args["field"]] = int(value) if self.coerce_to_int and isinstance(value, str) else value
            return {"success": True}
        if command == "introspect.registers":
            self._reads += 1
            if self._reads in self.unreadable_reads:
                return {"success": False, "error": "timeout"}
            return {"success": True, "process": process, "registers": self.registers}
        raise AssertionError(f"неожиданная команда: {command}")


def _driver(
    monkeypatch,
    registers: dict[str, dict[str, Any]],
    *,
    applies: bool,
    unreadable_reads: tuple[int, ...] = (),
    coerce_to_int: bool = False,
    unknown_field_refuses: bool = False,
    foreign_write: bool = False,
) -> tuple[BackendDriver, _FakeRegisterHost]:
    d = BackendDriver()
    host = _FakeRegisterHost(
        registers,
        applies=applies,
        unreadable_reads=unreadable_reads,
        coerce_to_int=coerce_to_int,
        unknown_field_refuses=unknown_field_refuses,
        foreign_write=foreign_write,
    )
    monkeypatch.setattr(d, "send_command", host.send)
    return d, host


def _snapshot(fields: dict[str, Any]) -> dict[str, Any]:
    return {"processes": {"preprocessor": {"resize": fields}}}


def test_rejected_write_equal_value_not_success(monkeypatch) -> None:
    """Поле 10, цель 10, хост отверг запись: раньше readback «10 == 10» давал success True."""
    d, host = _driver(monkeypatch, {"resize": {"target_width": 10}}, applies=False)

    res = _bounded(lambda: d.set_register_verified("preprocessor", "resize", "target_width", 10))

    assert host.writes == [{"register": "resize", "field": "target_width", "value": 10}]
    assert res["success"] is False, res
    assert res["verified"] is False, res
    assert res["verdict"] == "failed", res
    assert res["vacuous"] is True, res


def test_accepted_write_from_other_value_confirmed(monkeypatch) -> None:
    """Поле 5, цель 10, хост применил: образ до, подтверждение, образ после; порядок команд — литерал."""
    d, host = _driver(monkeypatch, {"resize": {"target_width": 5}}, applies=True)

    res = _bounded(lambda: d.set_register_verified("preprocessor", "resize", "target_width", 10))

    assert host.commands == ["introspect.registers", "register_update", "introspect.registers"]
    assert res["verdict"] == "confirmed", res
    assert res["success"] is True, res
    assert res["verified"] is True, res
    assert res["vacuous"] is False, res
    assert res["pre"] == 5, res
    assert res["actual"] == 10, res
    assert res["expected"] == 10, res
    assert res["unverifiable"] == [], res


def test_equal_value_accepted_is_vacuous_and_verified(monkeypatch) -> None:
    """Поле 10, цель 10, хост применил: запись ничего не меняла — ``vacuous``, но ``verified`` истинен."""
    d, _host = _driver(monkeypatch, {"resize": {"target_width": 10}}, applies=True)

    res = _bounded(lambda: d.set_register_verified("preprocessor", "resize", "target_width", 10))

    assert res["verdict"] == "vacuous", res
    assert res["vacuous"] is True, res
    assert res["success"] is True, res
    assert res["verified"] is True, res


def test_string_coerced_scalar_still_confirmed(monkeypatch) -> None:
    """MCP коэрсит скаляр в строку («10»), приёмник приводит к числу: строгое == дало бы ложный failed."""
    d, host = _driver(monkeypatch, {"resize": {"target_width": 5}}, applies=True, coerce_to_int=True)

    res = _bounded(lambda: d.set_register_verified("preprocessor", "resize", "target_width", "10"))

    assert host.writes == [{"register": "resize", "field": "target_width", "value": "10"}]
    assert res["actual"] == 10, res  # приёмник привёл строку к числу: строгое == с "10" ложно
    assert res["success"] is True, res
    assert res["verified"] is True, res
    assert res["verdict"] == "confirmed", res


@pytest.mark.parametrize(
    ("unreadable_reads", "expected_unverifiable"),
    [((2,), ["post"]), ((1,), ["pre"])],
    ids=["post_unreadable", "pre_unreadable"],
)
def test_unreadable_image_is_unverifiable(monkeypatch, unreadable_reads, expected_unverifiable) -> None:
    """Образ не прочитан (таймаут readback) — «не проверено», а не «провалено» и не «успех»."""
    d, host = _driver(monkeypatch, {"resize": {"target_width": 5}}, applies=True, unreadable_reads=unreadable_reads)

    res = _bounded(lambda: d.set_register_verified("preprocessor", "resize", "target_width", 10))

    assert host.writes == [{"register": "resize", "field": "target_width", "value": 10}]
    assert res["verdict"] == "unverifiable", res
    assert res["unverifiable"] == expected_unverifiable, res
    assert res["success"] is False, res
    assert res["verified"] is False, res


def test_absent_field_on_successful_read_is_failed_not_unreadable(monkeypatch) -> None:
    """Чтение успешно, поля нет, ack ``success True`` без эффекта: не «не прочитали» (unverifiable пуст), а провал."""
    d, _host = _driver(monkeypatch, {"resize": {"target_width": 5}}, applies=True)

    res = _bounded(lambda: d.set_register_verified("preprocessor", "resize", "width", 10))

    assert res["verdict"] == "failed", res
    assert res["unverifiable"] == [], res
    assert res["found"] is False, res
    assert res["success"] is False, res
    assert res["known_registers"] == ["resize"], res


def test_absent_field_real_host_refusal_is_failed(monkeypatch) -> None:
    """Текущий хост неизвестное поле ОТВЕРГАЕТ (``Поле ... не найдено``): failed, образ читается, unverifiable пуст."""
    d, host = _driver(monkeypatch, {"resize": {"target_width": 5}}, applies=True, unknown_field_refuses=True)

    res = _bounded(lambda: d.set_register_verified("preprocessor", "resize", "zz", 10))

    assert host.writes == [{"register": "resize", "field": "zz", "value": 10}]
    assert res["ack"]["success"] is False, res
    assert res["ack"]["field"] == "zz", res
    assert "не найдено" in res["ack"]["error"], res
    assert res["verdict"] == "failed", res
    assert res["unverifiable"] == [], res
    assert res["found"] is False, res
    assert res["success"] is False, res
    assert res["verified"] is False, res


def test_restore_rejected_write_not_success(monkeypatch) -> None:
    """Поле 5, снимок 10, хост отверг: запись ушла (сначала это), итог — провал и счётчик failed."""
    d, host = _driver(monkeypatch, {"resize": {"target_width": 5}}, applies=False)

    res = _bounded(lambda: d.register_restore(_snapshot({"target_width": 10})))

    assert host.writes == [{"register": "resize", "field": "target_width", "value": 10}]
    assert res["success"] is False, res
    assert res["written"] == 1, res
    assert res["failed"] == 1, res
    assert res["vacuous"] == 0, res


def test_restore_equal_state_counts_vacuous(monkeypatch) -> None:
    """Поле 10, снимок 10: запись не уходит, честный пустой restore: written 0, success True, vacuous 1."""
    d, host = _driver(monkeypatch, {"resize": {"target_width": 10}}, applies=True)

    res = _bounded(lambda: d.register_restore(_snapshot({"target_width": 10})))

    assert host.writes == []
    assert res["written"] == 0, res
    assert res["success"] is True, res
    assert res["vacuous"] == 1, res
    assert res["failed"] == 0, res


def test_restore_mixed_counts_per_field(monkeypatch) -> None:
    """a уже равно снимку (vacuous), b дрейфнуло и хост применил (written): единица счёта — поле."""
    d, host = _driver(monkeypatch, {"resize": {"a": 1, "b": 9}}, applies=True)

    res = _bounded(lambda: d.register_restore(_snapshot({"a": 1, "b": 2})))

    assert host.writes == [{"register": "resize", "field": "b", "value": 2}]
    assert res["success"] is True, res
    assert res["written"] == 1, res
    assert res["skipped"] == 1, res
    assert res["vacuous"] == 1, res
    assert res["failed"] == 0, res
    assert res["mismatches"] == [], res


def test_restore_coerced_snapshot_is_consistent(monkeypatch) -> None:
    """Снимок {"w": "10"}, живое 10, приёмник приводит строку к int: все ключи ответа согласованы.

    Запись уходит (строгое ``10 != "10"``), образ после 10 равен «10» по ``_values_match``: поле
    vacuous, ``success True`` и ``mismatches`` пуст, ``verified 1``. Раньше ``mismatches`` считался
    строгим ``!=`` и непустой список соседствовал с ``success True``.
    """
    d, host = _driver(monkeypatch, {"resize": {"w": 10}}, applies=True, coerce_to_int=True)

    res = _bounded(lambda: d.register_restore(_snapshot({"w": "10"})))

    assert host.writes == [{"register": "resize", "field": "w", "value": "10"}]
    assert res["success"] is True, res
    assert res["written"] == 1, res
    assert res["vacuous"] == 1, res
    assert res["failed"] == 0, res
    assert res["mismatches"] == [], res
    assert res["verified"] == 1, res


def test_restore_rejected_write_with_foreign_equal_image_is_failed(monkeypatch) -> None:
    """Поле 5, снимок 10, хост отверг запись, но чужой писатель поставил 10: образ после равен снимку.

    Образ без отказа выглядел бы подтверждением, а ack отказа решает: ``failed 1``, ``success False``.
    ``mismatches`` при этом пуст: образ совпал. Ответ с ``success`` из ``not mismatches`` соврал бы.
    """
    d, host = _driver(monkeypatch, {"resize": {"target_width": 5}}, applies=False, foreign_write=True)

    res = _bounded(lambda: d.register_restore(_snapshot({"target_width": 10})))

    assert host.writes == [{"register": "resize", "field": "target_width", "value": 10}]
    assert host.registers == {"resize": {"target_width": 10}}  # образ после действительно равен снимку
    assert res["success"] is False, res
    assert res["written"] == 1, res
    assert res["failed"] == 1, res
    assert res["vacuous"] == 0, res
    assert res["mismatches"] == [], res
    assert res["verified"] == 1, res


# --------------------------------------------------------------------------
# Блок 2: config_reload_verified и telemetry_set(verify=True)
# --------------------------------------------------------------------------


def _config_driver(monkeypatch, reload_reply: dict[str, Any]) -> tuple[BackendDriver, list[str]]:
    d = BackendDriver()
    calls: list[str] = []

    def fake_send(process, command, args=None, **kw):
        calls.append(command)
        if command == "config.reload":
            return reload_reply
        if command == "introspect.observability":
            return {
                "success": True,
                "result": {"success": True, "counters": {"logger": {"channel_written_records": 40, "at": 101.0}}},
            }
        return {"success": True, "result": {"success": True}}

    monkeypatch.setattr(d, "send_command", fake_send)
    return d, calls


def test_config_reload_rejected_reason_names_host_refusal(monkeypatch) -> None:
    """Хост отверг config.reload при переданной inline-секции: причина — отказ хоста, не «без inline-секции»."""
    d, calls = _config_driver(monkeypatch, _rejected("config.reload"))

    res = _bounded(lambda: d.config_reload_verified("lines", observability={"log_level": "DEBUG"}, settle=0))

    assert "config.reload" in calls
    assert res["success"] is False, res
    assert res["verdict"] == "unverifiable", res
    assert "No handler for config.reload" in res["verdict_reason"], res
    assert "без inline-секции" not in res["verdict_reason"], res


def test_config_reload_timeout_reason_is_not_a_refusal(monkeypatch) -> None:
    """Таймаут — не отказ (0.3): причина называет отсутствие ответа, а не «хост отверг» и не «без inline»."""
    d, calls = _config_driver(monkeypatch, {"success": False, "error": "timeout"})

    res = _bounded(lambda: d.config_reload_verified("lines", observability={"log_level": "DEBUG"}, settle=0))

    assert "config.reload" in calls
    assert res["success"] is False, res
    assert res["verdict"] == "unverifiable", res
    assert "timeout" in res["verdict_reason"], res
    assert "отверг" not in res["verdict_reason"], res
    assert "без inline-секции" not in res["verdict_reason"], res


def _router_refusal(command: str) -> dict[str, Any]:
    """Отказ роутера хоста: внешний ``success False``, причина внутри ``result`` без ключа ``success``."""
    return {"success": False, "result": {"status": "error", "reason": f"No handler for key '{command}'"}}


def test_config_reload_router_envelope_refusal_names_host_refusal(monkeypatch) -> None:
    """Реальная форма отказа роутера: после ``_leaf_result`` лист без ``success`` — причина всё равно отказ хоста."""
    d, calls = _config_driver(monkeypatch, _router_refusal("config.reload"))

    res = _bounded(lambda: d.config_reload_verified("lines", observability={"log_level": "DEBUG"}, settle=0))

    assert "config.reload" in calls
    assert res["success"] is False, res
    assert res["verdict"] == "unverifiable", res
    assert "No handler for key 'config.reload'" in res["verdict_reason"], res
    assert "отверг" in res["verdict_reason"], res
    assert "без inline-секции" not in res["verdict_reason"], res


def test_config_reload_bare_status_error_leaf_names_host_refusal(monkeypatch) -> None:
    """Голый лист ``{"status": "error", "reason": ...}`` без ``success``: тоже отказ хоста, причина названа."""
    bare = {"status": "error", "reason": "No handler for key 'config.reload'"}
    d, calls = _config_driver(monkeypatch, bare)

    res = _bounded(lambda: d.config_reload_verified("lines", observability={"log_level": "DEBUG"}, settle=0))

    assert "config.reload" in calls
    assert res["success"] is False, res
    assert res["verdict"] == "unverifiable", res
    assert "No handler for key 'config.reload'" in res["verdict_reason"], res
    assert "без inline-секции" not in res["verdict_reason"], res


def test_config_reload_path_only_refusal_keeps_no_inline_reason(monkeypatch) -> None:
    """Файловый reload (``path=``, inline-секции нет) и отказ хоста: прежняя причина «без inline-секции»."""
    d, calls = _config_driver(monkeypatch, _rejected("config.reload"))

    res = _bounded(lambda: d.config_reload_verified("lines", path="cfg.yaml", settle=0))

    assert "config.reload" in calls
    assert res["success"] is False, res
    assert res["verdict"] == "unverifiable", res
    assert "без inline-секции" in res["verdict_reason"], res
    assert "отверг" not in res["verdict_reason"], res


def _telemetry_readback(enabled: bool) -> dict[str, Any]:
    """Метрика fps есть и в ``resolved``, и в сырой ``publish.metrics`` — иначе сработает
    защита «значение совпало с дефолтом» и тест зелёный по другой причине."""
    return {
        "success": True,
        "process": "camera_0",
        "gate_active": True,
        "publish": {"metrics": {"fps": {}}},
        "resolved": {"fps": {"enabled": enabled, "interval_sec": 1.0}},
        "unknown_metrics": [],
        "gated_metrics": ["fps", "latency_ms", "effective_hz", "cycle_duration_ms", "shm"],
        "throttle_rules": None,
    }


def _telemetry_driver(
    monkeypatch, *, live_enabled: bool, broadcast_reply: dict[str, Any], applies: bool
) -> tuple[BackendDriver, list[tuple[Any, str]]]:
    """``broadcast_reply`` — ответ хоста на telemetry.broadcast; ``applies`` — правило fps в gate
    действительно выключается (ответ при этом может быть любым, в том числе таймаутом)."""
    d = BackendDriver()
    live = {"enabled": live_enabled}
    calls: list[tuple[Any, str]] = []

    def fake_send(process, command, args=None, **kw):
        calls.append((process, command))
        if command == "introspect.telemetry":
            return {"success": True, "result": _telemetry_readback(live["enabled"])}
        if command == "telemetry.broadcast":
            if applies:
                live["enabled"] = False
            return broadcast_reply
        return {"success": True, "result": {"success": True}}

    monkeypatch.setattr(d, "send_command", fake_send)
    return d, calls


def test_telemetry_verify_rejected_write_not_verified(monkeypatch) -> None:
    """Правило fps уже выключено, хост отверг запись: раньше readback «выключено» давал verified_effect True."""
    d, calls = _telemetry_driver(
        monkeypatch, live_enabled=False, broadcast_reply=_rejected("telemetry.broadcast"), applies=False
    )

    res = _bounded(lambda: d.telemetry_set("camera_0", "fps", enabled=False, verify=True, verify_within=0.0))

    assert ("ProcessManager", "telemetry.broadcast") in calls
    assert res["success"] is False, res
    assert res["verified_effect"] is False, res
    assert "No handler for telemetry.broadcast" in res["verification"]["reason"], res
    assert "отверг" in res["verification"]["reason"], res
    assert [c for _p, c in calls if c == "introspect.telemetry"] == [], "поллинг не должен запускаться"


def test_telemetry_verify_timeout_is_not_a_refusal(monkeypatch) -> None:
    """Таймаут — не отказ: запись могла дойти, решает readback (правило применилось -> verified_effect True)."""
    d, calls = _telemetry_driver(
        monkeypatch, live_enabled=True, broadcast_reply={"success": False, "error": "timeout"}, applies=True
    )

    res = _bounded(lambda: d.telemetry_set("camera_0", "fps", enabled=False, verify=True, verify_within=0.0))

    assert ("ProcessManager", "telemetry.broadcast") in calls
    assert [c for _p, c in calls if c == "introspect.telemetry"] != [], "readback должен был выполниться"
    assert res["success"] is False, res
    assert res["verified_effect"] is True, res
