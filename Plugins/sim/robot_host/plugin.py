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

import socket
import threading
from typing import Any

from multiprocess_framework.modules.process_module.plugins import (
    PluginContext,
    ProcessModulePlugin,
    register_plugin,
)

#: Дефолты конфига (Task 1.1 плана line-sim, §Task 1.1 pipeline.yaml).
_DEFAULT_HOST = "127.0.0.1"
_DEFAULT_PORT = 5021
_DEFAULT_UNIT_ID = 2


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

        self._server: Any = None
        self._lock = threading.Lock()
        self._writes_seen = 0
        # Сколько записей уже перенесено в плоскость stats (дельта, не абсолют —
        # тот же приём, что у ``OtelExportPlugin._queue_dropped_seen``).
        self._writes_reported = 0
        self._state = "configured"
        self._reason = ""

        ctx.log_info(f"sim_robot_host: конфиг принят, {self._host}:{self._port}, unit_id={self._unit_id}")

    def start(self, ctx: PluginContext) -> None:
        """RUNNING: поднять сервер, если ``auto_start``. Отказ не роняет процесс."""
        if self._auto_start:
            self._start_server(ctx)

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
    # Команды
    # ------------------------------------------------------------------ #

    def cmd_status(self, data: dict | None = None) -> dict:
        """``sim_robot.status`` → running/host/port/unit_id/writes_seen/state."""
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
        }
