"""Мониторинг состояний процессов. Реестр: get_all_process_data() -> ProcessData.

Расширено:
- Приём heartbeat-сообщений от дочерних процессов
- Определение статуса UNRESPONSIVE при отсутствии heartbeat
- Авто-рестарт crashed / unresponsive процессов по RestartPolicy
"""

from __future__ import annotations

import time
from multiprocessing import Event
from typing import Any

from ...worker_module import ThreadConfig, ThreadPriority
from ..core.restart_policy import RestartPolicy

_CUSTOM_EXCLUDE_KEYS = frozenset(
    {
        "stop_event",
        "pause_event",
        "error_manager",
        "system_ready_event",
    }
)


def _state_snapshot_from_process_data(process_data: Any) -> dict[str, Any] | None:
    if not process_data:
        return None
    status = getattr(process_data, "status", None)
    status_str = (
        status.value
        if status is not None and hasattr(status, "value")
        else (str(status) if status is not None else "unknown")
    )
    meta = getattr(process_data, "metadata", None) or {}
    cust = getattr(process_data, "custom", None) or {}
    safe_custom = {
        k: v
        for k, v in (dict(cust) if isinstance(cust, dict) else {}).items()
        if k not in _CUSTOM_EXCLUDE_KEYS
    }
    return {
        "status": status_str,
        "metadata": dict(meta) if isinstance(meta, dict) else {},
        "custom": safe_custom,
    }


class ProcessMonitor:
    """Монитор процессов: отслеживание состояний, heartbeat, авто-рестарт.

    Args:
        process_manager_process: Ссылка на ProcessManagerProcess (оркестратор)
        poll_interval: Интервал опроса состояний (секунды)
        heartbeat_timeout: Таймаут heartbeat — если процесс не присылал
            heartbeat дольше этого времени, он считается UNRESPONSIVE
        restart_policy: Политика авто-рестарта (None = default RestartPolicy)
    """

    def __init__(
        self,
        process_manager_process,
        poll_interval: float = 0.5,
        heartbeat_timeout: float = 15.0,
        restart_policy: RestartPolicy | None = None,
    ):
        self.process = process_manager_process
        self.poll_interval = poll_interval
        self.heartbeat_timeout = heartbeat_timeout
        self.restart_policy = restart_policy or RestartPolicy()
        self.previous_states: dict[str, dict[str, Any]] = {}
        self._monitoring = False

        # Heartbeat: время последнего heartbeat от каждого процесса
        self._last_heartbeat: dict[str, float] = {}

        # Статус воркеров: последние данные из heartbeat per process
        # Ключ — имя процесса, значение — dict[worker_name, worker_status_dict]
        self._workers_status: dict[str, dict] = {}

        # Авто-рестарт: счётчик попыток рестарта per process
        self._restart_counts: dict[str, int] = {}

        # Периодический полный broadcast: счётчик и интервал итераций
        self._full_broadcast_counter: int = 0
        self._full_broadcast_interval: int = 20  # каждые 20 итераций (~10с при poll_interval=0.5)

    def start(self):
        if self._monitoring:
            self.process._log_warning("Monitor already running")
            return
        self.process._log_info("Starting process state monitor")

        # Регистрируем обработчик heartbeat-сообщений на роутере ProcessManager-а
        self._register_heartbeat_handler()

        self.process.worker_manager.create_worker(
            "state_monitor",
            self._monitoring_loop,
            ThreadConfig(priority=ThreadPriority.NORMAL),
            auto_start=True,
        )
        self._monitoring = True

    def stop(self):
        if not self._monitoring:
            return
        self.process._log_info("Stopping process state monitor")
        self._monitoring = False

    # ----------------------------------------------------------------
    # Heartbeat: приём сообщений
    # ----------------------------------------------------------------

    def _register_heartbeat_handler(self) -> None:
        """Зарегистрировать обработчик heartbeat в роутере ProcessManager-а.

        Сообщения с command='heartbeat' будут обработаны _on_heartbeat_received
        через стандартный message_dispatcher (вызывается из SystemThreads._message_processing_loop).
        """
        if not self.process.router_manager:
            self.process._log_warning(
                "RouterManager недоступен — heartbeat handler не зарегистрирован"
            )
            return
        self.process.router_manager.register_message_handler(
            "heartbeat",
            self._on_heartbeat_received,
            expects_full_message=True,
        )
        self.process._log_debug("Heartbeat handler зарегистрирован в роутере")

    def _on_heartbeat_received(self, msg: dict) -> None:
        """Callback: вызывается при получении heartbeat-сообщения от дочернего процесса.

        Помимо обновления таймера heartbeat, обрабатывает поле status:
        - "paused"  → процесс сообщает о паузе; обновляем previous_states и
                      рассылаем status_changed чтобы GUI отобразил жёлтый цвет
        - "running" → процесс вернулся из паузы; аналогично обновляем статус
        """
        sender = msg.get("sender")
        ts = msg.get("timestamp")
        if not sender:
            return
        self._last_heartbeat[sender] = ts if isinstance(ts, (int, float)) else time.time()

        # Сохраняем данные о воркерах процесса
        workers = msg.get("workers_status")
        if workers and isinstance(workers, dict):
            self._workers_status[sender] = workers

        # Обрабатываем статус из heartbeat (paused / running)
        reported_status = msg.get("status")
        if reported_status in ("paused", "running"):
            prev = self.previous_states.get(sender)
            prev_status = (prev or {}).get("status", "unknown")
            # Обновляем только если статус реально изменился
            if prev_status != reported_status:
                snap = {"status": reported_status, "metadata": {}, "custom": {}}
                self._handle_state_change(sender, prev, snap)
                self.previous_states[sender] = snap.copy()
                self.process._log_debug(
                    f"Heartbeat от '{sender}': статус обновлён {prev_status} → {reported_status}"
                )

    # ----------------------------------------------------------------
    # Мониторинг: основной цикл
    # ----------------------------------------------------------------

    def _monitoring_loop(self, stop_event: Event, pause_event: Event):
        self.process._log_info("Process monitor loop started")
        while not stop_event.is_set():
            if pause_event.is_set():
                time.sleep(0.1)
                continue
            try:
                if not self.process.shared_resources:
                    time.sleep(self.poll_interval)
                    continue
                reg = self.process.shared_resources.process_state_registry
                if not reg:
                    time.sleep(self.poll_interval)
                    continue
                all_processes = reg.get_all_process_data()
                all_states: dict[str, dict[str, Any]] = {}
                for name, pd in all_processes.items():
                    snap = _state_snapshot_from_process_data(pd)
                    if snap is not None:
                        all_states[name] = snap
                for pname, cur in all_states.items():
                    prev = self.previous_states.get(pname)
                    if prev != cur:
                        self._handle_state_change(pname, prev, cur)
                        self.previous_states[pname] = cur.copy()
                cur_names = set(all_states.keys())
                for pname in set(self.previous_states.keys()) - cur_names:
                    self.process._log_info(f"Process removed: {pname}")
                    self.previous_states.pop(pname, None)

                # Проверка OS-liveness + heartbeat timeout + авто-рестарт
                self._check_heartbeats()

                # Периодический полный broadcast для новых подписчиков (GUI)
                self._full_broadcast_counter += 1
                if self._full_broadcast_counter >= self._full_broadcast_interval:
                    self._full_broadcast_counter = 0
                    self._broadcast_full_status()

                time.sleep(self.poll_interval)
            except Exception as e:
                self.process._log_error(f"Error in monitoring loop: {e}")
                time.sleep(self.poll_interval)
        self.process._log_info("Process monitor loop stopped")

    # ----------------------------------------------------------------
    # Проверка liveness: OS + heartbeat timeout
    # ----------------------------------------------------------------

    def _check_heartbeats(self) -> None:
        """Liveness-проверка процессов.

        1. OS-уровень: неживой процесс без актуального state -> stopped/crashed
        2. Heartbeat-уровень: живой процесс без heartbeat дольше timeout -> UNRESPONSIVE
        3. Авто-рестарт crashed / unresponsive процессов по RestartPolicy
        """
        if not hasattr(self.process, "_process_registry"):
            return

        now = time.time()

        for proc in self.process._process_registry.os_processes:
            if not proc.is_alive():
                self._handle_dead_process(proc)
                continue

            # Процесс жив: обновить статус если он был "created" или "unknown"
            # Важно: НЕ перезаписывать "paused" — он управляется через heartbeat.status
            prev = self.previous_states.get(proc.name)
            prev_status = (prev or {}).get("status", "unknown")
            if prev_status in ("created", "unknown", ""):
                snap = {"status": "running", "metadata": {}, "custom": {}}
                self._handle_state_change(proc.name, prev, snap)
                self.previous_states[proc.name] = snap.copy()

            # Проверяем heartbeat
            self._check_heartbeat_timeout(proc.name, now)

    def _handle_dead_process(self, proc) -> None:
        """Обработка мёртвого OS-процесса: обновить статус, запустить авто-рестарт."""
        exitcode = proc.exitcode
        prev = self.previous_states.get(proc.name)
        prev_status = (prev or {}).get("status", "unknown")

        # Не обрабатываем повторно уже зафиксированные терминальные статусы
        if prev_status in ("stopped", "error", "crashed", "failed"):
            return

        # Процесс зарегистрирован но не стартован: pid=None, exitcode=None
        # Это не crash — процесс просто ещё не запускался (created, ждёт start)
        if proc.pid is None and exitcode is None:
            if prev_status not in ("created",):
                snap = {"status": "created", "exitcode": None, "metadata": {}, "custom": {}}
                self._handle_state_change(proc.name, prev, snap)
                self.previous_states[proc.name] = snap.copy()
            return

        new_status = "stopped" if exitcode == 0 else "crashed"

        if new_status == "crashed":
            self.process._log_warning(f"Process '{proc.name}' crashed (exitcode={exitcode})")

        snap = {
            "status": new_status,
            "exitcode": exitcode,
            "metadata": {},
            "custom": {},
        }
        self._handle_state_change(proc.name, prev, snap)
        self.previous_states[proc.name] = snap.copy()

        # Обновить статус в shared_resources
        if self.process.shared_resources:
            try:
                psr = self.process.shared_resources.process_state_registry
                if psr is not None and hasattr(psr, "update_state"):
                    psr.update_state(proc.name, status=new_status)
            except Exception:
                pass

        # Авто-рестарт при crash или логирование
        if new_status == "crashed":
            if self.restart_policy.enabled and self.restart_policy.restart_on_crash:
                self._try_auto_restart(proc.name, reason="crashed")
            else:
                # Не останавливаем систему при crash одного процесса —
                # динамически созданные процессы могут падать без последствий.
                # Система останавливается только по явной команде system.shutdown.
                self.process._log_error(
                    f"Process '{proc.name}' crashed (exitcode={proc.exitcode}), "
                    f"авто-рестарт отключён — процесс оставлен в состоянии crashed"
                )

    def _check_heartbeat_timeout(self, process_name: str, now: float) -> None:
        """Проверить heartbeat timeout для живого процесса.

        Процесс со статусом "paused" НЕ считается UNRESPONSIVE:
        heartbeat_sender продолжает работать (SYSTEM воркер, не паузится),
        поэтому таймер обновляется — но явная проверка исключает ложные срабатывания
        в случае задержек IPC.
        """
        prev_status = (self.previous_states.get(process_name) or {}).get("status", "unknown")

        # Не проверяем heartbeat для процессов, которые ещё не running/ready/paused
        # "paused" — non-terminal статус, heartbeat продолжает идти (SYSTEM воркер не паузится)
        if prev_status not in ("running", "ready", "paused"):
            return

        last_hb = self._last_heartbeat.get(process_name)

        # Если heartbeat ещё ни разу не приходил — даём grace period от начала мониторинга
        if last_hb is None:
            return

        elapsed = now - last_hb
        if elapsed <= self.heartbeat_timeout:
            return

        # Heartbeat timeout — процесс UNRESPONSIVE
        # Не обрабатываем повторно если уже UNRESPONSIVE / failed
        if prev_status in ("unresponsive", "failed"):
            return

        self.process._log_warning(
            f"Process '{process_name}' не отвечает "
            f"(heartbeat timeout: {elapsed:.1f}с > {self.heartbeat_timeout}с)"
        )

        snap = {
            "status": "unresponsive",
            "metadata": {},
            "custom": {"heartbeat_elapsed": round(elapsed, 2)},
        }
        prev = self.previous_states.get(process_name)
        self._handle_state_change(process_name, prev, snap)
        self.previous_states[process_name] = snap.copy()

        # Обновить статус в shared_resources
        if self.process.shared_resources:
            try:
                psr = self.process.shared_resources.process_state_registry
                if psr is not None and hasattr(psr, "update_state"):
                    psr.update_state(process_name, status="unresponsive")
            except Exception:
                pass

        # Авто-рестарт при unresponsive или полная остановка
        if self.restart_policy.enabled and self.restart_policy.restart_on_unresponsive:
            self._try_auto_restart(process_name, reason="unresponsive")
        elif not self.restart_policy.enabled:
            self.process._log_error(
                f"Process '{process_name}' unresponsive, авто-рестарт отключён — останавливаю систему"
            )
            self.process._stop_requested = True

    # ----------------------------------------------------------------
    # Авто-рестарт
    # ----------------------------------------------------------------

    def _try_auto_restart(self, process_name: str, reason: str) -> None:
        """Попытка авто-рестарта процесса с учётом RestartPolicy.

        Args:
            process_name: Имя процесса для рестарта
            reason: Причина рестарта (crashed / unresponsive)
        """
        if not self.restart_policy.enabled:
            return

        count = self._restart_counts.get(process_name, 0)
        max_retries = self.restart_policy.max_retries

        if count >= max_retries:
            # Исчерпаны попытки — статус FAILED, больше не пытаемся
            self.process._log_error(
                f"Process '{process_name}' превысил лимит рестартов "
                f"({count}/{max_retries}), статус -> FAILED"
            )
            snap = {
                "status": "failed",
                "metadata": {"restart_attempts": count, "last_reason": reason},
                "custom": {},
            }
            prev = self.previous_states.get(process_name)
            self._handle_state_change(process_name, prev, snap)
            self.previous_states[process_name] = snap.copy()

            if self.process.shared_resources:
                try:
                    psr = self.process.shared_resources.process_state_registry
                    if psr is not None and hasattr(psr, "update_state"):
                        psr.update_state(process_name, status="failed")
                except Exception:
                    pass
            return

        # Выполняем рестарт с backoff
        attempt = count + 1
        backoff = self.restart_policy.backoff_sec
        self.process._log_info(
            f"Авто-рестарт процесса '{process_name}' "
            f"(причина: {reason}, попытка {attempt}/{max_retries}, "
            f"backoff: {backoff}с)"
        )
        time.sleep(backoff)

        # Очищаем heartbeat перед рестартом — новый процесс пришлёт свой
        self._last_heartbeat.pop(process_name, None)

        try:
            success = self.process.restart_process(process_name)
            if success:
                self._restart_counts[process_name] = attempt
                self.process._log_info(
                    f"Process '{process_name}' успешно перезапущен (попытка {attempt}/{max_retries})"
                )
            else:
                self._restart_counts[process_name] = attempt
                self.process._log_error(
                    f"Не удалось перезапустить процесс '{process_name}' "
                    f"(попытка {attempt}/{max_retries})"
                )
        except Exception as exc:
            self._restart_counts[process_name] = attempt
            self.process._log_error(f"Ошибка при авто-рестарте '{process_name}': {exc}")

    def reset_restart_count(self, process_name: str) -> None:
        """Сбросить счётчик рестартов для процесса.

        Вызывается когда процесс стабильно работает после рестарта,
        или при ручном вмешательстве оператора.
        """
        self._restart_counts.pop(process_name, None)

    # ----------------------------------------------------------------
    # Полный broadcast статуса (для синхронизации с GUI)
    # ----------------------------------------------------------------

    def _broadcast_full_status(self) -> None:
        """Бродкаст текущего статуса всех процессов.

        Используется для синхронизации с подписчиками, которые подключились
        после начала мониторинга (например GUI).
        """
        try:
            if not self.process.router_manager:
                return
            # Собрать текущие статусы из ProcessStatusMonitor
            all_status: dict = {}
            if hasattr(self.process, "_status"):
                all_status = self.process._status.get_all_status()

            # Обогатить конфигом если доступен
            if hasattr(self.process, "_process_configs"):
                for name, data in all_status.items():
                    cfg = self.process._process_configs.get(name, {})
                    if cfg:
                        data["class_path"] = cfg.get("class", "")
                        data["priority"] = cfg.get("priority", "normal")

            # Добавить данные о воркерах в snapshot каждого процесса
            for name, data in all_status.items():
                workers = self._workers_status.get(name)
                if workers:
                    data["workers"] = workers

            msg = {
                "type": "system",
                "subtype": "process_full_status",
                "sender": self.process.name,
                "processes": all_status,
                "timestamp": time.time(),
            }
            self.process.communication.broadcast(msg, exclude_self=True)
        except Exception as exc:
            self.process._log_debug(f"_broadcast_full_status ошибка: {exc}")

    # ----------------------------------------------------------------
    # Обработка изменений состояния
    # ----------------------------------------------------------------

    def _handle_state_change(
        self,
        process_name: str,
        previous_state: dict[str, Any] | None,
        current_state: dict[str, Any],
    ):
        cur_s = current_state.get("status", "unknown")
        prev_s = previous_state.get("status", "unknown") if previous_state else None
        if prev_s != cur_s:
            self.process._log_info(f"Process '{process_name}' status changed: {prev_s} -> {cur_s}")
            self._broadcast_status_change(process_name, prev_s, cur_s, current_state)

    def _broadcast_status_change(
        self,
        process_name: str,
        old_status: str | None,
        new_status: str,
        current_state: dict[str, Any],
    ):
        try:
            if not self.process.router_manager:
                return

            # Обогащаем state данными о воркерах процесса
            enriched_state = dict(current_state)
            workers = self._workers_status.get(process_name)
            if workers:
                enriched_state["workers"] = workers

            msg = {
                "type": "system",
                "subtype": "process_status_changed",
                "sender": self.process.name,
                "process_name": process_name,
                "old_status": old_status,
                "new_status": new_status,
                "state": enriched_state,
                "timestamp": time.time(),
            }
            sent = self.process.communication.broadcast(msg, exclude_self=True)
            if sent > 0:
                self.process._log_debug(
                    f"Broadcasted status change for '{process_name}' to {sent} processes"
                )
            else:
                self.process._log_warning(
                    f"No processes received status change for '{process_name}'"
                )
        except Exception as e:
            self.process._log_error(f"Failed to broadcast status change: {e}")

    # ----------------------------------------------------------------
    # Статистика
    # ----------------------------------------------------------------

    def get_stats(self) -> dict[str, Any]:
        return {
            "monitoring": self._monitoring,
            "tracked_processes": len(self.previous_states),
            "poll_interval": self.poll_interval,
            "heartbeat_timeout": self.heartbeat_timeout,
            "restart_policy": self.restart_policy.model_dump(),
            "last_heartbeats": {
                name: round(time.time() - ts, 1) for name, ts in self._last_heartbeat.items()
            },
            "restart_counts": dict(self._restart_counts),
            "crashed_processes": [
                n for n, st in self.previous_states.items() if st.get("status") == "crashed"
            ],
            "unresponsive_processes": [
                n for n, st in self.previous_states.items() if st.get("status") == "unresponsive"
            ],
            "failed_processes": [
                n for n, st in self.previous_states.items() if st.get("status") == "failed"
            ],
        }
