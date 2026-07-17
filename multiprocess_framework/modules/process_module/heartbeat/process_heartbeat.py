"""ProcessHeartbeat — отправка периодических heartbeat-сообщений ProcessManager-у."""

from __future__ import annotations

import time
from typing import TYPE_CHECKING, Any, Callable

if TYPE_CHECKING:
    pass


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

        from ...worker_module import ThreadConfig, ThreadPriority

        self._interval = interval
        # PC 1.2: собрать publisher-gate из секции telemetry.publish (если задана).
        self._telemetry_gate = self._build_telemetry_gate()
        self._services.worker_manager.create_worker(
            "heartbeat_sender",
            self._loop,
            ThreadConfig(priority=ThreadPriority.BACKGROUND),
            auto_start=True,
        )
        _log = getattr(self._services, "log_debug", self._services.log_info)
        _log(
            f"Heartbeat воркер запущен (interval={interval}с)",
            module="heartbeat",
        )

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
                # Self-publish метрик процесса напрямую в дерево StateStore.
                self._publish_metrics_to_tree(workers, allowed_metrics)
                # Ф7 G.3 H8: SHM-счётчики router'а (pickle-fallback / torn / границы) в дерево.
                self._publish_router_shm_stats_to_tree(allowed_metrics)

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
            "status": getattr(self._services, "_current_process_status", "running"),
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
        # Task 1.2: gate использует ТОТ ЖЕ clock, что и heartbeat-планирование (для
        # fake-clock тестов каденции; в проде обоим — time.monotonic).
        return TelemetryGate(config, clock=self._clock)

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
        # Атомарный swap: сборка завершена — переприсваиваем ссылку целиком (под GIL).
        # Gate использует clock heartbeat'а (fake-clock тесты; в проде time.monotonic).
        self._telemetry_gate = TelemetryGate(config, clock=self._clock)

    def _publish_metrics_to_tree(self, workers: dict, allowed_metrics: Any = None) -> None:
        """Опубликовать телеметрию процесса и каждого воркера в дерево StateStore.

        Здоровый путь телеметрии: процесс САМ репортит свои метрики через
        собственный StateProxy (``state.set`` → ProcessManager → StateStoreManager
        → GUI) — тот же проверенный канал, что и статус процесса. Минует
        центральную heartbeat-агрегацию в ProcessMonitor (хрупкий лишний участок).
        См. ``plans/telemetry-self-publish-redesign.md``.

        Per-worker (строки таблицы воркеров в детальном виде процесса):
          - ``processes.{name}.workers.{w}.status``            — живой статус;
          - ``processes.{name}.workers.{w}.effective_hz``      — частота воркера;
          - ``processes.{name}.workers.{w}.cycle_duration_ms`` — время цикла (latency).

        Агрегат уровня процесса (карточка):
          - ``processes.{name}.state.fps``        = max(``effective_hz``) по
            running-воркерам с hz > 0 (ведущий loop-воркер задаёт темп);
          - ``processes.{name}.state.latency_ms`` = max(``cycle_duration_ms``) —
            время самого медленного воркера (узкое горло процесса).
        Нет ни одного hz > 0 → агрегат не публикуем (карточка остаётся «—»).

        Процессы без StateProxy (чисто системные) тихо пропускаются.

        PC 1.2: ``status`` воркеров публикуется всегда (вне гейта); частота/цикл/агрегат
        фильтруются ``allowed_metrics`` (выключенная/зажатая метрика не считается и не
        уходит в merge).

        Args:
            workers: снимок ``get_all_workers_status()`` (тайминг цикла на верхнем
                уровне каждого статуса).
            allowed_metrics: разрешённые на этом тике суффиксы метрик (``None`` → все,
                обратная совместимость).
        """
        proxy = getattr(self._services, "_state_proxy", None)
        if proxy is None or not workers:
            return

        # E6/Task 5.7: собрать все листья (per-worker + агрегат) в один вложенный
        # payload и отправить ОДНИМ proxy.merge вместо 3W+2 proxy.set — глубокий
        # merge сохраняет сиблинги (health.* и пр.), число сообщений ↓ ~в W раз.
        from .telemetry import build_worker_telemetry

        result = build_worker_telemetry(workers, self._services.name, allowed_metrics)
        if result is None:
            return
        path, data = result
        try:
            proxy.merge(path, data)
        except Exception as exc:
            _log = getattr(self._services, "log_debug", self._services.log_info)
            _log(f"Не удалось self-publish метрик процесса: {exc}", module="heartbeat")

    def _publish_router_shm_stats_to_tree(self, allowed_metrics: Any = None) -> None:
        """Ф7 G.3 H8 / G.4.a: счётчики кадрового транспорта router'а → дерево StateStore
        (тот же self-publish канал, что телеметрия/health). Публикует
        ``processes.{name}.state.shm.{...}``: pickle_fallbacks (громкий slow-path),
        torn_reads (гонка seqlock), boundary_crossings (границ/кадр), а также
        queue_data_evicted (Ф7 G.4.a — дроп из полных data-очередей, drop_oldest) —
        все сигналы потери кадра в одном месте для вкладки Pipeline. Публикует только
        при НЕнулевых счётчиках (иначе no-op — не засоряем дерево у процессов без
        кадрового пути).

        PC 1.2: группа ``shm`` проходит publisher-gate. ``allowed_metrics`` не None и
        без ``"shm"`` → выходим сразу (не считаем ``get_stats()`` — экономим источник).
        ``None`` → shm разрешён (обратная совместимость).
        """
        if allowed_metrics is not None and "shm" not in allowed_metrics:
            return  # shm выключен/зажат частотой — не считаем и не публикуем
        proxy = getattr(self._services, "_state_proxy", None)
        router = getattr(self._services, "router_manager", None)
        if proxy is None or router is None:
            return
        try:
            stats = router.get_stats()
            rs = stats.get("router", stats) if isinstance(stats, dict) else {}
            pickle_fallbacks = int(rs.get("frame_pickle_fallbacks", 0) or 0)
            torn = int(rs.get("frame_torn_reads", 0) or 0)
            crossings = int(rs.get("frame_boundary_crossings", 0) or 0)
            queue_evicted = int(rs.get("queue_data_evicted", 0) or 0)
            # Ф7 G.4.a: system-backpressure тоже виден (блокировки вытеснения из полной
            # system-очереди — control-plane терять нельзя; ревью 2026-07-14: раньше
            # surface был, но публикации не было — асимметрия с data_evicted).
            sys_blocked = int(rs.get("queue_system_evict_blocked", 0) or 0)
            # Ф7 G.5.c: дроп по post-use re-check zero-copy view (слот перезаписан под
            # живым view — consumer отстал > глубины кольца). Ещё один сигнал потери
            # кадра в том же месте для вкладки Pipeline.
            stale_drops = int(rs.get("frame_stale_drops", 0) or 0)
            # Ф7 G.5.d (В3): исчерпание free-list → drop-на-источнике (back-pressure,
            # читатели отстали). Тот же сигнальный набор потери кадра.
            loan_exhausted = int(rs.get("frame_loan_exhausted", 0) or 0)
            # Ф7 G.5 ревью-фикс 15: здоровье loan-цикла (released/reclaimed) — не потери,
            # но обязательный сигнал: если exhausted растёт, а released стоит на нуле —
            # release-контур не замкнут (ревью поймало именно это через отсутствие сигнала).
            slots_released = int(rs.get("frame_slots_released", 0) or 0)
            slots_reclaimed = int(rs.get("frame_slots_reclaimed", 0) or 0)
            # Ф7 G.7 (0.5): размер reader-кэша SHM-handle. НЕ потеря, а health-сигнал:
            # под zero-copy эвикция отключена → рост на инкарнацию = утечка handle
            # (резидуал G.5). Без handle-кэша (флаг off) = 0 → guard ниже сохраняет
            # прежний no-op (off = бит-в-бит).
            cache_size = int(rs.get("frame_handle_cache_size", 0) or 0)
            if (
                pickle_fallbacks == 0
                and torn == 0
                and crossings == 0
                and queue_evicted == 0
                and sys_blocked == 0
                and stale_drops == 0
                and loan_exhausted == 0
                and slots_released == 0
                and slots_reclaimed == 0
                and cache_size == 0
            ):
                return  # нет кадрового пути / всё чисто — не публикуем
            proxy.merge(
                f"processes.{self._services.name}.state.shm",
                {
                    "pickle_fallbacks": pickle_fallbacks,
                    "torn_reads": torn,
                    "boundary_crossings": crossings,
                    "queue_data_evicted": queue_evicted,
                    "queue_system_evict_blocked": sys_blocked,
                    "stale_drops": stale_drops,
                    "loan_exhausted": loan_exhausted,
                    "slots_released": slots_released,
                    "slots_reclaimed": slots_reclaimed,
                    "cache_size": cache_size,
                },
            )
        except Exception as exc:  # noqa: BLE001 — телеметрия не критична для такта HB
            _log = getattr(self._services, "log_debug", self._services.log_info)
            _log(f"Не удалось self-publish SHM-счётчиков: {exc}", module="heartbeat")

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
