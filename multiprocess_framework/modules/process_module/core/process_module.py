"""
Базовый класс для всех процессов системы (Refactored).

Наследуется от BaseManager и использует ObservableMixin для логирования и мониторинга.
Все процессы теперь являются менеджерами с единым интерфейсом.
"""

import importlib
import os
from pathlib import Path
from typing import TYPE_CHECKING, Any, Dict, Optional

if TYPE_CHECKING:
    from ...state_store_module.interfaces import IStateProxy

from ...base_manager import BaseManager, ObservableMixin
from ...channel_routing_module.levels import LEVEL_ORDER, normalize_level_name
from ..communication import ProcessCommunication

# Публичные контракты и типы
from ..interfaces import IProcessModule, ISharedResources

# Импорт компонентов процесса
from ..lifecycle import ProcessLifecycle
from ..managers import ProcessManagers
from ..state import ProcessState
from ..threads import SystemThreads
from ..types import ProcessStatus


class ProcessModule(BaseManager, ObservableMixin, IProcessModule):
    """
    Базовый класс для всех процессов системы (Refactored).

    Наследуется от BaseManager и использует ObservableMixin для:
    - Единообразия со всеми менеджерами системы
    - Автоматического логирования через ObservableMixin
    - Стандартного жизненного цикла (initialize/shutdown)

    Реализует IProcessModule — публичный контракт для внешних модулей.
    Принимает shared_resources через DI (ISharedResources protocol) —
    нет прямого импорта из shared_resources_module.

    Attributes:
        name: Имя процесса (синоним manager_name)
        shared_resources: ISharedResources (DI — получается снаружи)
        config: Конфигурация процесса
        queues: Словарь очередей для коммуникации
        config_handler: ProcessConfigHandler для работы с конфигурацией
        communication: ProcessCommunication для межпроцессной коммуникации
    """

    #: Сток плоскости документов (Ф8.7). Атрибут КЛАССА со значением ``None``, а не
    #: «появляется при сшивке»: ``wire_document_sink`` ставит его только когда плоскость
    #: настроена, и до задачи 4.2 процесс без плоскости атрибута не имел вовсе. Пока
    #: ``IProcessServices`` о стоке не знал, это было незаметно; с объявлением в протоколе
    #: отсутствие атрибута означало бы, что штатно сконфигурированный процесс перестаёт
    #: удовлетворять протоколу — dev-проверка ``isinstance(process, IProcessServices)``
    #: падала бы там, где всё правильно. ``None`` — законное «плоскость не поднята».
    document_sink: Any = None

    #: Ф4 (задача 4.1): живой хозяин отбора широких записей. Атрибут КЛАССА со
    #: значением ``None`` — той же правкой, что объявление порта в
    #: ``IProcessServices``, и по тому же доводу, что у ``document_sink`` выше:
    #: объявление в протоколе без атрибута ломает ``isinstance(process,
    #: IProcessServices)`` на штатной конфигурации, где сшивка не проходила
    #: (одиночный запуск, тестовый стенд). ``None`` — законное «отбора нет»:
    #: фронты пишутся, поток нет.
    event_selector: Any = None

    #: Ф5 (задача 5.1): живой хозяин дампов кольца записей. Атрибут КЛАССА со
    #: значением ``None`` — ТОЙ ЖЕ правкой, что объявление порта
    #: ``IProcessServices.flight_recorder`` (Р5.1-2), и по тому же доводу, что у
    #: соседей выше: объявление в протоколе без атрибута ломает
    #: ``isinstance(process, IProcessServices)`` на штатной конфигурации без
    #: сшивки. ``None`` — законное «дампов нет», отвечающее тем же названным
    #: отказом, что и настроенный рекордер с ``enabled=False``.
    flight_recorder: Any = None

    #: Task 3.5 (ADR-PM-038): хранилище текущих уровней, отданных плагинами
    #: (``PluginLevels``). Атрибут КЛАССА со значением ``None`` — ТОЙ ЖЕ правкой,
    #: что объявление порта ``IProcessServices.plugin_levels``, и по тому же
    #: доводу, что у соседей выше. ``None`` — законное «уровней никто не отдавал»:
    #: хранилище создаётся лениво, на первом ``ctx.publish_metric``, и подменяется
    #: атрибутом ЭКЗЕМПЛЯРА, поэтому общий классовый ``None`` не может стать общим
    #: состоянием двух процессов.
    plugin_levels: Any = None

    #: Задача 5.6: намерения подписчиков хвоста — атрибут КЛАССА со значением-пустотой
    #: по тому же доводу, что у ``document_sink`` выше: объявление только в ``__init__``
    #: оставляет без механизма тех, кто собирает процесс иначе (оркестратор, тестовые
    #: стенды) — и подписка падала бы AttributeError вместо работы. Мутации на месте
    #: нет ни одной: все записи — атомарный rebind ``{**старое, ...}``, поэтому общий
    #: классовый словарь не может стать общим состоянием двух процессов.
    _observability_tail_intents: dict = {}

    #: Ф1.1 (C3): установленные процессные хуки (``ProcessHooks``). Атрибут КЛАССА
    #: со значением ``None`` — по тому же доводу, что у соседей выше: процесс,
    #: собранный без ``initialize()`` (тестовый стенд, частичная сборка), обязан
    #: отвечать на ``_uninstall_process_hooks()`` штатным «нечего снимать», а не
    #: AttributeError. ``None`` — законное «хуки не ставили».
    _process_hooks: Any = None

    def __init__(
        self,
        name: str,
        shared_resources: ISharedResources | None = None,
        config: dict | None = None,
        state_proxy: "IStateProxy | None" = None,
    ):
        """
        Инициализация процесса.

        Args:
            name: Имя процесса
            shared_resources: ISharedResources (DI — передаётся снаружи, не импортируется)
            config: Локальная конфигурация процесса (опционально)
            state_proxy: IStateProxy (ADR-SS-006) — если передан, handler state.changed
                         регистрируется автоматически после initialize().
        """
        BaseManager.__init__(self, manager_name=name, process=None)

        ObservableMixin.__init__(
            self,
            managers={},
            config={},
            auto_proxy=True,
        )

        self.name = name
        self.shared_resources: ISharedResources | None = shared_resources
        self.config = config or {}
        self.state_proxy: "IStateProxy | None" = state_proxy

        # Компоненты (настраиваются в initialize())
        self.config_handler = None
        self.config_manager = None
        self.communication = None
        self.queues = None
        self.queue_registry = None
        self.memory_manager = None

        self._stop_requested = False

        # Текущий статус процесса для трансляции в heartbeat.
        # Обновляется командами worker.pause_all / worker.resume_all и концом run().
        #
        # Ф6.4б (находка Н-5б живого прогона 2026-08-03). Здесь стоял литерал
        # ``"running"`` — то есть процесс объявлял себя работающим ИЗ
        # КОНСТРУКТОРА, до initialize(), до старта воркеров и до регистрации
        # команд. Наблюдалось снаружи: ``system_overview`` через ~10 с получал
        # ``introspect_failed`` по четырём ручкам процесса, который по статусу
        # был «running». Окно уже чинили однажды (``attach_ready_event``), но
        # на ОДНОМ пути из трёх: ready_event стал честным, а статус продолжал
        # врать.
        self._current_process_status: str = ProcessStatus.INITIALIZING.value

        # Менеджеры (создаются в initialize() через ManagersBundle, ADR-PM-009)
        self.worker_manager = None
        self.logger_manager = None
        self.error_manager = None
        self.command_manager = None
        self.router_manager = None
        self.stats_manager = None
        self.console_manager = None
        # Ф3, задача 3.1: порт наблюдений — четвёртый канонический слот.
        self.observation_manager = None

        # Внутренние компоненты (композиция)
        self._lifecycle = ProcessLifecycle(self)
        self._process_managers = ProcessManagers(self)
        self._threads = SystemThreads(self)
        self._state = ProcessState(self)

        # Heartbeat и встроенные команды (создаются в run())
        self._heartbeat = None
        self._builtin_cmds = None

        # ObservabilityHub процесса (Ф5.16): создаётся в _apply_managers_bundle,
        # дренируется по heartbeat, финально flush'ится на graceful-teardown.
        self._observability_hub = None
        self._observability_drain = None
        # Персистентный стор наблюдаемости (Ф5.20a): drain log/stats + error-tap'ы.
        self._observability_store = None
        self._observability_store_taps = []
        # Ф5.2: политика истории (порог записи + пределы ретеншена). None до сшивки
        # стора — и такт уборки на это опирается: политики нет → убирать нечего.
        self._observability_history_policy = None
        # Live-хвосты hub→подписчики (Ф5.20b, F1: per-subscriber). Ключ — адрес
        # подписчика, значение — ``(forwarder, taps)``. Несколько подписчиков (GUI +
        # backend_ctl) сосуществуют: раньше был единственный слот на процесс и второй
        # подписчик молча угонял хвост у первого. Пусто до подписки командой
        # observability.tail.subscribe (форвардер «мёртв» без подписчика — как log_tail).
        self._observability_forwarders: dict = {}
        # Задача 5.6: намерение подписчика — уровень и то, ЗАДАН ЛИ ОН ПРИЦЕЛЬНО.
        # Без этого оптовая раздача молча понижала порог, заданный адресно
        # (блокер Н2-1 переприёмки F2): {subscriber: {'level': str, 'targeted': bool}}.
        self._observability_tail_intents: dict = {}

        # Plugin orchestrator — опциональная композиция
        # Активируется если config["plugins"] непуст (см. _init_custom_managers)
        self._orchestrator = None

        # initialize() вызывается явно после создания

    # ========================================================================
    # РЕАЛИЗАЦИЯ BaseManager - ЖИЗНЕННЫЙ ЦИКЛ
    # ========================================================================

    def initialize(self) -> bool:
        """
        Инициализация процесса — оркестратор всех шагов (ADR-PM-009).

        ProcessModule владеет своим жизненным циклом.
        Helper-объекты (lifecycle, process_managers) возвращают результаты,
        ProcessModule сам присваивает атрибуты.

        Returns:
            bool: True если инициализация успешна
        """
        try:
            # 1-2. Конфигурация и очереди
            self._init_configuration()
            self._init_queues()

            # 3. Инициализация менеджеров через ManagersBundle
            self._init_managers()

            # 4. Инициализация коммуникации
            self._init_communication()

            # 5. Регистрация состояния процесса
            self._register_process_state()

            # 6. Воркеры и кастомные менеджеры — до message_processor,
            #    чтобы register_message_handler успел зарегистрироваться
            self._init_custom_managers()
            self._init_application_threads()

            # 6b. P4.4.1 (B2): команды НЕ копируются в event_dispatcher — kind-router
            # в receive() диспатчит type=="command" напрямую в CommandManager.

            # 7. Системные потоки (message_processor) — после воркеров
            self._init_system_threads()

            # 8. Обновляем статус на "ready" — ОБЕ плоскости разом (Ф6.х.7г):
            # прежде PSR получал ready, а _current_process_status оставался
            # initializing до конца run() — heartbeat и introspect всё окно
            # (у GuiProcess — вся жизнь Qt-loop) давали два разных ответа на
            # один вопрос. Правило то же, что у перехода в RUNNING (:857-859).
            self.update_process_state(status=ProcessStatus.READY.value)
            self._current_process_status = ProcessStatus.READY.value

            # 9. Контекст логирования (proc_name в extra для логов).
            #    Ф0.5: именно БАЗА процесса, а не push_context. proc_name — факт
            #    про процесс целиком, а этот вызов делается из главного потока,
            #    тогда как пишут логи потоки-воркеры. После того как контекст
            #    push_context стал потоковым, proc_name отсюда до воркеров бы
            #    не доехал — запись потеряла бы имя процесса.
            logger = self.get_manager("logger")
            if logger and hasattr(logger, "set_base_context"):
                logger.set_base_context(**self._build_resource())

            # 10. Регистрация state.changed handler (ADR-SS-006) — только в
            #     success-пути. Раньше вызов стоял в finally и при исключении
            #     ДО присвоения router_manager молча пропускался по guard'у
            #     (§11.22 comm-system): нельзя регистрировать handler на
            #     полуинициализированном процессе.
            self._init_state_proxy()

            self.is_initialized = True
            self._log_info(f"Process '{self.name}' initialized successfully")
            return True

        except Exception as e:
            import traceback as _tb

            # Ф1.1 (C3): провал подъёма НЕ зовёт shutdown() — он возвращает False
            # (см. вызывающих). Без этой строки хуки, поставленные в
            # ``_apply_managers_bundle``, пережили бы непонявшийся процесс:
            # слоты интерпретатора остались бы занятыми объектом, чей адресат
            # доставки полуразобран, и следующий ``install`` в том же
            # интерпретаторе увидел бы их занятыми.
            self._uninstall_process_hooks()
            self._log_error(f"Failed to initialize process '{self.name}': {e}")
            self._log_error(f"Traceback: {_tb.format_exc()}")
            return False

    def shutdown(self) -> bool:
        """
        Завершение работы процесса.

        Интегрирует функциональность ProcessCore:
        - Shutdown плагинов (если есть orchestrator)
        - Остановка всех потоков
        - Очистка ресурсов
        - Отключение менеджеров

        Returns:
            bool: True если завершение успешно
        """
        # Plugin shutdown (если orchestrator был создан)
        if self._orchestrator is not None:
            self._orchestrator.shutdown()

        return self._lifecycle.shutdown()

    # ========================================================================
    # ИНИЦИАЛИЗАЦИЯ КОМПОНЕНТОВ
    # ========================================================================

    def _init_configuration(self) -> None:
        """Инициализация конфигурации процесса (ADR-PM-009: return-based).

        Вызывает lifecycle helper и сам присваивает атрибуты ProcessModule.
        Имя метода сохранено для совместимости с тестами.
        """
        ch, cm, cfg = self._lifecycle.init_configuration()
        self.config_handler, self.config_manager, self.config = ch, cm, cfg

    def _init_queues(self) -> None:
        """Инициализация очередей процесса (ADR-PM-009: return-based).

        Вызывает lifecycle helper и сам присваивает атрибуты ProcessModule.
        Имя метода сохранено для совместимости с тестами.
        """
        q, qr, mm = self._lifecycle.init_queues()
        self.queues, self.queue_registry, self.memory_manager = q, qr, mm

    def _init_managers(self) -> None:
        """Инициализация менеджеров через ManagersBundle (ADR-PM-009).

        Вызывает create_all(), получает bundle, применяет через _apply_managers_bundle.
        Имя метода сохранено для совместимости с тестами.
        """
        bundle = self._process_managers.create_all()
        self._apply_managers_bundle(bundle)

    def _apply_managers_bundle(self, bundle) -> None:
        """Распаковать ManagersBundle — ProcessModule владеет своими атрибутами.

        ProcessModule сам присваивает менеджеры из bundle,
        затем регистрирует их через ObservableMixin и подключает адаптеры.
        """
        self.worker_manager = bundle.worker
        self.logger_manager = bundle.logger
        self.error_manager = bundle.error
        self.router_manager = bundle.router
        self.stats_manager = bundle.stats
        self.command_manager = bundle.command
        self.console_manager = bundle.console
        self.observation_manager = bundle.observation
        self._process_managers.register_all(bundle, self)
        self._process_managers.attach_adapters(bundle, self)
        self._process_managers.connect_event_manager(self)
        self._apply_boot_observability_layers()
        self._wire_observability_hub()
        self._install_process_hooks()

    def _install_process_hooks(self) -> None:
        """Ф1.1 (C3): поставить три процессных хука — ПОСЛЕ подъёма менеджеров.

        Порядок несущий. До подъёма плоскостей доставлять инцидент было бы
        некуда, и первое же исключение потока ушло бы в
        ``hook_delivery_failures`` — счётчик, который в норме обязан стоять на
        нуле; окно «менеджеров ещё нет» превратилось бы в постоянный ложный
        сигнал «маршрут ошибок сломан».

        Ставятся и тогда, когда ``ErrorManager`` НЕ создан (``config={}``:
        секции ошибок нет, ``_create_error_manager`` вернул None). Это не
        снисхождение к неполной сборке: дорога инцидента —
        :meth:`report_error` → health, и она есть у любого процесса; плоскость
        ошибок добавляет к ней запись, а не создаёт её. Счётчики в этом случае
        приватные (см. ``process_hooks._resolve_counter_store``).
        """
        from ...logger_module.core.process_hooks import install_process_hooks

        self._process_hooks = install_process_hooks(self)

    def _uninstall_process_hooks(self) -> None:
        """Снять процессные хуки. Идемпотентно, падать не имеет права.

        Зовут двое: :class:`ProcessLifecycle` на штатном останове и
        ``initialize()`` на своём провале — хуки не должны пережить процесс,
        который не поднялся (иначе следующий ``install`` в том же
        интерпретаторе увидел бы занятые слоты чужим объектом).
        """
        hooks = self._process_hooks
        if hooks is None:
            return
        self._process_hooks = None
        try:
            hooks.uninstall()
        except Exception as exc:  # noqa: BLE001 — отказ уборки не имеет права сорвать останов
            self._log_error(f"снятие процессных хуков не удалось: {exc}")

    def report_error(self, exc: BaseException, context: str | None = None, **fields: Any) -> None:
        """Дорога инцидента процесса: health-счётчик + плоскость ошибок + строка журнала.

        Тонкий делегат к процесс-общему :class:`HealthState` — сознательно, а не
        «пока так»: тремя адресатами инцидента уже владеет health (ADR-PM-030,
        C2), и второй распределитель рядом означал бы два ответа на вопрос
        «куда едет отказ». Задача 1.3 обобщит эту дорогу на миксин, чтобы её
        имели и менеджеры; здесь она нужна процессу, потому что именно процесс —
        адресат процессных хуков (``services.report_error`` их протокола).

        ``**fields`` уезжают в контекст записи плоскости ошибок (``thread``,
        ``traceback``, ``hook`` у хука).
        """
        from ..health import get_or_create_health_state

        get_or_create_health_state(self).report_error(exc, context=context, **fields)

    def _apply_boot_observability_layers(self) -> None:
        """Применить стек слоёв на старте — там, где ассемблер этого не сделал.

        Две причины пересобрать менеджеры из слоёв в момент boot, и обе про то,
        что готового ответа у процесса нет:

        1. **Менеджеры не пришли готовыми** (Task 5.13). Ассемблер раскладывает
           ``expand_observability(layers.resolve())`` в ``proc_dict["managers"]``
           ДОЧЕРНИМ процессам. Оркестратор спавнится другим кодом, и в его bundle
           ключа ``managers`` нет вовсе (``spawner.py``) — его ``LoggerManager``
           строился из голых дефолтов L0, то есть ``default_level="INFO"`` и
           ``log_directory=None``. Отсюда и «дети WARNING, PM INFO», и пустой
           ``effective.logger.log_directory`` у оркестратора: **один корень, два
           симптома** (резидуалы R6-C и R6-H). Воспроизводилось это и БЕЗ рецепта,
           одним ``system.yaml: log_level: WARNING``.

           Признак **структурный** — «секция менеджеров пуста», а не «имя равно
           ProcessManager». Проверка по имени починила бы ровно одного адресата и
           оставила бы дефект ждать следующего процесса, поднятого без готовой
           секции; кроме того, имя — это контракт адресации, а не контракт сборки.

        2. **Спутник рецепта говорит про ЭТОТ процесс** (Task 5.12). Живая
           находка прогона 5.12: ``observability.persist`` записывал спутник, но
           пересозданный процесс стартовал из boot-``proc_dict``, спутника не
           читал — и сохранённая настройка откатывалась на первом же рестарте.
           «Сохранить» сохраняло на диск, но не в систему.

        Ни одна не выполняется → выходим. У ребёнка со свежим ``proc_dict``
        пересборка была бы лишней работой на пути, который и так верен.

        **Инвариант (ревью 5.13):** пустая секция менеджеров разрешает пересборку
        только вместе с непустыми слоями. Молчащие слои не дают повода трогать
        менеджеры НИКОМУ — ни ассемблеру, ни этому месту; правило одно и живёт в
        :func:`~..configs.observability_layers.layers_are_silent`.
        """
        from ..configs.observability_companion import companion_path, compose_recipe_layer
        from ..configs.observability_layers import (
            LAYER_RECIPE,
            RECIPE_PATH_CONFIG_KEY,
            layers_are_silent,
            process_observability_layers,
            read_process_config,
        )

        # Пустая секция менеджеров = ассемблер этого процесса не касался.
        try:
            managers_ready = bool(self.config_handler.get_managers_config())
        except Exception as exc:  # noqa: BLE001 — нечитаемый конфиг не имеет права ронять старт
            # Отказ здесь ЗНАЧИМ: он выбирает консервативную ветку («менеджеры
            # готовы») и тем самым отменяет пересборку. Проглоти его молча — и
            # процесс поднялся бы на дефолтах L0, а причина осталась бы без следа.
            self._log_error(f"[observability] секция менеджеров не прочитана, пересборка на старте пропущена: {exc}")
            managers_ready = True

        layers = process_observability_layers(self)
        origin = "boot:layers"

        recipe_path = read_process_config(self, RECIPE_PATH_CONFIG_KEY)
        if recipe_path:
            try:
                # ФР-2: третье значение — ссылки без приёмника; `compose_recipe_layer`
                # их уже назвала в журнале. Boot ими не распоряжается (отвечать
                # некому — команды не было), но молчать про них он больше не может:
                # именно этой дорогой опечатка, сохранённая в спутник, въезжала в
                # систему на каждом старте как законный ключ.
                body, source, _ = compose_recipe_layer(self)
            except Exception as exc:  # noqa: BLE001 — битый спутник не имеет права ронять старт
                self._log_error(f"[observability] спутник рецепта не прочитан ({recipe_path}): {exc}")
                body, source = None, None
            # Спутник поверх boot-дельты рецепта: он новее — его писали уже после
            # старта. Источник называем конкретным файлом: при паре «рецепт +
            # спутник» оператор иначе не знает, какой из двух править.
            if source is not None and source == str(companion_path(recipe_path)):
                origin = "boot:companion"
                layers.replace_layer(LAYER_RECIPE, body, source=source, origin=origin)

        # Выходим в двух случаях: слой уже разложен ассемблером (и спутник про этот
        # процесс молчит) — либо слои молчат сами, и накладывать нечего.
        #
        # Вторая половина условия — ревью 5.13. «Секция менеджеров пуста» читалось
        # как «менеджеры не настроены», а это не следует: во фреймворке-конструкторе
        # встройщик вправе собрать LoggerManager программно и не заводить секцию
        # вовсе. Пересборка из молчащих слоёв дала бы ему голые дефолты L0 —
        # то есть тихо отменила бы его настройку. Молчание слоёв означает
        # «решает нижний», см. `layers_are_silent`.
        if origin == "boot:layers" and (managers_ready or layers_are_silent(layers)):
            return

        from ..managers.observability_reload import apply_observability_layers

        try:
            apply_observability_layers(
                layers,
                logger=self.logger_manager,
                error=self.error_manager,
                stats=self.stats_manager,
                log_info=getattr(self, "_log_info", None),
                origin=origin,
            )
        except Exception as exc:  # noqa: BLE001
            self._log_error(f"[observability] слои наблюдаемости не применены на старте: {exc}")

    def _wire_observability_hub(self) -> None:
        """Ф5.16: создать hub наблюдаемости процесса и инъектировать его в слоты
        пилота (worker_module). log/stats буферизуются в hub и дренируются по
        heartbeat; error-слот остаётся реальным error_manager (write-through)."""
        from ..managers.observability_wiring import (
            error_plane_store_warning,
            resolve_history_policy,
            wire_document_sink,
            wire_event_selector,
            wire_observability_store,
            wire_process_observability,
            wire_voices_policy,
        )

        # Ф8.5: плоскость документов — НЕЗАВИСИМО от наличия hub'а. Аудит смен
        # наблюдаемости есть у каждого процесса (команда смены приходит куда угодно),
        # а hub — только у пилота: сшей мы документы внутри условия ниже, «когда
        # включили DEBUG» отвечалось бы ровно на одном процессе из восьми.
        wire_document_sink(self)

        # Ф4 (4.1): отбор широких записей — тоже у каждого процесса и по тому же
        # доводу. Селектор читает те же разрешённые слои, поэтому идёт ПОСЛЕ
        # `_apply_boot_observability_layers` (см. вызывающего): ручки к этому
        # моменту уже разрешены, и второго резолва не заводится.
        wire_event_selector(self)

        # Ф1.4 (M17): окна голоса — политика процесса, не объект. Ставится
        # РАНЬШЕ прочих сшивок по существу, а не по вкусу: держатели окон
        # (роутер, реестр очередей) уже живы к этому моменту и берут окно на
        # первом же голосе. Опоздай политика — первые голоса процесса ушли бы по
        # встроенному дефолту, и настройка «тише на линии» не действовала бы ровно
        # в самый шумный отрезок жизни процесса, на старте.
        wire_voices_policy(self)

        # Ф5 (5.1): рекордер дампов — у каждого процесса и по тому же доводу.
        # ПОСЛЕ `wire_event_selector` только ради читаемости: обе сшивки читают
        # одни и те же разрешённые слои и друг о друге не знают.
        from ..managers.observability_flight import wire_flight_recorder

        wire_flight_recorder(self)

        self._observability_hub, self._observability_drain = wire_process_observability(
            self.name,
            self.worker_manager,
            self.logger_manager,
            self.stats_manager,
            self.error_manager,
        )
        # Ф5.20a: персистентный стор — только когда есть hub (пилот-телеметрия).
        # log/stats из drain-петли, error через store-tap'ы на error+logger-менеджерах.
        if self._observability_hub is not None:
            # Ф5.2: порог истории и её пределы — из конфига (секция
            # `observability.history`). Политика кладётся на процесс ДО проводки:
            # её читает такт уборки, и «стор есть, политики нет» означало бы
            # безлимитную таблицу — ровно то состояние, которое задача чинит.
            policy = resolve_history_policy(self)
            self._observability_history_policy = policy
            self._observability_store, self._observability_store_taps = wire_observability_store(
                self.error_manager, self.logger_manager, process=self.name, min_level=policy["level"]
            )
            # error-записи в стор идут ТОЛЬКО через tap (drain их не пишет).
            # Дырка в плоскости ошибок → вкладка «Ошибки» молча беднеет —
            # предупреждаем (терять можно, молчать нельзя; 5.20 review #6).
            # Само решение и оба текста живут у проводки, которая их и порождает
            # (`error_plane_store_warning`): ревью Task 1.3a показало, что
            # прежнее условие «список tap'ов пуст» пропускало молча раскладку
            # «есть logger-tap, нет error-tap» — ту самую, на которой инцидент
            # терялся целиком.
            store_warning = error_plane_store_warning(self.name, self._observability_store_taps)
            if store_warning:
                self._log_warning(store_warning, module="observability")

    def _init_communication(self):
        """Инициализация коммуникации процесса."""
        self.communication = ProcessCommunication(
            self.name,
            self.queues,
            self.router_manager,
            self.shared_resources,
            logger_callback=self._log_callback,
        )

        # Регистрация очередей
        self.communication.register_process_queues()
        self.communication.register_router_channels()

    def _build_resource(self) -> Dict[str, Any]:
        """``Resource`` процесса (Ф3.5) — то, что одинаково у ВСЕХ его записей.

        Понятие из словаря OTel: набор атрибутов, описывающих того, кто породил
        телеметрию. Собирается **один раз** — база контекста логгера ставится на
        инициализации и дальше не пересчитывается ни на запись, ни на кадр.

        Поля и почему именно они:

        * ``proc_name`` — было с Ф0.5, ради него база и заводилась;
        * ``fw_version`` — версия КОДА (``version.code_version()``):
          семантическая часть плюс хеш коммита и признак грязного дерева
          (``2.0.0+9950851b.dirty``). Рукописной константы здесь не хватало —
          она не менялась четыре месяца, и записи двух разных срезов дерева
          были неотличимы (ревью Ф3, Н-5; решение владельца 2026-08-05).
          Версия из ``pyproject`` не годится ни в каком виде: она версионирует
          дистрибутив, который здесь вообще не собирается;
        * ``incarnation`` — **самое ценное поле набора**. После перезапуска
          процесса его записи неотличимы от записей прежнего инстанса: имя то
          же, файл тот же, время растёт монотонно. Инкарнация их разделяет.
          Свою инкарнацию процесс НЕ бампит (``routing.refresh`` пропускает
          собственное имя и следит за соседями), она проставлена при рождении —
          значит снимок на инициализации не устаревает по построению;
        * ``recipe`` — имя (не путь) активного рецепта. Отвечает на «каким
          конвейером это порождено», когда записи нескольких прогонов лежат в
          одном каталоге;
        * ``pid`` — весь остаток задачи Ф4.4 «процессор обогащения». Она
          ставилась как механизм для тройки ``pid`` / имя процесса /
          ``trace_id``, но к моменту входа в Ф4 два поля из трёх уже ехали
          (имя — с Ф0.5, след — с Ф7 G.6 через ``log_context``), и заводить
          цепочку ради одного поля значило бы положить слой поверх работающего.
          Инкарнацию pid не дублирует: та различает инстансы по логике
          фреймворка, а pid — единственный ключ, которым запись сшивается с
          внешним миром (диспетчер задач, дамп, вывод сторонней утилиты).
          Берётся здесь и только здесь: метод зовётся из ``initialize()``, то
          есть уже в СВОЁМ процессе. Перенос сборки в родителя дал бы у всех
          процессов один родительский pid — правдоподобно и неверно.

        **Недостающее поле пропускается, а не заполняется словом «unknown»:**
        отсутствие ключа честно значит «не знаем», а строка-заглушка выглядела
        бы как знание. Ни одна ветка не вправе уронить инициализацию процесса —
        Resource это украшение записи, а не работа.

        **Цена в объёме — ноль на файлах.** Файловые каналы ``extra`` не
        рендерят (берут оттуда только ``proc_name``), поэтому вес ``system.log``
        не меняется; платят только IPC, стор и кольца памяти, а они на порядок
        меньше.
        """
        resource: Dict[str, Any] = {"proc_name": self.name, "pid": os.getpid()}

        try:
            # Из version.py, а не из фасада пакета — ради адреса, а не ради
            # дешевизны: импорт подмодуля всё равно исполняет __init__ пакета
            # (проверено запуском — 440 модулей), «лёгким» он не бывает.
            from multiprocess_framework.version import code_version

            resource["fw_version"] = code_version()
        except Exception:  # noqa: BLE001 — версия не стоит падения процесса
            pass

        try:
            psr = getattr(self.shared_resources, "process_state_registry", None)
            data = psr.get_process_data(self.name) if psr is not None else None
            meta = getattr(data, "metadata", None)
            if isinstance(meta, dict) and "routing_incarnation" in meta:
                resource["incarnation"] = int(meta.get("routing_incarnation", 0) or 0)
        except Exception:  # noqa: BLE001
            pass

        try:
            from ..configs.observability_layers import RECIPE_PATH_CONFIG_KEY, read_process_config

            # Через read_process_config, НЕ через голый get_config: оркестратор
            # получает конфиг плоским, а ребёнок — весь proc_dict, где ключи
            # ассемблера лежат под "config." — голое чтение на живом стенде
            # молча теряло поле recipe во всех записях (live webcam_sketch,
            # ревью Ф3). Класс уже был записан после 5.12 («форма доставки
            # конфига различается»), и хелпер для него уже существовал —
            # повторное изобретение здесь его обошло.
            recipe_path = str(read_process_config(self, RECIPE_PATH_CONFIG_KEY) or "")
            if recipe_path:
                # Имя, а не путь: путь длинный, машинно-специфичный и в каждой
                # записи бесполезен — различать прогоны достаточно именем.
                resource["recipe"] = Path(recipe_path).stem
        except Exception:  # noqa: BLE001
            pass

        return resource

    def _init_state_proxy(self) -> None:
        """Авто-регистрация handler'а state.changed (ADR-SS-006).

        Вызывается в конце initialize(). Если state_proxy задан и router_manager
        доступен — регистрирует on_state_changed как обработчик IPC-сообщений.
        """
        if self.state_proxy is None or self.router_manager is None:
            return
        try:
            self.router_manager.register_message_handler("state.changed", self.state_proxy.on_state_changed)
            self._log_debug(
                f"ProcessModule '{self.name}': state_proxy handler state.changed зарегистрирован",
                module="state",
            )
        except Exception as exc:
            self._log_warning(
                f"ProcessModule '{self.name}': не удалось зарегистрировать state_proxy handler: {exc}",
                module="state",
            )

    def _register_process_state(self):
        """Регистрация состояния процесса."""
        self._state.register()

    def update_process_state(
        self,
        status: str | None = None,
        events: dict[str, Any] | None = None,
        metadata: dict[str, Any] | None = None,
        custom: dict[str, Any] | None = None,
    ):
        """
        Обновление состояния процесса.

        Args:
            status: Новый статус процесса (ready, running, stopping, error)
            events: События для добавления
            metadata: Метаданные для обновления
            custom: Кастомные данные для обновления
        """
        self._state.update(status=status, events=events, metadata=metadata, custom=custom)

    # ========================================================================
    # СИСТЕМНЫЕ ПОТОКИ
    # ========================================================================

    def _init_system_threads(self):
        """Инициализация системных потоков."""
        self._threads.initialize()

    def _stop_system_threads(self):
        """Остановка системных потоков."""
        self._threads.stop()

    # ========================================================================
    # ХУКИ ДЛЯ ДОЧЕРНИХ КЛАССОВ
    # ========================================================================

    def _init_custom_managers(self):
        """Опциональная инициализация кастомных менеджеров.

        Если config["plugins"] задан — создаёт PluginOrchestrator
        и загружает плагины (early-init: configure_managers).
        Дочерние классы могут переопределить для дополнительной логики.
        """
        app_cfg = self.get_config("config") or {}
        plugin_defs: list[dict] = app_cfg.get("plugins", [])

        if plugin_defs:
            from ..generic.plugin_orchestrator import PluginOrchestrator
            from ..io import ProcessIO

            io = ProcessIO(self)
            self._orchestrator = PluginOrchestrator(services=self, io=io)
            self._orchestrator.load_and_configure_managers(plugin_defs)

    def _init_application_threads(self):
        """Опциональная инициализация потоков приложения."""
        # Создание воркеров из config["workers"] (конфиг-драйвен)
        workers_config = self.config.get("workers") if self.config else {}
        if workers_config and self.worker_manager:
            self._create_workers_from_config(workers_config)

        # Plugin boot (если orchestrator создан в _init_custom_managers)
        if self._orchestrator is not None:
            self._orchestrator.boot()

    def _create_workers_from_config(self, workers_config: dict[str, Any]) -> None:
        """Создать воркеры из config. worker_dict: {class: path, config: {...}, thread: {...}}."""
        from ...worker_module import ThreadConfig

        for name, wc in workers_config.items():
            if not isinstance(wc, dict) or "class" not in wc:
                continue
            try:
                module_path, class_name = wc["class"].rsplit(".", 1)
                module = importlib.import_module(module_path)
                cls = getattr(module, class_name)
                instance = cls(process=self, config=wc.get("config", {}))
                target = getattr(instance, "run", instance)
                if not callable(target):
                    raise TypeError(f"Worker '{name}' must have run(stop_event, pause_event) or be callable")
                thread_dict = wc.get("thread", {})
                thread_config = ThreadConfig.from_dict(thread_dict)
                self.worker_manager.create_worker(name, target, thread_config)
            except Exception as e:
                self._log_error(f"Failed to create worker '{name}': {e}")

    # ========================================================================
    # ФЛАГ ОСТАНОВКИ
    # ========================================================================

    def should_stop(self) -> bool:
        """Проверка флага остановки."""
        return self._stop_requested

    # ========================================================================
    # УДОБНЫЕ СВОЙСТВА ДЛЯ ДОСТУПА К КОМПОНЕНТАМ
    # ========================================================================

    @property
    def managers(self):
        """Доступ к менеджерам через ObservableMixin."""
        return {
            "logger": self.logger_manager,
            "command": self.command_manager,
            "router": self.router_manager,
            "worker": self.worker_manager,
            "console": self.console_manager,
        }

    @property
    def adapters(self):
        """
        Доступ к адаптерам (словарь {manager_name: adapter}).

        Note: Рекомендуется использовать доступ через менеджеры:
        process.command_manager.get_adapter() или process.command_adapter
        """
        adapters = {}
        for manager_name, manager in self.managers.items():
            if manager and hasattr(manager, "get_adapter"):
                adapter = manager.get_adapter()
                if adapter:
                    adapters[manager_name] = adapter
        return adapters

    @property
    def router(self):
        """Прямой доступ к роутеру для отправки сообщений."""
        return self.router_manager

    @property
    def command_adapter(self):
        """Доступ к command_adapter через менеджера."""
        return self.command_manager.get_adapter() if self.command_manager else None

    @property
    def router_adapter(self):
        """Доступ к router_adapter через менеджера."""
        return self.router_manager.get_adapter() if self.router_manager else None

    @property
    def worker_adapter(self):
        """Доступ к worker_adapter через менеджера."""
        return self.worker_manager.get_adapter() if self.worker_manager else None

    @property
    def console_adapter(self):
        """Доступ к console_adapter через менеджера."""
        return self.console_manager.get_adapter() if self.console_manager else None

    # ========================================================================
    # ЛОГИРОВАНИЕ (модуль = имя процесса для маршрутизации в отдельные файлы)
    # ========================================================================

    def _log(self, level: str, message: str, **kwargs) -> None:
        kwargs.setdefault("module", self.name)
        super()._log(level, message, **kwargs)

    def _log_debug(self, message: str, **kwargs) -> None:
        kwargs.setdefault("module", self.name)
        super()._log_debug(message, **kwargs)

    def _log_info(self, message: str, **kwargs) -> None:
        kwargs.setdefault("module", self.name)
        super()._log_info(message, **kwargs)

    def _log_warning(self, message: str, **kwargs) -> None:
        kwargs.setdefault("module", self.name)
        super()._log_warning(message, **kwargs)

    def _log_error(self, message: str, **kwargs) -> None:
        kwargs.setdefault("module", self.name)
        super()._log_error(message, **kwargs)

    def _log_critical(self, message: str, **kwargs) -> None:
        kwargs.setdefault("module", self.name)
        super()._log_critical(message, **kwargs)

    # ========================================================================
    # ВСПОМОГАТЕЛЬНЫЕ МЕТОДЫ
    # ========================================================================

    def _log_callback(self, level: str, msg: str, ctx: str = None):
        """Колбэк логирования для ``ProcessCommunication`` (уровень строкой + контекст).

        **Переименован из ``_fallback_log`` (2.2) — имя лгало.** «Fallback» на
        этом проекте означает аварийный выход мимо сломанного маршрута
        (``ChannelRoutingManager._fallback_log`` пишет в stdlib напрямую именно
        поэтому). Здесь же запись идёт по ШТАТНОМУ пути — через
        ``ObservableMixin._log_*``, со всеми гейтом, роутингом и учётом потерь.
        Никакого запасного маршрута тут нет и не было.

        Цена ложного имени не гипотетическая: разбирая, где у нас аварийные
        выходы, легко посчитать этот метод вторым — и «слить копии», которых не
        существует. Правило проекта прямое: уверенное неверное объяснение
        переживает баг.
        """
        log_fn = getattr(self, f"_log_{level.lower()}", self._log_info)
        log_fn(f"{ctx or self.name}: {msg}")

    def get_config(self, key: str, default: Any = None) -> Any:
        """Получить значение конфигурации."""
        return self.config_handler.get(key, default) if self.config_handler else self.config.get(key, default)

    def update_config(self, key: str, value: Any):
        """Обновить значение конфигурации.

        ``set(key, value)``, а не ``update(key, value)``: у ``Config`` метод
        ``update`` принимает СЛОВАРЬ и один позиционный аргумент, поэтому вызов
        с парой валился ``TypeError`` — у любого процесса с живым
        ``config_handler``, то есть у всех настоящих. Тест на метод был, но
        строил ``ProcessModule`` без обработчика и проверял только ветку
        ``self.config`` (R6, 2026-07-29: тот же класс, что «защита в базе мертва
        у наследника»).
        """
        if self.config_handler:
            self.config_handler.set(key, value)
        self.config[key] = value

    # ========================================================================
    # КОММУНИКАЦИЯ (делегирование к ProcessCommunication)
    # ========================================================================

    def send_message(self, target: str, message):
        """Отправить сообщение другому процессу."""
        if self.communication:
            return self.communication.send_message(target, message)
        return False

    def broadcast_message(self, message, exclude_self: bool = True):
        """Отправить broadcast сообщение."""
        if self.communication:
            return self.communication.broadcast_message(message, exclude_self)
        return False

    def receive_message(self, timeout: float = None, channel_types=None, return_messages: bool = True):
        """Получить сообщение из очереди.
        channel_types=['data'] — для воркеров, получающих DATA/EVENT (по умолчанию).
        channel_types=['system'] — для воркеров, получающих COMMAND (например Robot).
        return_messages=False — plain dict без пересборки Message (Ф7 G.5.a,
        флаг FW_DATA_PLANE_DICTS у DataReceiver).
        """
        if self.communication:
            return self.communication.receive_message(timeout, channel_types, return_messages)
        return None

    # ========================================================================
    # МЕТОДЫ ДЕЛЕГИРОВАНИЯ (для совместимости со старым API)
    # ========================================================================

    def register_manager(self, name: str, manager, enabled: bool = True):
        """Регистрация менеджера (делегирование к ObservableMixin напрямую)."""
        # Вызываем напрямую ObservableMixin, чтобы избежать рекурсии через ProcessManagers
        ObservableMixin.register_manager(self, name, manager, enabled=enabled)

    def get_manager(self, name: str):
        """Получение менеджера по имени (делегирование к ObservableMixin напрямую)."""
        # Вызываем напрямую ObservableMixin, чтобы избежать рекурсии через ProcessManagers
        return ObservableMixin.get_manager(self, name)

    # ========================================================================
    # КОММУНИКАЦИЯ (расширенные методы для совместимости)
    # ========================================================================

    def send(self, message) -> dict:
        """
        Универсальная отправка сообщения.

        Args:
            message: BaseMessage или Dict

        Returns:
            Dict: Результат отправки
        """
        if self.communication:
            return self.communication.send(message)
        return {"status": "error", "reason": "Communication not initialized"}

    def receive(self, timeout: float = 0.01, channel_types=None, return_messages: bool = True) -> list:
        """
        Получение входящих сообщений из каналов.

        Args:
            timeout: Таймаут опроса
            channel_types: Фильтр каналов (['data'] или ['system']). None — все каналы.
            return_messages: False — plain dict без пересборки Message (Ф7 G.5.a).

        Returns:
            List[Message | Dict]: Список полученных сообщений
        """
        if self.communication:
            return self.communication.receive(timeout, channel_types, return_messages)
        return []

    def send_to_process(self, target: str, message: dict) -> bool:
        """Отправка сообщения конкретному процессу."""
        if self.communication:
            return self.communication.send_to_process(target, message)
        return False

    # ========================================================================
    # УДОБНЫЕ МЕТОДЫ
    # ========================================================================

    def execute_command(self, command: str, data: dict = None) -> Any:
        """
        Выполнение команды через адаптер.

        Args:
            command: Имя команды
            data: Данные команды

        Returns:
            Результат выполнения команды
        """
        adapter = self.command_adapter
        if adapter and hasattr(adapter, "execute"):
            return adapter.execute(command, data)
        return None

    # ========================================================================
    # ЖИЗНЕННЫЙ ЦИКЛ (расширенные методы)
    # ========================================================================

    def attach_ready_event(self, event) -> None:
        """Принять от runner'а сигнал self-reported ready (Ф3.2) — объявит его сам процесс.

        Ф3.2 выставлял событие в runner'е СРАЗУ после ``initialize()``. Живой
        прогон 5.11 (2026-07-29, стенд switch+restart) показал, что это неправда:
        message-loop поднимается на шаге 7 ``initialize()``, а команды процесса
        регистрируются позже — в :meth:`run`. В это окно ребёнок читает адресованную
        ему команду и роняет её (``No handler for key 'observability.tail.subscribe'``
        в живом логе). Кто ориентировался на «готов», обращался к процессу, который
        отвечать ещё не умеет.

        Поэтому событие теперь ставит сам процесс — в точке, где он ДЕЙСТВИТЕЛЬНО
        умеет принимать команды (конец :meth:`run`). Хранится через атрибут, а не
        через ``__init__``: тесты строят модуль с no-op-инициализацией.
        """
        self._ready_event = event

    def _announce_ready(self) -> None:
        """Объявить готовность: команды зарегистрированы, воркеры и heartbeat живые.

        Сбой сигнала не имеет права уронить старт: PM переживает отсутствие event'а
        фолбэком по liveness. Но и молчать нельзя — иначе «процесс не объявился»
        неотличимо от «объявился, а мы не увидели».
        """
        event = getattr(self, "_ready_event", None)
        if event is None:
            return
        try:
            event.set()
        except Exception as exc:  # noqa: BLE001 — см. докстринг
            self._log_error(f"ready_event процесса '{self.name}' не выставлен: {exc}", module="lifecycle")

    def run(self):
        """Запуск процесса — старт воркеров, команды, heartbeat, затем RUNNING.

        Ф6.4б: ``RUNNING`` выставляется ПОСЛЕДНИМ, вместе с объявлением
        готовности, а не первой строкой. Раньше статус менялся здесь, а
        ``BuiltinCommands.register()`` шёл ниже — в это окно процесс по статусу
        уже работал, а на ``introspect.*`` отвечал «нет хендлера». Один момент
        истины вместо двух: статус и ``ready_event`` меняются в одной точке,
        поэтому разъехаться не могут.

        До этой точки статус остаётся тем, что выставил ``initialize()``
        (``READY`` — «поднят, но ещё не обслуживает»), и это правда.
        """
        if self.worker_manager:
            self.worker_manager.start_all_workers()

        # Встроенные команды (composition)
        from ..commands.builtin_commands import BuiltinCommands

        self._builtin_cmds = BuiltinCommands(self)
        self._builtin_cmds.register()
        # P4.4.1 (B2): builtins (worker.*/wire.*/introspect.*) живут в CommandManager;
        # ре-синк в event_dispatcher больше не нужен — kind-router в receive()
        # диспатчит type=="command" напрямую в CommandManager.

        # Heartbeat (composition)
        from ..heartbeat.process_heartbeat import ProcessHeartbeat

        self._heartbeat = ProcessHeartbeat(self)
        self._heartbeat.start()

        # Ф7 G.9(a): GC-дисциплина — заморозить startup-объекты в permanent-поколение
        # ПОСЛЕ старта воркеров/heartbeat (все долгоживущие объекты созданы), чтобы
        # сборщик не сканировал их на каждом цикле → меньше per-collection пауз (p99).
        # За FW_GC_FREEZE, дефолт off = штатный GC бит-в-бит.
        from ..lifecycle.gc_discipline import GcDiscipline

        self._gc_discipline = GcDiscipline(log=lambda m: self._log_info(m, module="lifecycle"))
        self._gc_discipline.freeze_after_startup()

        self._log_info(f"Process '{self.name}' started", module="lifecycle")
        # Готовность объявляется ПОСЛЕДНИМ действием run(): к этой строке команды
        # процесса зарегистрированы, воркеры и heartbeat подняты. Наследник с
        # блокирующим run() (GuiProcess: Qt-loop) зовёт super().run() первым, поэтому
        # объявление до него доходит — а вот перенос сигнала в runner ЗА run() его
        # бы навсегда лишил готовности.
        #
        # Ф6.4б: обе плоскости статуса меняются ЗДЕСЬ же, рядом с сигналом
        # готовности. Разнести их — значит завести два ответа на один вопрос
        # «процесс работает?», и живой прогон показал, чем это кончается.
        self.update_process_state(status=ProcessStatus.RUNNING.value)
        self._current_process_status = ProcessStatus.RUNNING.value
        self._announce_ready()

    def stop(self):
        """Остановка процесса — статус STOPPING, остановка воркеров и shutdown."""
        self.update_process_state(status=ProcessStatus.STOPPING.value)

        self._log_info(f"Process '{self.name}' stopping", module="lifecycle")
        self._stop_requested = True

        if self.worker_manager:
            self.worker_manager.stop_all_workers()

        # Ф5.16 (c): финальный дренаж hub'а на graceful-teardown — воркеры уже
        # остановлены, новых эмиссий нет. SIGKILL этот путь обходит (потому
        # error/critical идут write-through, а не в буфер).
        self._flush_observability()

        self.shutdown()

    def _flush_observability(self) -> None:
        """Ф5.16 (c): последний слив log/stats-буфера hub'а перед остановкой (в
        менеджеры и в стор Ф5.20a). Затем снять store-tap и закрыть стор.
        Дренаж не критичен — исключения глушим, чтобы не сорвать teardown."""
        from ..managers.observability_wiring import (
            drain_process_observability,
            unwire_document_sink,
            unwire_observability_forward,
            unwire_observability_store,
        )

        try:
            # F1: фан-аут финального drain всем подписчикам (по одному форвардеру).
            drain_process_observability(
                self._observability_hub,
                self._observability_drain,
                self._observability_store,
                [fwd for fwd, _taps in self._observability_forwarders.values()],
                # 2.1: окно агрегации закрывается ЗДЕСЬ, а не в `shutdown()`
                # менеджеров ниже — иначе последний снапшот смены родился бы
                # уже после дренажа и после закрытия стора. См. докстринг.
                stats_to_flush=self.stats_manager,
            )
        except Exception:  # noqa: BLE001 — потеря телеметрии не должна ронять stop()
            pass
        # Снять store-tap'ы и закрыть стор (graceful; SIGKILL этот путь обходит,
        # но записи уже во WAL-файле — стор переживает рестарт).
        unwire_observability_store(
            self._observability_store,
            self._observability_store_taps,
        )
        self._observability_store = None
        self._observability_store_taps = []
        # Снять live-forward-tap'ы ВСЕХ подписчиков (Ф5.20b, F1): процесс уходит целиком.
        for _fwd, taps in self._observability_forwarders.values():
            unwire_observability_forward(taps)
        self._observability_forwarders = {}
        self._observability_tail_intents = {}
        # Ф8.5: отцепить сток документов от аудита и закрыть БД. ПОСЛЕ дренажа: до
        # этой строки запись аудита ещё имеет право появиться (её может породить сам
        # teardown), и уехать ей есть куда.
        unwire_document_sink(self)

    def subscribe_observability_tail(
        self,
        subscriber: str,
        level: Optional[str] = None,
        *,
        wholesale: bool = False,
    ) -> dict:
        """Ф5.20b: подписать адрес на live-хвост записей наблюдаемости (F1: per-subscriber).

        Ставит форвардер (drain log/stats) + error-tap'ы (write-through) на push
        ``command="observability.record"`` → подписчик. F1: форвардер регистрируется
        ТОЛЬКО для своего ``subscriber`` — несколько подписчиков (GUI + backend_ctl)
        сосуществуют на одном процессе (раньше единственный слот перетирался, и второй
        подписчик угонял хвост у первого). Идемпотентно по подписчику: повторная
        подписка того же адреса снимает его прежние tap'ы и ставит заново. Требует
        hub — без него дренировать нечего.
        """
        from ..managers.observability_wiring import (
            unwire_observability_forward,
            wire_observability_forward,
        )

        if self.router_manager is None:
            return {"success": False, "reason": "router_manager недоступен"}
        # Task 5.11: подписка процесса на САМОГО СЕБЯ — петля: каждая запись
        # уезжает пушем в собственную очередь, где становится сообщением, о
        # котором тоже можно записать. Инвариант живёт здесь, а не у вызывающего:
        # GUI фильтровал себя сам, брокер фильтровал бы вторым местом, а третий
        # потребитель забыл бы — «дефект чинится на одном пути из трёх».
        # Брокер шлёт ОДИН конверт всем сразу и адресно исключить себя не может;
        # отказ — его штатный ответ, поэтому он громкий и с причиной.
        if subscriber == self.name:
            return {
                "success": False,
                "process": self.name,
                "subscriber": subscriber,
                "reason": "подписка процесса на собственный хвост — петля (записи ушли бы в свою же очередь)",
            }
        if self._observability_hub is None:
            return {"success": False, "reason": "observability hub не активен (нет пилот-воркеров)"}
        # Идемпотентность ТОЛЬКО для своего подписчика: снять его прежние tap'ы (если были),
        # форвардеры прочих подписчиков не трогаем.
        prev = self._observability_forwarders.get(subscriber)
        if prev is not None:
            unwire_observability_forward(prev[1])
        # Ф6.х.5: уровень задаёт подписчик (как у log.tail) — прежде порог был
        # захардкожен ERROR внутри проводки, и хвост молчал на здоровом стенде.
        # Ф3.1: и проверяется он здесь же — второй путь той же поверхности.
        # Без проверки опечатка в имени уровня давала порог «пропускать всё» при
        # успешном ответе с эхом запрошенного порога.
        # A1: ЕДИНСТВЕННАЯ позиция дефолта на всей цепочке подписки. ``None``
        # («уровень не назван») приходит и от хендлера команды, и от брокера —
        # ни один из них константу не повторяет, иначе смена дефолта здесь
        # доехала бы одним путём из трёх.
        min_level = normalize_level_name(level or "ERROR")
        if min_level is None:
            return {
                "success": False,
                "process": self.name,
                "subscriber": subscriber,
                "reason": f"неизвестный level '{level}' ({'|'.join(LEVEL_ORDER)})",
            }
        # Задача 5.6 (блокер Н2-1 переприёмки F2 раунд 2): ПРИЦЕЛЬНАЯ подписка
        # сильнее ОПТОВОЙ. Прежде побеждала последняя воля, и молча: живьём
        # `subscribe(camera_0, INFO)` + `subscribe_all(WARNING)` давали 31 запись
        # `{info}` → 0 info `{error: 6}`, при том что манифест продолжал обещать
        # INFO. Процесс сам различить дороги не мог — брокер разворачивает оптовую
        # команду в те же самые `observability.tail.subscribe`, поэтому намерение
        # едет НА ПРОВОДЕ (`scope="all"`), а не выводится из догадки.
        #
        # Решение владельца 2026-08-12: объединение по мерилу 1 («подписчик с
        # level=INFO получает INFO от каждого процесса»). Понижать уровень
        # по-прежнему можно — но прицельной же командой, то есть тем же жестом,
        # которым его задавали.
        held = self._observability_tail_intents.get(subscriber)
        kept_from: Optional[str] = None
        if wholesale and held is not None and held.get("targeted") and held.get("level") != min_level:
            kept_from, min_level = min_level, str(held["level"])
        targeted = bool(held and held.get("targeted")) or not wholesale
        forwarder, taps = wire_observability_forward(
            self.router_manager,
            subscriber,
            self.name,
            self.logger_manager,
            self.error_manager,
            min_level=min_level,
        )
        # Атомарный rebind, не in-place set: heartbeat-drain итерирует .values() в
        # другом потоке — смена размера dict во время итерации дала бы RuntimeError.
        self._observability_forwarders = {**self._observability_forwarders, subscriber: (forwarder, taps)}
        # Намерение живёт рядом с форвардером и тем же атомарным rebind'ом: без него
        # «кто задал этот уровень» пришлось бы выводить из порядка команд, то есть
        # из догадки. Снимается вместе с подпиской (см. unsubscribe).
        self._observability_tail_intents = {
            **self._observability_tail_intents,
            subscriber: {"level": min_level, "targeted": targeted},
        }
        # Ф6.х.5: ответ громкий, как у log.tail — tap'ы, менеджеры, порог.
        # Молча-пустой список tap'ов и был лицом дефекта З-1: подписка
        # «успешна», а слушать некому.
        tap_names = [name for _mgr, name in taps]
        managers = [getattr(m, "manager_name", m.__class__.__name__) for m, _n in taps]
        if not taps:
            self._log_warning(
                f"observability.tail: подписка '{subscriber}' принята, но tap'ов ноль — "
                "live-хвоста не будет (менеджеры без add_tap?)",
                module="observability",
            )
        reply = {
            "success": True,
            "process": self.name,
            "subscriber": subscriber,
            "min_level": min_level,
            "taps": tap_names,
            "managers": managers,
        }
        if kept_from is not None:
            # Молчание здесь и было половиной дефекта: оптовая раздача обязана
            # сказать, что НЕ понизила прицельный порог, — иначе оператор считает
            # действующим то, что запросил последним.
            reply["kept_level"] = min_level
            reply["ignored_level"] = kept_from
            reply["reason"] = (
                f"прицельная подписка сильнее оптовой: порог '{min_level}' сохранён, оптовый '{kept_from}' не применён"
            )
        return reply

    def unsubscribe_observability_tail(
        self,
        subscriber: Optional[str] = None,
        *,
        wholesale: bool = False,
    ) -> dict:
        """Ф5.20b: снять подписку на live-хвост (форвардер + error-tap'ы), F1: per-subscriber.

        ``subscriber`` задан → снять форвардер ТОЛЬКО этого подписчика (форвардеры
        прочих — GUI и т.д. — продолжают работать). ``None`` (legacy/teardown) — снять
        форвардеры всех подписчиков процесса.
        """
        from ..managers.observability_wiring import unwire_observability_forward

        if subscriber is None:
            had = bool(self._observability_forwarders)
            for _fwd, taps in self._observability_forwarders.values():
                unwire_observability_forward(taps)
            self._observability_forwarders = {}
            self._observability_tail_intents = {}
            return {"success": had, "process": self.name}

        # Задача 5.6, зеркало (находка Н2-2): ОПТОВОЕ снятие не сносит подписку,
        # заданную ПРИЦЕЛЬНО. Воспроизведено живьём до правки: `unwatch()` глушил
        # прицельный хвост, которого сам не создавал (28 записей → 28 после
        # снятия профиля, который ни разу не включался). Симметрия с подпиской
        # обязательна: закрой один конец — и «объединение» превратилось бы в
        # «объединение до первого unwatch».
        held = self._observability_tail_intents.get(subscriber)
        if wholesale and held is not None and held.get("targeted"):
            return {
                "success": True,
                "process": self.name,
                "subscriber": subscriber,
                "removed": False,
                "kept_targeted": True,
                "reason": (
                    "прицельная подписка сильнее оптовой: оптовое снятие её не тронуло "
                    f"(порог '{held.get('level')}' держится) — снимать адресной командой"
                ),
            }
        # Атомарный rebind вместо .pop() (см. subscribe): убрать гонку с heartbeat-drain.
        prev = self._observability_forwarders.get(subscriber)
        if prev is not None:
            self._observability_forwarders = {
                k: v for k, v in self._observability_forwarders.items() if k != subscriber
            }
            # Намерение уходит вместе с подпиской: оставь его — и следующая ОПТОВАЯ
            # подписка сохранила бы порог от снятой прицельной, то есть память о отменённом
            # решении пережила бы само решение.
            self._observability_tail_intents = {
                k: v for k, v in self._observability_tail_intents.items() if k != subscriber
            }
            unwire_observability_forward(prev[1])
        return {"success": prev is not None, "process": self.name, "subscriber": subscriber}

    # ========================================================================
    # СТАТИСТИКА
    # ========================================================================

    def get_stats(self) -> dict[str, Any]:
        """
        Получение статистики процесса.

        Returns:
            Dict: Статистика всех компонентов
        """
        # Базовая статистика из BaseManager
        stats = super().get_stats()

        # Добавляем специфичную статистику процесса
        stats.update(
            {
                "name": self.name,
                "running": not self._stop_requested,
            }
        )

        # Статистика очередей
        if self.communication and hasattr(self.communication, "get_queue_stats"):
            stats["queues"] = self.communication.get_queue_stats()

        # Статистика воркеров
        if self.worker_manager and hasattr(self.worker_manager, "get_stats"):
            try:
                stats["workers"] = self.worker_manager.get_stats()
            except Exception as e:
                stats["workers"] = {"error": str(e)}

        return stats
