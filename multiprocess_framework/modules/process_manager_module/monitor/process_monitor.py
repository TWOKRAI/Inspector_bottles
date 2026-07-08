"""Мониторинг состояний процессов. Реестр: get_all_process_data() -> ProcessData.

Расширено:
- Приём heartbeat-сообщений от дочерних процессов
- Определение статуса UNRESPONSIVE при отсутствии heartbeat
- Авто-рестарт crashed / unresponsive процессов по RestartPolicy
"""

from __future__ import annotations

import threading
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
        # Ф3.2: per-process ready-event — mp.Event не пиклится через Queue,
        # broadcast состояния обязан его исключать (как прочие сырые события).
        "ready_event",
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
        k: v for k, v in (dict(cust) if isinstance(cust, dict) else {}).items() if k not in _CUSTOM_EXCLUDE_KEYS
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
        # _monitoring — реальный run/pause gate цикла (loop его проверяет). stop()
        # ставит False → цикл паузится (НЕ убивает воркер), start() → True + resume.
        self._monitoring = False
        # Воркер state_monitor создаётся РОВНО один раз (первый start); повторные
        # start() (resume после паузы на replace_blueprint) лишь снимают паузу —
        # иначе плодились бы дубли воркера.
        self._worker_created = False

        # Heartbeat: время последнего heartbeat от каждого процесса
        self._last_heartbeat: dict[str, float] = {}

        # Статус воркеров: последние данные из heartbeat per process
        # Ключ — имя процесса, значение — dict[worker_name, worker_status_dict]
        self._workers_status: dict[str, dict] = {}

        # Время первого появления процесса в статусе "running" — для uptime.
        # Сбрасывается при остановке/удалении процесса.
        self._first_seen: dict[str, float] = {}

        # Авто-рестарт: счётчик попыток рестарта per process
        self._restart_counts: dict[str, int] = {}

        # Отложенные рестарты: {name: monotonic-время, когда пора}. Диспатчатся
        # из цикла (после backoff) IPC-командой в PM — НЕ исполняются на потоке
        # монитора (Task 3.1: гонка с apply_topology исключена).
        self._pending_restarts: dict[str, float] = {}

        # Замок текущей итерации цикла: stop(wait=True) дожидается его
        # освобождения — после возврата stop() ни одна проверка/рестарт
        # монитора не в полёте (синхронная пауза перед hot-swap).
        self._iteration_lock = threading.Lock()

        # Периодический полный broadcast: счётчик и интервал итераций
        self._full_broadcast_counter: int = 0
        self._full_broadcast_interval: int = 20  # каждые 20 итераций (~10с при poll_interval=0.5)

    def start(self):
        if self._monitoring:
            self.process._log_warning("Monitor already running")
            return

        # Resume после паузы (replace_blueprint глушит монитор на время горячей
        # замены процессов): перезапускаем heartbeat-таймер для уже известных
        # процессов. Иначе простой паузы (секунды на spawn/stop) засчитается как
        # пропущенные heartbeat → ложный UNRESPONSIVE → при disabled-policy
        # shutdown всей системы (крах GUI по SIGTERM), при enabled — авто-рестарт.
        if self._last_heartbeat:
            resume_ts = time.time()
            for name in self._last_heartbeat:
                self._last_heartbeat[name] = resume_ts

        self._monitoring = True

        # Воркер цикла создаём один раз; повторный start() — это resume (снятие
        # паузы через _monitoring), а не новый воркер.
        if not self._worker_created:
            self.process._log_info("Starting process state monitor")
            self._register_heartbeat_handler()
            self.process.worker_manager.create_worker(
                "state_monitor",
                self._monitoring_loop,
                ThreadConfig(priority=ThreadPriority.NORMAL),
                auto_start=True,
            )
            self._worker_created = True
        else:
            self.process._log_info("Resuming process state monitor")

    def stop(self, wait: bool = True, timeout: float = 10.0):
        """Пауза цикла (НЕ убийство воркера).

        ``_monitoring=False`` → цикл встаёт на idle и НЕ выполняет
        ``_check_heartbeats`` — на время hot-swap это исключает ложный
        UNRESPONSIVE по застывшим heartbeat.

        Task 3.1: пауза СИНХРОННАЯ — ``wait=True`` дожидается завершения
        текущей итерации (``_iteration_lock``). Раньше stop() был только
        флагом: итерация в полёте (включая авто-рестарт) продолжалась
        ПАРАЛЛЕЛЬНО с apply_topology и могла воскресить процесс старой
        топологии посреди замены.

        Args:
            wait: дождаться завершения текущей итерации цикла.
            timeout: максимум ожидания итерации (секунды).
        """
        if not self._monitoring:
            return
        self.process._log_info("Pausing process state monitor")
        self._monitoring = False
        if not wait:
            return
        acquired = self._iteration_lock.acquire(timeout=timeout)
        if acquired:
            self._iteration_lock.release()
        else:
            self.process._log_warning(
                f"Monitor: текущая итерация не завершилась за {timeout}с — пауза НЕ синхронна"
            )

    # ----------------------------------------------------------------
    # Heartbeat: приём сообщений
    # ----------------------------------------------------------------

    def _register_heartbeat_handler(self) -> None:
        """Зарегистрировать обработчик heartbeat в роутере ProcessManager-а.

        Сообщения с command='heartbeat' будут обработаны _on_heartbeat_received
        через стандартный event_dispatcher (вызывается из SystemThreads._message_processing_loop).
        """
        if not self.process.router_manager:
            self.process._log_warning("RouterManager недоступен — heartbeat handler не зарегистрирован")
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

        # Сохраняем данные о воркерах процесса (для legacy full-status broadcast).
        # Телеметрию (per-worker + агрегат fps/latency) в дерево здесь НЕ публикуем:
        # каждый процесс делает это сам (self-publish — ProcessHeartbeat.
        # _publish_metrics_to_tree). Heartbeat ProcessManager-у нужен только для
        # liveness/timeout и переходов paused/running. См.
        # plans/telemetry-self-publish-redesign.md (Task 2).
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
                self.process._log_debug(f"Heartbeat от '{sender}': статус обновлён {prev_status} → {reported_status}")

    def _publish_state(self, path: str, value: Any) -> None:
        """Опубликовать значение в общий StateStore (если доступен).

        Идёт локально через StateStoreManager ProcessManager (без IPC):
        handle_state_set → store.set → DeltaDispatcher → подписчики (GUI).
        store.set отдаёт дельту только при реальном изменении — спама нет.
        """
        ssm = getattr(self.process, "_state_store_manager", None)
        if ssm is None:
            return
        try:
            ssm.handle_state_set({"data": {"path": path, "value": value, "source": "ProcessMonitor"}})
        except Exception as exc:  # nosec B110 — телеметрия не критична
            self.process._log_debug(f"_publish_state('{path}') failed: {exc}")

    def _publish_uptime(self, all_states: dict[str, dict[str, Any]]) -> None:
        """Опубликовать uptime каждого running-процесса в StateStore.

        first_seen фиксируется при первом появлении статуса "running" и живёт,
        пока процесс не остановится/исчезнет → uptime = now - first_seen.
        """
        now = time.time()
        for pname, snap in all_states.items():
            status = snap.get("status", "unknown")
            if status == "running":
                self._first_seen.setdefault(pname, now)
                uptime = now - self._first_seen[pname]
                self._publish_state(f"processes.{pname}.state.uptime", round(uptime, 1))
            else:
                # Процесс не работает — сбрасываем точку отсчёта.
                self._first_seen.pop(pname, None)

    def _publish_health(self, all_states: dict[str, dict[str, Any]]) -> None:
        """Опубликовать сводное здоровье системы в StateStore (system.health.*).

        Источник для health-меток внизу вкладки «Процессы»:
        - ``system.health.active``  = число процессов в статусе "running".
        - ``system.health.avg_fps`` = среднее ``processes.{p}.state.fps`` по
          running-процессам. fps больше не агрегируется здесь из heartbeat —
          его публикует сам процесс (self-publish), а монитор лишь ЧИТАЕТ
          опубликованное из локального дерева. Нет ни одного fps — НЕ публикуем
          (карточка остаётся «—», не «0»). См. plans/telemetry-self-publish-redesign.md.
        - ``system.health.broken_wires`` = число оборванных wire-проводов (Ф3.5).
          Источник истины — ``ProcessManager._active_wires`` (заполняется
          ``wire.setup``; путь B — GUI ``connect_wire``). Провод broken, если его
          статус помечен ``"broken"`` (окно рестарта/switch) ИЛИ source/target не
          в числе running. При ЖИВОЙ топологии без проводов → 0 (не «константа»,
          а честный ноль). Публикация per-wire статусов — ``_publish_wires``.
        """
        running = [pname for pname, snap in all_states.items() if snap.get("status") == "running"]
        self._publish_state("system.health.active", len(running))

        # avg_fps: читаем self-опубликованный fps каждого running-процесса из
        # локального дерева (guard деления на ноль — не публикуем без данных).
        fps_values: list[float] = []
        ssm = getattr(self.process, "_state_store_manager", None)
        if ssm is not None:
            for pname in running:
                try:
                    resp = ssm.handle_state_get({"data": {"path": f"processes.{pname}.state.fps"}})
                    value = resp.get("value") if resp.get("status") == "ok" else None
                    if isinstance(value, (int, float)) and value > 0:
                        fps_values.append(float(value))
                except Exception:  # nosec B110 — телеметрия не критична
                    pass
        if fps_values:
            self._publish_state("system.health.avg_fps", round(sum(fps_values) / len(fps_values), 2))

        # broken_wires (Ф3.5): реальный счёт из PM._active_wires + per-wire статусы.
        broken_wires = self._publish_wires()
        self._publish_state("system.health.broken_wires", broken_wires)

    def _endpoint_alive(self, name: str) -> bool:
        """OS-liveness endpoint'а провода через ProcessRegistry (не status-снимок).

        Намеренно НЕ полагаемся на статус процесса из state-дерева: после
        graceful stop / restart монитор может не промотировать «stopped»→«running»
        (whitelist промоушена), из-за чего живой (is_alive) процесс ложно
        выглядел бы мёртвым endpoint'ом. Истина — ``proc.is_alive()`` (pid жив).
        """
        reg = getattr(self.process, "_process_registry", None)
        getp = getattr(reg, "get_process_by_name", None) if reg is not None else None
        if not callable(getp):
            return False
        try:
            proc = getp(name)
        except Exception:  # nosec B110 — liveness-проба не критична
            return False
        is_alive = getattr(proc, "is_alive", None)
        return bool(proc is not None and callable(is_alive) and is_alive())

    def _publish_wires(self) -> int:
        """Опубликовать per-wire статусы (``system.wires.<key>.status``) + счёт broken.

        Источник — ``ProcessManager._active_wires`` (wire_key → метаданные,
        заполняется ``wire.setup``). Провод считается ``broken``, если его
        сохранённый статус ``"broken"`` (окно рестарта/switch, honest-marking PM)
        ИЛИ хотя бы один endpoint (source/target) не ``is_alive`` (OS-liveness).
        Иначе ``pending`` (не активирован) либо ``active``.

        Guard'ы: ``_active_wires`` отсутствует / не dict (mock-PM, здоровая
        топология без проводов) → 0 без публикаций. Это сохраняет прежнее
        поведение «0 при живой топологии» — но теперь это ЧЕСТНЫЙ ноль, а не
        безусловная константа.

        Returns:
            Число оборванных проводов (для ``system.health.broken_wires``).
        """
        wires = getattr(self.process, "_active_wires", None)
        if not isinstance(wires, dict) or not wires:
            return 0
        broken = 0
        for wire_key, info in wires.items():
            if not isinstance(info, dict):
                continue
            src = info.get("source_process", "")
            tgt = info.get("target_process", "")
            endpoints_alive = self._endpoint_alive(src) and self._endpoint_alive(tgt)
            if info.get("status") == "broken" or not endpoints_alive:
                status = "broken"
                broken += 1
            elif info.get("status") == "pending":
                status = "pending"
            else:
                status = "active"
            self._publish_state(f"system.wires.{wire_key}.status", status)
        return broken

    # ----------------------------------------------------------------
    # Мониторинг: основной цикл
    # ----------------------------------------------------------------

    def _monitoring_loop(self, stop_event: Event, pause_event: Event):
        self.process._log_info("Process monitor loop started")
        while not stop_event.is_set():
            # _monitoring — пауза от stop() (hot-swap): цикл встаёт на idle,
            # НЕ выполняет _check_heartbeats → нет ложного UNRESPONSIVE во время
            # горячей замены. pause_event — пауза от worker_manager.
            if not self._monitoring or pause_event.is_set():
                time.sleep(0.1)
                continue
            # Итерация под замком: stop(wait=True) дожидается его освобождения —
            # синхронная пауза (Task 3.1). Хвостовой sleep — ВНЕ замка, чтобы
            # stop() не ждал poll_interval впустую.
            with self._iteration_lock:
                if self._monitoring and not pause_event.is_set():
                    self._run_iteration()
            time.sleep(self.poll_interval)
        self.process._log_info("Process monitor loop stopped")

    def _run_iteration(self) -> None:
        """Одна итерация мониторинга (вызывается под ``_iteration_lock``)."""
        try:
            if not self.process.shared_resources:
                return
            reg = self.process.shared_resources.process_state_registry
            if not reg:
                return
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
                self._first_seen.pop(pname, None)

            # Live-uptime процессов → StateStore (троттлится middleware до ~1 Гц).
            self._publish_uptime(all_states)

            # Сводное здоровье системы → StateStore (system.health.*).
            self._publish_health(all_states)

            # Проверка OS-liveness + heartbeat timeout + планирование рестартов
            self._check_heartbeats()

            # Отложенные рестарты, чей backoff истёк → IPC-команда в PM
            self._dispatch_due_restarts()

            # Периодический полный broadcast для новых подписчиков (GUI)
            self._full_broadcast_counter += 1
            if self._full_broadcast_counter >= self._full_broadcast_interval:
                self._full_broadcast_counter = 0
                self.broadcast_full_status()
        except Exception as e:
            self.process._log_error(f"Error in monitoring loop: {e}")

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

            # Процесс жив: повысить до "running" из любого pre-running статуса.
            # ВАЖНО: включаем "initializing"/"ready" — реестр спавна ставит процессам
            # "initializing" и сам не двигает дальше; без этого процесс навечно застревал
            # на "initializing" (heartbeat-переход не срабатывал) → GUI не видел "running".
            # НЕ перезаписываем "paused" — он управляется через heartbeat.status.
            prev = self.previous_states.get(proc.name)
            prev_status = (prev or {}).get("status", "unknown")
            if prev_status in ("created", "unknown", "", "initializing", "ready"):
                snap = {"status": "running", "metadata": {}, "custom": {}}
                self._handle_state_change(proc.name, prev, snap)
                self.previous_states[proc.name] = snap.copy()
                # Синхронизировать реестр: иначе следующий проход loop'а перечитает
                # старый "initializing" из registry и статус будет флапать.
                if self.process.shared_resources:
                    try:
                        psr = self.process.shared_resources.process_state_registry
                        if psr is not None and hasattr(psr, "update_state"):
                            psr.update_state(proc.name, status="running")
                    except Exception:  # nosec B110 — best-effort синхронизация реестра
                        pass

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
            except Exception:  # nosec B110 — best-effort обновление статуса в SR, сбой некритичен
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
            f"Process '{process_name}' не отвечает (heartbeat timeout: {elapsed:.1f}с > {self.heartbeat_timeout}с)"
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
            except Exception:  # nosec B110 — best-effort обновление статуса в SR, сбой некритичен
                pass

        # Авто-рестарт при unresponsive. При ВЫКЛЮЧЕННОЙ политике НЕ роняем всю
        # систему из-за одного unresponsive — это консистентно с обработкой crashed
        # (см. _check_process_alive: «Не останавливаем систему при crash одного
        # процесса»). Иначе транзиентный/ложный unresponsive (например сразу после
        # горячей замены, пока новый процесс не прислал первый heartbeat) каскадом
        # инициировал shutdown и ронял protected GUI (SIGTERM). Процесс остаётся
        # помеченным unresponsive (статус выставлен выше); восстановится по heartbeat.
        if self.restart_policy.enabled and self.restart_policy.restart_on_unresponsive:
            self._try_auto_restart(process_name, reason="unresponsive")
        elif not self.restart_policy.enabled:
            self.process._log_error(
                f"Process '{process_name}' unresponsive, авто-рестарт отключён — "
                f"оставлен в состоянии unresponsive (система не останавливается)"
            )

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

        # Protected-процессы (GUI, ProcessManager) НИКОГДА не авто-рестартим:
        # их жизненным циклом владеет launcher/shutdown, а terminate живого
        # protected (например ложный unresponsive после паузы монитора на
        # replace_blueprint) = крах ядра приложения (GUI получает SIGTERM).
        protected: set[str] = set()
        try:
            protected = self.process._get_protected_names()
        except Exception:  # nosec B110 — best-effort; при сбое не блокируем рестарт обычных процессов
            protected = set()
        if process_name in protected:
            self.process._log_warning(f"Process '{process_name}' protected — авто-рестарт ({reason}) пропущен")
            return

        count = self._restart_counts.get(process_name, 0)
        max_retries = self.restart_policy.max_retries

        if count >= max_retries:
            # Исчерпаны попытки — статус FAILED, больше не пытаемся
            self.process._log_error(
                f"Process '{process_name}' превысил лимит рестартов ({count}/{max_retries}), статус -> FAILED"
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
                except Exception:  # nosec B110 — best-effort обновление статуса в SR, сбой некритичен
                    pass
            return

        # Запланировать рестарт после backoff (Task 3.1): БЕЗ sleep и БЕЗ
        # прямого restart_process на потоке монитора — исполнение уйдёт
        # IPC-командой в PM (_dispatch_due_restarts), где оно сериализуется
        # с apply_topology на message_processor-потоке (гонка исключена).
        attempt = count + 1
        backoff = self.restart_policy.backoff_sec
        if process_name in self._pending_restarts:
            return  # уже запланирован
        self._restart_counts[process_name] = attempt
        self._pending_restarts[process_name] = time.monotonic() + backoff
        self.process._log_info(
            f"Авто-рестарт процесса '{process_name}' запланирован "
            f"(причина: {reason}, попытка {attempt}/{max_retries}, backoff: {backoff}с)"
        )

    def _dispatch_due_restarts(self) -> None:
        """Отправить в PM рестарты, чей backoff истёк (IPC, не прямой вызов).

        ``process.command {cmd: process.restart}`` в СОБСТВЕННУЮ очередь PM →
        message_processor-поток → CommandManager → PM.restart_process. На том
        же потоке исполняется topology.apply, поэтому рестарт НЕ может бежать
        параллельно с заменой топологии. Если имя заменено switch'ем до
        диспатча — cleanup уже вызвал forget_process и снял pending.
        """
        if not self._pending_restarts:
            return
        now = time.monotonic()
        due = [name for name, ts in self._pending_restarts.items() if ts <= now]
        for name in due:
            self._pending_restarts.pop(name, None)
            # Очищаем heartbeat перед рестартом — новый процесс пришлёт свой
            self._last_heartbeat.pop(name, None)
            try:
                comm = getattr(self.process, "communication", None)
                sent = bool(
                    comm.send_message(
                        self.process.name,
                        {
                            "type": "system",
                            "command": "process.command",
                            "sender": self.process.name,
                            "data": {"cmd": "process.restart", "process_name": name},
                        },
                    )
                ) if comm is not None else False
            except Exception as exc:
                sent = False
                self.process._log_error(f"Monitor: отправка рестарта '{name}' не удалась: {exc}")
            if sent:
                self.process._log_info(f"Monitor: рестарт '{name}' отправлен PM (вне потока монитора)")
            else:
                self.process._log_error(
                    f"Monitor: рестарт '{name}' НЕ отправлен — процесс остаётся в текущем статусе"
                )

    def reset_restart_count(self, process_name: str) -> None:
        """Сбросить счётчик рестартов для процесса.

        Вызывается когда процесс стабильно работает после рестарта,
        или при ручном вмешательстве оператора.
        """
        self._restart_counts.pop(process_name, None)

    def forget_process(self, process_name: str) -> None:
        """Забыть служебную историю имени при cleanup (hot-swap / удаление).

        Вызывается PM._cleanup_process_resources. Без этого новый процесс
        с тем же именем наследует чужой heartbeat-таймер, счётчик рестартов
        и previous_states: ложный UNRESPONSIVE сразу после switch и
        преждевременный FAILED после нескольких замен. Отложенный рестарт
        заменённого имени также отменяется (Task 3.1).
        """
        self._last_heartbeat.pop(process_name, None)
        self._restart_counts.pop(process_name, None)
        self._workers_status.pop(process_name, None)
        self._first_seen.pop(process_name, None)
        self.previous_states.pop(process_name, None)
        self._pending_restarts.pop(process_name, None)

    # ----------------------------------------------------------------
    # Полный broadcast статуса (для синхронизации с GUI)
    # ----------------------------------------------------------------

    def broadcast_full_status(self) -> None:
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
                "sender": self.process.name,
                "processes": all_status,
                "timestamp": time.time(),
            }
            self.process.communication.broadcast(msg, exclude_self=True)
        except Exception as exc:
            self.process._log_debug(f"broadcast_full_status ошибка: {exc}")

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
        # Live-статус процесса → StateStore (GUI карточки processes.X.state.status)
        self._publish_state(f"processes.{process_name}.state.status", new_status)
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
                "sender": self.process.name,
                "process_name": process_name,
                "old_status": old_status,
                "new_status": new_status,
                "state": enriched_state,
                "timestamp": time.time(),
            }
            sent = self.process.communication.broadcast(msg, exclude_self=True)
            if sent > 0:
                self.process._log_debug(f"Broadcasted status change for '{process_name}' to {sent} processes")
            else:
                self.process._log_warning(f"No processes received status change for '{process_name}'")
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
            "last_heartbeats": {name: round(time.time() - ts, 1) for name, ts in self._last_heartbeat.items()},
            "restart_counts": dict(self._restart_counts),
            "crashed_processes": [n for n, st in self.previous_states.items() if st.get("status") == "crashed"],
            "unresponsive_processes": [
                n for n, st in self.previous_states.items() if st.get("status") == "unresponsive"
            ],
            "failed_processes": [n for n, st in self.previous_states.items() if st.get("status") == "failed"],
        }
