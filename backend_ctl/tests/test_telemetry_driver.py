# -*- coding: utf-8 -*-
"""Тесты driver-обёрток телеметрии (PC 3.2/3.3): telemetry_reconfigure / telemetry_set.

Форма, а не логика: обёртки строят правильные router-сообщения и прокидывают наверх
результат применения. Транспорт мокается (``send_command`` записывает вызовы) — тот же
приём, что TestDebugSession / TestSetRegisterVerified в test_driver.py. Проверяем:

  - адресный кейс → ``telemetry.broadcast`` на PM с ``target=<процесс>`` (Task 1.4:
    транзит через PM ради cap-детекции на per-process пути);
  - fan-out (``process="all"``/``None``/``"*"``) → ``telemetry.broadcast`` на PM без ``target``;
  - ``publish=None`` доезжает как валидная под-секция (сентинел ≠ None);
  - ``telemetry_set`` строит верные args для publisher- и throttle-плоскостей;
  - результат применения (``applied`` / охват) прокидывается наверх (``_leaf_result``).

Плюс провенанс нулей ``telemetry_snapshot``/``telemetry_history`` (BCTL-ADR-007: сигнал
без доказанной способности к ненулю не считается подключённым):

  - ``ingest_active``/``ingested_total`` разводят «нет данных» и «нет подписки»
    (unit — fake-транспорт; live-плечо ненуля — ``TestIngestActiveLive`` ниже);
  - ``tracked`` разводит «путь не трекается» и «данных пока нет» (unit, пара).
"""

from __future__ import annotations

import time
from typing import Any, Dict, List, Tuple

import pytest

from backend_ctl.driver import BackendDriver
from backend_ctl.harness import BackendHarness
from backend_ctl.tests.conftest import wire_line

_PORT = 8789  # уникальный порт этого модуля (свободен на момент написания, см. AGENTS.md)


def _recorder(monkeypatch, response: Dict[str, Any] | None = None) -> Tuple[BackendDriver, List[tuple]]:
    """Driver с замоканным send_command, записывающим (process, command, args)."""
    d = BackendDriver()
    calls: List[tuple] = []

    def fake_send(process, command, args=None, **kw):
        calls.append((process, command, args))
        return response if response is not None else {"success": True}

    monkeypatch.setattr(d, "send_command", fake_send)
    return d, calls


def _delta(path: str, new_value: Any, old_value: Any = None) -> Dict[str, Any]:
    """Дельта в проводной форме Delta.to_dict() (тот же формат, что у fake-конвертов driver'а)."""
    return {
        "path": path,
        "old_value": old_value,
        "new_value": new_value,
        "source": "test",
        "timestamp": 0.0,
        "transaction_id": "t",
        "revision": 0,
    }


def _state_changed(*deltas: Dict[str, Any]) -> bytes:
    return wire_line({"command": "state.changed", "data": {"deltas": list(deltas)}})


def _wait_ingested(drv: BackendDriver, deadline: float) -> Dict[str, Any]:
    """Дождаться, пока read-model реально получит дельты (``ingested_total > 0``).

    Строже, чем ждать ``count > 0``: считает и удаления узлов, не только текущие значения.
    """
    snap = drv.telemetry_snapshot()
    while time.time() < deadline:
        snap = drv.telemetry_snapshot()
        if snap.get("ingested_total", 0) > 0:
            return snap
        time.sleep(0.2)
    return snap


class TestTelemetryReconfigureAddressing:
    def test_addressed_process_routes_via_pm_with_target(self, monkeypatch) -> None:
        """Task 1.4: адресный кейс идёт через PM (target), а НЕ напрямую ребёнку —
        чтобы PM детектил capped_by_throttle своим central-троттлом."""
        d, calls = _recorder(monkeypatch)
        d.telemetry_reconfigure("camera_0", publish={"metrics": {"fps": {"enabled": False}}})
        assert len(calls) == 1
        process, command, args = calls[0]
        assert (process, command) == ("ProcessManager", "telemetry.broadcast")
        assert args == {"publish": {"metrics": {"fps": {"enabled": False}}}, "target": "camera_0"}

    def test_all_process_sends_broadcast_to_pm(self, monkeypatch) -> None:
        d, calls = _recorder(monkeypatch)
        d.telemetry_reconfigure("all", publish={"default_interval_sec": 2.0})
        process, command, args = calls[0]
        assert (process, command) == ("ProcessManager", "telemetry.broadcast")
        assert args == {"publish": {"default_interval_sec": 2.0}}

    def test_none_process_is_fanout(self, monkeypatch) -> None:
        d, calls = _recorder(monkeypatch)
        d.telemetry_reconfigure(None, throttle={"a.b": 1.0})
        assert calls[0][1] == "telemetry.broadcast"
        assert calls[0][0] == "ProcessManager"

    def test_star_process_is_fanout(self, monkeypatch) -> None:
        d, calls = _recorder(monkeypatch)
        d.telemetry_reconfigure("*", publish={})
        assert calls[0][1] == "telemetry.broadcast"

    def test_custom_pm_name(self, monkeypatch) -> None:
        d, calls = _recorder(monkeypatch)
        d.telemetry_reconfigure("all", publish={}, pm_name="Orchestrator")
        assert calls[0][0] == "Orchestrator"


class TestTelemetryReconfigureArgs:
    def test_publish_none_is_sent_as_subsection(self, monkeypatch) -> None:
        """publish=None — валидная команда «выключить gate»: доезжает как ключ (+ target)."""
        d, calls = _recorder(monkeypatch)
        d.telemetry_reconfigure("camera_0", publish=None)
        assert calls[0][2] == {"publish": None, "target": "camera_0"}

    def test_both_planes_in_one_call(self, monkeypatch) -> None:
        d, calls = _recorder(monkeypatch)
        d.telemetry_reconfigure("camera_0", publish={"x": 1}, throttle={"p.q": 2.0})
        assert calls[0][2] == {"publish": {"x": 1}, "throttle": {"p.q": 2.0}, "target": "camera_0"}

    def test_no_subsection_is_error_and_sends_nothing(self, monkeypatch) -> None:
        d, calls = _recorder(monkeypatch)
        res = d.telemetry_reconfigure("camera_0")
        assert res["success"] is False
        assert "publish" in res["error"] or "throttle" in res["error"]
        assert calls == []  # ничего не отправлено

    def test_applied_result_propagated(self, monkeypatch) -> None:
        """Результат применения (handler: applied) прокидывается наверх через _leaf_result."""
        response = {"success": True, "result": {"success": True, "process": "camera_0", "applied": {"publish": True}}}
        d, _calls = _recorder(monkeypatch, response=response)
        res = d.telemetry_reconfigure("camera_0", publish={})
        assert res["applied"] == {"publish": True}

    def test_no_receiver_visible_in_result(self, monkeypatch) -> None:
        """«Нет приёмника» (throttle на процесс без StateStoreManager) виден наверху."""
        response = {"success": True, "result": {"applied": {"throttle": False}}}
        d, _calls = _recorder(monkeypatch, response=response)
        res = d.telemetry_reconfigure("camera_0", throttle={"a": 1.0})
        assert res["applied"] == {"throttle": False}


class TestTelemetryFanoutCoverage:
    def test_fanout_coverage_propagated(self, monkeypatch) -> None:
        """Агрегированный охват fan-out (reached/target_count) виден наверху."""
        response = {
            "success": True,
            "result": {
                "success": True,
                "process": "ProcessManager",
                "publish": {"requested": True, "target_count": 3, "reached": 3, "complete": True},
            },
        }
        d, _calls = _recorder(monkeypatch, response=response)
        res = d.telemetry_reconfigure("all", publish={})
        assert res["publish"]["reached"] == 3
        assert res["publish"]["target_count"] == 3
        assert res["publish"]["complete"] is True

    def test_fanout_incomplete_coverage_visible(self, monkeypatch) -> None:
        """Недоставка части детей (reached < target_count) видна — «no silent caps»."""
        response = {
            "success": True,
            "result": {"publish": {"target_count": 3, "reached": 2, "complete": False}},
        }
        d, _calls = _recorder(monkeypatch, response=response)
        res = d.telemetry_reconfigure("all", publish={})
        assert res["publish"]["complete"] is False
        assert res["publish"]["reached"] < res["publish"]["target_count"]


class TestTelemetryReconfigureMode:
    """Task 1.1: driver прокидывает mode на провод только при merge (replace — бит-в-бит)."""

    def test_replace_default_omits_mode_on_wire(self, monkeypatch) -> None:
        """mode='replace' (дефолт) → telemetry_mode НЕ добавляется (прежний конверт)."""
        d, calls = _recorder(monkeypatch)
        d.telemetry_reconfigure("camera_0", publish={"metrics": {"fps": {"enabled": False}}})
        assert "telemetry_mode" not in calls[0][2]

    def test_merge_adds_mode_on_wire(self, monkeypatch) -> None:
        d, calls = _recorder(monkeypatch)
        d.telemetry_reconfigure("camera_0", publish={"x": 1}, mode="merge")
        assert calls[0][2]["telemetry_mode"] == "merge"
        assert calls[0][2]["publish"] == {"x": 1}


class TestTelemetrySet:
    def test_publisher_enabled_builds_metric_override(self, monkeypatch) -> None:
        d, calls = _recorder(monkeypatch)
        d.telemetry_set("camera_0", "fps", enabled=False)
        process, command, args = calls[0]
        # Task 1.4: адресный кейс → PM с target (транзит ради cap-детекции).
        assert (process, command) == ("ProcessManager", "telemetry.broadcast")
        # Task 1.1: telemetry_set обещает точечность → merge (сохраняет соседей).
        assert args == {
            "publish": {"metrics": {"fps": {"enabled": False}}},
            "telemetry_mode": "merge",
            "target": "camera_0",
        }

    def test_publisher_interval_only(self, monkeypatch) -> None:
        d, calls = _recorder(monkeypatch)
        d.telemetry_set("camera_0", "latency_ms", interval_sec=5.0)
        assert calls[0][2] == {
            "publish": {"metrics": {"latency_ms": {"interval_sec": 5.0}}},
            "telemetry_mode": "merge",
            "target": "camera_0",
        }

    def test_publisher_enabled_and_interval(self, monkeypatch) -> None:
        d, calls = _recorder(monkeypatch)
        d.telemetry_set("camera_0", "shm", enabled=True, interval_sec=10.0)
        assert calls[0][2] == {
            "publish": {"metrics": {"shm": {"enabled": True, "interval_sec": 10.0}}},
            "telemetry_mode": "merge",
            "target": "camera_0",
        }

    def test_publisher_requires_a_field(self, monkeypatch) -> None:
        d, calls = _recorder(monkeypatch)
        res = d.telemetry_set("camera_0", "fps")
        assert res["success"] is False
        assert calls == []

    def test_throttle_plane_builds_rule(self, monkeypatch) -> None:
        d, calls = _recorder(monkeypatch)
        d.telemetry_set("all", "processes.**.state.fps", interval_sec=1.0, plane="throttle")
        process, command, args = calls[0]
        assert (process, command) == ("ProcessManager", "telemetry.broadcast")
        # Task 1.1: throttle-плоскость тоже merge (update_rule, не set_rules).
        assert args == {"throttle": {"processes.**.state.fps": 1.0}, "telemetry_mode": "merge"}

    def test_throttle_plane_requires_interval(self, monkeypatch) -> None:
        d, calls = _recorder(monkeypatch)
        res = d.telemetry_set("camera_0", "a.b", enabled=True, plane="throttle")
        assert res["success"] is False
        assert "interval_sec" in res["error"]
        assert calls == []

    def test_unknown_plane_is_error(self, monkeypatch) -> None:
        d, calls = _recorder(monkeypatch)
        res = d.telemetry_set("camera_0", "fps", enabled=True, plane="bogus")
        assert res["success"] is False
        assert calls == []

    def test_set_all_is_fanout(self, monkeypatch) -> None:
        d, calls = _recorder(monkeypatch)
        d.telemetry_set("all", "fps", enabled=False)
        assert calls[0][0] == "ProcessManager"
        assert calls[0][1] == "telemetry.broadcast"


def _verify_recorder(monkeypatch, *, readback: Dict[str, Any]) -> Tuple[BackendDriver, List[tuple]]:
    """Driver, у которого запись отвечает охватом, а ``introspect.telemetry`` — заданным readback'ом.

    Разные ответы по команде — иначе verify «проверял» бы эхо собственной записи.
    """
    d = BackendDriver()
    calls: List[tuple] = []

    def fake_send(process, command, args=None, **kw):
        calls.append((process, command, args))
        if command == "introspect.telemetry":
            return {"success": True, "result": readback}
        return {
            "success": True,
            "result": {
                "success": True,
                "process": "ProcessManager",
                "publish": {
                    "requested": True,
                    "target_count": 1,
                    "reached": 1,
                    "targets": [process],
                    "complete": True,
                    "semantics": "delivered",
                },
            },
        }

    monkeypatch.setattr(d, "send_command", fake_send)
    return d, calls


def _readback(
    metrics: Dict[str, Any],
    *,
    unknown: List[str] | None = None,
    raw_metrics: Dict[str, Any] | None = None,
    **extra: Any,
) -> Dict[str, Any]:
    """Ответ ``introspect.telemetry`` с заданным ``resolved`` (форма Task 4.1).

    ``raw_metrics`` — сырая секция ``publish.metrics``. По умолчанию зеркалит ключи
    ``resolved``: правило метрики РЕАЛЬНО присутствует в живом gate. Расхождение
    (``raw_metrics={}``) моделирует «значение совпало с дефолтом, но правила нет» —
    случай вакуумного True из ревью Ф4.
    """
    return {
        "success": True,
        "process": "camera_0",
        "gate_active": True,
        "publish": {"metrics": raw_metrics if raw_metrics is not None else {k: {} for k in metrics}},
        "resolved": metrics,
        "unknown_metrics": unknown or [],
        "gated_metrics": ["fps", "latency_ms", "effective_hz", "cycle_duration_ms", "shm"],
        "throttle_rules": None,
        **extra,
    }


class TestTelemetrySetVerify:
    """Ф4 Task 4.2: доставка ≠ применение — ``verify=True`` даёт вердикт по READBACK'у.

    Пары: применилось → ``verified_effect=True``; опечатка/не применилось → ``False``
    с названной причиной. Серверный ``reached`` во всех этих случаях = 1 (доставка
    состоялась) — именно поэтому одного его мало.
    """

    def test_applied_rule_verifies_true(self, monkeypatch) -> None:
        d, calls = _verify_recorder(monkeypatch, readback=_readback({"fps": {"enabled": False, "interval_sec": 1.0}}))
        res = d.telemetry_set("camera_0", "fps", enabled=False, verify=True)
        assert res["verified_effect"] is True
        assert res["verification"]["observed"]["enabled"] is False
        # readback реально сходил на процесс-адресат отдельной командой
        assert ("camera_0", "introspect.telemetry", None) in calls

    def test_typo_metric_verifies_false_with_reason(self, monkeypatch) -> None:
        """Опечатка: правило записано, но метрики нет в GATED_METRICS → ничего не гейтит."""
        d, _calls = _verify_recorder(
            monkeypatch,
            readback=_readback({"fps": {"enabled": True, "interval_sec": 1.0}}, unknown=["latency"]),
        )
        res = d.telemetry_set("camera_0", "latency", enabled=False, verify=True, verify_within=0.0)
        assert res["success"] is True  # консервативно: не блокируем
        assert res["verified_effect"] is False
        assert "GATED_METRICS" in res["verification"]["reason"]

    def test_value_mismatch_verifies_false(self, monkeypatch) -> None:
        """Правило есть, но значение чужое (перезаписал кто-то другой) → честный False."""
        d, _calls = _verify_recorder(monkeypatch, readback=_readback({"fps": {"enabled": True, "interval_sec": 1.0}}))
        res = d.telemetry_set("camera_0", "fps", enabled=False, verify=True, verify_within=0.0)
        assert res["verified_effect"] is False
        assert res["verification"]["observed"]["enabled"] is True

    def test_interval_only_delta_ignores_enabled(self, monkeypatch) -> None:
        """Дельта несла только interval_sec → enabled в readback не сверяется (иначе ложный False)."""
        d, _calls = _verify_recorder(
            monkeypatch, readback=_readback({"latency_ms": {"enabled": True, "interval_sec": 5.0}})
        )
        res = d.telemetry_set("camera_0", "latency_ms", interval_sec=5.0, verify=True)
        assert res["verified_effect"] is True

    def test_gate_off_verifies_false_with_reason(self, monkeypatch) -> None:
        """Gate выключен → правило негде наблюдать; «не проверено» не выдаётся за «применено»."""
        d, _calls = _verify_recorder(
            monkeypatch,
            readback={
                "success": True,
                "process": "camera_0",
                "gate_active": False,
                "publish": None,
                "resolved": None,
                "unknown_metrics": [],
                "gated_metrics": [],
                "throttle_rules": None,
            },
        )
        res = d.telemetry_set("camera_0", "fps", enabled=False, verify=True, verify_within=0.0)
        assert res["verified_effect"] is False
        assert "gate выключен" in res["verification"]["reason"]

    def test_default_match_without_rule_is_not_verified(self, monkeypatch) -> None:
        """Значение совпало с ДЕФОЛТОМ, но правила метрики в gate нет → не «да».

        Ревью Ф4 (находка 4): ``resolved`` разворачивает наследование, поэтому запрос
        ``enabled=True`` совпал бы с дефолтом даже при полностью потерянной дельте —
        вакуумное подтверждение. Теперь требуется наличие ключа в сырой секции.
        """
        d, _calls = _verify_recorder(
            monkeypatch,
            readback=_readback({"fps": {"enabled": True, "interval_sec": 1.0}}, raw_metrics={}),
        )
        res = d.telemetry_set("camera_0", "fps", enabled=True, verify=True, verify_within=0.0)
        assert res["verified_effect"] is False
        assert "дефолт" in res["verification"]["reason"].lower()

    def test_rule_present_in_raw_section_verifies(self, monkeypatch) -> None:
        """Плечо пары: то же значение, но правило РЕАЛЬНО есть в секции → verified_effect=True."""
        d, _calls = _verify_recorder(
            monkeypatch,
            readback=_readback(
                {"fps": {"enabled": True, "interval_sec": 1.0}},
                raw_metrics={"fps": {"enabled": True}},
            ),
        )
        res = d.telemetry_set("camera_0", "fps", enabled=True, verify=True, verify_within=0.0)
        assert res["verified_effect"] is True

    def test_fanout_cannot_verify_and_says_so(self, monkeypatch) -> None:
        """process='all' — одного адресата для readback'а нет; причина названа, эффект не выдуман."""
        d, _calls = _verify_recorder(monkeypatch, readback=_readback({}))
        res = d.telemetry_set("all", "fps", enabled=False, verify=True)
        assert res["verified_effect"] is False
        assert "fan-out" in res["verification"]["reason"]

    def test_without_verify_no_fields_and_no_readback(self, monkeypatch) -> None:
        """Плечо OFF пары: без verify ответ бит-в-бит прежний, лишнего IPC нет."""
        d, calls = _verify_recorder(monkeypatch, readback=_readback({"fps": {"enabled": False, "interval_sec": 1.0}}))
        res = d.telemetry_set("camera_0", "fps", enabled=False)
        assert "verified_effect" not in res and "verification" not in res
        assert [c[1] for c in calls] == ["telemetry.broadcast"]

    def test_throttle_plane_verifies_against_central_rules(self, monkeypatch) -> None:
        """Throttle-плоскость сверяется с правилами оркестратора (readback ProcessManager)."""
        d, calls = _verify_recorder(
            monkeypatch,
            readback=_readback({}, throttle_rules={"processes.**.state.fps": 2.0}),
        )
        res = d.telemetry_set("all", "processes.**.state.fps", interval_sec=2.0, plane="throttle", verify=True)
        assert res["verified_effect"] is True
        assert ("ProcessManager", "introspect.telemetry", None) in calls


class TestTelemetrySetUnreachedHint:
    """BCTL-ADR-007: ``publish.reached=0``/``target_count=0`` → клиентская подсказка, не отказ.

    Консервативно (как и unknown_metric у ``await_condition``): только маркировка —
    ``success`` и остальная форма ответа не трогаются, пара ON/OFF на ``reached``.
    """

    def test_addressed_zero_reached_gets_hint(self, monkeypatch) -> None:
        """Адресный кейс (``target_count`` всегда 1): ``reached=0`` — процесс не доставлен,
        вероятная опечатка в имени. Ответ не блокируется (``success`` остаётся True)."""
        response = {
            "success": True,
            "result": {
                "success": True,
                "process": "ProcessManager",
                "publish": {
                    "requested": True,
                    "target_count": 1,
                    "reached": 0,
                    "targets": ["camera_x"],
                    "complete": False,
                },
            },
        }
        d, _calls = _recorder(monkeypatch, response=response)
        res = d.telemetry_set("camera_x", "fps", enabled=True)
        assert res["success"] is True  # консервативно: не блокируем
        assert "проверь имя" in res["hint"]
        assert "camera_x" in res["hint"] and "fps" in res["hint"]

    def test_fanout_zero_target_count_gets_hint(self, monkeypatch) -> None:
        """Fan-out без единого живого ребёнка (``target_count=0``) — та же подсказка."""
        response = {
            "success": True,
            "result": {
                "success": True,
                "process": "ProcessManager",
                "publish": {"requested": True, "target_count": 0, "reached": 0, "targets": [], "complete": True},
            },
        }
        d, _calls = _recorder(monkeypatch, response=response)
        res = d.telemetry_set("all", "fps", enabled=True)
        assert "hint" in res

    def test_reached_nonzero_no_hint(self, monkeypatch) -> None:
        """Плечо OFF пары: доставка состоялась (``reached=1/1``) — ``hint`` НЕ добавляется,
        ответ бит-в-бит (см. TestTelemetryFanoutCoverage.test_fanout_coverage_propagated)."""
        response = {
            "success": True,
            "result": {
                "success": True,
                "process": "ProcessManager",
                "publish": {
                    "requested": True,
                    "target_count": 1,
                    "reached": 1,
                    "targets": ["camera_x"],
                    "complete": True,
                },
            },
        }
        d, _calls = _recorder(monkeypatch, response=response)
        res = d.telemetry_set("camera_x", "fps", enabled=True)
        assert "hint" not in res
        assert res["publish"]["reached"] == 1

    def test_throttle_plane_response_has_no_hint(self, monkeypatch) -> None:
        """Throttle-плоскость не несёт ``publish`` (только ``throttle.applied``) — функция
        не падает и ничего не маркирует (нет реестра метрик, чтобы судить throttle-правило)."""
        response = {
            "success": True,
            "result": {"success": True, "process": "ProcessManager", "throttle": {"requested": True, "applied": False}},
        }
        d, _calls = _recorder(monkeypatch, response=response)
        res = d.telemetry_set("camera_x", "a.b", interval_sec=1.0, plane="throttle")
        assert "hint" not in res


class TestTelemetryIngestActiveUnit:
    """``ingest_active``/``ingested_total`` на fake-транспорте — плечо OFF и механика счётчика.

    Плечо ON (доказанный ненуль под живой подпиской) — только live, см.
    ``TestIngestActiveLive`` ниже (BCTL-ADR-007: сигнал без live-доказательства ненуля
    не считается подключённым).
    """

    def test_no_subscription_is_inactive_and_zero(self) -> None:
        d = BackendDriver()
        snap = d.telemetry_snapshot()
        assert snap["count"] == 0
        assert snap["ingest_active"] is False
        assert snap["ingested_total"] == 0

    def test_state_subscribe_intent_marks_active(self, monkeypatch) -> None:
        """Durable-намерение регистрируется реестром сразу при успешном ответе — без
        реального сервера (``send_command`` замокан). ``ingest_active`` читает РЕЕСТР
        намерений, а не факт прихода дельт — за дельты отвечает ``ingested_total``."""
        d, _calls = _recorder(monkeypatch, response={"success": True, "result": {"status": "subscribed"}})
        d.state_subscribe("processes.**")
        assert d.telemetry_snapshot()["ingest_active"] is True

    def test_state_unsubscribe_clears_active(self, monkeypatch) -> None:
        d, _calls = _recorder(monkeypatch, response={"success": True, "result": {"status": "subscribed"}})
        d.state_subscribe("processes.**")
        d.state_unsubscribe("processes.**")
        assert d.telemetry_snapshot()["ingest_active"] is False

    def test_ingested_total_counts_deltas_including_deletions(self) -> None:
        """Счётчик — «сколько дельт прошло через ingest», а не «сколько путей живо
        сейчас»: удаление узла тоже проходит через ingest и должно быть учтено."""
        d = BackendDriver()
        d.dispatch_raw(_state_changed(_delta("processes.cam.state.fps", 1.0)))
        d.dispatch_raw(_state_changed(_delta("processes.cam.state.fps", 2.0)))
        d.dispatch_raw(_state_changed(_delta("processes.cam.state.fps", "__MISSING__", old_value=2.0)))
        snap = d.telemetry_snapshot()
        assert snap["ingested_total"] == 3
        assert snap["count"] == 0  # путь удалён — снимок пуст, но дельты были


class TestTelemetryIngestPatterns:
    """``ingest_patterns`` (довесок к Task 1.2/BCTL-ADR-007) — провенанс ПОКРЫТИЯ ingest:
    список паттернов активных ``state.subscribe``-намерений. ``ingest_active`` сам по
    себе значит только «подписка объявлена», а не «покрывает источник телеметрии»
    (``processes.**``) — этот пробел и закрывает список: агент сверяет паттерн сам,
    второй glob-матчер рядом со state_store не строится."""

    def test_no_subscription_is_empty(self) -> None:
        d = BackendDriver()
        assert d.telemetry_snapshot()["ingest_patterns"] == []
        assert d.telemetry_history("processes.cam.state.fps")["ingest_patterns"] == []

    def test_subscribed_pattern_is_listed_in_snapshot(self, monkeypatch) -> None:
        d, _calls = _recorder(monkeypatch, response={"success": True, "result": {"status": "subscribed"}})
        d.state_subscribe("calibration.**")
        assert d.telemetry_snapshot()["ingest_patterns"] == ["calibration.**"]

    def test_subscribed_pattern_is_listed_in_history(self, monkeypatch) -> None:
        d, _calls = _recorder(monkeypatch, response={"success": True, "result": {"status": "subscribed"}})
        d.state_subscribe("calibration.**")
        hist = d.telemetry_history("processes.cam.state.fps")
        assert hist["ingest_patterns"] == ["calibration.**"]

    def test_unsubscribe_clears_pattern(self, monkeypatch) -> None:
        d, _calls = _recorder(monkeypatch, response={"success": True, "result": {"status": "subscribed"}})
        d.state_subscribe("calibration.**")
        d.state_unsubscribe("calibration.**")
        assert d.telemetry_snapshot()["ingest_patterns"] == []


class TestTelemetryHistoryTracked:
    """``tracked`` разводит «путь вне DEFAULT_TRACKED_SUFFIXES» и «данных пока нет» (пара)."""

    def test_untracked_path_is_not_tracked(self) -> None:
        d = BackendDriver()
        hist = d.telemetry_history("совершенно.не.трекаемый.путь")
        assert hist["tracked"] is False
        assert hist["count"] == 0

    def test_tracked_suffix_reports_tracked_true_even_when_empty(self) -> None:
        """Путь трекается (суффикс ``.state.fps``), но точек ещё не было — count=0
        не значит то же самое, что untracked: ``tracked`` их различает."""
        d = BackendDriver()
        hist = d.telemetry_history("processes.cam.state.fps")
        assert hist["tracked"] is True
        assert hist["count"] == 0

    def test_tracked_path_with_points_still_tracked(self) -> None:
        d = BackendDriver()
        d.dispatch_raw(_state_changed(_delta("processes.cam.state.fps", 25.0)))
        hist = d.telemetry_history("processes.cam.state.fps")
        assert hist["tracked"] is True
        assert hist["count"] == 1

    def test_untracked_metric_path_status(self) -> None:
        """``status`` не входит в DEFAULT_TRACKED_SUFFIXES — регресс существующего
        поведения (test_driver.py::test_history_untracked_metric_empty), теперь с явным
        провенансом ``tracked=False`` вместо голого count=0."""
        d = BackendDriver()
        d.dispatch_raw(_state_changed(_delta("processes.cam.state.status", "running")))
        hist = d.telemetry_history("processes.cam.state.status")
        assert hist["tracked"] is False
        assert hist["count"] == 0


@pytest.mark.harness_smoke
def test_ingest_active_and_ingested_total_live() -> None:
    """Live-плечо ON пары BCTL-ADR-007: без подписки ingest_active=false — это самая
    дешёвая, детерминированная половина (свежий driver не может иметь намерений),
    поэтому проверяется на том же харнессе, что и доказанный ненуль. После
    watch_like_gui на реальном бэкенде — ingest_active=true И ingested_total>0
    (read-model физически получил дельты, а не просто «подписка объявлена»).
    """
    harness = BackendHarness(with_base=True, port=_PORT)
    try:
        drv = harness.start()

        off = drv.telemetry_snapshot()
        assert off["count"] == 0
        assert off["ingest_active"] is False
        assert off["ingested_total"] == 0

        res = drv.watch_like_gui()
        assert res.get("success") is True

        on = _wait_ingested(drv, time.time() + 15.0)
        assert on["ingest_active"] is True
        assert on["ingested_total"] > 0, "read-model должен реально получить дельты под watch_like_gui"
    finally:
        harness.stop()


_PORT_UNKNOWN_METRIC = 8790  # уникальный порт этого модуля (свободен на момент написания, см. AGENTS.md)


@pytest.mark.harness_smoke
def test_unknown_metric_live() -> None:
    """Фикс 3 (довесок к Task 1.4/BCTL-ADR-007): ``unknown_metric`` доказан на живом
    бэкенде, не только на бессокетном driver'е (``TestMetricThresholdUnknownMetric`` в
    ``test_await_condition.py`` — сплошь fake dispatch_raw, ни одного ``harness_smoke``).

    Плечо ненуля достигается штатным API: ``watch_like_gui`` наполняет read-model
    реальными дельтами живой системы, из них берётся ЛЮБОЙ реально наблюдённый
    трекаемый путь (не захардкожен конкретный процесс/метрику — топология рецепта
    может меняться) и опечатывается на одну букву — по тому же принципу, что unit-тест
    ``test_typo_path_pair_flags_unknown_with_candidates``.
    """
    harness = BackendHarness(with_base=True, port=_PORT_UNKNOWN_METRIC)
    try:
        drv = harness.start()
        assert drv.watch_like_gui().get("success") is True

        snap = _wait_ingested(drv, time.time() + 15.0)
        assert snap["ingested_total"] > 0

        tracked_paths = [p for p in snap["metrics"] if drv._telemetry_is_tracked(p)]
        assert tracked_paths, "живая система не опубликовала ни одной трекаемой метрики — нечем опечататься"
        real_path = sorted(tracked_paths)[0]
        typo_path = real_path + "s"  # опечатка: не совпадает ни с одним DEFAULT_TRACKED_SUFFIXES

        res = drv.await_condition("metric_threshold", {"path": typo_path, "op": ">", "value": 10**9}, timeout=2.0)

        assert res["success"] is False and res["timed_out"] is True
        assert res["unknown_metric"] is True
        assert real_path in res["candidates"], f"{real_path!r} не попал в кандидаты: {res['candidates']}"
    finally:
        harness.stop()


_PORT_UNREACHED_HINT = 8791  # уникальный порт этого модуля (свободен на момент написания, см. AGENTS.md)


@pytest.mark.harness_smoke
def test_telemetry_set_addressed_delivery_is_fire_and_forget_live() -> None:
    """Фикс 4 (довесок к Task 1.4/BCTL-ADR-007) — ГРАНИЦА ДОКАЗУЕМОСТИ, замерена живьём.

    Замер 2026-07-22 опроверг и посылку ревью (Fable: «опечатка в метрике → reached=0»),
    и первую ревизию («несуществующий процесс → reached=0»): ``reached=0`` у publish
    НЕдостижим детерминированно через публичный API. Адресная доставка — fire-and-forget
    (``_send_child_command`` → ``comm.send_to_process``, ``process_manager_process.py:
    1331-1354``): возвращает факт ПОСТАНОВКИ билета в очередь, а не существование
    адресата. Поэтому ``telemetry_set`` даже НЕсуществующему процессу даёт ``reached=1``
    (билет ушёл в PSR), а не 0. Единственный False-путь — ``comm is None``
    (минимальный/тестовый PM), на живом харнессе недостижим.

    Следствие для BCTL-ADR-007: reached=0-ветка клиентского ``hint``
    (``_flag_unreached_metric``) доказуема только unit'ом (``TestTelemetrySetUnreachedHint``),
    её live-ненуль — нет; честный уровень сигнала — unit. Этот тест доказывает ЗАМЕРОМ
    саму границу — и заодно почему клиентский hint вообще нужен: сервер не различает
    «плохое имя» и «хорошее имя», оба дают reached=1.
    """
    harness = BackendHarness(with_base=True, port=_PORT_UNREACHED_HINT)
    try:
        drv = harness.start()

        res = drv.telemetry_set("нет_такого_процесса_xyz", "fps", enabled=True)

        assert res["success"] is True, "консервативно: подсказка не блокирует ответ"
        # Fire-and-forget: билет ушёл в очередь, адресат не проверяется → reached=1, не 0.
        assert res["publish"]["reached"] == 1
        # reached≠0 → клиентский hint НЕ навешивается (навесился бы только на живой reached=0,
        # который через публичный API не воспроизвести — см. докстринг).
        assert "hint" not in res
    finally:
        harness.stop()
