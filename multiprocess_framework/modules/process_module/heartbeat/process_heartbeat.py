"""ProcessHeartbeat — отправка периодических heartbeat-сообщений ProcessManager-у."""

from __future__ import annotations

import time
from typing import TYPE_CHECKING, Any, Callable, Dict, Optional

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


def _observation_port_of(services: Any) -> Any:
    """Порт наблюдений процесса — ЕДИНСТВЕННАЯ дорога heartbeat к уровням (Ф3).

    До задачи 3.1 состояние доставалось сырым ``getattr(services,
    PLUGIN_LEVELS_ATTR)`` в трёх местах этого файла, и в каждом стояла своя
    duck-typed проверка «а есть ли у него нужный метод». Три копии одного
    вопроса — три места, где ответ может разойтись; теперь вопрос задаётся один
    раз и не здесь. Часы остались у heartbeat (тик, publisher-гейт, один merge
    за такт), правда переехала в порт.

    ``create=False``: тик не заводит хранилище. У процесса без единой публикации
    его нет, и заводить пустое на каждом такте значило бы стереть разницу между
    «плагины уровней не отдавали» и «отдавали, но всё придержал гейт».

    Флаг доходит до КОНЦА дороги, а не до резолвера: со ступени 1 возвращается
    менеджер, и решение о создании принимает уже он
    (``ObservationManager.levels(create=…)``). До правки ревью 2026-08-25 порт из
    слота заводил хранилище безусловно, и один вызов :meth:`_level_names` на
    настоящем ``ProcessModule`` поднимал ``plugin_levels`` из ``None`` — то есть
    обещание держалось везде, КРОМЕ боевой сборки.

    Свободная функция, а не метод, и это не мелочь: три шага тика обязаны
    зависеть от ``self`` ровно тем, чем зависели до Ф3, — одним ``_services``.
    Сделай резолв методом — и минимальный носитель ``SimpleNamespace(_services=…)``,
    которым существующие тесты зовут шаг снятия напрямую, потребовал бы
    собственной копии резолва, то есть фейк доказывал бы фейк.

    Импорт ЛЕНИВЫЙ — тем же жестом, что у соседних ``from .telemetry import …``
    ниже: ``statistics_module`` и ``process_module`` тянут друг друга, и порядок
    загрузки не должен решать, кто получит частично инициализированный пакет.

    Returns:
        Порт либо ``None`` — «уровней у процесса нет», обычное состояние
        процесса без плагинов, а не сбой.
    """
    from ...statistics_module.observation.observation_manager import observation_port

    return observation_port(services)


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
        # Ф4 (задача 4.1): политика порта по ПУТЯМ дерева. Держится отдельным
        # полем, а не только внутри гейта, потому что переживает пересборку
        # гейта: `telemetry.reconfigure` меняет легаси-секцию и обязан сохранить
        # действующую политику, иначе правка одной плоскости молча сносила бы
        # другую (ровно класс «второй писатель сокращает кольцо»).
        self._observation_policy: Any = None
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
                #
                # Ф4 (задача 4.1): решений стало ДВА, потому что плоскостей две.
                # До Ф4 обе спрашивали одно множество имён — и именно поэтому
                # правило одной неизбежно задевало другую (решение принималось по
                # ИМЕНИ, а имя у них общее). Теперь фреймворковую плоскость
                # решает `due_metrics` (путь `…state.<имя>`), а поддерево порта —
                # `due_plugin_metrics` (путь `…state.plugins.<писатель>.<имя>`),
                # и правило адресует ровно ту, которую назвал оператор.
                if gate is not None:
                    allowed_metrics = gate.due_metrics()
                    allowed_levels: Any = gate.due_plugin_metrics(self._level_names_by_writer())
                    # Ф0.4 (m6): цикл оценки завершён — правила поддерева порта
                    # получили свой шанс совпасть, и только теперь «ноль
                    # попаданий» у правила означает «не совпало», а не «ещё не
                    # спрашивали». Отметка ЯВНАЯ, а не счётчик резолвов:
                    # диагностическое чтение (`provenance_for`) резолвит с
                    # `count=False` и тиком не является.
                    observation_policy = self._observation_policy
                    if observation_policy is not None:
                        observation_policy.mark_tick()
                else:
                    allowed_metrics = None
                    allowed_levels = None
                # Self-publish телеметрии процесса напрямую в дерево StateStore:
                # воркеры + агрегат + shm + уровни плагинов ОДНИМ merge (Р3.5-12).
                self._publish_telemetry_to_tree(workers, allowed_metrics, allowed_levels)

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

        Ф4 (задача 4.1): в тот же голос вошли glob-правила порта — их частота
        упирается в тот же потолок, а через ``config`` они не проходят вовсе.

        Ф2 (задача 2.3, M9, шаг 2). **Больше не no-op при ``tick_sec is None``.**
        Такт существует и без явного ``tick_sec`` — он тогда просто равен
        ``heartbeat_interval`` (см. :meth:`_telemetry_tick`, та же формула), и метрика
        может упираться в НЕГО ровно так же, как в явный ``tick_sec``. Раньше эта ветка
        возвращалась немедленно (см. историю метода) — голос молчал ВСЕГДА, независимо
        от того, зажата ли метрика фактическим тактом. Эффективный тик считается ИЗ
        ``config`` (параметра), а не из :meth:`_telemetry_tick` — на пути
        :meth:`_build_telemetry_gate` этот метод зовётся ДО того, как ``config``
        становится живым гейтом (``self._telemetry_gate`` в этот момент ещё старый),
        поэтому вопрос о такте обязан решаться по тому же ``config``, который проверяется.

        **Находка стадии 2, СУЖЕНИЕ шага 2 — не в тексте задачи, требует подтверждения
        владельца (см. отчёт реализатора).** В ветке ``tick_sec is None`` политика порта
        (``self._observation_policy``) в голос НЕ идёт — только явные записи
        ``config.metrics`` (то же сужение уже стоит в :func:`~.telemetry.capped_metrics`
        для каталога по имени, см. её докстринг). Причина числом: дефолт поддерева
        порта (:data:`~..configs.observation_policy.DEFAULT_SUBTREE_INTERVAL_SEC` = 1.0)
        меньше дефолта такта (``heartbeat_interval_sec`` = 5.0) БЕЗУСЛОВНО — эти два
        дефолта разных задач (4.1 и 2.3) никогда не сверялись друг с другом. Без этого
        сужения ЛЮБОЙ boot с ``tick_sec`` не заданным (боевой конфиг прототипа —
        именно такой) кричал бы про предохранитель поддерева, которого оператор не
        трогал, на КАЖДОЙ пересборке гейта НАВСЕГДА — воспроизведено 10 красными в
        существовавшем ДО этой задачи наборе (``test_metric_catalog_order_gate.py``,
        ``test_metric_catalog_producer_hazards.py``, ``test_telemetry_gate.py``,
        ``test_telemetry_tick.py::test_no_warning_when_tick_sec_none``,
        ``test_writer_subtree_acceptance.py``) — все они ждут тишины на boot без
        явной конфигурации, и все называли ``processes.*.state.plugins.**``
        источником шума. Явный ``tick_sec`` (ветка ``if`` выше) политику по-прежнему
        видит — это Ф4-поведение, которое задача 2.3 не трогает и не обязана трогать.
        """
        tick_sec = getattr(config, "tick_sec", None)
        if isinstance(tick_sec, (int, float)) and tick_sec > 0:
            effective_tick = min(self._interval, float(tick_sec))
            policy = self._observation_policy
        else:
            effective_tick = self._interval
            policy = None
        from .telemetry import capped_metrics

        capped = capped_metrics(config, effective_tick, policy)
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

        # Ф4 (задача 4.1): политика порта резолвится ДО гейта и живёт отдельно от
        # него. Порядок важен: секция `observability.observation` — L0..L3 слоями,
        # а легаси `telemetry.publish` — именованный источник ТОЙ ЖЕ сборки; гейт
        # получает обе одним объектом.
        self._install_observation_policy(self._resolve_observation_policy())
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
        gate = self._make_gate(config)
        # Task 2.3: WARNING по ключам metrics, отсутствующим в каталоге метрик (опечатка).
        # ПОСЛЕ `_make_gate` (Ф0.3, находка M1) — той же причины, что у соседнего
        # `_warn_capped_metrics` в `reconfigure_telemetry`: голос судит конфиг по
        # каталогу, а каталог наполняется ИМПОРТОМ, и именно `_make_gate` тянет
        # `.telemetry` — производителя четырёх из пяти метрик фреймворка. Голос
        # раньше импорта видел каталог из одной `shm` и объявлял живые `fps` /
        # `latency_ms` опечатками (семь ложных WARNING за boot webcam_sketch).
        self._warn_unknown_metrics(config)
        # Голос на УСПЕХЕ — вторая половина пары. Лог только на отказе не отличает
        # «гейт выключен» от «код не исполнялся вовсе».
        self._log_heartbeat(
            f"[telemetry] publisher-gate активен: default_enabled={config.default_enabled}, "
            f"явных правил {len(config.metrics)}, интервал по умолчанию "
            f"{config.default_interval_sec} с"
        )
        return gate

    def _make_gate(self, config: Any) -> Any:
        """Собрать ``TelemetryGate`` из легаси-секции и действующей политики порта.

        Одна точка сборки на все три дороги (старт, ``telemetry.reconfigure``,
        ``config.reload`` с секцией порта): разойдись они хоть в одном
        аргументе — и правка одной дороги давала бы гейт без политики, то есть
        молча возвращала бы плоскость порта под старое решение по имени.

        **Счёт попаданий правил переносится в новый объект** (находка З3 ревью
        Ф4). Сюда приходит КАЖДАЯ правка легаси-плоскости — то есть каждое
        движение пульта, — а правила порта при этом не менялись. Без переноса
        соседняя правка обнуляла бы счёт, и работающее правило возвращалось бы
        в ``rules_matched_nothing``: единственный голос про опечатку в ПУТИ
        начинал бы кричать на здоровые правила.
        """
        from ..configs.observation_policy import ObservationPolicy
        from .telemetry import TelemetryGate

        policy = self._observation_policy
        if policy is None:
            policy = ObservationPolicy(None, config)
            self._install_observation_policy(policy)
        else:
            # Легаси-секция могла смениться этой же командой — политика обязана
            # держать АКТУАЛЬНУЮ: она читает из неё умолчание и белый список.
            # Возраст правил переносится вместе со счётом (Ф0.4, m6): иначе
            # чужая правка возвращала бы все правила в `rules_pending`.
            policy = ObservationPolicy(
                policy.config,
                config,
                hits=policy.rule_hits(),
                evaluated_ticks=policy.evaluated_ticks,
                rule_first_tick=policy.rule_first_tick(),
            )
            self._install_observation_policy(policy)
        return TelemetryGate(
            config,
            clock=self._clock,
            policy=policy,
            process=str(getattr(self._services, "name", "") or ""),
        )

    def _install_observation_policy(self, policy: Any) -> None:
        """Поставить политику на место — ОБА её потребителя, одним швом (Ф2, задача 2.1).

        Потребителя два: гейт УРОВНЕЙ (через поле ``_observation_policy``, из
        которого его собирает :meth:`_make_gate`) и гейт ЧИСЕЛ (порт наблюдений,
        :meth:`ObservationManager.attach_numbers_policy`). Механизм при этом ОДИН
        — один объект политики, одна секция конфига, один счёт попаданий; вторая
        сборка означала бы две политики с похожими именами, расходящиеся тем
        тише, чем реже на них смотрят.

        **Шов, а не четыре ветки.** Политика встаёт на место из ЧЕТЫРЁХ мест
        (загрузочный резолв, две ветки ``_make_gate``, ``apply_observation_policy``),
        и до этой правки каждое присваивало поле напрямую. Допиши доставку в
        порт в три из четырёх — и четвёртая дорога тихо оставляла бы числа без
        политики; ровно этот класс («провод есть, маршрута нет») уже стоил
        проекту живого разбора.

        Отказ доставки НЕ роняет такт: порт может быть не зарегистрирован
        (процесс, поднятый не через ``ProcessManagers.register_all``), а ступень 2
        резолвера отдаёт вид без менеджера, у которого этого метода нет вовсе.
        Уровни в обоих случаях продолжают работать — и молчание здесь честное:
        числа такого процесса никуда и не доставляются (см.
        ``bare_port_number_losses``).
        """
        self._observation_policy = policy
        try:
            from ...statistics_module.observation.observation_manager import observation_port

            port = observation_port(self._services)
            attach = getattr(port, "attach_numbers_policy", None)
            if callable(attach):
                attach(policy)
        except Exception as exc:  # noqa: BLE001 — доставка политики чисел не смеет ронять такт
            self._log_heartbeat(f"[observation] политика чисел не доставлена в порт: {exc!r}")

    def _resolve_observation_policy(self) -> Any:
        """Политика порта из секции ``observability.observation`` разрешённых слоёв.

        Слои не читаются (процесс без конфига, иммутабельный дубль) → политика
        дефолтов L0. Это НЕ «механизма нет»: дефолтное правило поддерева порта и
        есть решение владельца (вариант «в»), и отсутствие секции означает
        «оператор его не правил», а не «его нет».
        """
        from ..configs.observability_layers import process_observability_layers
        from ..configs.observation_policy import OBSERVATION_SECTION_KEY, ObservationPolicy, ObservationPolicyConfig

        section: Any = None
        try:
            section = process_observability_layers(self._services).resolve().get(OBSERVATION_SECTION_KEY)
        except Exception as exc:  # noqa: BLE001 — процесс без слоёв живёт на дефолтах L0
            self._log_heartbeat(f"[observation] секция observability.{OBSERVATION_SECTION_KEY} не прочитана: {exc!r}")
        try:
            config = ObservationPolicyConfig.from_dict(section)
        except Exception as exc:  # noqa: BLE001 — негодная секция не смеет ронять такт
            self._log_heartbeat(
                f"[observation] секция observability.{OBSERVATION_SECTION_KEY} отвергнута ({exc!r}) — "
                "действуют дефолты L0"
            )
            config = ObservationPolicyConfig()
        return ObservationPolicy(config, None)

    def apply_observation_policy(self, section: Any) -> Dict[str, Any]:
        """Применить секцию ``observability.observation`` к ЖИВОМУ гейту (Ф4, 4.1).

        Третья точка дороги ручки — та, без которой ``config.reload`` менял бы
        слой и не менял поведение: гейт собирается один раз на старте, и правка,
        не дошедшая до него, осталась бы видимой в провенансе и не действующей
        (тот же довод, что у ``apply_event_selector``).

        Потокобезопасность — ДОСЛОВНО та же, что у
        :meth:`reconfigure_telemetry`: новый ``TelemetryGate`` собирается
        ЦЕЛИКОМ, и только потом ссылка ``self._telemetry_gate`` переприсваивается
        (атомарно под GIL). ``_loop`` читает эту ссылку в локальную переменную
        один раз за тик, поэтому такт работает либо со старым гейтом целиком,
        либо с новым целиком. Расписание (``_next_due``) у нового гейта пустое —
        как и при смене легаси-секции: одна публикация сразу после правки.

        Returns:
            Применённая политика (``effective_view``) — она едет в ответ команды
            и в readback. Гейта нет (нет секции ``telemetry.publish``) → политика
            всё равно запоминается и подействует, как только гейт появится;
            ответ несёт ``gate_active: false``, чтобы «применено» не читалось как
            «действует».
        """
        from ..configs.observation_policy import ObservationPolicy, ObservationPolicyConfig
        from .telemetry import TelemetryGate

        config = ObservationPolicyConfig.from_dict(section)
        gate = self._telemetry_gate
        legacy = getattr(gate, "config", None) if gate is not None else None
        live = self._observation_policy
        # **Пересборка ТОЛЬКО при реальном расхождении.** Пересборка гейта
        # обнуляет расписание (`_next_due`), а зовут эту функцию КАЖДЫЙ
        # `config.reload` — в том числе тот, что менял `log_level` и про порт не
        # сказал ни слова. Без этой сверки соседняя ручка сбрасывала бы частотный
        # предохранитель порта, то есть чужая правка молча меняла бы темп
        # публикации. Сверяется СОДЕРЖИМОЕ политики, а не «упоминал ли кто-то
        # секцию»: липкий флаг соседней плоскости отвечает на другой вопрос и
        # здесь дал бы тот же сброс на каждом reload'е после первой правки.
        if live is not None and live.config.model_dump() == config.model_dump():
            applied = dict(live.effective_view())
            applied["gate_active"] = gate is not None
            return applied
        # Счёт попаданий переживает пересборку — см. `_make_gate` (находка З3).
        # Вместе с ним переносится ВОЗРАСТ каждого правила (Ф0.4, m6): правило,
        # которое эта же правка ДОБАВИЛА, в переносе отсутствует и честно
        # начинает возраст с нуля — то есть едет в `rules_pending`, а не в
        # обвиняемые.
        policy = ObservationPolicy(
            config,
            legacy,
            hits=live.rule_hits() if live is not None else None,
            evaluated_ticks=live.evaluated_ticks if live is not None else 0,
            rule_first_tick=live.rule_first_tick() if live is not None else None,
        )
        self._install_observation_policy(policy)
        if gate is not None:
            # Сборка завершена — только теперь подменяем ссылку (см. докстринг).
            self._telemetry_gate = TelemetryGate(
                legacy,
                clock=self._clock,
                policy=policy,
                process=str(getattr(self._services, "name", "") or ""),
            )
        if legacy is not None:
            # Голос про недостижимую частоту — и для новых glob-правил тоже.
            self._warn_capped_metrics(legacy)
        applied = dict(policy.effective_view())
        applied["gate_active"] = gate is not None
        self._log_heartbeat(
            f"[observation] политика порта применена: поддерево "
            f"{applied['subtree']} enabled={applied['subtree_enabled']} "
            f"частота {applied['subtree_interval_sec']} с, явных правил {len(applied['rules'])}, "
            f"гейт активен={applied['gate_active']}"
        )
        return applied

    def apply_heartbeat_interval(self, value: Any) -> float:
        """Применить ``observability.heartbeat_interval_sec`` к ЖИВОМУ такту (Ф2, 2.3, шаг 1).

        Третья точка дороги ручки — та же роль, что у :meth:`apply_observation_policy`
        для секции порта: без неё ``config.reload`` менял бы слой и не менял поведение.

        ``value is None`` — секция слоями не задана (ключ ушёл из L3 по TTL, либо его
        не было ни в одном слое) — применяется СХЕМНЫЙ дефолт (5.0), а не «оставить как
        было»: `_rebuild_and_apply` — это пересборка ИЗ ИСТОЧНИКОВ (см. докстринг
        ``observability_reload.apply_observability_layers``), и снятие ключа обязано
        вернуть такт к L0 так же, как это уже устроено у соседних плоскостей
        (``observation``/``voices``/``events``/``flight``).

        Негодное значение (не число, отрицательное) — тот же откат к дефолту, без
        исключения: readback инициатора и так увидит применённое число, а падать
        heartbeat'у на кривом ``config.reload`` незачем (тот же довод, что у
        :meth:`start`, где парсинг ``heartbeat_interval`` укрыт тем же ``try``).

        Никакого рестарта: только атомарное присваивание ``self._interval`` — воркер,
        если он уже запущен, подхватит новое значение на СЛЕДУЮЩЕЙ итерации `_loop`
        (та же семантика, что у смены ``tick_sec`` через `reconfigure_telemetry`).

        Returns:
            Применённое значение (для readback в ответе ``config.reload``).
        """
        try:
            interval = float(value) if value is not None else 5.0
        except (TypeError, ValueError):
            interval = 5.0
        self._interval = interval
        self._log_heartbeat(f"[heartbeat] такт применён рантайм-командой: {interval} с")
        return interval

    def current_observation_policy(self) -> Optional[Dict[str, Any]]:
        """Действующая политика порта — readback для ``introspect``/вердикта.

        Читается ЖИВОЙ объект, а не конфиг: пересчёт из того же источника
        показывал бы согласие всегда, в том числе когда правка до гейта не
        доехала.
        """
        policy = self._observation_policy
        if policy is None:
            return None
        view = dict(policy.effective_view())
        view["gate_active"] = self._telemetry_gate is not None
        view["rules_matched_nothing"] = policy.rules_matched_nothing()
        # Ф0.4 (m6): правила, ещё не дожившие до цикла оценки, — отдельным
        # полем. «Свежее» и «не совпало ни с чем» — разные диагнозы, и до этой
        # задачи они ехали одним списком: правило обвинялось в тот же миг, когда
        # его применили.
        view["rules_pending"] = policy.rules_pending()
        # Счёт, а не «ноль/не ноль»: правило, совпадающее раз в час, и правило,
        # совпадающее каждый такт, — разные факты (открытый вопрос З3 ревью Ф4).
        view["rule_hits"] = policy.rule_hits()
        # Ф2 (задача 2.3, M9, шаг 3): та же «честная каденция», что у
        # `current_resolved_metrics` ниже, но для правил ПОРТА. `cap_candidates`
        # (`configs/observation_policy.py`) уже собирает ПОЛНЫЙ охват правил порта,
        # включая дефолт поддерева, — тем же сборщиком, что и голос
        # `_warn_capped_metrics` (находка З1 ревью Ф4: два отчёта о потолках,
        # разошедшихся в охвате). Здесь тот же сборщик даёт readback, а не голос.
        from ..configs.observation_policy import cap_candidates

        tick = self._telemetry_tick()
        effective: Dict[str, Dict[str, Any]] = {}
        for pattern, rule in cap_candidates(view).items():
            raw = rule.get("interval_sec")
            interval = float(raw) if isinstance(raw, (int, float)) and not isinstance(raw, bool) else 0.0
            effective[pattern] = {"interval_sec": interval, "effective_interval_sec": max(interval, tick)}
        view["effective"] = effective
        return view

    def current_resolved_metrics(self) -> Optional[Dict[str, Any]]:
        """Решение ЖИВОГО гейта по каждому имени каталога — с ПУТЁМ, о котором оно.

        Существует из-за блокера Б1 ревью Ф4: ``introspect.telemetry.resolved``
        считался из одной легаси-секции и выдавал вердикт про ИМЯ, а решение по
        плагинному листу с тем же именем принимает политика порта по ПУТИ. На
        стенде это дало два взаимно противоречащих readback'а об одном листе:
        ``resolved`` показывал ``enabled: false`` для ``frame_count``, а лист
        продолжал шагать. Теперь ответ (а) считается тем же гейтом, что и решает,
        и (б) НАЗЫВАЕТ путь, к которому относится, — плоскость фреймворка
        ``processes.<P>.state.<имя>``.

        **Второй заход, живой стенд 2026-08-26.** Одного пути мало: имя из
        каталога может не жить в этой плоскости вовсе. ``capture_fps`` стоял
        здесь как ``enabled: false`` по пути ``…state.capture_fps``, куда не
        пишет никто, — при работающем 21.3 по ``…state.plugins.capture.capture_fps``.
        Отсылка в соседнюю команду предупреждала, но вердикт всё равно читался
        как «погашена». Поэтому у имени, живущего в поддереве писателя, рядом
        стоит ``port_paths`` — вердикт по КАЖДОМУ реальному пути, посчитанный
        ТЕМ ЖЕ гейтом, — и флаг ``also_decided_by_port``.

        Расписание не двигается: ``decide(..., count=False)`` — ни ``_next_due``,
        ни счёт попаданий правил.

        **Размер ответа растёт с числом ЖИВЫХ писателей** (названо ревью,
        итерация 2): у имени, которое публикуют N писателей, будет N вердиктов.
        Замерено: 200 писателей одного имени → 20 449 байт всего ``resolved``.
        Живьём это единицы плагинов на процесс, потолка поэтому нет; если
        писателей станет много, резать надо здесь, а не у читателя.

        Returns:
            ``{имя: {enabled, interval_sec, path[, port_paths, also_decided_by_port]}}``
            либо ``None``, если гейта нет.
        """
        gate = self._telemetry_gate
        if gate is None:
            return None
        from ..configs.telemetry_publish_config import gated_metrics
        from .telemetry import plugin_metric_path, state_metric_path

        process = str(getattr(self._services, "name", "") or "")
        by_writer = self._level_names_by_writer()
        # Ф2 (задача 2.3, M9, шаг 3): ДОСТИЖИМЫЙ интервал — тот же `_telemetry_tick`,
        # что решает реальный такт воркера, а не пересчёт его составляющих. Один раз
        # на весь снимок: тик не меняется между метриками ОДНОГО ответа.
        tick = self._telemetry_tick()
        out: Dict[str, Any] = {}
        for metric in gated_metrics():
            path = state_metric_path(process, metric)
            enabled, interval = gate.decide(path, metric, count=False)
            entry: Dict[str, Any] = {
                "enabled": bool(enabled),
                "interval_sec": float(interval),
                # M9: заявленный `interval_sec` мог и раньше не совпадать с
                # действующей частотой (тик режет её сверху) — расхождение «сконфигу-
                # рировано 1с, действует 5с» было слышно только в логе WARNING на
                # пересборке, а не в этом readback'е.
                "effective_interval_sec": max(float(interval), tick),
                "path": path,
            }
            # Второй адрес того же ИМЕНИ. Живой стенд 2026-08-26: `capture_fps`
            # стоял здесь как `enabled: false` по пути `…state.capture_fps`,
            # которого не пишет никто, — рядом с работающим 21.3 по пути
            # `…state.plugins.capture.capture_fps`. Вердикт был верен для СВОЕЙ
            # плоскости и читался как «метрика погашена». Отсылка к соседней
            # команде (`resolved_plane`) — предупреждение, а не ответ; ответ —
            # вердикт по КАЖДОМУ реальному пути, посчитанный тем же гейтом.
            writers = sorted(w for w, names in by_writer.items() if metric in names)
            if writers:
                port_paths: Dict[str, Any] = {}
                for writer in writers:
                    port_path = plugin_metric_path(process, writer, metric)
                    p_enabled, p_interval = gate.decide(port_path, metric, count=False)
                    port_paths[port_path] = {
                        "enabled": bool(p_enabled),
                        "interval_sec": float(p_interval),
                        # M9: тот же тик решает достижимую частоту у ВСЕХ путей
                        # этого имени — плагинного и фреймворкового (один механизм).
                        "effective_interval_sec": max(float(p_interval), tick),
                    }
                entry["port_paths"] = port_paths
                # Прямая подсказка оператору: вердикт выше — не про то место,
                # где это имя реально живёт у ЭТОГО процесса.
                entry["also_decided_by_port"] = True
            out[metric] = entry
        return out

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

    def current_telemetry_tick(self) -> float:
        """Достижимый тик воркера — readback-обёртка над :meth:`_telemetry_tick` (Ф2, 2.3, M9).

        Сама формула (``min(heartbeat_interval, tick_sec)``, фолбэк на
        ``heartbeat_interval``) — уже существующий приватный метод; здесь только имя
        из публичной readback-поверхности (тот же ряд, что `current_observation_policy`
        / `current_resolved_metrics` / `current_telemetry_publish` ниже), потому что
        значение это идёт наружу — в ответ команды `introspect.telemetry`
        (``tick_effective_sec``), а звать приватный метод другого модуля через границу
        readback'а — не эта дорога.
        """
        return self._telemetry_tick()

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

        config = TelemetryPublishConfig.from_dict(publish_section)
        # Атомарный swap: сборка завершена — переприсваиваем ссылку целиком (под GIL).
        # Gate использует clock heartbeat'а (fake-clock тесты; в проде time.monotonic).
        # Ф4: политика порта ПЕРЕЖИВАЕТ пересборку легаси-секции — `_make_gate`
        # пересобирает её поверх новой легаси-секции, а не выбрасывает.
        gate = self._make_gate(config)
        # Task 2.3: WARNING по ключам metrics, отсутствующим в каталоге метрик (опечатка).
        # ПОСЛЕ `_make_gate` (Ф0.3, находка M1): каталог наполняется импортом, а
        # `.telemetry` — производителя `fps`/`latency_ms`/`effective_hz`/
        # `cycle_duration_ms` — тянет именно `_make_gate`. Второй вход сюда попадает
        # первым, если рантайм-команда пришла раньше первой сборки гейта (гейт при
        # старте не собран, когда секции `telemetry.publish` в конфиге нет вовсе), —
        # тогда порядок значит здесь ровно то же, что и на буте.
        self._warn_unknown_metrics(config)
        # Task 1.2: WARNING по метрикам, чья частота ограничена телеметрийным тиком.
        # ПОСЛЕ `_make_gate`: голос считает и glob-правила порта, а они живут в
        # политике, которую `_make_gate` только что и пересобрал.
        self._warn_capped_metrics(config)
        self._telemetry_gate = gate
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

        Порта нет (процесс без плагинов, иммутабельный дубль сервисов) → пустое
        множество: гейт тогда работает ровно по каталогу, как раньше.
        """
        port = _observation_port_of(self._services)
        if port is None:
            return set()
        try:
            return set(port.level_names())
        except Exception as exc:  # noqa: BLE001 — телеметрия не критична для такта HB
            _log = getattr(self._services, "log_debug", self._services.log_info)
            _log(f"Имена уровней плагинов недоступны: {exc}", module="heartbeat")
            return set()

    def _level_names_by_writer(self) -> Dict[str, set]:
        """Имена листьев ПО ПИСАТЕЛЯМ — вход гейта Ф4 (решение принимается по пути).

        Адресная форма :meth:`_level_names`: сегмент писателя входит в путь, и
        плоское множество имён его теряет. Порта нет → пустой словарь: гейт
        тогда просто не выдаёт разрешений поддерева, как и раньше.
        """
        port = _observation_port_of(self._services)
        if port is None:
            return {}
        try:
            return dict(port.level_names_by_writer())
        except Exception as exc:  # noqa: BLE001 — телеметрия не критична для такта HB
            _log = getattr(self._services, "log_debug", self._services.log_info)
            _log(f"Имена уровней плагинов по писателям недоступны: {exc}", module="heartbeat")
            return {}

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
            ``{"plugins": {писатель: {имя: значение}}}`` — пусто, если порта
            нет, хранилище пусто или всё придержал гейт.
        """
        port = _observation_port_of(self._services)
        if port is None:
            return {}  # ни один плагин процесса уровней не отдавал
        try:
            return port.collect_subtree(allowed_metrics)
        except Exception as exc:  # noqa: BLE001 — телеметрия не критична для такта HB
            _log = getattr(self._services, "log_debug", self._services.log_info)
            _log(f"Уровни плагинов недоступны: {exc}", module="heartbeat")
            return {}

    def _emit_observation_hub_records(self, plugin_levels: dict) -> None:
        """Ф3.2: те же уровни плагинов — записями ``kind=observation`` в ``ObservabilityHub``.

        **Под тем же гейтом, что и лист дерева, и БЕЗ второго гейта.** Аргумент
        ``plugin_levels`` — РОВНО то поддерево, которое этот же тик уже положил
        в ``state["plugins"]`` (см. вызов в :meth:`_publish_telemetry_to_tree`,
        шаг 1) — не пересчитывается и не собирается заново. Разойдись «что в
        дереве» и «что в хабе» здесь могли бы только два независимых сборщика;
        второго нет, поэтому и расходиться нечему (Task 3.2, шаг 2).

        **Хаб отсутствует → именованный no-op** (Task 3.2, критерий A5): уровни
        в дерево едут как ехали (шаг ниже по коду уже отработал), а запись в
        хаб просто не случается — не заводим второй хаб и не роняем такт.

        Исключения глушим тем же жестом, что и весь такт HB: наблюдаемость
        порта не критична для доставки самого уровня в дерево, а `hub` —
        общий ресурс процесса, который могут дренировать конкурентно.
        """
        if not plugin_levels:
            return
        hub = getattr(self._services, "_observability_hub", None)
        if hub is None:
            return
        from ...statistics_module.observation.observation_manager import records_for_hub

        try:
            for record in records_for_hub(plugin_levels):
                hub.emit_observation_record(record)
        except Exception as exc:  # noqa: BLE001 — телеметрия не критична для такта HB
            _log = getattr(self._services, "log_debug", self._services.log_info)
            _log(f"Записи наблюдений (kind=observation) не ушли в hub: {exc}", module="heartbeat")

    def _delete_departed_subtrees(self, proxy: Any) -> None:
        """Утвердить удаление поддеревьев писателей, ушедших с процесса (Ф2).

        Снятие адресуется ПИСАТЕЛЕМ, а не именем листа: уходит плагин — уходит
        весь его узел ``processes.<процесс>.state.plugins.<писатель>``. Имя листа
        в этой дороге не участвует нигде, поэтому «отложил снятие имени, которое
        к моменту тика принадлежит другому» перестало быть выразимым (класс A1
        старого мира). ``None`` как «показания нет» тоже исчез: нет писателя —
        нет поддерева, а не лист с надгробием.

        **Запас тратится только на успехе.** Успех здесь — «вызов вернулся без
        исключения», и большего дорога не даёт: ``StateProxy.delete``
        fire-and-forget, ответа обработчика нет (см.
        :data:`~.telemetry.DEPARTED_DELETE_BUDGET`). Исключение (прокси без этой
        дороги, отказ транспорта, поднятый наружу) означает, что сообщение из
        процесса не вышло вовсе, — списывать за него страховку не за что, и
        писатель остаётся в ведомости до следующего тика.

        Названная цена этого выбора: прокси, у которого ``delete`` падает
        КАЖДЫЙ раз, держит писателя в ведомости бессрочно и стоит одной пойманной
        попытки за тик. Ограничитель — число писателей (ведомость по ключу
        писателя), а не время; воспроизведено в авторских hazard'ах
        (``test_writer_retraction_hazards.py``, класс про исключение).

        Зовётся ПЕРВЫМ шагом тика — до сборки уровней и до раннего выхода «нечего
        слать». Оба порядка существенны и оба сторожатся тестами:

        * до раннего выхода — потому что у процесса, чей последний писатель
          только что ушёл, публиковать больше нечего вовсе, и снятие, стоящее
          после ``if not data: return``, не случилось бы НИКОГДА (ровно тот
          случай, который механизм и обслуживает);
        * до сборки — потому что публикация возвращённого писателя, пришедшая
          между снимком ведомости и вызовом ``delete``, иначе стёрла бы уже
          живой узел до следующего тика. При этом порядке тот же тик собирает
          значения ПОСЛЕ удаления и возвращает лист в дереве тем же merge.

        Окно всё же остаётся, и оно названо, а не заговорено: публикация,
        пришедшая ПОСЛЕ сборки уровней этого тика, приедет в дерево следующим
        тиком — обычная задержка в один тик, та же, что у любой публикации сразу
        после сборки. Про порядок ДВУХ сообщений на проводе (``state.delete``
        уходит раньше ``state.merge``) сказано только то, что проверено чтением:
        оба уходят одним ``_send`` → ``router.send_async(priority="normal")`` в
        одну очередь того же адресата; замера порядка на живом стенде у этой
        задачи нет.

        Args:
            proxy: StateProxy процесса — тот же, которым тик шлёт merge.
        """
        # Путь строится ТОЙ ЖЕ константой, что и поддерево в сборщике: снятие,
        # адресующее другой ключ, чем публикация, чистило бы не то место — и
        # разъезд был бы виден только на стенде.
        from .telemetry import PLUGINS_SUBTREE_KEY

        port = _observation_port_of(self._services)
        if port is None:
            return  # процесс без порта уровней — снимать нечего
        try:
            writers = tuple(port.departed_writers())
        except Exception as exc:  # noqa: BLE001 — телеметрия не критична для такта HB
            _log = getattr(self._services, "log_debug", self._services.log_info)
            _log(f"Ведомость ушедших писателей недоступна: {exc}", module="heartbeat")
            return

        for writer in writers:
            path = f"processes.{self._services.name}.state.{PLUGINS_SUBTREE_KEY}.{writer}"
            try:
                proxy.delete(path)
            except Exception as exc:  # noqa: BLE001 — запас НЕ тратится, повторим на следующем тике
                _log = getattr(self._services, "log_debug", self._services.log_info)
                _log(f"Снятие поддерева писателя {writer!r} не ушло: {exc}", module="heartbeat")
                continue
            port.note_delete_delivered(writer)

    def _publish_telemetry_to_tree(
        self,
        workers: dict,
        allowed_metrics: Any = None,
        allowed_levels: Any = None,
    ) -> None:
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
            allowed_metrics: разрешённые на этом тике суффиксы метрик
                ФРЕЙМВОРКОВОЙ плоскости (``None`` → все, обратная совместимость).
            allowed_levels: разрешённые листья ПОРТА — ``{писатель: имена}``
                (Ф4, задача 4.1). ``None`` → падаем обратно на
                ``allowed_metrics``, то есть на прежнее решение по имени: так
                ведут себя прямые вызывающие, у которых гейта нет вовсе.
        """
        proxy = getattr(self._services, "_state_proxy", None)
        if proxy is None:
            return  # чисто системный процесс без StateProxy

        from .telemetry import build_router_shm_telemetry, build_worker_telemetry

        # (0) Снятие поддеревьев ушедших писателей — ДО сборки и ДО раннего
        # выхода «нечего слать»: у процесса, чей последний писатель только что
        # ушёл, публиковать нечего вовсе, и снятие в конце метода не случилось бы
        # никогда. Порядок «сначала снять, потом собрать» ещё и лечит гонку с
        # возвращённым писателем в пределах ОДНОГО тика — см.
        # :meth:`_delete_departed_subtrees`.
        self._delete_departed_subtrees(proxy)

        data: dict = {}
        state: dict = {}

        # (1) Уровни плагинов — первыми (см. «порядок наложения» выше).
        #
        # Поддерево ``plugins.<писатель>.<имя>``: ОДИН ключ ``plugins`` в секции
        # ``state``, а не россыпь плоских имён. Столкнуться с агрегатом
        # фреймворка оно больше не может по построению — ``fps`` плагина лежит
        # под ``plugins.<он>.fps``, а не рядом с ``state.fps``.
        plugin_levels = self._collect_plugin_levels(allowed_levels if allowed_levels is not None else allowed_metrics)
        state.update(plugin_levels)
        # Ф3.2: те же уровни — ВТОРЫМ адресатом, записями kind=observation в
        # ObservabilityHub процесса (см. :meth:`_emit_observation_hub_records`).
        # Вход — ТО ЖЕ поддерево, что только что легло в ``state`` — второго
        # гейта здесь нет (шаг 2 задачи 3.2: хаб не становится дорогой мимо гейта).
        self._emit_observation_hub_records(plugin_levels)

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

        # (4) Снятие здесь не стоит — оно ушло шагом (0) наверх, и это не
        # перестановка ради красоты.
        #
        # Прежний шаг клал ``None``-надгробие на плоский путь ИМЕНИ, чей писатель
        # ушёл, с запасом переутверждений и фильтром «только СВОИ имена» по
        # каталогу владения. Каталог владения удалён вместе с арбитражем (Ф1), а
        # во вложенной форме страж надгробия («имени нет в payload») ВСЕГДА
        # истинен для плагинных имён: имя ушедшего писателя лежит теперь под
        # ``plugins.<он>.<имя>``, в плоской секции его нет и не было — надгробие
        # легло бы на ``state.<имя>``, то есть на чужой (или несуществующий) лист
        # при живом писателе. Это ровно класс A1, который механизм чинил.
        #
        # Ф2 заменила его удалением ПОДДЕРЕВА писателя дорогой ``state.delete``:
        # адрес снятия — писатель, а не имя; ``None`` как «показания нет» не
        # существует вовсе (нет писателя — нет узла). Место вызова — начало
        # метода, потому что снятие обязано случиться и тогда, когда публиковать
        # уже нечего (ровно случай «ушёл последний писатель»), а этот хвост
        # метода из-под ``if not data: return`` недостижим.
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
