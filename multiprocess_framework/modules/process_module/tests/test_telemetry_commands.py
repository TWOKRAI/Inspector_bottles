# -*- coding: utf-8 -*-
"""Тесты IPC-команд рантайм-переконфигурации телеметрии (PC 3.1).

Проверяем:
  - ``telemetry.reconfigure`` c ``publish`` → publisher-gate процесса перестроен
    (реальный ProcessHeartbeat в контексте svc);
  - ``telemetry.reconfigure`` c ``throttle`` → ``ThrottleMiddleware.rules`` изменились
    через ``StateStoreManager.get_middleware("throttle")``;
  - ``config.reload`` c ``data["telemetry"]`` применяет telemetry, НЕ ломая
    observability-путь (обе секции в одном сообщении — обе применились);
  - backward-compat: нет telemetry в reload → ничего telemetry не активируется.
"""

from __future__ import annotations

from multiprocess_framework.modules.process_module.commands.builtin_commands import BuiltinCommands
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
    """Минимальный StateStoreManager: держит живой ThrottleMiddleware по имени."""

    def __init__(self, throttle: ThrottleMiddleware) -> None:
        self._throttle = throttle

    def get_middleware(self, name: str):
        return self._throttle if name == "throttle" else None


class _HeartbeatServices:
    """Контекст для ProcessHeartbeat (нужен только name + get_config + логгеры)."""

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


class _FakeLogger:
    def __init__(self) -> None:
        self.reconfigured: list = []

    def reconfigure(self, config: dict) -> bool:
        self.reconfigured.append(config)
        return True


class _FakeServices:
    """Процесс-адресат: heartbeat + StateStoreManager + observability-менеджеры."""

    def __init__(self, *, throttle=None, logger=None) -> None:
        self.command_manager = _FakeCommandManager()
        self.name = "camera_0"
        self.logger_manager = logger
        self.error_manager = None
        self.stats_manager = None
        self.router_manager = None
        self._config: dict = {}
        # Реальный ProcessHeartbeat — handler достаёт его через getattr(svc, "_heartbeat").
        self._heartbeat = ProcessHeartbeat(_HeartbeatServices())
        # StateStoreManager с живым троттлом (только у оркестратора; здесь эмулируем).
        self._state_store_manager = _FakeStoreManager(throttle) if throttle is not None else None

    def get_config(self, key, default=None):
        return self._config.get(key, default)

    def _log_info(self, *a, **k) -> None: ...
    def _log_debug(self, *a, **k) -> None: ...


def _make(**kw):
    svc = _FakeServices(**kw)
    bc = BuiltinCommands(svc)
    bc._register_observability_commands()
    return svc, svc.command_manager


class TestTelemetryReconfigureCommand:
    def test_publish_rebuilds_gate(self) -> None:
        """publish → publisher-gate процесса перестроен (fps выключен в gate)."""
        svc, cm = _make()
        assert svc._heartbeat._telemetry_gate is None  # изначально гейта нет
        res = cm.dispatch(
            "telemetry.reconfigure",
            {"publish": {"metrics": {"fps": {"enabled": False}}}},
        )
        assert res["success"] is True
        assert res["applied"] == {"publish": True}
        gate = svc._heartbeat._telemetry_gate
        assert gate is not None
        assert "fps" not in gate.due_metrics(now=0.0)

    def test_publish_none_disables_gate(self) -> None:
        """publish=None → gate выключается (все метрики каждый тик)."""
        svc, cm = _make()
        # Сначала включим гейт, затем выключим.
        cm.dispatch("telemetry.reconfigure", {"publish": {}})
        assert svc._heartbeat._telemetry_gate is not None
        res = cm.dispatch("telemetry.reconfigure", {"publish": None})
        assert res["success"] is True and res["applied"] == {"publish": True}
        assert svc._heartbeat._telemetry_gate is None

    def test_throttle_updates_middleware_rules(self) -> None:
        """throttle → ThrottleMiddleware.rules изменились через get_middleware."""
        throttle = ThrottleMiddleware({"old.rule": 9.0})
        svc, cm = _make(throttle=throttle)
        res = cm.dispatch(
            "telemetry.reconfigure",
            {"throttle": {"processes.**.state.fps": 2.0}},
        )
        assert res["success"] is True
        assert res["applied"] == {"throttle": True}
        # set_rules ПОЛНОСТЬЮ заменяет набор (PC 0.1 семантика).
        assert throttle.rules == {"processes.**.state.fps": 2.0}

    def test_both_planes_in_one_command(self) -> None:
        throttle = ThrottleMiddleware({})
        svc, cm = _make(throttle=throttle)
        res = cm.dispatch(
            "telemetry.reconfigure",
            {"publish": {"metrics": {"shm": {"enabled": False}}}, "throttle": {"a.b": 1.0}},
        )
        assert res["applied"] == {"publish": True, "throttle": True}
        assert "shm" not in svc._heartbeat._telemetry_gate.due_metrics(now=100.0)
        assert throttle.rules == {"a.b": 1.0}

    def test_throttle_without_store_reports_no_receiver(self) -> None:
        """Процесс без StateStoreManager → throttle не применён (нет приёмника)."""
        svc, cm = _make(throttle=None)  # _state_store_manager is None
        res = cm.dispatch("telemetry.reconfigure", {"throttle": {"a": 1.0}})
        assert res["success"] is True
        assert res["applied"] == {"throttle": False}

    def test_empty_command_is_error(self) -> None:
        _svc, cm = _make()
        res = cm.dispatch("telemetry.reconfigure", {})
        assert res["success"] is False
        assert "publish" in res["reason"] or "throttle" in res["reason"]


class TestTelemetryReconfigureMergeMode:
    """Task 1.1: mode='merge' — точечная правка не стирает соседние правила/метрики."""

    def test_throttle_merge_changes_only_target_rule(self) -> None:
        """Acceptance: telemetry_mode=merge меняет ТОЛЬКО одно правило (снимок до/после)."""
        throttle = ThrottleMiddleware({"processes.**.state.latency_ms": 1.0, "processes.**.state.fps": 1.0})
        _svc, cm = _make(throttle=throttle)
        before = throttle.rules
        res = cm.dispatch(
            "telemetry.reconfigure",
            {"throttle": {"processes.**.state.fps": 0.2}, "telemetry_mode": "merge"},
        )
        assert res["success"] is True and res["applied"] == {"throttle": True}
        # fps изменён, latency_ms НЕ тронут (в отличие от replace/set_rules).
        assert throttle.rules == {"processes.**.state.latency_ms": 1.0, "processes.**.state.fps": 0.2}
        assert before["processes.**.state.latency_ms"] == 1.0

    def test_throttle_merge_none_removes_rule(self) -> None:
        """merge + None → remove_rule: правило исчезает, остальные сохранены."""
        throttle = ThrottleMiddleware({"keep": 5.0, "drop.me": 1.0})
        _svc, cm = _make(throttle=throttle)
        res = cm.dispatch(
            "telemetry.reconfigure",
            {"throttle": {"drop.me": None}, "telemetry_mode": "merge"},
        )
        assert res["success"] is True
        assert throttle.rules == {"keep": 5.0}

    def test_publish_merge_keeps_other_metric_overrides(self) -> None:
        """merge publisher: выключить fps → override соседней метрики сохранён в живом gate."""
        _svc, cm = _make()
        cm.dispatch(
            "telemetry.reconfigure",
            {"publish": {"metrics": {"fps": {"enabled": True}, "latency_ms": {"enabled": False}}}},
        )
        cm.dispatch(
            "telemetry.reconfigure",
            {"publish": {"metrics": {"fps": {"enabled": False}}}, "telemetry_mode": "merge"},
        )
        eff = _svc._heartbeat.current_telemetry_publish()
        assert eff["metrics"]["fps"]["enabled"] is False
        assert eff["metrics"]["latency_ms"]["enabled"] is False  # соседний override уцелел

    def test_replace_is_default_wipes_rules(self) -> None:
        """Характеризация: без telemetry_mode → replace → set_rules сносит соседей."""
        throttle = ThrottleMiddleware({"latency": 1.0, "fps": 1.0})
        _svc, cm = _make(throttle=throttle)
        cm.dispatch("telemetry.reconfigure", {"throttle": {"fps": 0.2}})
        assert throttle.rules == {"fps": 0.2}  # latency снесён (replace)


class TestUnknownModeSurfaced:
    """Task 1.2 finding-1: неизвестный mode → success=False, ошибка НЕ хоронится в applied.

    Наблюдаемость через оба хендлера-обёртки (telemetry.reconfigure, config.reload). Для
    fan-out-пути (telemetry.broadcast) — см. test_telemetry_broadcast.TestUnknownModeRejected.
    """

    def test_telemetry_reconfigure_unknown_mode_fails(self) -> None:
        throttle = ThrottleMiddleware({"keep": 1.0})
        _svc, cm = _make(throttle=throttle)
        res = cm.dispatch(
            "telemetry.reconfigure",
            {"throttle": {"a.b": 2.0}, "telemetry_mode": "mrege"},
        )
        assert res["success"] is False
        assert res["mode"] == "mrege"
        assert "mrege" in res["reason"]
        assert "applied" not in res  # ошибка не похоронена в applied
        assert throttle.rules == {"keep": 1.0}  # ничего не применено

    def test_config_reload_unknown_mode_fails(self) -> None:
        throttle = ThrottleMiddleware({"keep": 1.0})
        _svc, cm = _make(throttle=throttle)
        res = cm.dispatch(
            "config.reload",
            {"telemetry": {"throttle": {"a.b": 2.0}}, "telemetry_mode": "mrege"},
        )
        assert res["success"] is False
        assert res["mode"] == "mrege"
        assert "mrege" in res["reason"]
        assert "telemetry_applied" not in res
        assert throttle.rules == {"keep": 1.0}


class TestConfigReloadTelemetry:
    def test_reload_telemetry_only(self) -> None:
        """config.reload только с telemetry (без observability, без файла) → применяется."""
        throttle = ThrottleMiddleware({})
        svc, cm = _make(throttle=throttle)
        res = cm.dispatch(
            "config.reload",
            {"telemetry": {"publish": {"metrics": {"fps": {"enabled": False}}}, "throttle": {"x.y": 3.0}}},
        )
        assert res["success"] is True
        assert res["telemetry_applied"] == {"publish": True, "throttle": True}
        assert "applied" not in res  # observability не запрашивалась
        assert "fps" not in svc._heartbeat._telemetry_gate.due_metrics(now=0.0)
        assert throttle.rules == {"x.y": 3.0}

    def test_reload_observability_and_telemetry_together(self) -> None:
        """Обе секции в одном config.reload → обе применились, пути не конфликтуют."""
        throttle = ThrottleMiddleware({})
        logger = _FakeLogger()
        svc, cm = _make(throttle=throttle, logger=logger)
        res = cm.dispatch(
            "config.reload",
            {
                "observability": {"log_level": "DEBUG"},
                "telemetry": {"throttle": {"p.q": 4.0}},
            },
        )
        assert res["success"] is True
        # observability применилась (прежний контракт applied.log_level).
        assert res["applied"]["log_level"] == "DEBUG"
        assert logger.reconfigured[-1].get("default_level") == "DEBUG"
        # telemetry применилась.
        assert res["telemetry_applied"] == {"throttle": True}
        assert throttle.rules == {"p.q": 4.0}

    def test_reload_observability_only_backward_compatible(self) -> None:
        """Нет telemetry в reload → telemetry-плоскость не активируется (backward-compat)."""
        throttle = ThrottleMiddleware({"keep": 1.0})
        logger = _FakeLogger()
        svc, cm = _make(throttle=throttle, logger=logger)
        res = cm.dispatch("config.reload", {"observability": {"log_level": "WARNING"}})
        assert res["success"] is True
        assert res["applied"]["log_level"] == "WARNING"
        assert "telemetry_applied" not in res
        assert throttle.rules == {"keep": 1.0}  # троттл не тронут
        assert svc._heartbeat._telemetry_gate is None  # gate не строился
