# -*- coding: utf-8 -*-
"""Тесты телеметрийного тика в контракте (`publish.tick_sec`) — Task 1.2.

Частота публикации телеметрии управляется ``TelemetryPublishConfig.tick_sec`` (boot +
runtime), а НЕ захардкоженным ``heartbeat_interval=5.0``. Инвариант: частота
heartbeat-СООБЩЕНИЙ к ProcessMonitor (liveness) НЕ меняется телеметрийным тиком.

Acceptance:
  - fake-clock: ``tick_sec=0.5`` → телеметрийный merge ~2 Гц при ``heartbeat_interval=5.0``;
    heartbeat-сообщения остаются ~0.2 Гц;
  - ``tick_sec=None`` → каденция публикации бит-в-бит прежняя (телеметрия = такт heartbeat);
  - runtime-смена ``tick_sec`` через ``reconfigure_telemetry`` меняет каденцию без рестарта;
  - ``interval_sec < tick_sec`` → WARNING в логе (не тихий no-op).
"""

from __future__ import annotations

from multiprocess_framework.modules.process_module.heartbeat.process_heartbeat import (
    ProcessHeartbeat,
)


class FakeClock:
    """Управляемый монотонный источник времени для детерминированной каденции."""

    def __init__(self) -> None:
        self.t = 0.0

    def __call__(self) -> float:
        return self.t

    def advance(self, dt: float) -> None:
        self.t += float(dt or 0.0)


class FakeStop:
    """``stop_event``-заглушка: завершает цикл при достижении ``t_end`` фейк-часами.

    ``wait(timeout)`` продвигает фейк-часы на ``timeout`` (моделирует сон воркера).
    """

    def __init__(self, clock: FakeClock, t_end: float) -> None:
        self._clock = clock
        self._t_end = t_end

    def is_set(self) -> bool:
        return self._clock() >= self._t_end

    def wait(self, timeout=None) -> None:
        self._clock.advance(timeout)


class _NoPause:
    def is_set(self) -> bool:
        return False


class _WorkerManager:
    def __init__(self, workers: dict) -> None:
        self._workers = workers

    def get_all_workers_status(self) -> dict:
        # Свежая (поверхностная) копия на каждый тик — как реальный менеджер.
        return {w: dict(v) for w, v in self._workers.items()}


class _Proxy:
    def __init__(self) -> None:
        self.merged: list[tuple[str, dict]] = []

    def merge(self, path: str, data: dict) -> None:
        self.merged.append((path, data))


class RecordingServices:
    """Сервисы процесса: пишут heartbeat-сообщения, телеметрию и логи."""

    def __init__(self, workers: dict | None = None, *, name: str = "proc") -> None:
        self.name = name
        self._state_proxy = _Proxy()
        self.worker_manager = _WorkerManager(workers) if workers is not None else None
        self.router_manager = None
        self._health_state = None
        self._current_process_status = "running"
        self._config: dict = {}
        self.heartbeats: list[dict] = []
        self.logs: list[tuple[str, str]] = []  # (level, message)

    def get_config(self, key: str, default=None):
        return self._config.get(key, default)

    def send_message(self, target: str, message: dict) -> bool:
        if isinstance(message, dict) and message.get("command") == "heartbeat":
            self.heartbeats.append(message)
        return True

    def log_info(self, msg, *a, **k) -> None:
        self.logs.append(("info", str(msg)))

    def log_debug(self, msg, *a, **k) -> None:
        self.logs.append(("debug", str(msg)))

    def log_warning(self, msg, *a, **k) -> None:
        self.logs.append(("warning", str(msg)))


def _running_workers(n: int = 2) -> dict:
    return {f"w{i}": {"status": "running", "effective_hz": 10.0 + i, "cycle_duration_ms": 5.0 + i} for i in range(n)}


def _telemetry_merges(svc: RecordingServices) -> list[tuple[str, dict]]:
    """Только телеметрийные merge'и (карточка/воркеры), не health/shm."""
    return svc._state_proxy.merged


class TestCadenceFastTelemetry:
    """Acceptance 1: tick_sec=0.5 → телеметрия ~2 Гц, heartbeat ~0.2 Гц (fake-clock)."""

    def test_telemetry_two_hz_heartbeat_stays_slow(self) -> None:
        clock = FakeClock()
        svc = RecordingServices(_running_workers(2))
        hb = ProcessHeartbeat(svc, clock=clock)
        # heartbeat_interval = 5.0 (дефолт self._interval); телеметрия — 0.5с (2 Гц).
        hb.reconfigure_telemetry({"tick_sec": 0.5, "default_interval_sec": 0.5})

        hb._loop(FakeStop(clock, t_end=10.0), _NoPause())

        # 10с / 0.5с тик = 20 телеметрийных публикаций (~2 Гц).
        assert len(_telemetry_merges(svc)) == 20
        # heartbeat-сообщения — по расписанию liveness (5с): t=0 и t=5 → 2 (~0.2 Гц).
        assert len(svc.heartbeats) == 2
        # Телеметрия существенно чаще heartbeat — суть Task 1.2.
        assert len(_telemetry_merges(svc)) > len(svc.heartbeats) * 5


class TestCadenceBackwardCompat:
    """Acceptance 2: tick_sec=None → каденция бит-в-бит прежняя (телеметрия = такт HB)."""

    def test_none_tick_telemetry_rides_heartbeat(self) -> None:
        clock = FakeClock()
        svc = RecordingServices(_running_workers(2))
        hb = ProcessHeartbeat(svc, clock=clock)
        # Гейт не активирован (tick_sec отсутствует) → тик = heartbeat_interval = 5.0.
        assert hb._telemetry_tick() == 5.0

        hb._loop(FakeStop(clock, t_end=10.0), _NoPause())

        # Прежнее поведение: телеметрия публикуется РОВНО на такте heartbeat.
        assert len(svc.heartbeats) == 2
        assert len(_telemetry_merges(svc)) == len(svc.heartbeats)

    def test_tick_sec_none_via_gate(self) -> None:
        """Явный gate без tick_sec → всё равно heartbeat_interval (backward-compat)."""
        svc = RecordingServices(_running_workers(1))
        hb = ProcessHeartbeat(svc)
        hb.reconfigure_telemetry({"default_interval_sec": 0.5})  # tick_sec не задан
        assert hb._telemetry_tick() == 5.0


class TestRuntimeTickChange:
    """Acceptance 3: runtime-смена tick_sec меняет каденцию без рестарта."""

    def test_reconfigure_changes_tick_live(self) -> None:
        svc = RecordingServices(_running_workers(1))
        hb = ProcessHeartbeat(svc)
        assert hb._telemetry_tick() == 5.0  # старт: гейт off

        hb.reconfigure_telemetry({"tick_sec": 0.5, "default_interval_sec": 0.5})
        assert hb._telemetry_tick() == 0.5  # тик перевзведён живьём

        # И обратно (снять tick_sec → merge мимо, здесь replace целиком без tick_sec).
        hb.reconfigure_telemetry({"default_interval_sec": 0.5})
        assert hb._telemetry_tick() == 5.0

    def test_cadence_speeds_up_after_reconfigure(self) -> None:
        """После reconfigure(tick_sec=0.5) цикл в 1с окне даёт 2 телеметрийных тика."""
        clock = FakeClock()
        svc = RecordingServices(_running_workers(1))
        hb = ProcessHeartbeat(svc, clock=clock)
        hb.reconfigure_telemetry({"tick_sec": 0.5, "default_interval_sec": 0.5})

        hb._loop(FakeStop(clock, t_end=1.0), _NoPause())
        # t=0, t=0.5 → 2 публикации в 1с окне.
        assert len(_telemetry_merges(svc)) == 2


class TestCappedMetricWarning:
    """Acceptance 4: interval_sec < tick_sec → WARNING (не тихий no-op)."""

    def test_warns_when_metric_interval_below_tick(self) -> None:
        svc = RecordingServices(_running_workers(1))
        hb = ProcessHeartbeat(svc)
        # fps хочет 0.1с, но тик = min(5.0, 0.5) = 0.5с → недостижимо → WARNING.
        hb.reconfigure_telemetry({"tick_sec": 0.5, "metrics": {"fps": {"interval_sec": 0.1}}})

        warnings = [m for lvl, m in svc.logs if lvl in ("warning", "info")]
        assert any("fps" in m and "ограничена" in m for m in warnings), svc.logs

    def test_no_warning_when_all_intervals_above_tick(self) -> None:
        svc = RecordingServices(_running_workers(1))
        hb = ProcessHeartbeat(svc)
        # default 1.0 >= tick 0.5, ни одной явной метрики ниже тика → тихо.
        hb.reconfigure_telemetry({"tick_sec": 0.5, "default_interval_sec": 1.0})
        assert not any("ограничена" in m for _lvl, m in svc.logs), svc.logs

    def test_no_warning_when_tick_sec_none(self) -> None:
        """tick_sec не задан → легаси-процессы не шумят (finding D осознанно тихо в None)."""
        svc = RecordingServices(_running_workers(1))
        hb = ProcessHeartbeat(svc)
        hb.reconfigure_telemetry({"metrics": {"fps": {"interval_sec": 0.1}}})
        assert not any("ограничена" in m for _lvl, m in svc.logs), svc.logs


class TestTelemetryTickHelper:
    """Юнит: _telemetry_tick = min(heartbeat_interval, tick_sec), с фолбэками."""

    def test_gate_off_returns_interval(self) -> None:
        hb = ProcessHeartbeat(RecordingServices())
        assert hb._telemetry_tick() == 5.0

    def test_tick_below_interval(self) -> None:
        hb = ProcessHeartbeat(RecordingServices())
        hb.reconfigure_telemetry({"tick_sec": 0.5})
        assert hb._telemetry_tick() == 0.5

    def test_tick_above_interval_clamped_to_interval(self) -> None:
        hb = ProcessHeartbeat(RecordingServices())
        hb.reconfigure_telemetry({"tick_sec": 10.0})
        assert hb._telemetry_tick() == 5.0  # min(5.0, 10.0)

    def test_tick_zero_falls_back_to_interval(self) -> None:
        hb = ProcessHeartbeat(RecordingServices())
        hb.reconfigure_telemetry({"tick_sec": 0.0})
        assert hb._telemetry_tick() == 5.0


class TestHeartbeatDueHelper:
    """Юнит: инвариант liveness — heartbeat-сообщение раз в heartbeat_interval."""

    def test_tick_equals_interval_always_due(self) -> None:
        """tick_sec=None → tick=interval → каждый тик = heartbeat-такт (бит-в-бит)."""
        hb = ProcessHeartbeat(RecordingServices())
        hb._last_heartbeat_sent = 100.0
        assert hb._heartbeat_due(now=100.0, tick=5.0) is True

    def test_first_tick_always_due(self) -> None:
        hb = ProcessHeartbeat(RecordingServices())
        assert hb._last_heartbeat_sent is None
        assert hb._heartbeat_due(now=1000.0, tick=0.5) is True

    def test_not_due_before_interval_elapsed(self) -> None:
        hb = ProcessHeartbeat(RecordingServices())
        hb._last_heartbeat_sent = 0.0
        # tick=0.5, порог = 5.0 - 0.25 = 4.75.
        assert hb._heartbeat_due(now=4.5, tick=0.5) is False
        assert hb._heartbeat_due(now=5.0, tick=0.5) is True
