"""ProcessHeartbeat — отправка периодических heartbeat-сообщений ProcessManager-у."""

from __future__ import annotations

import time
from typing import TYPE_CHECKING, Any, Callable

from ...observability_declarations import declare_metric

if TYPE_CHECKING:
    pass

# Ф8.1: `shm` объявляется здесь, потому что её счёт заказывает `_publish_telemetry_to_tree`
# в этом файле. Остальные четыре — у `telemetry.py`, где собираются они. Каталог
# перестал быть кортежем-литералом в configs/, и объявление метрики теперь стоит
# там же, где она вычисляется, а не двумя слоями ниже.
#
# Импорт на уровне модуля, а не ленивый, как соседи: ленивый объявил бы метрику
# только после первого вызова публикатора, то есть каталог отвечал бы на вопрос
# «что бывает» уже после того, как по нему приняли решение.
METRIC_SHM = declare_metric("shm", owner=__name__)


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
                # ``extra`` — имена листьев, реально лежащие в хранилище уровней
                # (Ф1, шаг 5). Гейт матчит по ИМЕНИ ЛИСТА и обязан быть тотален:
                # необъявленное имя решается дефолтным правилом конфига, ровно как
                # ``TelemetryPublishConfig.resolve``. Обходи гейт только каталог
                # объявлений — необъявленное имя не попало бы в ``allowed`` никогда,
                # и «едет легально» оказалось бы тихим отказом.
                #
                # Имена берутся отдельным дешёвым чтением (без значений), а сами
                # значения читает сборщик ниже. Между двумя чтениями писатель может
                # завести НОВОЕ имя — оно поедет следующим тиком, потому что на этом
                # решения по нему гейт не выдавал. Это та же семантика «разрешение
                # выдаётся, а не подтверждается данными», что уже описана у
                # ``TelemetryGate``, и та же задержка, что у публикации сразу после
                # тика: один тик, то есть секунды.
                allowed_metrics = gate.due_metrics(extra=self._level_names()) if gate is not None else None
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
        раньше). Это ТРЕТЬЕ состояние, отличное и от «всё выключено»
        (``default_enabled: false``), и от «всё включено»: в :meth:`_loop`
        ``allowed_metrics=None`` значит «разрешено всё», а ``set()`` — «ничего».

        **Адрес ключа — два, и оба законны (исправлено 2026-08-18).** Оркестратор
        получает конфиг ПЛОСКИМ (спавнер мержит ``orchestrator_config`` в корень), а
        дочерний процесс — ВЕСЬ ``proc_dict``, поэтому его ключи лежат под ``config.``.
        Голый ``get_config("telemetry")`` работал только у оркестратора и у ДЕТЕЙ
        ВОЗВРАЩАЛ ``None`` молча. Измерено живым стендом 2026-08-18
        (``logs_live/rt2_config_flip``): при действующей секции
        ``telemetry.publish.default_enabled: false`` в боевом ``system.yaml`` семь из
        семи детей рапортовали ``gate_active: false``, а тот же процесс после
        ``config.reload`` того же файла — ``gate_active: true``; reload читает YAML сам
        (``builtin_commands.py``) и потому мимо сломанного звена проезжал. Читаем через
        :func:`read_process_config` — он пробует плоский адрес, затем ``config.<ключ>``,
        то есть обе формы. Тот же класс дефекта до этого кусал ``observability.persist``
        (5.12) и ``telemetry_override`` (находка C задачи 2.2).

        **L0 обязан читаться ТЕМ ЖЕ способом.** ``telemetry_targets`` в
        ``managers/observability_reload.py`` достаёт ``telemetry_boot`` для возврата
        рантайм-правок по сроку и обещает докстрингом совпадение с загрузочным гейтом.
        Чинить адрес здесь и забыть там — значит порвать это обещание молча: истечение
        срока вернуло бы не то, из чего гейт собран.
        """
        from ..configs.observability_layers import read_process_config

        try:
            telemetry = read_process_config(self._services, "telemetry")
        except Exception:  # noqa: BLE001 — отсутствие/битость конфига не должна ронять heartbeat
            telemetry = None
        if not isinstance(telemetry, dict) or telemetry.get("publish") is None:
            # Голос на ОТКАЗЕ — обязателен и симметричен голосу на успехе (ниже).
            # До 2026-08-18 обе ветки молчали, и неработающий флип выглядел как
            # штатный дефолт: на стенде это стоило полного расследования.
            # Формулировка — ФАКТ («не найдена по адресам»), а не вывод («секции нет»):
            # секция в конфиге БЫЛА, просто по другому адресу, и вывод увёл диагностику.
            self._log_heartbeat(
                "[telemetry] publisher-gate ВЫКЛЮЧЕН: секция publish не найдена ни по "
                "'telemetry', ни по 'config.telemetry' — все метрики публикуются каждый тик"
            )
            return None
        publish = telemetry["publish"]
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
        # Голос на УСПЕХЕ — вторая половина пары. Лог только на отказе не отличает
        # «гейт выключен» от «код не исполнялся вовсе».
        self._log_heartbeat(
            f"[telemetry] publisher-gate активен: default_enabled={config.default_enabled}, "
            f"явных правил {len(config.metrics)}, интервал по умолчанию "
            f"{config.default_interval_sec} с"
        )
        # Task 1.2: gate использует ТОТ ЖЕ clock, что и heartbeat-планирование (для
        # fake-clock тестов каденции; в проде обоим — time.monotonic).
        return TelemetryGate(config, clock=self._clock)

    def _log_heartbeat(self, message: str) -> None:
        """Сказать вслух, не уронив такт: у дублёров ``services`` логгера может не быть."""
        log = getattr(self._services, "log_info", None)
        if not callable(log):
            return
        try:
            log(message, module="heartbeat")
        except Exception:  # noqa: BLE001 — голос не смеет ронять сборку гейта
            pass

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

        # Голос на ОБОИХ исходах — тот же парный контракт, что у загрузочного
        # ``_build_telemetry_gate`` (блокер 2 ревью 2026-08-18). Раньше рантайм-снятие
        # гейта молчало, и ответ ``introspect.telemetry`` посылал оператора к строке
        # лога, которой при этом пути не существовало: «gate не собран … почему —
        # в логе» при пустом логе читается как «диагностика соврала».
        if publish_section is None:
            self._telemetry_gate = None
            self._log_heartbeat(
                "[telemetry] publisher-gate СНЯТ рантайм-командой: секция передана как null — "
                "все метрики снова публикуются каждый тик"
            )
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
        self._log_heartbeat(
            f"[telemetry] publisher-gate пересобран рантайм-командой (mode={mode}): "
            f"default_enabled={config.default_enabled}, явных правил {len(config.metrics)}, "
            f"интервал по умолчанию {config.default_interval_sec} с"
        )

    def _level_names(self) -> set[str]:
        """Имена листьев, лежащих в хранилище уровней, — кандидаты гейта на тике.

        Отдельно от :meth:`_collect_plugin_levels`, потому что гейт решает ДО
        сборки: чтобы ответить «поедет ли имя», он должен сначала узнать, какие
        имена вообще есть (каталог объявлений знает только объявленные — см.
        ``TelemetryGate.due_metrics``). Значения сюда не копируются.

        Хранилища нет (процесс без плагинов, иммутабельный дубль сервисов) →
        пустое множество: гейт тогда работает ровно по каталогу, как раньше.
        """
        from .telemetry import PLUGIN_LEVELS_ATTR

        store = getattr(self._services, PLUGIN_LEVELS_ATTR, None)
        names: Any = getattr(store, "names", None)
        if not callable(names):
            return set()
        try:
            return set(names())
        except Exception as exc:  # noqa: BLE001 — телеметрия не критична для такта HB
            _log = getattr(self._services, "log_debug", self._services.log_info)
            _log(f"Имена уровней плагинов недоступны: {exc}", module="heartbeat")
            return set()

    def _collect_plugin_levels(self, allowed_metrics: Any = None) -> dict:
        """Поддерево ``plugins.<писатель>.<имя>`` для секции ``state``.

        Общий шов push и poll: одно место, а не две копии в тике и опросе —
        разойдись они, «опрос отдаёт то же, что push» стало бы ложью, которую
        видно только на стенде (ADR-PM-035). Различие ровно одно и оно
        параметром: опрос зовёт с ``allowed_metrics=None``.

        Голоса здесь больше нет вовсе. Он сообщал об отсеве по владению —
        механизме, который Ф1 удалила: писатель стал сегментом пути, отсеивать
        по владению нечего, и «публикация в чужое имя» перестала существовать
        как событие.

        Args:
            allowed_metrics: разрешённые на этом тике имена листьев (``None`` →
                все).

        Returns:
            ``{"plugins": {писатель: {имя: значение}}}`` — пусто, если хранилища
            нет, оно пусто или всё придержал гейт.
        """
        from .telemetry import PLUGIN_LEVELS_ATTR, build_plugin_levels

        store = getattr(self._services, PLUGIN_LEVELS_ATTR, None)
        publications: Any = getattr(store, "publications", None)
        if not callable(publications):
            return {}  # ни один плагин процесса уровней не отдавал
        try:
            return build_plugin_levels(publications(), allowed_metrics)
        except Exception as exc:  # noqa: BLE001 — телеметрия не критична для такта HB
            _log = getattr(self._services, "log_debug", self._services.log_info)
            _log(f"Уровни плагинов недоступны: {exc}", module="heartbeat")
            return {}

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
        * ``state.plugins.<писатель>.<имя>`` — уровни, отданные плагинами
          процесса, каждый в поддереве СВОЕГО писателя (Ф1 «порт наблюдений»:
          владение = путь). Одинаковое имя у двух плагинов — два разных листа.

        **Почему один merge, а не три.** До Р3.5-12 тик слал три отдельных merge,
        и продовое правило троттла ``processes.**.state.fps: 0.05`` пропускало
        одну запись на путь за окно. Воспроизведено 2026-08-16: два merge с
        разницей 0.5 мс на Windows-сетке 15.6 мс читают ОДИН таймстамп, второй
        возвращает ``proceed=True`` с уже вырезанным листом и без
        ``rejection_reason`` — потерю не видел даже отправитель. Один merge
        возвращает систему к собственному принципу E6/Task 5.7 («один merge
        вместо 3W+2 set») и снимает с транспорта роль, которой у него нет.

        **Порядок наложения внутри payload больше не страхует — потому что
        страховать нечего.** Уровни плагинов кладутся ПЕРВЫМИ, агрегат
        фреймворка — поверх, и это осталось лишь стабильным порядком сборки.
        Столкновение имён исчезло структурно (Ф1): плагинный ``fps`` лежит под
        ``state.plugins.<писатель>.fps``, а агрегат — под ``state.fps``; ключа,
        за который они могли бы спорить, у них нет.

        Прежняя редакция называла порядок второй линией защиты при протечке
        отбора по владению и честно мерила её: инъекция «отбор по каталогу
        вместо владения» показала, что порядок спасал **1 случай из 5** (только
        ``fps``/``latency_ms`` и только при наличии агрегата на том же тике).
        Единственной настоящей защитой была проверка владельца в сборщике; вместе
        с ней ушёл и повод для второй линии.

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

        from .telemetry import build_router_shm_telemetry, build_worker_telemetry

        data: dict = {}
        state: dict = {}

        # (1) Уровни плагинов — первыми (см. «порядок наложения» выше).
        #
        # Поддерево ``plugins.<писатель>.<имя>``: ОДИН ключ ``plugins`` в секции
        # ``state``, а не россыпь плоских имён. Столкнуться с агрегатом
        # фреймворка оно больше не может по построению — ``fps`` плагина лежит
        # под ``plugins.<он>.fps``, а не рядом с ``state.fps``.
        state.update(self._collect_plugin_levels(allowed_metrics))

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

        # (4) Снятия здесь больше НЕТ, и это не пропуск.
        #
        # Прежний шаг клал ``None``-надгробие на плоский путь имени, чей писатель
        # ушёл, с запасом переутверждений и фильтром «только СВОИ имена» по
        # каталогу владения. Каталог владения удалён вместе с арбитражем (Ф1), а
        # во вложенной форме страж надгробия («имени нет в payload») ВСЕГДА
        # истинен для плагинных имён: имя ушедшего писателя лежит теперь под
        # ``plugins.<он>.<имя>``, в плоской секции его нет и не было — надгробие
        # легло бы на ``state.<имя>``, то есть на чужой (или несуществующий) лист
        # при живом писателе. Это ровно класс A1, который механизм чинил.
        #
        # Замена — удаление ПОДДЕРЕВА писателя дорогой ``state.delete`` (Ф2).
        # Интерим не заводится намеренно: между Ф1 и Ф2 механизма снятия из
        # дерева нет, и пара фаз поставляется вместе (§11.7 плана). Пока Ф2 не
        # пришла, лист остановленного плагина живёт в дереве с последним
        # значением — известная и принятая цена неделимой поставки, а не дефект,
        # который стоит прикрыть половинчатым надгробием.
        if state:
            data["state"] = state
        if not data:
            return  # показаний нет вовсе — пустой merge не шлём
        try:
            proxy.merge(f"processes.{self._services.name}", data)
        except Exception as exc:  # noqa: BLE001 — телеметрия не критична для такта HB
            _log = getattr(self._services, "log_debug", self._services.log_info)
            _log(f"Не удалось self-publish телеметрии процесса: {exc}", module="heartbeat")

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

        Task 3.5 сдвинула границу, но не стёрла её. Уровень, который плагин ОТДАЁТ
        (``ctx.publish_metric``), собирается здесь же и приезжает опросом — под
        ``state.plugins.<писатель>.<имя>``, в той же вложенной форме, что уходит
        push'ем. Объявления для этого больше не требуется: каталог остался именами
        для гейта и авто-строк GUI, а не правом на имя (Ф1). За границей осталось
        два РАЗНЫХ класса, и путать их нельзя (ADR-PM-038):

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

        # Уровни плагинов — тем же швом и в ту же секцию ``state``, в той же
        # вложенной форме ``plugins.<писатель>.<имя>``, что уходит push'ем.
        # Разойдись формы — «опрос отдаёт то же, что push» стало бы ложью,
        # которую видно только на стенде (ADR-PM-035, инвариант «один сборщик»).
        plugin_levels = self._collect_plugin_levels(None)
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
