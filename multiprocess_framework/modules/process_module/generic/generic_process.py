"""GenericProcess — backward-compat shim + data pipeline.

DEPRECATED: Используйте ProcessModule напрямую с config.plugins.
ProcessModule теперь нативно поддерживает плагины через PluginOrchestrator.

GenericProcess добавляет только app-specific data pipeline
(DataReceiver, PipelineExecutor, SourceProducer) — это не часть
фреймворка, а логика Inspector vision приложения.
"""

from __future__ import annotations

import queue

from ..core.process_module import ProcessModule
from .data_receiver import DataReceiver
from ...router_module.middleware.frame_shm_middleware import FrameShmMiddleware
from .inspector_registry import build_inspector
from .pipeline_executor import PipelineExecutor
from .plugin_runner import PluginRunner
from .source_producer import SourceProducer


# Ф7 G.7: copy-out терминалы кадрового fan-out — display/GUI-читатели. Они КОПИРУЮТ кадр
# и release loan-протокола (В3) НЕ шлют, поэтому в num_consumers (refcount владельца) НЕ
# входят. Владелец, чей fan-out состоит ТОЛЬКО из них, работает по В1 (round-robin) без
# loan (иначе refcount застревает → free-list исчерпание → drop-на-источнике).
# Ф7 ревью фазы G: ДЕФОЛТ, а не истина — имя процесса-дисплея принадлежит приложению,
# не framework'у. Рецепт/конфиг процесса перекрывает списком ``copy_out_targets``
# (мульти-дисплей: display_0/display_1/hmi — иначе они считались бы loan-aware, release
# от них не пришёл бы → free-list исчерпание). Полный вынос в топологию (роль
# потребителя на wire, не имя) — G.7/G.F.
_COPY_OUT_TARGETS: frozenset[str] = frozenset({"gui"})


def _count_loan_aware_consumers(chain_targets, copy_out_targets=None) -> int:
    """Число loan-aware потребителей кадра (шлют release) среди ``chain_targets``.

    copy-out терминалы исключаются — они кадр копируют и release НЕ шлют.
    ``copy_out_targets`` — из конфига процесса (``app_cfg["copy_out_targets"]``,
    рецепт-перекрытие для мульти-дисплеев); None → дефолт :data:`_COPY_OUT_TARGETS`.
    Цели дедуплицируются: дубль-target шлёт release ОДИН раз (dedup по reader в пуле),
    а завышенный refcount застрял бы навсегда. Результат = ``num_consumers``
    (refcount владельца, дизайн §8.2 G.5): занижение безопасно (В1 re-check дропнет),
    завышение → loan-exhaustion, поэтому считаем ТОЛЬКО реально релизящих потребителей.
    """
    copy_out = _COPY_OUT_TARGETS if copy_out_targets is None else frozenset(copy_out_targets)
    return len({t for t in (chain_targets or []) if t not in copy_out})


class GenericProcess(ProcessModule):
    """DEPRECATED: ProcessModule теперь поддерживает плагины нативно.

    GenericProcess = ProcessModule + data pipeline (app-specific).
    Plugin lifecycle (load → configure → start → shutdown) полностью
    обрабатывается ProcessModule через PluginOrchestrator.
    """

    def _init_application_threads(self) -> None:
        """super() делает plugin boot, здесь только data pipeline."""
        super()._init_application_threads()

        # Data pipeline — только если orchestrator загрузил плагины
        if self._orchestrator is not None:
            self._init_data_pipeline()

    # --- Data Pipeline (Phase 5) — остаётся без изменений ---

    def _init_data_pipeline(self) -> None:
        """Bootstrap data pipeline: DataReceiver, PipelineExecutor, SourceProducer."""
        app_cfg = self.get_config("config") or {}

        # Pipeline config
        chain_targets = app_cfg.get("chain_targets", [])
        queue_size = app_cfg.get("queue_size", 64)
        lag_threshold = app_cfg.get("lag_alert_threshold_sec", 2.0)
        source_fps = app_cfg.get("source_target_fps", 25.0)
        max_fails = app_cfg.get("error_max_consecutive_fails", 5)
        auto_reset = app_cfg.get("error_auto_reset_sec", 60.0)
        critical = app_cfg.get("error_critical_plugins", [])

        # Плагины через orchestrator
        all_plugins = self._orchestrator.plugins

        # Разделить плагины на source и processing
        source_plugins = [p for p in all_plugins if p.is_source]
        processing_plugins = [p for p in all_plugins if not p.is_source]

        # Если нет ни source, ни processing — pipeline не нужен
        if not source_plugins and not processing_plugins:
            return

        # FrameShmMiddleware — регистрируется НЕЗАВИСИМО от наличия memory_manager
        # (Ф7 G.6 ревью 2026-07-13, F3): без mm strip_and_write сам деградирует в
        # pickle-fallback (try/except внутри уже это делает), но middleware ДОЛЖЕН
        # быть на месте — иначе счётчик границ (frame_boundary_crossings) на этом
        # пути вообще не считает, а wire.configure-путь (builtin_commands.py) считает
        # всегда — раньше была асимметрия.
        router = getattr(self, "router_manager", None)
        # Ф7 G.4.b: глубина кольца per-camera из конфига процесса (рецепт). Гейт
        # FW_QOS_PROFILES (ревью 2026-07-14, откат бит-в-бит): off → None → middleware
        # даёт прежние 3; on → frame_ring_depth (или профиль). Каждый source-процесс =
        # свой owner = своё независимое кольцо (изоляция per-camera).
        from multiprocess_framework.modules.config_module.feature_flags import is_enabled

        frame_ring_depth = app_cfg.get("frame_ring_depth") if is_enabled("FW_QOS_PROFILES") else None
        # Ф7 G.7: num_consumers loan-протокола (В3) = число loan-aware потребителей кадра
        # этого owner'а из топологии (chain_targets минус copy-out/GUI). 0 → middleware
        # не создаёт пул (round-robin В1), исключая исчерпание free-list на GUI-only fan-out.
        # ``copy_out_targets`` из конфига процесса (рецепт: extras.copy_out_targets)
        # перекрывает дефолт {"gui"} — мульти-дисплей (display_0/hmi) объявляет своих
        # copy-out читателей сам. Пусто/отсутствует = «не задано» → дефолт (typed-поле
        # конфига даёт [] всем процессам — иначе дефолт {"gui"} молча отключился бы).
        copy_out_targets = app_cfg.get("copy_out_targets") or None
        num_consumers = _count_loan_aware_consumers(chain_targets, copy_out_targets)
        copy_out_view = sorted(_COPY_OUT_TARGETS if copy_out_targets is None else set(copy_out_targets))
        self._log_debug(
            f"GenericProcess[{self.name}]: loan num_consumers={num_consumers} "
            f"(chain_targets={list(chain_targets)}, copy-out {copy_out_view} исключены)"
        )
        shm_middleware = FrameShmMiddleware(
            memory_manager=self.memory_manager,
            owner=self.name,
            slot="output_frames",
            coll=frame_ring_depth,
            log_error=self._log_error,
            num_consumers=num_consumers,
        )
        if router is not None:
            # P3.1.2: Claim Check кадров — забота хаба, а не producer'ов. Регистрируем
            # send-middleware: SourceProducer/PipelineExecutor шлют msg с frame в data,
            # router сам выносит его в SHM (strip_and_write по generic-семантике). Guard
            # внутри метода (type=="data") — no-op для команд/heartbeat/state.
            router.add_send_middleware(shm_middleware.strip_data_frame_on_send)
            # Ф7 G.6 (F5): агрегация счётчика границ через RouterManager.get_stats()
            # (introspect.router_stats), БЕЗ колбэка — см. класс-докстринг middleware.
            router.register_frame_middleware(shm_middleware)
            # Ф7 G.5.d-2 (В3): owner-handler release'ов zero-copy займов. Consumer,
            # дочитав view, шлёт пачку тикетов (type="shm_release" на system-канал) →
            # event_dispatcher → сюда → декремент refcount владельца (release_slots
            # само no-op без loan-протокола). Регистрируем всегда (срабатывает только на
            # shm_release-сообщениях, которых нет без флага).
            router.register_message_handler("shm_release", lambda msg: self._handle_shm_release(msg, shm_middleware))
            # Ф7 G.5.e (В3): owner-handler reclaim'а займов мёртвого читателя. Supervisor
            # (confirmed-death соседа) шлёт {type:"shm_reclaim", data:{dead_reader}} →
            # сюда → reclaim_reader освобождает зависшие займы. Без авто-триггера мёртвый
            # держатель В1-безопасен (исчербание→drop, не corruption), но кадры теряются;
            # reclaim — штатное восстановление free-list.
            router.register_message_handler("shm_reclaim", lambda msg: self._handle_shm_reclaim(msg, shm_middleware))

        # Единый PluginRunner на процесс — общий шов вызова process()/produce() для
        # PipelineExecutor И SourceProducer. io-debug post-хук регистрируется ОДИН
        # раз здесь → наблюдение покрывает все плагины процесса.
        self._plugin_runner = PluginRunner(log_error=self._log_error)
        self._attach_io_peek(app_cfg)

        # chain_queue: DataReceiver -> PipelineExecutor
        self._chain_queue: queue.Queue = queue.Queue(maxsize=queue_size)

        # --- DataReceiver (если есть processing плагины) ---
        if processing_plugins:
            # Домен fan-in/join живёт в Plugins/_shared/fanin (C6 b); framework получает
            # готовый буфер через реестр (build_inspector), не зная конкретный класс.
            inspector = build_inspector(app_cfg, self._log_info, self._log_error, self._log_debug)
            self._data_receiver = DataReceiver(
                receive_fn=self.receive_message,
                shm_middleware=shm_middleware,
                inspector_manager=inspector,
                chain_queue=self._chain_queue,
                lag_alert_threshold_sec=lag_threshold,
                log_info=self._log_info,
                log_error=self._log_error,
                log_debug=self._log_debug,
                node_name=self.name,
            )
            # Подключить callback
            inspector._on_ready = self._data_receiver.on_items_ready

            # PipelineExecutor
            self._pipeline_executor = PipelineExecutor(
                plugins=processing_plugins,
                chain_targets=chain_targets,
                shm_middleware=shm_middleware,
                send_fn=self.send_message,
                max_consecutive_fails=max_fails,
                auto_reset_sec=auto_reset,
                critical_plugins=critical,
                log_info=self._log_info,
                log_error=self._log_error,
                log_debug=self._log_debug,
                node_name=self.name,
                plugin_runner=self._plugin_runner,
            )

            # Запуск workers через WorkerManager
            if self.worker_manager:
                self.worker_manager.create_worker(
                    worker_name="data_receiver",
                    target=self._data_receiver.run_loop,
                    config={"execution_mode": "loop", "priority": "REALTIME"},
                    auto_start=True,
                )
                # bound-метод (не lambda): иначе WorkerManager.get_worker_status
                # не найдёт get_cycle_metrics через target.__self__ → нет FPS в GUI.
                self._pipeline_executor.bind_queue(self._chain_queue)
                self.worker_manager.create_worker(
                    worker_name="pipeline_executor",
                    target=self._pipeline_executor.run,
                    config={"execution_mode": "loop", "priority": "REALTIME"},
                    auto_start=True,
                )
                self._log_info(
                    f"GenericProcess[{self.name}]: data pipeline started ({len(processing_plugins)} processing plugins)"
                )

        # --- SourceProducer (для каждого source-плагина) ---
        # Общий на процесс HealthReporter (Task 2.2): produce()-фейлы кормят тот же
        # честный breaker, что и плагины через ctx.health — единый агрегат здоровья
        # процесса (тот же _health_state, что читает heartbeat).
        from ..health import HealthReporter, get_or_create_health_state

        health_state = get_or_create_health_state(self)
        breaker_backoff = app_cfg.get("source_breaker_backoff_sec", 1.0)

        self._source_producers: list[SourceProducer] = []
        for i, source_plugin in enumerate(source_plugins):
            producer = SourceProducer(
                plugin=source_plugin,
                shm_middleware=shm_middleware,
                send_fn=self.send_message,
                chain_targets=chain_targets,
                target_fps=source_fps,
                log_info=self._log_info,
                log_error=self._log_error,
                log_debug=self._log_debug,
                node_name=self.name,
                plugin_runner=self._plugin_runner,
                health=HealthReporter(health_state, source=source_plugin.name),
                breaker_backoff_sec=breaker_backoff,
            )
            self._source_producers.append(producer)

            if self.worker_manager:
                worker_name = f"source_producer_{source_plugin.name}"
                self.worker_manager.create_worker(
                    worker_name=worker_name,
                    target=producer.run_loop,
                    config={"execution_mode": "loop", "priority": "REALTIME"},
                    auto_start=True,
                )
                self._log_info(f"GenericProcess[{self.name}]: source '{source_plugin.name}' producer started")

    def _handle_shm_release(self, msg: dict, shm_middleware) -> None:
        """Ф7 G.5.d-2 (В3): owner-handler release-пачки zero-copy займов.

        Consumer, дочитав view, шлёт ``{type:"shm_release", data:{releases:[...]}}`` →
        event_dispatcher → сюда. Делегируем в middleware (release_slots само no-op без
        loan-протокола). Ошибка/битый конверт не роняет процесс (наблюдаемость через
        лог); потеря release покрыта В1-страховкой + reclaim (G.5.e).
        """
        try:
            data = msg.get("data", {}) if isinstance(msg, dict) else {}
            releases = data.get("releases", []) if isinstance(data, dict) else []
            if releases:
                shm_middleware.release_slots(releases)
        except Exception as exc:  # noqa: BLE001 — release не критичен для такта
            self._log_error(f"GenericProcess[{self.name}]: shm_release handler error: {exc}")

    def _handle_shm_reclaim(self, msg: dict, shm_middleware) -> None:
        """Ф7 G.5.e (В3): owner-handler reclaim'а. Supervisor по confirmed-death соседа
        шлёт ``{data:{dead_reader}}`` → освобождаем зависшие займы мёртвого читателя.
        Битый конверт не роняет процесс."""
        try:
            data = msg.get("data", {}) if isinstance(msg, dict) else {}
            dead_reader = data.get("dead_reader", "") if isinstance(data, dict) else ""
            if dead_reader:
                shm_middleware.reclaim_reader(dead_reader)
        except Exception as exc:  # noqa: BLE001 — reclaim не критичен для такта
            self._log_error(f"GenericProcess[{self.name}]: shm_reclaim handler error: {exc}")

    def _attach_io_peek(self, app_cfg: dict) -> None:
        """Подключить io-debug publisher к PluginRunner (opt-in, по умолчанию вкл).

        Читает секцию процесса ``io_peek: {enabled, rate_hz, head_len}``. Когда
        включено — вешает pre/post-хуки IoPeekPublisher, публикующие O(1) сводку
        in/out каждого плагина в ``processes.{proc}.plugins.{plugin}.io_peek``
        (throttle rate_hz). Выключено или нет state_proxy → хуки не вешаются,
        раннер остаётся пустым (нулевой overhead, гарантия Этапа 4).
        """
        cfg = app_cfg.get("io_peek", {}) or {}
        if not cfg.get("enabled", True):
            return
        # Прототип (GenericProcessApp) хранит живой StateProxy в self._state_proxy
        # (создан в _init_custom_managers ДО _init_application_threads); базовый
        # self.state_proxy — конструкторный арг (часто None). Берём приватный, затем публичный.
        state_proxy = getattr(self, "_state_proxy", None) or getattr(self, "state_proxy", None)
        if state_proxy is None:
            self._log_info(f"GenericProcess[{self.name}]: io-debug отключён (нет state_proxy)")
            return
        from ..plugins.io_peek import IoPeekPublisher

        publisher = IoPeekPublisher(
            state_proxy=state_proxy,
            process_name=self.name,
            rate_hz=cfg.get("rate_hz", 1.0),
            head_len=cfg.get("head_len", 3),
            log_error=self._log_error,
        )
        publisher.attach(self._plugin_runner)
        # Держим ссылку (хуки — bound-методы publisher, иначе GC).
        self._io_peek_publisher = publisher
        self._log_info(f"GenericProcess[{self.name}]: io-debug publisher активен (rate={cfg.get('rate_hz', 1.0)} Гц)")
