# -*- coding: utf-8 -*-
"""Тесты readback'а телеметрийного gate — ``introspect.telemetry`` (Ф4 Task 4.1).

План: `plans/truth-holes-closure.md`. Закрываемая дыра — «gate виден только по
эффекту»: до этой команды узнать, публикуется ли метрика, можно было лишь наблюдая
её появление/пропажу в дереве. Проверяем ПАРАМИ (выключил → readback показывает
выключено; включил → включено), а не одиночным снимком: одиночный снимок не
отличает «readback работает» от «команда всегда отдаёт дефолты».
"""

from __future__ import annotations

from multiprocess_framework.modules.process_module.commands.builtin_commands import BuiltinCommands
from multiprocess_framework.modules.process_module.configs.telemetry_publish_config import (
    GATED_METRICS,
)
from multiprocess_framework.modules.process_module.heartbeat.process_heartbeat import (
    ProcessHeartbeat,
)
from multiprocess_framework.modules.state_store_module.middleware.throttle import (
    ThrottleMiddleware,
)


class _FakeCommandManager:
    def __init__(self) -> None:
        self.handlers: dict = {}
        self.metadata: dict = {}

    def register_command(self, name, handler, metadata=None, tags=None) -> None:
        self.handlers[name] = handler
        self.metadata[name] = metadata or {}

    def dispatch(self, command: str, data: dict | None = None) -> dict:
        return self.handlers[command](data or {})


class _FakeStoreManager:
    def __init__(self, throttle: ThrottleMiddleware) -> None:
        self._throttle = throttle

    def get_middleware(self, name: str):
        return self._throttle if name == "throttle" else None


class _HeartbeatServices:
    def __init__(self) -> None:
        self.name = "camera_0"
        self.worker_manager = None
        self._state_proxy = None
        self.router_manager = None
        self._config: dict = {}

    def get_config(self, key, default=None):
        return self._config.get(key, default)

    def log_info(self, *a, **k) -> None: ...
    def log_debug(self, *a, **k) -> None: ...


class _FakeServices:
    """Процесс-адресат: реальный ProcessHeartbeat + опционально живой троттл."""

    def __init__(self, *, throttle=None, heartbeat: bool = True) -> None:
        self.command_manager = _FakeCommandManager()
        self.name = "camera_0"
        self.logger_manager = None
        self.error_manager = None
        self.stats_manager = None
        self.router_manager = None
        self._config: dict = {}
        self._heartbeat = ProcessHeartbeat(_HeartbeatServices()) if heartbeat else None
        self._state_store_manager = _FakeStoreManager(throttle) if throttle is not None else None

    def get_config(self, key, default=None):
        return self._config.get(key, default)

    def _log_info(self, *a, **k) -> None: ...
    def _log_debug(self, *a, **k) -> None: ...


def _make(**kw):
    """Процесс с зарегистрированными introspect.* и observability.* командами.

    Обе группы нужны в одном CommandManager: приёмка — ПАРА «записал через
    telemetry.reconfigure → прочитал через introspect.telemetry».
    """
    svc = _FakeServices(**kw)
    bc = BuiltinCommands(svc)
    bc._register_introspect_commands()
    bc._register_observability_commands()
    return svc, svc.command_manager


class TestGateOff:
    """Gate не построен → честное «нечего резолвить», а не пустота без причины."""

    def test_reports_gate_inactive_with_reason(self) -> None:
        _svc, cm = _make()
        res = cm.dispatch("introspect.telemetry")
        assert res["success"] is True
        assert res["process"] == "camera_0"
        assert res["gate_active"] is False
        assert res["publish"] is None
        assert res["resolved"] is None
        assert "note" in res  # причина названа, а не «нет данных»

    def test_gated_metrics_catalog_always_present(self) -> None:
        """Каталог известных метрик отдаётся и при выключенном gate (справочник от опечаток)."""
        _svc, cm = _make()
        res = cm.dispatch("introspect.telemetry")
        assert res["gated_metrics"] == list(GATED_METRICS)

    def test_process_without_heartbeat(self) -> None:
        """Нет ProcessHeartbeat → success=True + note, а не падение команды."""
        _svc, cm = _make(heartbeat=False)
        res = cm.dispatch("introspect.telemetry")
        assert res["success"] is True
        assert res["gate_active"] is False
        assert "ProcessHeartbeat" in res["note"]


class TestReadbackPair:
    """Acceptance Task 4.1: выключил метрику → readback это ВИДИТ; включил → видит обратное."""

    def test_disable_then_enable_fps_visible_in_readback(self) -> None:
        _svc, cm = _make()

        cm.dispatch("telemetry.reconfigure", {"publish": {"metrics": {"fps": {"enabled": False}}}})
        off = cm.dispatch("introspect.telemetry")
        assert off["gate_active"] is True
        assert off["resolved"]["fps"]["enabled"] is False

        cm.dispatch(
            "telemetry.reconfigure",
            {"publish": {"metrics": {"fps": {"enabled": True}}}, "telemetry_mode": "merge"},
        )
        on = cm.dispatch("introspect.telemetry")
        assert on["resolved"]["fps"]["enabled"] is True

    def test_interval_inheritance_is_resolved_not_raw(self) -> None:
        """resolved разворачивает наследование default_interval_sec (итог, а не правила)."""
        _svc, cm = _make()
        cm.dispatch(
            "telemetry.reconfigure",
            {
                "publish": {
                    "default_interval_sec": 2.0,
                    "metrics": {"fps": {"interval_sec": 0.25}},
                }
            },
        )
        res = cm.dispatch("introspect.telemetry")
        assert res["resolved"]["fps"]["interval_sec"] == 0.25  # явный override
        assert res["resolved"]["shm"]["interval_sec"] == 2.0  # унаследован от default
        assert set(res["resolved"]) == set(GATED_METRICS)  # все метрики каталога

    def test_publish_section_is_effective_not_last_command(self) -> None:
        """publish = ЭФФЕКТИВНАЯ секция живого gate: merge-правка видна поверх прежней."""
        _svc, cm = _make()
        cm.dispatch(
            "telemetry.reconfigure",
            {"publish": {"metrics": {"latency_ms": {"enabled": False}}}},
        )
        cm.dispatch(
            "telemetry.reconfigure",
            {"publish": {"metrics": {"fps": {"enabled": False}}}, "telemetry_mode": "merge"},
        )
        res = cm.dispatch("introspect.telemetry")
        assert res["publish"]["metrics"]["latency_ms"]["enabled"] is False
        assert res["publish"]["metrics"]["fps"]["enabled"] is False

    def test_gate_turned_off_again_returns_to_inactive(self) -> None:
        """publish=None выключает gate → readback снова gate_active=False (пара в обе стороны)."""
        _svc, cm = _make()
        cm.dispatch("telemetry.reconfigure", {"publish": {}})
        assert cm.dispatch("introspect.telemetry")["gate_active"] is True
        cm.dispatch("telemetry.reconfigure", {"publish": None})
        assert cm.dispatch("introspect.telemetry")["gate_active"] is False


class TestUnknownMetricsReadback:
    """Опечатка в имени метрики видна в readback, а не только в ответе команды записи."""

    def test_typo_surfaces_after_the_fact(self) -> None:
        _svc, cm = _make()
        cm.dispatch("telemetry.reconfigure", {"publish": {"metrics": {"latency": {"interval_sec": 0.5}}}})
        res = cm.dispatch("introspect.telemetry")
        assert res["unknown_metrics"] == ["latency"]

    def test_known_metrics_give_empty_list(self) -> None:
        _svc, cm = _make()
        cm.dispatch("telemetry.reconfigure", {"publish": {"metrics": {"fps": {"enabled": False}}}})
        assert cm.dispatch("introspect.telemetry")["unknown_metrics"] == []


class TestThrottlePlaneReadback:
    """Вторая плоскость (central-троттл, ADR-PM-017) тоже перестаёт быть невидимой."""

    def test_rules_visible_when_process_holds_throttle(self) -> None:
        throttle = ThrottleMiddleware({"processes.**.state.fps": 2.0})
        _svc, cm = _make(throttle=throttle)
        res = cm.dispatch("introspect.telemetry")
        assert res["throttle_rules"] == {"processes.**.state.fps": 2.0}

    def test_rules_snapshot_follows_reconfigure(self) -> None:
        throttle = ThrottleMiddleware({})
        _svc, cm = _make(throttle=throttle)
        cm.dispatch("telemetry.reconfigure", {"throttle": {"processes.**.state.fps": 5.0}})
        assert cm.dispatch("introspect.telemetry")["throttle_rules"] == {"processes.**.state.fps": 5.0}

    def test_none_for_process_without_store_manager(self) -> None:
        """Обычный процесс не держит StateStoreManager → null, а не пустой dict (нет плоскости ≠ нет правил)."""
        _svc, cm = _make(throttle=None)
        assert cm.dispatch("introspect.telemetry")["throttle_rules"] is None


class TestReadOnly:
    """Команда — чтение: повторный вызов не меняет живое состояние gate."""

    def test_readback_does_not_touch_gate(self) -> None:
        svc, cm = _make()
        cm.dispatch("telemetry.reconfigure", {"publish": {"metrics": {"fps": {"enabled": False}}}})
        gate_before = svc._heartbeat._telemetry_gate
        first = cm.dispatch("introspect.telemetry")
        second = cm.dispatch("introspect.telemetry")
        assert svc._heartbeat._telemetry_gate is gate_before  # тот же объект — ничего не пересобрано
        assert first["publish"] == second["publish"]

    def test_registered_with_description(self) -> None:
        """Команда объявлена в каталоге (capabilities/introspect.handlers её видят)."""
        _svc, cm = _make()
        assert "introspect.telemetry" in cm.handlers
        assert cm.metadata["introspect.telemetry"]["description"]
