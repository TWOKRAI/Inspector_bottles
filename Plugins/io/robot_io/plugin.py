"""RobotIoPlugin v2 — тонкий job-форвардер в процесс devices.

Соединением с роботом владеет DeviceHubPlugin (always-on процесс devices).
Этот плагин:
1. Извлекает job-координаты из item[job_source] в process() (НЕ блокирующий).
2. Кладёт координаты в локальную forward-deque (maxlen из конфига).
3. Worker ``job_forwarder`` (LOOP) забирает из deque и шлёт
   ``robot_enqueue_job`` в hub через DeviceHubClient (IPC request).

Команды плагина УДАЛЕНЫ — GUI теперь ходит напрямую в процесс devices.

Refs: plans/device-hub.md Фаза 3, Р10
"""

from __future__ import annotations

import time
from collections import deque
from typing import Any

from multiprocess_framework.modules.process_module.plugins import (
    ExecutionMode,
    PluginContext,
    Port,
    ProcessModulePlugin,
    ThreadConfig,
    register_plugin,
)

from Plugins.hub.device_hub.client import DeviceHubClient

from .registers import RobotIoRegisters

# Интервал поллинга deque в job_forwarder, сек.
_FORWARDER_POLL_S = 0.02
# Таймаут IPC-запроса к hub, сек.
_HUB_REQUEST_TIMEOUT = 1.0


@register_plugin(
    "robot_io",
    category="io",
    description="Тонкий job-форвардер: координаты из pipeline -> devices (robot_enqueue_job)",
)
class RobotIoPlugin(ProcessModulePlugin):
    """Тонкий job-форвардер: pipeline -> devices через DeviceHubClient."""

    name = "robot_io"
    category = "io"
    thread_safe = False

    inputs = [
        Port(name="robot_job", dtype="dict", optional=True, description="Задание {x_mm, y_mm} в forward-deque"),
    ]
    outputs = []  # side-effect к железу, кадры pass-through

    # Команды УДАЛЕНЫ — GUI ходит в процесс devices напрямую
    commands: dict[str, str] = {}
    register_class = RobotIoRegisters

    @classmethod
    def config_class(cls) -> type | None:
        """Явный config_class -> register_schema() резолвит register_bindings."""
        from .config import RobotIoPluginConfig

        return RobotIoPluginConfig

    # ------------------------------------------------------------------ #
    # LIFECYCLE
    # ------------------------------------------------------------------ #

    def configure(self, ctx: PluginContext) -> None:
        """IDLE -> READY: создать register, инициализировать состояние."""
        self._ctx = ctx
        self._reg: RobotIoRegisters = self._init_register(ctx)
        self._deque: deque[dict[str, Any]] = deque(maxlen=self._reg.forward_deque_maxlen)
        self._client: DeviceHubClient | None = None
        # Флаг once-per-transition: True = последний запрос был ошибкой
        self._last_was_error = False
        ctx.log_info(f"RobotIoPlugin v2: configured (device_id={self._reg.device_id})")

    def start(self, ctx: PluginContext) -> None:
        """READY -> RUNNING: создать DeviceHubClient, запустить job_forwarder."""
        self._client = DeviceHubClient(ctx)
        cfg = ThreadConfig(execution_mode=ExecutionMode.LOOP)
        ctx.worker_manager.create_worker("job_forwarder", self._forwarder_loop, cfg, auto_start=True)
        ctx.log_info("RobotIoPlugin v2: started (job_forwarder запущен)")

    def shutdown(self, ctx: PluginContext) -> None:
        """* -> STOPPED: остановить воркер (worker_manager делает stop_worker)."""
        remaining = len(self._deque)
        self._deque.clear()
        self._client = None
        ctx.log_info(
            f"RobotIoPlugin v2: shutdown "
            f"(forwarded={self._reg.jobs_forwarded}, dropped={self._reg.jobs_dropped}, "
            f"remaining_in_deque={remaining})"
        )

    # ------------------------------------------------------------------ #
    # PROCESS — приём заданий из pipeline (pass-through, НЕ блокируется)
    # ------------------------------------------------------------------ #

    def process(self, items: list[dict]) -> list[dict]:
        """Извлечь job-координаты из item[job_source] -> forward-deque; кадр — дальше."""
        for item in items:
            job = item.get(self._reg.job_source)
            if isinstance(job, dict) and "x_mm" in job and "y_mm" in job:
                job_data = {
                    "device_id": self._reg.device_id,
                    "x_mm": float(job["x_mm"]),
                    "y_mm": float(job["y_mm"]),
                }
                # deque(maxlen=N) автоматически дропает старые при переполнении
                was_full = len(self._deque) >= self._deque.maxlen
                self._deque.append(job_data)
                if was_full:
                    self._reg.jobs_dropped += 1
                self._reg.queue_len = len(self._deque)
        return items

    # ------------------------------------------------------------------ #
    # FORWARDER (worker) — IPC-мост в процесс devices
    # ------------------------------------------------------------------ #

    def _forwarder_loop(self, stop_event: Any, pause_event: Any) -> None:
        """Фоновый цикл: забираем из deque -> robot_enqueue_job через DeviceHubClient."""
        while not stop_event.is_set():
            if pause_event.is_set():
                time.sleep(0.1)
                continue

            if not self._deque:
                time.sleep(_FORWARDER_POLL_S)
                continue

            job = self._deque.popleft()
            self._reg.queue_len = len(self._deque)

            if self._client is None:
                self._reg.jobs_dropped += 1
                continue

            try:
                result = self._client.request(
                    "robot_enqueue_job",
                    job,
                    timeout=_HUB_REQUEST_TIMEOUT,
                )
            except Exception as exc:
                self._reg.jobs_dropped += 1
                self._reg.hub_errors += 1
                self._reg.last_error = str(exc)
                # once-per-transition: логируем только при смене состояния
                if not self._last_was_error:
                    self._ctx.log_error(f"RobotIoPlugin: hub ошибка: {exc}")
                    self._last_was_error = True
                continue

            if result.get("status") == "ok":
                self._reg.jobs_forwarded += 1
                # once-per-transition: при восстановлении — лог
                if self._last_was_error:
                    self._ctx.log_info("RobotIoPlugin: hub восстановлен")
                    self._last_was_error = False
            else:
                self._reg.jobs_dropped += 1
                self._reg.hub_errors += 1
                error_msg = result.get("message", "неизвестная ошибка hub")
                self._reg.last_error = error_msg
                # once-per-transition
                if not self._last_was_error:
                    self._ctx.log_error(f"RobotIoPlugin: hub отказ: {error_msg}")
                    self._last_was_error = True
