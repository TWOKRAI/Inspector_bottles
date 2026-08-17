"""ProcessHeartbeat — отправка периодических heartbeat-сообщений ProcessManager-у."""

from __future__ import annotations

import time
from typing import TYPE_CHECKING, Any, Callable

from ...observability_declarations import declare_metric

if TYPE_CHECKING:
    pass

# Ф8.1: `shm` объявляется здесь, потому что её счёт заказывает `_publish_telemetry_to_tree`
# в этом файле. Остальные четыре — у `telemetry.py`, где собираются они. Каталог
# перестал быть кортежем-литералом в configs/, и владение метрикой теперь совпадает
# с местом её вычисления, а не держится совпадением имени.
#
# Импорт на уровне модуля, а не ленивый, как соседи: ленивый объявил бы метрику
# только после первого вызова публикатора, то есть каталог отвечал бы на вопрос
# «что бывает» уже после того, как по нему приняли решение.
METRIC_SHM = declare_metric("shm", owner=__name__)

#: Сколько отсеянных уровней перечислять в ОДНОЙ строке WARNING (ревью З2).
#: Голос обязан назвать виновника, а не воспроизвести его вход: 5000 отсеянных
#: имён давали строку в 289 107 символов. Хвост «…и ещё M» сохраняет масштаб.
_REJECTION_VOICE_LIMIT = 10


class ProcessHeartbeat:
    """Heartbeat sender через IProcessServices.

    Отправляет периодические heartbeat-сообщения в ProcessManager
    для мониторинга состояния процесса.

    Task 1.2 — ДВА независимых частотных контура в одном воркере:
      - **heartbeat-СООБЩЕНИЕ** к ``ProcessManager`` (liveness для ``ProcessMonitor``) —
        строго каждые ``heartbeat_interval`` секунд (``self._interval``). Эта частота
        НЕ меняется телеметрийным контрактом — иначе ложные «process dead»;
      - **телеметрийная публикация** в дерево StateStore — каждый ``_telemetry_tick()``
        (``min(heartbeat_interval, telemetry.publish.tick_sec)``). Управляется контрактом
        ``TelemetryPublishConfig.tick_sec`` (boot + runtime), а не захардкоженным 5.0с.

    Воркер тикает по МЕНЬШЕМУ из двух интервалов; heartbeat-сообщение и «хозяйственные»
    self-publish'ы (health/observability/GC) выходят по расписанию liveness (счётчик по
    времени), а телеметрия — каждый тик (per-метрика rate-limit держит ``TelemetryGate``).
    ``tick_sec=None`` → тик = ``heartbeat_interval`` → оба контура совпадают → поведение
    бит-в-бит прежнее (backward-compat).
    """

    def __init__(self, services: Any, *, clock: Callable[[], float] = time.monotonic) -> None:
        """
        Args:
            services: объект удовлетворяющий IProcessServices
            clock: монотонный источник времени для ПЛАНИРОВАНИЯ (heartbeat-расписание +
                gate). По умолчанию ``time.monotonic``; инъекция — для fake-clock тестов
                каденции. Wall-clock ``timestamp`` в heartbeat-сообщении остаётся
                ``time.time`` (реальное время для мониторинга).
        """
        self._services = services
        self._interval: float = 5.0
        self._clock = clock
        # Task 1.2: монотонная метка последней ОТПРАВКИ heartbeat-сообщения. None → ещё
        # не слали (первый тик всегда шлёт — паритет с прежним «send на первой итерации»).
        self._last_heartbeat_sent: float | None = None
        # PC 1.2: publisher-gate телеметрии. None → гейт неактивен (нет секции
        # telemetry.publish в конфиге) → все метрики каждый тик (обратная совместимость).
        self._telemetry_gate: Any = None
        # Task 5.8: запущен ли воркер такта. Единственный честный ответ на вопрос
        # «сработает ли авто-возврат TTL» — подметальщик живёт на этом такте, и
        # процесс без него срок принимает, но не исполняет.
        self._started: bool = False
        # Р3.5-11: пары (имя, публикатор), про отсев которых уже сказано (чужое
        # имя либо имя, не объявленное никем). Голос один раз на ПАРУ — тик идёт
        # секундами (см. _warn_rejected_levels).
        self._warned_rejected_levels: set[tuple[str, str]] = set()

    def start(self) -> None:
        """Создать и запустить heartbeat воркер если включён в конфиге."""
        interval = self._services.get_config("heartbeat_interval", 5.0)
        try:
            interval = float(interval)
        except (TypeError, ValueError):
            interval = 5.0

        if interval <= 0:
            _log = getattr(self._services, "log_debug", self._services.log_info)
            _log("Heartbeat отключён (heartbeat_interval <= 0)", module="heartbeat")
            return

        if not self._services.worker_manager:
            return

        from ...worker_module import ThreadConfig, ThreadPriority, WorkerType

        self._interval = interval
        # PC 1.2: собрать publisher-gate из секции telemetry.publish (если задана).
        self._telemetry_gate = self._build_telemetry_gate()
        self._services.worker_manager.create_worker(
            "heartbeat_sender",
            self._loop,
            # worker_type=SYSTEM — не косметика, а единственное, что выводит этот
            # воркер из-под ``worker.pause_all``: guard в ``pause_all_workers``
            # сравнивает именно ``WorkerType.SYSTEM`` (worker_manager.py:269-272),
            # а реестр берёт тип из конфига (worker_registry.py:70). До 2026-08-07
            # тип здесь не передавался вовсе, то есть был APPLICATION, и пауза
            # процесса глушила его вместе с прикладными воркерами: heartbeat
            # замолкал → ProcessMonitor объявлял процесс UNRESPONSIVE → супервизия
            # рестартила его → флап ``unresponsive ↔ running`` каждые ~5 с.
            # Приоритет остаётся BACKGROUND: SYSTEM здесь про НАЗНАЧЕНИЕ воркера
            # (внутренний механизм, не прикладная задача), а не про планировщик.
            ThreadConfig(priority=ThreadPriority.BACKGROUND, worker_type=WorkerType.SYSTEM),
            auto_start=True,
        )
        self._started = True
        _log = getattr(self._services, "log_debug", self._services.log_info)
        _log(
            f"Heartbeat воркер запущен (interval={interval}с)",
            module="heartbeat",
        )

    def is_running(self) -> bool:
        """Идёт ли такт (Task 5.8: от него зависит исполнение сроков L3).

        Отвечает на «воркер создан», а не «поток прямо сейчас в цикле»: между
        ними разница только на teardown, где спрашивать уже некому. Все ветки
        раннего выхода :meth:`start` (интервал ≤ 0, нет worker_manager) оставляют
        ``False`` — а именно они и означают процесс без авто-возврата.
        """
        return self._started

    def _loop(self, stop_event, pause_event) -> None:
        """Цикл: телеметрия по ``_telemetry_tick``, heartbeat-сообщение по ``heartbeat_interval``.

        Task 1.2: воркер тикает по МЕНЬШЕМУ из двух интервалов. На каждом тике:
          - **телеметрия** (метрики/SHM-счётчики) публикуется в дерево — ``TelemetryGate``
            держит per-метрика rate-limit, поэтому «лишние» тики не грузят дерево;
          - **heartbeat-сообщение + хозяйственные self-publish'ы** (health/observability/GC)
            выходят только когда наступает срок liveness (``_heartbeat_due``) — их частота
            равна ``heartbeat_interval`` НЕЗАВИСИМО от телеметрийного тика (инвариант: не
            дать ``ProcessMonitor`` ложно счесть процесс мёртвым).

        ``tick_sec=None`` → тик = ``heartbeat_interval`` → ``_heartbeat_due`` истинно каждый
        тик → структура и каденция бит-в-бит прежние.
        """
        while not stop_event.is_set():
            if pause_event.is_set():
                time.sleep(0.1)
                continue
            # Тик читаем в начале итерации: reconfigure_telemetry() мог живьём сменить
            # tick_sec (перевзвод интервала ожидания применяется со следующего тика).
            tick = self._telemetry_tick()
            try:
                now = self._clock()
                # Снимок воркеров нужен И телеметрии, И (при наступлении срока)
                # heartbeat-сообщению — берём один раз за тик.
                workers = self._collect_workers()

                # --- Телеметрия (каждый тик; gate rate-limit'ит per-метрика) ---
                # PC 3.1: ссылку на gate читаем в ЛОКАЛЬНУЮ переменную ОДИН раз за тик —
                # reconfigure_telemetry() может атомарно подменить self._telemetry_gate
                # из потока диспетчера команд. Локальная ссылка гарантирует, что на этом
                # тике мы работаем с одним и тем же gate целиком (старым/новым/None), а не
                # с частично подменённым состоянием. None → гейт неактивен → все метрики.
                gate = self._telemetry_gate
                allowed_metrics = gate.due_metrics() if gate is not None else None
                # Self-publish телеметрии процесса напрямую в дерево StateStore:
                # воркеры + агрегат + shm + уровни плагинов ОДНИМ merge (Р3.5-12).
                self._publish_telemetry_to_tree(workers, allowed_metrics)

                # --- Heartbeat-сообщение + хозяйственные self-publish'ы (частота liveness) ---
                if self._heartbeat_due(now, tick):
                    # Liveness-сообщение к ProcessMonitor — строго раз в heartbeat_interval.
                    self._send_heartbeat(workers)

                    # Self-publish здоровья процесса (Ф2 Task 2.1) — тот же канал.
                    # health публикуется даже без воркеров и только при изменениях
                    # (take_dirty) — естественный rate-limit на такт HB.
                    self._publish_health_to_tree()

                    # Дренаж ObservabilityHub процесса (Ф5.16): log/stats-буфер hub'а
                    # → реальные менеджеры адаптером. error/critical идут мимо буфера
                    # (write-through), здесь их нет. Прецедент — health self-publish 2.1.
                    self._drain_observability()

                    # Task 5.8: вернуть рантайм-правки наблюдаемости, чей срок вышел.
                    # Тот же такт и та же роль, что у дренажа выше: хозяйственное
                    # дело процесса, которому не нужен собственный поток.
                    self._sweep_observability_session()

                    # Ф8.5 (Р-8.5-В): удалить документы с истёкшим сроком. Четвёртое
                    # хозяйственное дело того же такта; сам вызов не чаще
                    # purge_interval_sec, то есть на подавляющем большинстве тиков
                    # это один if по атрибуту процесса.
                    self._sweep_documents()

                    # Ф5.2: ретеншен истории наблюдаемости. Пятое хозяйственное дело
                    # того же такта и по той же причине: с приходом лог-плоскости в
                    # стор безлимитная таблица стала бы инцидентом 645 МБ в SQLite.
                    self._sweep_observability_history()

                    # Ф7 G.9(a) H-ревью: pump scheduled-GC. Heartbeat — периодический
                    # BACKGROUND-тик вне hot-path кадра → законная «пауза» для явной сборки.
                    # Без этого pump FW_GC_SCHEDULED отключил бы авто-GC НАВСЕГДА (сборки
                    # не происходило бы → утечка). No-op при флаге off (бит-в-бит).
                    self._pump_scheduled_gc()

                    self._last_heartbeat_sent = now
            except Exception as exc:
                _log = getattr(self._services, "log_debug", self._services.log_info)
                _log(f"Не удалось отправить heartbeat: {exc}", module="heartbeat")
            # Ожидание с проверкой stop_event для быстрого завершения
            stop_event.wait(timeout=tick)

    def _telemetry_tick(self) -> float:
        """Эффективный интервал тика воркера, сек (Task 1.2).

        ``min(heartbeat_interval, telemetry.publish.tick_sec)``: телеметрия не может
        выходить чаще ``tick_sec``, а heartbeat-сообщение требует тика не реже
        ``heartbeat_interval``. Gate неактивен / ``tick_sec`` не задан (``None``/≤0) →
        ``heartbeat_interval`` (backward-compat: прежние 5.0с). Читается каждую итерацию
        ``_loop`` → рантайм-смена ``tick_sec`` через ``reconfigure_telemetry`` подхватывается
        на следующем тике (перевзвод интервала ожидания).
        """
        gate = self._telemetry_gate
        if gate is not None:
            cfg = getattr(gate, "config", None)
            tick_sec = getattr(cfg, "tick_sec", None) if cfg is not None else None
            if isinstance(tick_sec, (int, float)) and tick_sec > 0:
                return min(self._interval, float(tick_sec))
        return self._interval

    def _heartbeat_due(self, now: float, tick: float) -> bool:
        """Пора ли слать heartbeat-СООБЩЕНИЕ (liveness) на этом тике (Task 1.2).

        Инвариант: частота heartbeat-сообщений = ``heartbeat_interval`` НЕЗАВИСИМО от
        телеметрийного тика (иначе ProcessMonitor ложно счёл бы процесс мёртвым).

          - ``tick >= self._interval`` (``tick_sec`` не задан/не меньше heartbeat) → тик
            И ЕСТЬ heartbeat-такт → шлём каждый тик (бит-в-бит прежнее поведение);
          - телеметрия быстрее heartbeat → шлём по расписанию: прошло ≥ ``heartbeat_interval``
            с прошлой отправки. Порог с запасом ``tick/2`` поглощает джиттер планировщика
            (иначе тик, пришедший на ε раньше срока, отложил бы отправку на целый тик и
            эффективная частота heartbeat просела бы вдвое);
          - ``_last_heartbeat_sent is None`` → ещё не слали → первый тик всегда шлёт
            (паритет с прежним «send на первой итерации»).
        """
        if tick >= self._interval:
            return True
        if self._last_heartbeat_sent is None:
            return True
        return (now - self._last_heartbeat_sent) >= (self._interval - tick * 0.5)

    def _collect_workers(self) -> dict:
        """Снимок ``get_all_workers_status()`` (Dict at Boundary — чистые dict).

        Общий источник для телеметрии (читает верхнеуровневые ``effective_hz`` /
        ``cycle_duration_ms``) и heartbeat-сообщения. Нет worker_manager / ошибка →
        пустой dict (телеметрия/сообщение просто без воркерных данных).
        """
        wm = getattr(self._services, "worker_manager", None)
        if not wm:
            return {}
        get_status = getattr(wm, "get_all_workers_status", None)
        if get_status is None:
            return {}
        try:
            return get_status()
        except Exception:  # noqa: BLE001 — сбой снятия статуса не должен ронять такт HB
            return {}

    def _send_heartbeat(self, workers: dict) -> None:
        """Собрать и отправить heartbeat-сообщение к ``ProcessManager`` (liveness).

        Тайминг цикла (``effective_hz`` / ``cycle_duration_ms``) подмешан на ВЕРХНИЙ
        уровень статуса воркера (не внутри ``metrics``) и сохраняется; вложенный
        ``metrics`` вырезается для экономии трафика IPC.
        """
        heartbeat_msg = {
            "type": "system",
            "command": "heartbeat",
            "sender": self._services.name,
            "timestamp": time.time(),
            # Ф6.4б: фолбэк был ``"running"`` — третье место, где отсутствие
            # знания подменялось утверждением «работает». Соседний
            # ``introspect.status`` в тех же условиях отвечает ``"unknown"``;
            # два разных ответа на один вопрос — хуже, чем один незнающий.
            "status": getattr(self._services, "_current_process_status", "unknown"),
        }
        if getattr(self._services, "worker_manager", None):
            for w in workers.values():
                if isinstance(w, dict):
                    w.pop("metrics", None)
            heartbeat_msg["workers_status"] = workers
        self._services.send_message("ProcessManager", heartbeat_msg)

    def _warn_capped_metrics(self, config: Any) -> None:
        """Залогировать WARNING по метрикам, чья частота ограничена телеметрийным тиком.

        Task 1.2: если у метрики ``interval_sec`` МЕНЬШЕ эффективного тика
        (``min(heartbeat_interval, tick_sec)``), настроенная частота недостижима — метрика
        публикуется на каждом тике, но не чаще. Раньше это был тихий no-op (finding D) —
        теперь явный WARNING (не отвергаем секцию: метрика продолжает публиковаться).
        No-op, если ``tick_sec`` не задан (``None``) — легаси-процессы не шумят.
        """
        tick_sec = getattr(config, "tick_sec", None)
        if not isinstance(tick_sec, (int, float)) or tick_sec <= 0:
            return
        effective_tick = min(self._interval, float(tick_sec))
        from .telemetry import capped_metrics

        capped = capped_metrics(config, effective_tick)
        if not capped:
            return
        _warn = getattr(self._services, "log_warning", None) or getattr(self._services, "log_info", None)
        if _warn is None:
            return
        names = ", ".join(f"{m} (interval_sec={iv}с)" for m, iv in capped)
        _warn(
            f"Частота метрик ограничена телеметрийным тиком {effective_tick}с: {names} "
            "— метрика публикуется не чаще тика (подними tick_sec или ослабь interval_sec)",
            module="heartbeat",
        )

    def _warn_unknown_metrics(self, config: Any) -> None:
        """Залогировать WARNING по ключам ``metrics``, отсутствующим в каталоге метрик.

        Task 2.3: опечатка в имени метрики (например ``latency`` вместо ``latency_ms``)
        раньше была тихим no-op — правило существует в конфиге, но ``resolve()`` его
        никогда не находит (метрика не публикуется, диагностики нет). Секция НЕ
        отвергается (forward-compat: новая метрика в старом процессе не должна ронять
        boot/reload) — только явный WARNING, чтобы опечатка была видна оператору.
        """
        unknown = config.unknown_metrics()
        if not unknown:
            return
        _warn = getattr(self._services, "log_warning", None) or getattr(self._services, "log_info", None)
        if _warn is None:
            return
        names = ", ".join(sorted(unknown))
        _warn(
            f"Неизвестные ключи telemetry.publish.metrics: {names} "
            "— возможна опечатка в имени метрики (секция применена, метрика игнорируется)",
            module="heartbeat",
        )

    def _pump_scheduled_gc(self) -> None:
        """Ф7 G.9(a) H-ревью: дать GcDiscipline тик для scheduled-сборки (FW_GC_SCHEDULED).

        Heartbeat создаётся ДО gc_discipline (см. ProcessModule.run) → на первых тиках
        атрибута может не быть: getattr-guard. ``collect_scheduled`` сам no-op при
        выключенном расписании (флаг off = бит-в-бит). Ошибки не критичны для такта HB.
        """
        gc_disc = getattr(self._services, "_gc_discipline", None)
        if gc_disc is None:
            return
        try:
            gc_disc.collect_scheduled(time.monotonic())
        except Exception:  # noqa: BLE001 — сборка мусора не критична для такта HB
            pass

    def _drain_observability(self) -> None:
        """Ф5.16: слить log/stats-буфер ObservabilityHub процесса в реальные
        менеджеры по такту heartbeat. Процессы без hub'а тихо пропускаются;
        исключения глушим — дренаж телеметрии не критичен для такта HB."""
        hub = getattr(self._services, "_observability_hub", None)
        drain = getattr(self._services, "_observability_drain", None)
        if hub is None or drain is None:
            return
        store = getattr(self._services, "_observability_store", None)
        # F1: фан-аут пачки каждому подписчику (per-subscriber форвардеры).
        forwarders_map = getattr(self._services, "_observability_forwarders", None)
        forwarders = [fwd for fwd, _taps in forwarders_map.values()] if forwarders_map else None
        from ..managers.observability_wiring import drain_process_observability

        try:
            drain_process_observability(hub, drain, store, forwarders)
        except Exception as exc:  # noqa: BLE001 — телеметрия не критична
            _log = getattr(self._services, "log_debug", self._services.log_info)
            _log(f"Не удалось слить observability-буфер: {exc}", module="heartbeat")

    def _sweep_observability_session(self) -> None:
        """Task 5.8: снять просроченные правки слоя L3 и пересобрать конфиг.

        Сам ``sweep_session_ttl`` исключений не бросает (отказ пересборки — его
        отчёт и повтор на следующем такте). Внешний ``except`` здесь — на
        неожиданное, и он пишет ОШИБКУ, а не debug-строку: «возврат не сработал»
        — это отказ защиты от инцидента 645 МБ, а не шум телеметрии.
        """
        try:
            from ..managers.observability_ttl import sweep_session_ttl

            sweep_session_ttl(self._services)
        except Exception as exc:  # noqa: BLE001 — такт HB не роняем, но и не молчим
            _log = getattr(self._services, "_log_error", None) or getattr(self._services, "log_error", None)
            if not callable(_log):
                _log = getattr(self._services, "log_info", None)
            if callable(_log):
                _log(f"[observability] подметальщик сроков L3 упал: {exc!r}", module="observability")

    def _sweep_documents(self) -> None:
        """Ф8.5: удалить документы с истёкшим сроком (не чаще ``purge_interval_sec``).

        ``sweep_process_documents`` сам решает, наступил ли срок, и сам глушит отказ
        БД именным WARNING'ом. Внешний ``except`` здесь — на неожиданное: плоскость
        документов хозяйственна, а такт heartbeat несёт liveness, и уронить второе
        ради первого нельзя.
        """
        try:
            from ..managers.observability_wiring import sweep_process_documents

            sweep_process_documents(self._services)
        except Exception as exc:  # noqa: BLE001 — такт HB не роняем, но и не молчим
            _log = getattr(self._services, "log_debug", self._services.log_info)
            _log(f"[observability] уборка документов сорвалась: {exc!r}", module="heartbeat")

    def _sweep_observability_history(self) -> None:
        """Ф5.2: срезать историю по возрасту и числу строк (не чаще интервала).

        Форма — дословно ``_sweep_documents``: ``sweep_observability_history`` сам
        решает, наступил ли срок, и сам глушит отказ БД именным WARNING'ом. Второй
        способ делать то же дело в такте означал бы второе место, где его забудут.
        """
        try:
            from ..managers.observability_wiring import sweep_observability_history

            sweep_observability_history(self._services)
        except Exception as exc:  # noqa: BLE001 — такт HB не роняем, но и не молчим
            _log = getattr(self._services, "log_debug", self._services.log_info)
            _log(f"[observability] уборка истории сорвалась: {exc!r}", module="heartbeat")

    def _build_telemetry_gate(self) -> Any:
        """Собрать ``TelemetryGate`` из секции ``telemetry.publish`` конфига процесса.

        Обратная совместимость: нет секции ``telemetry`` / нет под-секции ``publish``
        → ``None`` (гейт неактивен, все метрики публикуются каждый тик — поведение как
        раньше). Плумбинг значений из ``system.yaml``/blueprint — отдельная задача
        (PC 1.3); здесь читаем уже доставленный ``get_config("telemetry")``.
        """
        try:
            telemetry = self._services.get_config("telemetry", None)
        except Exception:  # noqa: BLE001 — отсутствие/битость конфига не должна ронять heartbeat
            telemetry = None
        if not isinstance(telemetry, dict):
            return None
        publish = telemetry.get("publish")
        if publish is None:
            return None
        from ..configs.telemetry_publish_config import TelemetryPublishConfig
        from .telemetry import TelemetryGate

        try:
            config = TelemetryPublishConfig.from_dict(publish)
        except Exception as exc:  # noqa: BLE001 — кривой конфиг → без гейта (как раньше), но залогировать
            _log = getattr(self._services, "log_debug", self._services.log_info)
            _log(f"Не удалось собрать TelemetryPublishConfig, гейт выключен: {exc}", module="heartbeat")
            return None
        # Task 1.2: WARNING по метрикам, чей interval_sec < эффективного тика (не тихий no-op).
        self._warn_capped_metrics(config)
        # Task 2.3: WARNING по ключам metrics, отсутствующим в каталоге метрик (опечатка).
        self._warn_unknown_metrics(config)
        # Task 1.2: gate использует ТОТ ЖЕ clock, что и heartbeat-планирование (для
        # fake-clock тестов каденции; в проде обоим — time.monotonic).
        return TelemetryGate(config, clock=self._clock)

    def current_unknown_metrics(self) -> list[str]:
        """Отсортированный список неизвестных ключей ``metrics`` текущего живого gate (Task 2.3).

        Источник для видимой диагностики опечаток инициатору рантайм-переконфигурации
        (``BuiltinCommands._cmd_telemetry_reconfigure``) — не тихий no-op (finding E).
        Gate выключен (``None``) → пустой список (нечего резолвить).
        """
        gate = self._telemetry_gate
        if gate is None:
            return []
        return sorted(gate.config.unknown_metrics())

    def current_telemetry_publish(self) -> dict | None:
        """Текущая эффективная секция ``telemetry.publish`` живого gate (Task 1.1).

        Источник истины для дельта-переконфигурации (``mode="merge"``): сериализует
        конфиг активного gate в dict (``TelemetryPublishConfig.to_dict``), поверх
        которого мержится дельта. Gate выключен (``None``) → ``None`` (нет эффективной
        секции; merge стартует с пустой базы — дефолтный конфиг + дельта).
        """
        gate = self._telemetry_gate
        if gate is None:
            return None
        return gate.config.to_dict()

    def reconfigure_telemetry(self, publish_section: dict | None, *, mode: str = "replace") -> None:
        """Пересобрать publisher-gate из секции ``telemetry.publish`` (рантайм, PC 3.1 / Task 1.1).

        Единый механизм рантайм-переконфигурации телеметрии БЕЗ рестарта процесса —
        тот же результат, что ``_build_telemetry_gate`` на старте, но из ЯВНО переданной
        секции (а не из ``get_config``).

        Режим ``mode`` (Task 1.1):
          - ``"replace"`` (дефолт, backward-compat) — ``publish_section`` применяется
            ЦЕЛИКОМ: не указанные метрики берут дефолты. Прежнее поведение PC 3.1;
          - ``"merge"`` — ``publish_section`` трактуется как ДЕЛЬТА поверх текущей
            эффективной секции (:meth:`current_telemetry_publish`): собирается
            ``deep_merge(current_effective, delta)`` и из результата строится новый gate.
            «Точечная» правка одной метрики не стирает override'ы остальных.

        Семантика значений (в обоих режимах после разворота дельты):
          - ``publish_section is None`` → gate ВЫКЛЮЧАЕТСЯ (``self._telemetry_gate = None``)
            → все метрики публикуются каждый тик (обратная совместимость — как при
            отсутствии секции ``telemetry.publish`` на старте, PC 1.2). ``None`` = «нет
            секции» и означает выключение НЕЗАВИСИМО от ``mode`` (merge с None — дегенерат);
          - dict → строит новый ``TelemetryGate`` из ``TelemetryPublishConfig.from_dict``
            (пустой dict → дефолт 1.0с на все метрики — осознанная явная команда).

        Потокобезопасность относительно потока heartbeat (``_loop``): gate читается в
        потоке heartbeat, а этот метод зовётся из потока диспетчера команд. Смена —
        АТОМАРНОЕ переприсвоение ссылки ``self._telemetry_gate`` под GIL на ПОЛНОСТЬЮ
        собранный объект (конструирование ``TelemetryGate`` завершается ДО присвоения).
        ``_loop`` читает ``self._telemetry_gate`` в локальную переменную один раз за тик,
        поэтому видит либо старый, либо новый gate целиком — никогда частично собранный.
        Старый gate НЕ мутируется (его ``_next_due`` живёт до GC), новый стартует со
        свежим (пустым) ``_next_due`` → все включённые метрики «созревают» на ближайшем
        тике (одна публикация сразу после смены — приемлемо для телеметрии, gate остаётся
        чистым/тестируемым).

        Args:
            publish_section: под-секция ``telemetry.publish`` (dict) или ``None`` —
                при ``mode="merge"`` это дельта поверх текущей эффективной секции.
            mode: ``"replace"`` (полное применение) или ``"merge"`` (дельта).

        Raises:
            Пробрасывает исключение валидации ``TelemetryPublishConfig.from_dict`` при
            некорректной секции — вызывающий (``telemetry.reconfigure`` handler /
            ``apply_telemetry_reconfigure``) решает, как сообщить об ошибке инициатору.
        """
        if publish_section is not None and mode == "merge":
            # Дельта поверх живой эффективной секции. Gate off → пустая база (дефолтный
            # конфиг + дельта). deep_merge из data_schema_module (нижний слой) — канон.
            from ...data_schema_module import deep_merge

            base = self.current_telemetry_publish() or {}
            publish_section = deep_merge(base, publish_section)

        if publish_section is None:
            self._telemetry_gate = None
            return
        from ..configs.telemetry_publish_config import TelemetryPublishConfig
        from .telemetry import TelemetryGate

        config = TelemetryPublishConfig.from_dict(publish_section)
        # Task 1.2: WARNING по метрикам, чья частота ограничена телеметрийным тиком.
        self._warn_capped_metrics(config)
        # Task 2.3: WARNING по ключам metrics, отсутствующим в каталоге метрик (опечатка).
        self._warn_unknown_metrics(config)
        # Атомарный swap: сборка завершена — переприсваиваем ссылку целиком (под GIL).
        # Gate использует clock heartbeat'а (fake-clock тесты; в проде time.monotonic).
        self._telemetry_gate = TelemetryGate(config, clock=self._clock)

    def _collect_plugin_levels(self, allowed_metrics: Any = None, *, voice: bool) -> dict:
        """Листья уровней плагинов для секции ``state`` (общий шов push и poll).

        Одно место, а не две копии в тике и опросе: разойдись они, «опрос отдаёт
        то же, что push» стало бы ложью, которую видно только на стенде.
        Различие ровно одно и оно параметром: голос об отсеянном подаёт ТИК
        (``voice=True``). Опрос молчит намеренно — он идёт по команде оператора,
        и жалоба на его такте зависела бы от того, как часто опрашивают.

        Args:
            allowed_metrics: разрешённые на этом тике суффиксы (``None`` → все).
            voice: сказать ли про отсеянные имена (один раз на имя).

        Returns:
            ``{имя: значение}`` — пусто, если хранилища нет, оно пусто или всё
            отсеяно.
        """
        from .telemetry import PLUGIN_LEVELS_ATTR, build_plugin_levels

        store = getattr(self._services, PLUGIN_LEVELS_ATTR, None)
        publications: Any = getattr(store, "publications", None)
        if not callable(publications):
            return {}  # ни один плагин процесса уровней не отдавал
        try:
            payload, rejected = build_plugin_levels(publications(), allowed_metrics)
        except Exception as exc:  # noqa: BLE001 — телеметрия не критична для такта HB
            _log = getattr(self._services, "log_debug", self._services.log_info)
            _log(f"Уровни плагинов недоступны: {exc}", module="heartbeat")
            return {}
        if voice:
            self._warn_rejected_levels(rejected)
        return payload

    def _publish_telemetry_to_tree(self, workers: dict, allowed_metrics: Any = None) -> None:
        """Вся телеметрия процесса за тик — ОДНИМ ``proxy.merge`` (Р3.5-12).

        Здоровый путь телеметрии: процесс САМ репортит свои метрики через
        собственный StateProxy (→ ProcessManager → StateStoreManager → GUI) — тот
        же проверенный канал, что и статус процесса. Минует центральную
        heartbeat-агрегацию в ProcessMonitor (хрупкий лишний участок).
        См. ``plans/telemetry-self-publish-redesign.md``.

        Собирается под одним путём ``processes.{name}``:

        * ``workers.{w}.{status, effective_hz, cycle_duration_ms}`` — строки
          таблицы воркеров;
        * ``state.fps`` = max(``effective_hz``) по running-воркерам с hz > 0,
          ``state.latency_ms`` = max(``cycle_duration_ms``) среди них — агрегат
          карточки; нет ни одного hz > 0 → агрегата нет;
        * ``state.shm.*`` — счётчики кадрового транспорта router'а (Ф7 G.3 H8 /
          G.4.a): pickle_fallbacks, torn_reads, boundary_crossings,
          queue_data_evicted и прочие сигналы потери кадра для вкладки Pipeline;
        * ``state.<имя>`` — уровни, объявленные и отданные плагинами процесса.

        **Почему один merge, а не три.** До Р3.5-12 тик слал три отдельных merge,
        и продовое правило троттла ``processes.**.state.fps: 0.05`` пропускало
        одну запись на путь за окно. Воспроизведено 2026-08-16: два merge с
        разницей 0.5 мс на Windows-сетке 15.6 мс читают ОДИН таймстамп, второй
        возвращает ``proceed=True`` с уже вырезанным листом и без
        ``rejection_reason`` — потерю не видел даже отправитель. Один merge
        возвращает систему к собственному принципу E6/Task 5.7 («один merge
        вместо 3W+2 set») и снимает с транспорта роль, которой у него нет.

        **Порядок наложения внутри payload — fail-safe, а не политика разрешения
        конфликта.** Уровни плагинов кладутся ПЕРВЫМИ, агрегат фреймворка —
        поверх. Спор за имя сюда не доходит: его снимает проверка владельца в
        :func:`build_plugin_levels` (лист с чужим именем отбрасывается ещё в
        сборщике). Прежняя редакция имела ОБРАТНЫЙ порядок и называла его несущей
        политикой («плагин побеждает») — эта политика снята целиком (ADR-PM-038).

        **Насколько порядок страхует — измерено, а не заявлено** (ревью З1,
        2026-08-17). Прежняя формулировка обещала «тогда виден будет уровень
        фреймворка, а не подменённый». Инъекция «отбор по каталогу вместо
        владения» показала, что порядок спасает **1 случай из 5** и только когда
        агрегат есть НА ЭТОМ ЖЕ ТИКЕ:

        =========================================  ==================
        случай                                     с протечкой отбора
        =========================================  ==================
        ``fps``, живой воркер с hz>0                ``8.0`` — спас
        ``fps``, воркеров нет                       ``99.0`` — НЕ спас
        ``latency_ms``, hz>0 без замера латентности  ``99.0`` — НЕ спас
        ``effective_hz`` (лист воркера, не state)   ``99.0`` — НЕ спас
        ``shm`` при нулевых счётчиках                ``99.0`` скаляром на месте
                                                    поддерева — НЕ спас
        =========================================  ==================

        Поэтому честная формулировка узкая: порядок страхует ``fps`` и
        ``latency_ms`` **при наличии агрегата на том же тике**, и ничего больше.
        Единственный настоящий предохранитель — проверка владельца в сборщике;
        порядок оставлен как дешёвая вторая линия там, где он работает.

        **Что осталось политикой ПУБЛИКАТОРА** (а не сборщиков, которые чисты):
        гейт метрик, «нет прокси — молчим», «все счётчики ``shm`` нулевые — не
        грузим дерево» и «нечего слать — не шлём пустой merge».

        Args:
            workers: снимок ``get_all_workers_status()`` (тайминг цикла на верхнем
                уровне каждого статуса). Пустой — НЕ причина пропустить тик: до
                Р3.5-12 ранний выход по ``not workers`` жил в отдельном методе и
                глотал только воркерные листья, а ``shm`` и уровни ехали своими
                merge. В объединённой сборке тот же выход проглотил бы и их.
            allowed_metrics: разрешённые на этом тике суффиксы метрик (``None`` →
                все, обратная совместимость).
        """
        proxy = getattr(self._services, "_state_proxy", None)
        if proxy is None:
            return  # чисто системный процесс без StateProxy

        from .telemetry import PLUGIN_LEVELS_ATTR, build_router_shm_telemetry, build_worker_telemetry

        data: dict = {}
        state: dict = {}

        # (1) Уровни плагинов — первыми (см. «порядок наложения» выше).
        state.update(self._collect_plugin_levels(allowed_metrics, voice=True))

        # (2) Воркеры + агрегат фреймворка — поверх.
        if workers:
            result = build_worker_telemetry(workers, self._services.name, allowed_metrics)
            if result is not None:
                _path, worker_data = result
                workers_payload = worker_data.get("workers")
                if workers_payload:
                    data["workers"] = workers_payload
                state.update(worker_data.get("state") or {})

        # (3) Счётчики кадрового транспорта. Гейт спрашивается ДО чтения router'а:
        # полный get_stats() у router'ов без узкого аксессора стоит десятки мс
        # (ADR-PM-035), и платить их за выключенную метрику незачем.
        if allowed_metrics is None or "shm" in allowed_metrics:
            router = getattr(self._services, "router_manager", None)
            if router is not None:
                try:
                    shm = build_router_shm_telemetry(router)
                except Exception as exc:  # noqa: BLE001 — телеметрия не критична для такта HB
                    _log = getattr(self._services, "log_debug", self._services.log_info)
                    _log(f"SHM-счётчики недоступны: {exc}", module="heartbeat")
                    shm = None
                # Все счётчики нулевые → нет кадрового пути / всё чисто — не
                # публикуем. Проверка по значениям, а не поимённым сравнением с
                # нулём: добавленный в сборщик счётчик попадает под тот же guard
                # сам, без правки здесь.
                if shm and any(shm.values()):
                    state["shm"] = shm

        # (4) Снятые уровни: сказать дереву «показания больше нет».
        #
        # Без этого шага обещание «уровень мёртвого владельца исчезает в момент
        # смерти» было ложью: `retract` убирал публикацию, payload становился
        # чист, а лист в дереве жил вечно с последним значением (ревью Н1).
        #
        # `None`, а не `state.delete`: у `StateProxy` метода `delete` НЕТ (есть
        # только `handle_state_delete` на менеджере), то есть настоящее удаление
        # означало бы новую публичную дорогу записи в чужом модуле — на случай,
        # у которого сегодня нет ни одного живого источника кроме teardown'а
        # процесса. `None` едет ТОЙ ЖЕ дорогой, тем же владельцем и тем же
        # сообщением, а потребители его уже понимают: VM-сеттер карточки рисует
        # «—» на нечисловом (`test_deleted_delta_shows_no_data_placeholder`),
        # сток пишет NULL. Разница названа: ключ листа остаётся в дереве, значение
        # становится «нет показания».
        # ponytail: апгрейд до настоящего удаления — `StateProxy.delete` +
        # `throttle.prune`; заводить, когда появится читатель, которому мешает
        # именно наличие ключа, а не отсутствие значения.
        #
        # ВНЕ ГЕЙТА намеренно, как `status` воркеров: гейт управляет ЧАСТОТОЙ
        # уровня, а снятие — однократный факт. Пропусти его гейт (метрика
        # выключена) — и лист остался бы навсегда с мёртвым числом, то есть гейт
        # порождал бы ровно ту ложь, которую этот шаг убирает.
        #
        # ЧИТАЕМ без дренажа и СПИСЫВАЕМ только после успешной отправки (S-1,
        # нога A). Прежняя редакция вычёркивала имя ДО ``proxy.merge``, а тот
        # обёрнут в ``except Exception`` — любой отказ доставки хоронил снятие
        # навсегда, и в дереве оставалось мёртвое число. Это единственный payload
        # тика, который сам не восстанавливается: прочие уровни переотправляются
        # каждым тиком. Запас конечен (``RETRACTION_REASSERT_TICKS``) и тратится
        # ТОЛЬКО на успехах — иначе три провала подряд съели бы его целиком.
        store = getattr(self._services, PLUGIN_LEVELS_ATTR, None)
        pending = getattr(store, "pending_retractions", None)
        # Подтверждаем РОВНО те имена, которые реально положили в payload: имя,
        # перебитое живым значением, снятия не утверждало, и списывать ему такт
        # было бы приписыванием чужой доставки.
        asserted: list[str] = []
        if callable(pending):
            for name in pending():
                # Живое значение на этом же тике побеждает: плагин мог быть
                # поднят заново между снятием и тиком, и обнулять его показание
                # было бы новой ложью.
                if name not in state:
                    state[name] = None
                    asserted.append(name)

        if state:
            data["state"] = state
        if not data:
            return  # показаний нет вовсе — пустой merge не шлём
        try:
            proxy.merge(f"processes.{self._services.name}", data)
        except Exception as exc:  # noqa: BLE001 — телеметрия не критична для такта HB
            _log = getattr(self._services, "log_debug", self._services.log_info)
            _log(f"Не удалось self-publish телеметрии процесса: {exc}", module="heartbeat")
            return  # запас переутверждений НЕ тратится: такт провален
        if asserted:
            confirm = getattr(store, "confirm_retracted", None)
            if callable(confirm):
                confirm(asserted)

    def _warn_rejected_levels(self, rejected: tuple[tuple[str, str, Any], ...]) -> None:
        """Сказать про отсеянный уровень ОДИН раз на имя (Р3.5-11).

        Один раз, а не каждый тик: тик идёт секундами, и голос на каждом
        превратил бы диагностику в поток, к которому перестают прислушиваться —
        тот же довод, что у ``note_metric_without_plane``. Множество уже
        названных живёт на heartbeat'е процесса, потому что и хранилище уровней
        процессное.

        В голосе названы все три участника: имя, публикатор и владелец. Без
        владельца оператор не отличает «я опечатался в имени» от «это имя не
        моё», а это два разных действия — переименовать своё против убрать
        публикацию в чужое.

        Ругаться здесь, а не в ``publish_metric``: на момент публикации порядок
        «объявил → отдал» ещё не устоялся (плагин вправе отдать значение до
        объявления в том же ``configure``), а на момент тика — уже.
        """
        if not rejected:
            return
        warned = self._warned_rejected_levels
        # Ключ «сказано» — ПАРА (имя, публикатор), а не имя: на одно имя может
        # прийти несколько перехватчиков, и дедуп по имени озвучил бы только
        # первого — второй молча пропал бы ровно там, где его и надо назвать.
        fresh = [item for item in rejected if (item[0], item[1]) not in warned]
        if not fresh:
            return
        warned.update((name, publisher) for name, publisher, _owner in fresh)
        _warn = getattr(self._services, "log_warning", None) or getattr(self._services, "log_info", None)
        if _warn is None:
            return
        # Голос обрезается по числу записей (ревью З2, 2026-08-17): плагин,
        # опубликовавший в 5000 необъявленных имён, давал ОДНУ строку WARNING
        # длиной 289 107 символов — голос подорожал впятеро против прежнего
        # формата и сам стал инцидентом. Первых N достаточно, чтобы назвать
        # виновника; полное число говорит хвостом.
        # ponytail: `_warned_rejected_levels` предела тоже не имеет (5000 пар на
        # том же прогоне). Потолок — |имён × публикаторов| у runaway-плагина;
        # кап не заводится, пока такого писателя нет, — см. PluginLevels.
        shown = fresh[:_REJECTION_VOICE_LIMIT]
        details = ", ".join(
            f"{name!r} (публикует {publisher!r}, "
            + (f"владелец имени — {owner!r}" if owner is not None else "имя не объявлено никем")
            + ")"
            for name, publisher, owner in shown
        )
        if len(fresh) > len(shown):
            details += f" …и ещё {len(fresh) - len(shown)}"
        _warn(
            f"Уровни не опубликованы — имя принадлежит не публикатору: {details} "
            "— объяви СВОЁ имя через ctx.declare_metric(имя) рядом с вычислением; "
            "публикация в чужое имя не поедет ни при каком состоянии гейта "
            "(дальше молчим по этим именам)",
            module="heartbeat",
        )

    def current_levels_snapshot(self) -> dict | None:
        """Пакетный снимок текущих УРОВНЕЙ процесса — один вызов, все метрики (Task 3.2).

        Отвечает на «сколько сейчас» БЕЗ включённой публикации: publisher-гейт
        (ADR-PM-018) управляет push'ем в дерево, а не тем, что процесс знает о себе.
        Поэтому сборщик зовётся с ``allowed_metrics=None`` — гейт закрыт наглухо, а
        снимок всё равно полон. Обратное («опрос показывает только разрешённое к
        публикации») сделало бы поле бесполезным ровно в том случае, ради которого оно
        заводилось: закрытое окно, ноль push-трафика, оператор всё ещё хочет числа.

        **Тот же сборщик, что у тика** (:func:`build_worker_telemetry` +
        :func:`build_router_shm_telemetry` + :meth:`_collect_plugin_levels`), и та же
        форма пути: возвращаемый dict ложится в дерево как ``processes.<name>``
        (``workers.*`` + ``state.*``, включая ``state.shm.*``). Второго способа
        посчитать те же величины не заводится: разойдись они, «опрос отдаёт то же,
        что push» стало бы ложью, которую видно только на стенде с router'ом (в
        юнит-тестах router обычно ``None``).

        **Граница названа: снимок — это то, что собирает ТЕЛЕМЕТРИЙНЫЙ ТИК, а не всё,
        что кто-либо когда-либо писал под ``processes.<name>.state``.** Проверено на
        живом стенде 2026-08-14: рядом с ``fps``/``latency_ms``/``shm`` в дереве лежали
        ключи, которые писали ДРУГИЕ публикаторы (``uptime``/``status``/``pid`` от ПМ,
        прикладные счётчики от плагинов), и этот сборщик их не считал.

        Task 3.5 сдвинула границу, но не стёрла её. Уровень, который плагин ОБЪЯВИЛ
        СВОИМ ИМЕНЕМ (``ctx.declare_metric``) и ОТДАЁТ (``ctx.publish_metric``),
        теперь собирается здесь же и приезжает опросом; уровень, положенный в чужое
        имя, не приезжает ни сюда, ни в дерево (Р3.5-11). За границей осталось два
        РАЗНЫХ класса, и путать их нельзя (ADR-PM-038):

        * ``uptime``/``status``/``pid`` принадлежат **ProcessManager'у** — он публикует
          их О ЧУЖОМ процессе из своего ``first_seen``, и опрос процесса их отдать не
          может по построению. Это граница, а не долг;
        * прикладные ключи, которые плагин публикует **фронтом** (при смене состояния,
          а не по тику), уровнем не являются: собранный тиком «уровень», который между
          сменами не обновляется, был бы хуже прямой записи. Такие ключи остаются на
          прежней дороге сознательно.

        Прикладных имён здесь не перечисляется намеренно (§3.6 «универсальность»):
        поимённый реестр немигрированных писателей с причинами живёт в ``README.md``
        модуля, а не в коде фреймворка.

        Следствие общего сборщика, принятое осознанно: **округление до 1 знака**
        (``round(x, 1)``) действует и на опросе. Снимок — вид уровней для глаз, а не
        измерительный прибор; расхождение push/poll в последнем знаке было бы дороже
        потерянной точности.

        **Только чтение.** ``get_all_workers_status()`` и узкий ``router.get_shm_stats()``
        ничего не мутируют, ``_next_due`` гейта НЕ продвигается (``due_metrics()``
        здесь не зовётся), в дерево не пишется ни одного merge/set. Читать дёшево:
        узкий аксессор не строит маршруты/хендлеры/каналы — цена измерена в ADR-PM-035.

        **Чем определяется свежесть — и чем НЕ определяется.** ``snapshot_ts`` в ответе
        команды говорит только «когда собран ЭТОТ ОТВЕТ» — это возраст ответа, НЕ
        возраст чисел. Воспроизведено: воркер остановлен полностью, два опроса с
        разницей 4.00 с несут разные ``snapshot_ts`` и **идентичные**
        ``fps=21.0 / latency_ms=47.7``, а ``status`` при этом ``running``. Признак
        движения даёт per-worker ``cycles`` (``include_cycles=True`` ниже): счётчик
        завершённых циклов стоит — числа протухли, растёт — живые. Судить по паре
        (``snapshot_ts``, ``cycles``), а не по штампу.

        Returns:
            Поддерево уровней (непустой dict) — ЛИБО ``None``, если показаний нет
            вовсе (нет ``worker_manager`` / ноль воркеров / нет router'а). ``None``
            означает «сенсоров нет», а не «команда не сработала».

        Raises:
            Ничего не поднимает по своей воле: сбой снятия статуса воркеров глотает
            ``_collect_workers``, сбой ``router.get_stats()`` — секция ``shm``
            пропускается (best-effort по образцу ``introspect.memory``).
        """
        from .telemetry import build_router_shm_telemetry, build_worker_telemetry

        # allowed_metrics=None — намеренно: см. докстринг (гейт про push, не про знание).
        # include_cycles=True — признак движения, нужный только опрашивающему.
        result = build_worker_telemetry(self._collect_workers(), self._services.name, None, include_cycles=True)
        data: dict = dict(result[1]) if result is not None else {}

        # Уровни плагинов — тем же швом, что у тика, и в ту же секцию ``state``.
        # Порядок наложения тот же, что в :meth:`_publish_telemetry_to_tree`
        # (уровни первыми, агрегат поверх) — иначе push и poll разошлись бы, если
        # отбор по владельцу когда-нибудь протечёт. Голоса здесь нет: жалоба на
        # такте опроса зависела бы от того, как часто опрашивают (voice=False).
        plugin_levels = self._collect_plugin_levels(None, voice=False)
        if plugin_levels:
            state = dict(plugin_levels)
            state.update(data.get("state") or {})
            data["state"] = state

        router = getattr(self._services, "router_manager", None)
        if router is not None:
            try:
                shm = build_router_shm_telemetry(router)
            except Exception as exc:  # noqa: BLE001 — best-effort: без секции, не отказ
                _log = getattr(self._services, "log_debug", self._services.log_info)
                _log(f"Снимок уровней: SHM-счётчики недоступны: {exc}", module="heartbeat")
                shm = None
            if shm:
                # Нули включительно: для ОПРОСА «все нули» — показание «всё чисто», а не
                # отсутствие данных (у публикатора наоборот — там нули не грузят дерево).
                state = dict(data.get("state") or {})
                state["shm"] = shm
                data["state"] = state

        return data or None

    def _publish_health_to_tree(self) -> None:
        """Опубликовать здоровье процесса (Ф2 Task 2.1) в дерево StateStore.

        Тот же self-publish канал, что и телеметрия: процесс сам репортит своё
        здоровье через ``_state_proxy`` (``processes.<name>.health.*``). Публикатор
        (``health.publish_health``) снимает грязный снапшот единого HealthState
        процесса и шлёт только при изменениях — публикация вырождается в no-op,
        пока никто не звал report_error/set_status. Процессы без StateProxy или без
        HealthState (никто ещё не трогал health) тихо пропускаются.
        """
        proxy = getattr(self._services, "_state_proxy", None)
        if proxy is None:
            return
        state = getattr(self._services, "_health_state", None)
        if state is None:
            return

        from ..health import publish_health

        try:
            # Task 2.2: пассивный шаг восстановления breaker по тишине — на такте
            # heartbeat, до публикации (переход open→half_open→closed попадёт в снапшот).
            poll = getattr(state, "poll", None)
            if callable(poll):
                poll()
            publish_health(state, proxy, self._services.name)
        except Exception as exc:  # noqa: BLE001 — health не критичен для работы процесса
            _log = getattr(self._services, "log_debug", self._services.log_info)
            _log(f"Не удалось self-publish health процесса: {exc}", module="heartbeat")
