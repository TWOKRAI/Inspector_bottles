# -*- coding: utf-8 -*-
"""``SimRobotHostPlugin`` — хост ``Services.robot_comm.server.sim_robot.SimRobotServer``.

Обычный side-effect плагин ``ProcessModulePlugin`` в ``GenericProcessApp`` (форма —
как у ``Plugins/io/otel_export``: сервис в ``Services``, тонкий плагин здесь). Он
поднимает Modbus TCP-симулятор робота на своём порту, считает записи обмена
(``writes_seen``) и отдаёт статус командой ``sim_robot.status``.

**Деградация без ``pymodbus`` — состояние, не отказ процесса** (образец:
``OtelExportPlugin`` без extra ``[otel]``, Р-14 из его докстринга). Импорт
``Services.robot_comm.server.sim_robot`` и конструктор ``SimRobotServer`` живут
ВНУТРИ ``try`` в :meth:`_start_server`: без ``pymodbus`` конструктор бросает
``ModbusNotAvailableError`` (текст уже содержит слово «modbus» —
``Services/robot_comm/server/sim_robot.py:109``), плагин ловит её, уходит в
``_state = "error"`` и зовёт ``ctx.health.report_error(...)`` — тот же коннектор,
что кладёт факт в плоскость ошибок (``errors.log``) И пишет строку журнала одним
вызовом (ADR-PM-030). Процесс при этом поднимается: `start()` не пробрасывает
исключение наружу.

**Порт занят — обнаруживается СВОИМ пробным bind'ом, а не исключением
``SimRobotServer``.** ``SimRobotServer.start()`` не блокирует до подтверждения
бинда: он запускает ``pymodbus`` (``StartTcpServer``) в фоновом daemon-потоке
(``sim_robot.py:121-126``) и возвращается немедленно, а ошибка ``bind()`` при
занятом порту случится ВНУТРИ этого потока — синхронный ``try/except`` вокруг
``.start()`` её никогда не поймает (поток просто тихо умирает). Поэтому
:meth:`_start_server` сперва сам биндит и сразу закрывает пробный сокет на том же
``host``/``port`` — если ОС отказала (``OSError``, порт занят), это ловится здесь,
синхронно, ДО обращения к ``pymodbus``. Окно гонки между пробным закрытием и
реальным биндом сервера теоретически есть, но для одиночного процесса-симулятора
на выделенном порту (5021, out of scope — гонка с параллельным конкурентом) этого
достаточно; более сильная гарантия потребовала бы правки ``Services/robot_comm``,
которая вне области задачи.

**Счёт записей — под ``Lock``, публикация метрики — с чужого потока не зовётся.**
``on_write`` вызывается ``pymodbus``-сервером на ЕГО СОБСТВЕННОМ потоке
(``sim_robot.py:69`` — корутина ``binder`` исполняется event-loop'ом сервера, не
приёмным потоком процесса). ``PluginContext.record_metric`` документирован как
безопасный только со штатного потока плагина (``_stats_call`` держит свой
``_counters_lock`` не всегда — у ``StatsManager``/порта наблюдений явных
гарантий межпотокового вызова в докстринге ``base.py`` нет). Поэтому
:meth:`_on_write` только инкрементирует счётчик под ``self._lock`` (примитив,
безопасный из любого потока по построению) и НЕ зовёт ``ctx.record_metric``
напрямую; перенос в плоскость stats делает :meth:`_sync_writes_metric` —
дельтой, тем же приёмом, что ``OtelExportPlugin._sync_queue_counters`` — и
зовётся она только из :meth:`cmd_status` и :meth:`shutdown`, то есть с потока
диспетчера команд/останова процесса, а не с потока ``pymodbus``.
"""

from __future__ import annotations

import os
import socket
import threading
import time
from typing import Any

from multiprocess_framework.modules.process_module.plugins import (
    ExecutionMode,
    PluginContext,
    ProcessModulePlugin,
    ThreadConfig,
    register_plugin,
)

from Services.robot_comm.core.registers import FACTOR_MM

#: Дефолты конфига (Task 1.1 плана line-sim, §Task 1.1 pipeline.yaml).
_DEFAULT_HOST = "127.0.0.1"
_DEFAULT_PORT = 5021
_DEFAULT_UNIT_ID = 2

#: Период публикации энкодера в общий мир (Task 2.2 плана line-sim, §Task 2.2).
_DEFAULT_PUBLISH_MS = 50


@register_plugin("sim_robot_host", category="io", description="Хост Modbus TCP-симулятора робота (SimRobotServer)")
class SimRobotHostPlugin(ProcessModulePlugin):
    """Плагин-хост ``SimRobotServer``: конфиг → пробный порт → сервер → счёт записей."""

    name = "sim_robot_host"
    category = "io"

    VERSION = "1.0.0"
    REQUIRES: tuple[str, ...] = ("manager:command_manager",)

    inputs: list = []
    outputs: list = []

    commands = {
        "sim_robot.status": "cmd_status",
    }

    def configure(self, ctx: PluginContext) -> None:
        """READY: разобрать конфиг, завести состояние. Сеть здесь не трогаем."""
        self._ctx = ctx
        cfg = ctx.config
        self._host: str = cfg.get("host", _DEFAULT_HOST)
        self._port: int = cfg.get("port", _DEFAULT_PORT)
        self._unit_id: int = cfg.get("unit_id", _DEFAULT_UNIT_ID)
        self._auto_start: bool = cfg.get("auto_start", True)
        self._publish_ms: int = cfg.get("publish_ms", _DEFAULT_PUBLISH_MS)

        self._server: Any = None
        self._lock = threading.Lock()
        self._writes_seen = 0
        # Сколько записей уже перенесено в плоскость stats (дельта, не абсолют —
        # тот же приём, что у ``OtelExportPlugin._queue_dropped_seen``).
        self._writes_reported = 0
        self._state = "configured"
        self._reason = ""

        # Паблишер энкодера в общий мир (Task 2.2): последний опубликованный
        # энкодер/момент — для вычисления mm_s ПРОИЗВОДНОЙ между тиками
        # публикации, без обращения к приватным полям RobotSimCore/BeltDrive
        # (Services/robot_comm вне области этой задачи, Task 2.1b его владеет).
        self._last_pub_encoder: int | None = None
        self._last_pub_t: float | None = None

        # Task 2.0 не влит → ctx.state_proxy is None: плагин живёт, мир недоступен.
        ctx.declare_metric("encoder")
        ctx.declare_metric("belt_mm_s")
        ctx.declare_metric("writes_seen")

        ctx.log_info(f"sim_robot_host: конфиг принят, {self._host}:{self._port}, unit_id={self._unit_id}")

    def start(self, ctx: PluginContext) -> None:
        """RUNNING: поднять сервер, если ``auto_start``, и паблишер мира."""
        if self._auto_start:
            self._start_server(ctx)

        if ctx.state_proxy is None:
            ctx.log_info("sim_robot_host: ctx.state_proxy is None — мир недоступен, паблишер не запущен")
        else:
            cfg = ThreadConfig(execution_mode=ExecutionMode.LOOP)
            ctx.worker_manager.create_worker("sim_robot_world_publisher", self._publish_loop, cfg, auto_start=True)

    def shutdown(self, ctx: PluginContext) -> None:
        """STOPPED: дожать счётчик, остановить сервер симметрично ``start()``."""
        self._sync_writes_metric()
        if self._server is not None:
            self._server.stop()
            self._server = None
        self._state = "stopped"
        ctx.log_info(f"sim_robot_host: остановлен, writes_seen={self._writes_seen}")

    # ------------------------------------------------------------------ #
    # Старт сервера
    # ------------------------------------------------------------------ #

    def _start_server(self, ctx: PluginContext) -> None:
        """Поднять ``SimRobotServer``. Живой сервер — no-op (повторный ``start``)."""
        if self._server is not None:
            return

        try:
            self._probe_port_free()
        except OSError as exc:
            self._fail(ctx, exc)
            return

        try:
            from Services.modbus.sdk.errors import ModbusNotAvailableError
            from Services.robot_comm.server.sim_robot import SimRobotServer

            server = SimRobotServer(self._host, self._port, self._unit_id, on_write=self._on_write)
            server.start()
        except (ModbusNotAvailableError, ImportError, OSError) as exc:  # noqa: BLE001 — деградация, не отказ
            self._fail(ctx, exc)
            return

        self._server = server
        self._state = "running"
        self._reason = ""
        ctx.log_info(f"sim_robot_host: SimRobotServer поднят на {self._host}:{self._port}")

    def _probe_port_free(self) -> None:
        """Синхронно проверить, что порт свободен, ДО обращения к pymodbus.

        См. докстринг модуля: ``SimRobotServer.start()`` биндит порт в фоновом
        потоке и не сообщает об ошибке синхронно вызывающему.
        """
        probe = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            # SO_REUSEADDR — как у самого сервера (pymodbus передаёт reuse_address=True):
            # порт в TIME_WAIT после прошлого запуска не считается занятым, а живой
            # слушатель на том же адресе всё равно даёт EADDRINUSE (тесты AC1/AC2 в
            # tests/test_acceptance_time_wait.py). Без него рестарт в течение ~30 с на
            # macOS падал в error при свободном порту (стенд Task 1.3, 2026-09-21).
            # Только POSIX: на Windows SO_REUSEADDR разрешает bind поверх живого
            # слушателя, и проба перестала бы замечать ещё живой прошлый сим.
            if os.name == "posix":
                probe.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            probe.bind((self._host, self._port))
        finally:
            probe.close()

    def _fail(self, ctx: PluginContext, exc: Exception) -> None:
        """Перевести плагин в ``error``: факт в плоскость ошибок + голос, процесс живёт."""
        self._state = "error"
        self._reason = str(exc)
        ctx.health.report_error(exc, context="sim_robot_host.start", host=self._host, port=self._port)

    # ------------------------------------------------------------------ #
    # Приём обмена
    # ------------------------------------------------------------------ #

    def _on_write(self, fc: int, addr: int, values: list[int] | None) -> None:
        """Наблюдатель обмена ``SimRobotServer`` (чужой поток — см. докстринг модуля).

        ``values is None`` — чтение, не считаем. Иначе — запись, инкремент под
        локом; публикация в plane stats отложена до :meth:`_sync_writes_metric`.
        """
        if values is None:
            return
        with self._lock:
            self._writes_seen += 1

    def _sync_writes_metric(self) -> None:
        """Перенести накопленные записи в ``ctx.record_metric`` ДЕЛЬТОЙ.

        Зовётся только со штатных потоков плагина (диспетчер команд —
        :meth:`cmd_status`, либо останов — :meth:`shutdown`), никогда с потока
        ``pymodbus``.
        """
        with self._lock:
            delta = self._writes_seen - self._writes_reported
            if delta <= 0:
                return
            self._writes_reported = self._writes_seen
        self._ctx.record_metric("sim_robot.writes", delta)

    # ------------------------------------------------------------------ #
    # Паблишер мира (Task 2.2) — энкодер в ``sim.belt.encoder`` + уровни
    # ------------------------------------------------------------------ #

    def _publish_loop(self, stop_event: Any, pause_event: Any) -> None:
        """Тик паблишера: ``publish_ms`` (форма — ``TelemetrySinkPlugin._sample_loop``).

        Ошибка одного тика (например, сервер ещё не поднят) не должна убивать
        воркер — иначе публикация мира молча умирает навсегда.
        """
        interval_s = self._publish_ms / 1000.0
        while not stop_event.is_set():
            if pause_event.is_set():
                time.sleep(0.1)
                continue
            time.sleep(interval_s)
            try:
                self._publish_once()
            except Exception as exc:  # noqa: BLE001 — тик не должен убить воркер
                self._ctx.health.report_error(exc, context="sim_robot_host.publish")

    def _publish_once(self) -> None:
        """Один тик: снять энкодер сервера, положить в мир, отдать уровни.

        ``mm_s`` — производная энкодера МЕЖДУ ДВУМЯ ТИКАМИ ПУБЛИКАЦИИ, а не
        чтение внутреннего состояния ``BeltDrive``: ``RobotSimCore``/``BeltDrive``
        не выставляют публичного ``mm_s``-аксессора (``core.encoder`` — да,
        ``core._belt`` — приватное поле чужого модуля, Task 2.1b его владеет и
        трогать его отсюда не входит в область этой задачи). Побочный эффект —
        то же самое число: пока лента едет с постоянной скоростью, средняя
        скорость за интервал публикации равна мгновенной; на пульсе смены
        команды ПЧ (не чаще, чем раз в ``publish_ms``) один тик даёт смешанное
        среднее — не проверено отдельным тестом, см. отчёт разработчика.
        """
        if self._server is None or self._ctx.state_proxy is None:
            return

        encoder = self._server.core.encoder
        now = time.monotonic()
        mm_s = 0.0
        if self._last_pub_t is not None and self._last_pub_encoder is not None:
            dt = now - self._last_pub_t
            if dt > 0:
                mm_s = (encoder - self._last_pub_encoder) * FACTOR_MM / dt
        self._last_pub_encoder = encoder
        self._last_pub_t = now

        self._ctx.state_proxy.set("sim.belt.encoder", {"value": encoder, "mm_s": mm_s, "t": now})

        with self._lock:
            writes_seen = self._writes_seen
        self._ctx.publish_metric("encoder", encoder)
        self._ctx.publish_metric("belt_mm_s", mm_s)
        self._ctx.publish_metric("writes_seen", writes_seen)

    # ------------------------------------------------------------------ #
    # Команды
    # ------------------------------------------------------------------ #

    def cmd_status(self, data: dict | None = None) -> dict:
        """``sim_robot.status`` → running/host/port/unit_id/writes_seen/state/world."""
        self._sync_writes_metric()
        with self._lock:
            writes_seen = self._writes_seen
        return {
            "running": self._state == "running",
            "host": self._host,
            "port": self._port,
            "unit_id": self._unit_id,
            "writes_seen": writes_seen,
            "state": self._state,
            "world": "unavailable" if self._ctx.state_proxy is None else "ok",
        }
