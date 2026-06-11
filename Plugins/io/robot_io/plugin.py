"""RobotIoPlugin — ВЛАДЕЛЕЦ соединения с роботом + исполнитель CVT.

Модель владельца (ADR-RC-003): единственный плагин, который создаёт/коннектит/
закрывает RobotClient. В start() публикует клиент в process-local
``Services.robot_comm.runtime`` — потребители (vfd_control, robot_draw,
calibration) берут его через ``runtime.get_client()`` и обязаны жить в ОДНОМ
``process_name`` рецепта с этим плагином.

Feeder (порт логики ``Console.feeder`` из pc_full.py): фоновый worker держит
очередь заданий, при свободном роботе отдаёт следующее (send_job -> ожидание
приёма -> ожидание завершения), плюс периодически публикует телеметрию в
state-дерево (``robot/telemetry``).

CVT-срез: координаты приходят командой ``send_test_job`` (вкладка/CLI) или в
item по ключу ``job_source`` (dict {x_mm, y_mm}). Калибровка pixel->robot —
отдельный план, подключается upstream позже.

Флаг ``manual_mode`` приостанавливает авто-подачу из очереди (P2.5: оператор
управляет роботом с вкладки/калибрует — авто-job'ы не должны вмешиваться).
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

from Services.modbus import ModbusDriverError
from Services.robot_comm import RobotClient, RobotConfig, RobotJobError, runtime

from .registers import RobotIoRegisters

# Минимальный интервал между попытками переподключения, сек.
_RECONNECT_THROTTLE_SEC = 2.0


@register_plugin(
    "robot_io",
    category="io",
    description="Робот Delta: владелец соединения + CVT-исполнитель (feeder)",
)
class RobotIoPlugin(ProcessModulePlugin):
    """Владелец RobotClient: feeder-очередь CVT-заданий + телеметрия в state."""

    name = "robot_io"
    category = "io"
    # Единственное соединение + очередь под Lock — не параллелить.
    thread_safe = False

    inputs = [
        Port(name="robot_job", dtype="dict", optional=True, description="Задание {x_mm, y_mm} в очередь feeder"),
    ]
    outputs = []  # лист: side-effect к железу, кадры pass-through

    commands = {
        "send_test_job": "cmd_send_test_job",
        "abort": "cmd_abort",
        "set_mode": "cmd_set_mode",
        "set_servo": "cmd_set_servo",
        "set_robot_config": "cmd_set_robot_config",
        "get_robot_config": "cmd_get_robot_config",
        "get_telemetry": "cmd_get_telemetry",
        "read_echo": "cmd_read_echo",
        "set_manual_mode": "cmd_set_manual_mode",
        "clear_queue": "cmd_clear_queue",
    }
    register_class = RobotIoRegisters

    @classmethod
    def config_class(cls) -> type | None:
        """Явный config_class → register_schema() резолвит register_bindings."""
        from .config import RobotIoPluginConfig

        return RobotIoPluginConfig

    # ------------------------------------------------------------------ #
    # LIFECYCLE
    # ------------------------------------------------------------------ #

    def configure(self, ctx: PluginContext) -> None:
        """IDLE → READY: register + состояние. Соединение НЕ открываем здесь."""
        self._ctx = ctx
        self._reg: RobotIoRegisters = self._init_register(ctx)
        self._client: RobotClient | None = None
        self._queue: deque[tuple[float, float, int]] = deque()
        self._last_reconnect = 0.0
        self._last_telemetry = 0.0
        ctx.log_info(f"RobotIoPlugin: configured ({self._reg.host}:{self._reg.port} unit {self._reg.unit_id})")

    def start(self, ctx: PluginContext) -> None:
        """READY → RUNNING: создать клиент, опубликовать (владелец), поднять feeder."""
        self._client = RobotClient(self._build_config())
        runtime.set_client(self._client)  # владелец публикует ДО connect: потребители ждут is_connected
        if self._reg.auto_connect:
            self._try_connect()
        cfg = ThreadConfig(execution_mode=ExecutionMode.LOOP)
        ctx.worker_manager.create_worker("robot_feeder", self._feeder_loop, cfg, auto_start=True)
        ctx.log_info("RobotIoPlugin: started (владелец RobotClient опубликован в runtime)")

    def shutdown(self, ctx: PluginContext) -> None:
        """* → STOPPED: снять публикацию и закрыть соединение (graceful)."""
        runtime.clear()
        if self._client is not None:
            try:
                self._client.disconnect()
            except Exception as exc:  # pragma: no cover - defensive на shutdown
                ctx.log_error(f"RobotIoPlugin: disconnect упал: {exc}")
            self._client = None
        ctx.log_info(f"RobotIoPlugin: shutdown (выполнено заданий: {self._reg.jobs_done})")

    # ------------------------------------------------------------------ #
    # PROCESS — приём заданий из pipeline (pass-through)
    # ------------------------------------------------------------------ #

    def process(self, items: list[dict]) -> list[dict]:
        """Положить задания из item[job_source] в очередь feeder; кадр — дальше."""
        for item in items:
            job = item.get(self._reg.job_source)
            if isinstance(job, dict) and "x_mm" in job and "y_mm" in job:
                self._enqueue_job(float(job["x_mm"]), float(job["y_mm"]))
        return items

    def _enqueue_job(self, x_mm: float, y_mm: float) -> bool:
        """Поставить задание в очередь со снимком энкодера (момент детекции)."""
        client = self._client
        if client is None or not client.is_connected:
            self._reg.last_error = "робот не подключён — задание отброшено"
            return False
        try:
            e_capture = client.read_encoder()
        except ModbusDriverError as exc:
            self._set_error(f"энкодер не прочитан: {exc}")
            return False
        self._queue.append((x_mm, y_mm, e_capture))
        self._reg.queue_len = len(self._queue)
        return True

    # ------------------------------------------------------------------ #
    # FEEDER (worker) — порт Console.feeder
    # ------------------------------------------------------------------ #

    def _feeder_loop(self, stop_event, pause_event) -> None:
        """Фон: подключение (throttled), телеметрия, подача заданий при free."""
        while not stop_event.is_set():
            if pause_event.is_set():
                time.sleep(0.1)
                continue
            time.sleep(self._reg.feed_poll_s)
            if not self._ensure_connected():
                continue
            self._publish_telemetry_maybe()
            if self._reg.manual_mode or not self._queue:
                continue
            try:
                if self._client.is_free():
                    job = self._queue.popleft() if self._queue else None
                    self._reg.queue_len = len(self._queue)
                    if job is not None:
                        self._deliver(job, stop_event)
            except ModbusDriverError as exc:
                self._set_error(f"feeder: {exc}")

    def _deliver(self, job: tuple[float, float, int], stop_event) -> None:
        """Отдать задание: send_job -> ждать приёма -> ждать завершения."""
        x_mm, y_mm, e_capture = job
        try:
            self._client.send_job(x_mm, y_mm, e_capture)
        except (RobotJobError, ModbusDriverError) as exc:
            self._reg.jobs_failed += 1
            self._set_error(f"send_job: {exc}")
            return
        self._reg.jobs_sent += 1
        if not self._wait(self._client.job_accepted, self._reg.accept_wait_s, stop_event):
            # робот не принял — вернуть в начало очереди (как в оригинале)
            self._queue.appendleft(job)
            self._reg.queue_len = len(self._queue)
            self._set_error("робот не принял задание — возвращено в очередь")
            return
        if not self._wait(self._client.is_free, self._reg.job_wait_s, stop_event):
            self._reg.jobs_failed += 1
            self._set_error("задание не завершилось вовремя")
            return
        self._reg.jobs_done += 1

    def _wait(self, condition, timeout: float, stop_event) -> bool:
        """Поллить условие до timeout (прерываемо stop_event)."""
        t_end = time.monotonic() + timeout
        while time.monotonic() < t_end:
            if stop_event.is_set():
                return False
            try:
                if condition():
                    return True
            except ModbusDriverError as exc:
                self._set_error(f"wait: {exc}")
                return False
            time.sleep(self._reg.feed_poll_s)
        return False

    # ------------------------------------------------------------------ #
    # Соединение / телеметрия
    # ------------------------------------------------------------------ #

    def _build_config(self) -> RobotConfig:
        r = self._reg
        return RobotConfig(
            host=r.host,
            port=r.port,
            unit_id=r.unit_id,
            timeout_sec=r.timeout_sec,
            word_order=r.word_order,
        )

    def _try_connect(self) -> bool:
        if self._client is None:
            return False
        ok = self._client.connect()
        self._reg.conn_state = "connected" if ok else "error"
        return ok

    def _ensure_connected(self) -> bool:
        """Гарантировать соединение: throttled-reconnect (реконнект — у владельца, не в sdk)."""
        if self._client is None:
            return False
        if self._client.is_connected:
            return True
        now = time.monotonic()
        if now - self._last_reconnect < _RECONNECT_THROTTLE_SEC:
            return False
        self._last_reconnect = now
        return self._try_connect()

    def _publish_telemetry_maybe(self) -> None:
        """Раз в telemetry_interval_s: телеметрия -> register + state-дерево."""
        now = time.monotonic()
        if now - self._last_telemetry < self._reg.telemetry_interval_s:
            return
        self._last_telemetry = now
        try:
            telemetry = self._client.read_telemetry()
            free = self._client.is_free()
            encoder = self._client.read_encoder()
        except ModbusDriverError as exc:
            self._set_error(f"телеметрия: {exc}")
            return
        self._reg.free = free
        self._reg.encoder = encoder
        self._reg.conn_state = "connected"
        if self._ctx.state_proxy is not None:
            self._ctx.state_proxy.merge(
                "robot/telemetry",
                {**telemetry.to_dict(), "free": free, "encoder": encoder, "queue_len": len(self._queue)},
            )

    def _set_error(self, message: str) -> None:
        self._reg.last_error = message
        self._ctx.log_error(f"RobotIoPlugin: {message}")

    # ------------------------------------------------------------------ #
    # КОМАНДЫ (round-trip из GUI/CLI)
    # ------------------------------------------------------------------ #

    def cmd_send_test_job(self, data: dict) -> dict:
        """Тестовое CVT-задание: {x, y} -> очередь feeder."""
        try:
            x_mm, y_mm = float(data["x"]), float(data["y"])
        except (KeyError, TypeError, ValueError):
            return {"status": "error", "message": "нужно: {x: float, y: float}"}
        ok = self._enqueue_job(x_mm, y_mm)
        return {"status": "ok" if ok else "error", "queue_len": len(self._queue), "error": self._reg.last_error}

    def cmd_abort(self, data: dict) -> dict:
        """Стоп робота: {mode: 1|2|3} (1=домой+цикл, 2=домой+выход, 3=на месте)."""
        mode = int(data.get("mode", 1))
        return self._safe_call(lambda: self._client.stop(mode), extra={"mode": mode})

    def cmd_set_mode(self, data: dict) -> dict:
        """Режим робота: {mode: cvt|draw}. Переключать только при free."""
        mode = str(data.get("mode", "cvt"))
        result = self._safe_call(lambda: self._client.set_mode(mode), extra={"mode": mode})
        if result["status"] == "ok":
            self._reg.mode = mode
        return result

    def cmd_set_servo(self, data: dict) -> dict:
        """Серво: {on: bool}."""
        on = bool(data.get("on", True))
        return self._safe_call(lambda: self._client.set_servo(on), extra={"on": on})

    def cmd_set_robot_config(self, data: dict) -> dict:
        """Конфиг робота (speed/home_*/place_*/pick_z/zone_*/grip_ms): {field: value, ...}."""
        fields = {k: v for k, v in data.items() if isinstance(v, (int, float))}
        if not fields:
            return {"status": "error", "message": "нет числовых полей конфига"}
        return self._safe_call(lambda: self._client.set_config(**fields), extra={"fields": fields})

    def cmd_get_robot_config(self, _data: dict) -> dict:
        """Прочитать конфиг-блок робота."""
        return self._safe_call(lambda: {"config": self._client.get_config()})

    def cmd_get_telemetry(self, _data: dict) -> dict:
        """Телеметрия по запросу (для round-trip из вкладки)."""
        return self._safe_call(
            lambda: {
                "telemetry": self._client.read_telemetry().to_dict(),
                "free": self._client.is_free(),
                "encoder": self._client.read_encoder(),
                "queue_len": len(self._queue),
            }
        )

    def cmd_read_echo(self, _data: dict) -> dict:
        """Эхо последнего принятого задания."""
        return self._safe_call(lambda: {"echo": self._client.read_echo().to_dict()})

    def cmd_set_manual_mode(self, data: dict) -> dict:
        """Ручной режим: {on: bool} — пауза авто-подачи (P2.5)."""
        self._reg.manual_mode = bool(data.get("on", True))
        return {"status": "ok", "manual_mode": self._reg.manual_mode}

    def cmd_clear_queue(self, _data: dict) -> dict:
        """Очистить очередь заданий."""
        dropped = len(self._queue)
        self._queue.clear()
        self._reg.queue_len = 0
        return {"status": "ok", "dropped": dropped}

    def _safe_call(self, call, extra: dict | None = None) -> dict[str, Any]:
        """Выполнить операцию с роботом, завернув ошибки в dict-ответ."""
        if self._client is None or not self._client.is_connected:
            return {"status": "error", "message": "робот не подключён"}
        try:
            result = call()
        except (ModbusDriverError, RobotJobError, ValueError, KeyError) as exc:
            self._set_error(str(exc))
            return {"status": "error", "message": str(exc), **(extra or {})}
        payload = result if isinstance(result, dict) else {}
        return {"status": "ok", **(extra or {}), **payload}
