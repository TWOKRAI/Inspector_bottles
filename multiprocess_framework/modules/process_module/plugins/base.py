"""ProcessModulePlugin + PluginContext — ядро plugin-системы.

Единый интерфейс для всех плагинов — от мощных (webcam: SHM, workers,
ring buffer, middleware) до простых (color_mask: вход → cv2 → выход).

State machine (от GStreamer):
    IDLE → READY → RUNNING → STOPPED
           ↑          ↓
           ←── PAUSED ←

PluginContext даёт доступ ко всему что есть в ProcessModule,
плагин использует только то что ему нужно.
"""

from __future__ import annotations

import functools
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import TYPE_CHECKING, Any, Callable, ClassVar

from .interfaces import IProcessServices
from .manifest import PLUGIN_API_VERSION

if TYPE_CHECKING:
    from ..health import HealthReporter
    from .metrics import PluginMetrics


def for_each(func):
    """Сахар: per-item функция -> process(items) -> list[dict].

    Применяется к методу process плагина.
    Возврат декорируемой функции:
      dict       -> 1:1
      list[dict] -> 1:N (fan-out)
      None       -> фильтрация (item отбрасывается)
    """

    @functools.wraps(func)
    def wrapper(self, items: list[dict]) -> list[dict]:
        result = []
        for item in items:
            out = func(self, item)
            if out is None:
                continue
            if isinstance(out, list):
                result.extend(out)
            else:
                result.append(out)
        return result

    return wrapper


class PluginState(str, Enum):
    """Состояние плагина (от GStreamer element states)."""

    IDLE = "idle"  # Зарегистрирован, не инициализирован
    READY = "ready"  # configure() выполнен, ресурсы выделены
    RUNNING = "running"  # start() выполнен, данные текут
    PAUSED = "paused"  # Приостановлен, ресурсы удерживаются
    STOPPED = "stopped"  # shutdown() выполнен, ресурсы освобождены


class PluginContext:
    """Фасад над ProcessModule — всё что нужно плагину, без прямой связи с кишками.

    Создаётся GenericProcess'ом и передаётся в каждый плагин.
    Для каждого плагина создаётся копия с plugin-specific config.
    """

    def __init__(
        self,
        services: IProcessServices,
        config: dict[str, Any] | None = None,
        io: Any | None = None,
        registers: Any | None = None,
    ) -> None:
        self.services = services
        self.process_name = services.name
        self.config = config or {}

        # Менеджеры через Protocol (плагин использует только то, что ему нужно)
        self.worker_manager = getattr(services, "worker_manager", None)
        self.command_manager = getattr(services, "command_manager", None)
        self.router_manager = getattr(services, "router_manager", None)
        self.memory_manager = getattr(services, "memory_manager", None)

        # IPC facade (передаётся отдельно — ProcessIO app-specific, не часть Protocol)
        self.io = io

        # Registers (Phase 5.9) — RegistersManager | None
        # Плагин читает self._reg = ctx.registers.get_register("plugin_name")
        self.registers = registers

        # StateProxy (Phase 8) — из services
        self.state_proxy = getattr(services, "state_proxy", None)

        # Логирование и IPC — публичные методы Protocol
        self.log_info: Callable[[str], None] = services.log_info
        self.log_error: Callable[[str], None] = services.log_error
        self.send_message: Callable = getattr(services, "send_message", None)  # type: ignore[assignment]
        self.receive_message: Callable = getattr(services, "receive_message", None)  # type: ignore[assignment]

    def with_config(
        self,
        plugin_config: dict[str, Any],
        registers: Any | None = None,
    ) -> PluginContext:
        """Создать копию контекста с plugin-specific конфигом."""
        new = PluginContext(
            services=self.services,
            config=plugin_config,
            io=self.io,
            registers=registers,
        )
        # state_proxy ставится оркестратором ПОСЛЕ __init__ (процесс хранит его как
        # services._state_proxy — приватный атрибут, недоступный через публичный
        # services.state_proxy, который читает __init__). Без явного проброса копия
        # теряет proxy → per-plugin ctx.state_proxy=None, и плагины не видят дерево
        # состояний (latent gap: затрагивал capture/color_mask/telemetry_sink).
        new.state_proxy = self.state_proxy
        return new

    @property
    def health(self) -> "HealthReporter":
        """Фасад наблюдаемости отказов процесса (Ф2 Task 2.1).

        ``ctx.health.report_error(exc, context=..., throttle=...)`` — учесть
        проглоченную/обработанную ошибку; ``set_status(...)`` / ``degraded(...)`` —
        явная деградация. Публикуется в state-дерево через heartbeat процесса
        (``processes.<name>.health.*`` — см. ``..health.schema``).

        Один :class:`HealthState` на процесс (агрегат уровня процесса); reporter
        подставляет имя плагина как context по умолчанию. Кэшируется на ctx, чтобы
        не пересоздавать при каждом обращении из горячего пути обработки.
        """
        reporter = getattr(self, "_health_reporter", None)
        if reporter is None:
            from ..health import HealthReporter, get_or_create_health_state

            state = get_or_create_health_state(self.services)
            reporter = HealthReporter(state, source=getattr(self, "_plugin_name", "") or "")
            self._health_reporter = reporter
        return reporter


def _noop_log(msg: str) -> None:
    """No-op fallback для логирования в SubPluginContext."""


def _standalone_health() -> Any:
    """Fallback-reporter для SubPluginContext без родителя (волна C, Ф2 Task 2.5).

    Sub-плагины зовут ``ctx.health.report_error(...)`` наравне с обычными —
    без поля health это AttributeError на error-пути. Дефолт — автономный
    log-only HealthState (не публикуется, счётчик локальный); родительский
    плагин пробрасывает свой reporter через ``SubPluginContext(health=...)``.
    """
    from ..health import HealthReporter, HealthState

    return HealthReporter(HealthState(log_only=True), source="sub_plugin")


@dataclass
class SubPluginContext:
    """Облегчённый контекст для вложенных плагинов (chain_executor, worker_pool).

    Совместим с PluginContext по duck-typing — плагины используют
    ctx.config, ctx.log_info, ctx.log_error, ctx.registers, ctx.command_manager.

    Заменяет unittest.mock.MagicMock в production-коде.

    Для логирования через LoggerManager фреймворка — передайте log_info/log_error
    из родительского PluginContext::

        sub_ctx = SubPluginContext(
            config=sub_config,
            log_info=self._ctx.log_info,
            log_error=self._ctx.log_error,
        )
    """

    process_name: str = "sub_plugin"
    config: dict[str, Any] = field(default_factory=dict)
    registers: Any = None
    log_info: Callable[[str], None] = _noop_log
    log_error: Callable[[str], None] = _noop_log
    command_manager: Any = None
    worker_manager: Any = None
    router_manager: Any = None
    memory_manager: Any = None
    # StateProxy (Phase 8) — для публикации состояния через реактивное дерево
    # None по умолчанию для обратной совместимости
    state_proxy: Any = None
    # Health-фасад (Ф2): дефолт — автономный log-only reporter; родитель
    # пробрасывает свой ctx.health, чтобы ошибки sub-плагинов кормили процесс.
    health: Any = field(default_factory=_standalone_health)


class ProcessModulePlugin(ABC):
    """Единица поведения, подключаемая к GenericProcess.

    Единый интерфейс для всех плагинов:
    - source (webcam, hikvision, file_source, simulator)
    - processing (color_mask, blur, threshold, edge_detect)
    - output (renderer, database, robot)

    State machine (от GStreamer):
        IDLE → READY → RUNNING → STOPPED
               ↑          ↓
               ←── PAUSED ←

    GenericProcess управляет state transitions:
    - _init_application_threads(): IDLE → READY → RUNNING
    - pause():                     RUNNING → PAUSED
    - resume():                    PAUSED → RUNNING
    - shutdown():                  * → STOPPED

    Контракт портов (от GStreamer caps + UE pins):
        inputs  — что плагин ожидает на входе
        outputs — что плагин отдаёт на выходе

    Команды — {имя_команды: имя_метода}
        Автоматически регистрируются в CommandManager процесса.

    Статический манифест (Ф4 Task 4.4, см. ``plugins/manifest.py``):
        VERSION      — semver плагина (не версия контракта). Дефолт "0.0.0".
        API_VERSION  — semver контракта плагин↔фреймворк. Дефолт — текущий
                        ``PLUGIN_API_VERSION``. Boot mismatch по major → WARNING
                        (не отказ, см. ``PluginOrchestrator.boot()``).
        REQUIRES     — декларация зависимостей, проверяется на boot ДО
                        configure(): "manager:<атрибут ctx>" (напр.
                        "manager:worker_manager"), "service:<имя>" (менеджер на
                        ctx.services, напр. "service:sql_manager"), "shm".
                        Недостающая зависимость → громкая ошибка с именем
                        плагина вместо позднего немого AttributeError.
    """

    name: str = ""
    # Канон — plugins.manifest.PluginCategory (source/processing/render/io/sink/
    # hub/control/filter/calibration/runtime/utility). Легаси-строки (rendering/
    # output и любые другие) канонизируются PluginRegistry.register() через
    # CATEGORY_LEGACY_ALIASES; неканоничное значение — громкий WARNING, не отказ.
    category: str = ""

    # --- Манифест плагина (Ф4 Task 4.4) — статически читаемые метаданные ---
    VERSION: ClassVar[str] = "0.0.0"
    API_VERSION: ClassVar[str] = PLUGIN_API_VERSION
    REQUIRES: ClassVar[tuple[str, ...]] = ()

    # Контракт портов — переопределяется в подклассах
    inputs: list = []  # list[Port]
    outputs: list = []  # list[Port]

    # Команды — {command_name: method_name}
    # Автоматически регистрируются в CommandManager при configure
    commands: dict[str, str] = {}

    # Thread-safety контракт (Q8):
    # False (default) — sequential, safe by default.
    # True — разрешает параллельный вызов process() (для stateless плагинов).
    thread_safe: ClassVar[bool] = False

    def __init_subclass__(cls, **kwargs) -> None:
        """Авто-обернуть process/produce в frame-trace таймер (универсально).

        Любой плагин получает пер-сегментный замер обработки без явного декоратора.
        No-op при выключенной трассировке (INSPECTOR_FRAME_TRACE). См. frame_trace.
        """
        super().__init_subclass__(**kwargs)
        from ..generic import frame_trace

        for _method in ("process", "produce"):
            fn = cls.__dict__.get(_method)
            if callable(fn) and not getattr(fn, "_traced", False):
                setattr(cls, _method, frame_trace.traced(fn))

    def __init__(self) -> None:
        self.state: PluginState = PluginState.IDLE
        self.metrics: PluginMetrics | None = None
        # Имя процесса-узла для frame-trace (ставит PluginOrchestrator.boot).
        self._trace_node: str = ""
        # Bypass-флаг: если False — PluginRunner НЕ вызывает process(), кадр идёт
        # насквозь без обработки (live-тумблер в инспекторе ноды). Источники (produce)
        # bypass не поддерживают (нечего пропускать). См. PluginRunner.call_process.
        self.enabled: bool = True

    # --- Data pipeline контракт (Phase 5) ---

    @property
    def is_source(self) -> bool:
        """True если плагин — источник данных (category == 'source')."""
        return self.category == "source"

    @classmethod
    def register_schema(cls) -> list:
        """Register-классы плагина (list[type[SchemaBase]]).

        Источники (по приоритету):
          1. ``config_class().register_bindings`` (если config_class переопределён);
          2. **fallback** ``register_class`` на самом плагине — канонический и самый
             частый способ объявить регистр. Благодаря этому fallback любой плагин с
             ``register_class = X`` автоматически получает RegistersManager и приёмник
             ``register_update`` (live field-write из GUI) БЕЗ boilerplate-override
             ``config_class``. Без него (была дыра) плагины вида blob_detector/line_filter
             молча теряли live-редактирование («No handler for key 'register_update'»).
          3. Иначе — пустой список (graceful degradation).

        Returns:
            Список SchemaBase-классов (не инстансов).
        """
        config_cls = cls.config_class()
        if config_cls is not None and hasattr(config_cls, "register_bindings"):
            bindings = list(config_cls.register_bindings)
            if bindings:
                return bindings
        rc = getattr(cls, "register_class", None)
        if rc is not None:
            return [rc]
        return []

    @classmethod
    def config_class(cls) -> type | None:
        """PluginConfig-класс этого плагина (lazy discovery через PluginRegistry).

        Override если автоматический discovery не работает.
        """
        return None

    def _init_register(self, ctx: PluginContext, register_cls: type | None = None) -> Any:
        """Инициализировать register: managed (GUI) → локальный fallback → YAML overrides.

        Порядок:
          1. Если ctx.registers есть — берёт managed register (GUI видит и меняет)
          2. Если нет — создаёт локальный экземпляр register_cls (defaults)
          3. Применяет YAML overrides из ctx.config (inline-значения из topology)

        Args:
            ctx: PluginContext с config и registers.
            register_cls: Класс регистра. Если None — берёт из self.register_class.

        Returns:
            Инстанс регистра (managed или локальный).

        Raises:
            ValueError: если register_cls не задан ни явно, ни через self.register_class.

        Пример использования::

            class MyPlugin(ProcessModulePlugin):
                register_class = MyRegisters

                def configure(self, ctx):
                    self._ctx = ctx
                    self._reg = self._init_register(ctx)
        """
        cls = register_cls or getattr(self, "register_class", None)
        if cls is None:
            raise ValueError(
                f"Plugin '{self.name}': register_class не задан. "
                f"Укажите register_class на классе или передайте register_cls аргументом."
            )

        # 1. Managed register (GUI видит)
        reg = None
        if ctx.registers is not None:
            managed = ctx.registers.get_register(self.name)
            # Проверяем что managed — реальный SchemaBase, а не mock
            if managed is not None and hasattr(type(managed), "model_fields"):
                reg = managed

        # 2. Fallback: локальный экземпляр
        if reg is None:
            reg = cls()

        # 3. YAML overrides из config (ctx.config всегда плоский — нормализация
        #    формата pdef живёт в PluginOrchestrator._extract_plugin_config).
        for field_name in type(reg).model_fields:
            if field_name in ctx.config:
                setattr(reg, field_name, ctx.config[field_name])

        return reg

    def process(self, items: list[dict]) -> list[dict]:
        """Обработка items. Override в processing/output-плагинах.

        Default: pass-through (return items).
        items — список {"frame": ndarray, ...metadata}.
        Чистая обработка: без IPC, без SHM, без PluginContext.

        Покрывает все семантики:
          1:1   resize, grayscale, negative, ...
          1:N   region_split
          N:1   stitcher
          N:0   фильтрация (return [])
          batch frame_counter, FPS log
        """
        return items

    def produce(self) -> list[dict]:
        """Генерация items. Override в source-плагинах.

        Default: raise NotImplementedError.
        """
        raise NotImplementedError(f"Plugin '{self.name}' does not implement produce()")

    @abstractmethod
    def configure(self, ctx: PluginContext) -> None:
        """Объявить ресурсы: SHM, middleware, обработчики сообщений.

        Transition: IDLE → READY.
        Команды из self.commands регистрируются автоматически (GenericProcess).
        """

    def start(self, ctx: PluginContext) -> None:
        """Запуск после configure всех плагинов. Создание воркеров.

        Transition: READY → RUNNING.
        Default: no-op. Override при необходимости (воркеры, фоновые задачи).
        """

    def pause(self, ctx: PluginContext) -> None:
        """Приостановка. Default: no-op.

        Transition: RUNNING → PAUSED.
        """

    def resume(self, ctx: PluginContext) -> None:
        """Возобновление. Default: no-op.

        Transition: PAUSED → RUNNING.
        """

    def configure_managers(self, ctx: PluginContext) -> None:
        """Ранняя инициализация менеджеров ДО основного lifecycle. Default: no-op.

        Вызывается из GenericProcess._init_custom_managers() — до configure().
        Используется плагинами, которым нужно создать framework-менеджеры
        (SQLManager, кастомный RouterManager и т.д.) до того, как другие
        плагины начнут configure().

        Не путать с configure() — тот для SHM, middleware, воркеров.
        """

    def shutdown(self, ctx: PluginContext) -> None:
        """Очистка ресурсов. Default: no-op.

        Transition: * → STOPPED.
        """

    # --- State transitions (вызываются GenericProcess) ---

    def _do_configure(self, ctx: PluginContext) -> None:
        """IDLE → READY: configure + авторегистрация команд + метрики."""
        if self.state != PluginState.IDLE:
            ctx.log_error(f"Plugin '{self.name}': configure() в состоянии {self.state}, ожидается IDLE")
            return

        # Инициализация метрик
        from .metrics import PluginMetrics

        self.metrics = PluginMetrics(self.name)

        with self.metrics.measure("configure"):
            self.configure(ctx)
            self._auto_register_commands(ctx)

        self.state = PluginState.READY

    def _do_start(self, ctx: PluginContext) -> None:
        """READY → RUNNING."""
        if self.state != PluginState.READY:
            ctx.log_error(f"Plugin '{self.name}': start() в состоянии {self.state}, ожидается READY")
            return

        if self.metrics:
            with self.metrics.measure("start"):
                self.start(ctx)
        else:
            self.start(ctx)

        self.state = PluginState.RUNNING

    def _do_pause(self, ctx: PluginContext) -> None:
        """RUNNING → PAUSED."""
        if self.state != PluginState.RUNNING:
            return
        self.pause(ctx)
        self.state = PluginState.PAUSED

    def _do_resume(self, ctx: PluginContext) -> None:
        """PAUSED → RUNNING."""
        if self.state != PluginState.PAUSED:
            return
        self.resume(ctx)
        self.state = PluginState.RUNNING

    def _do_shutdown(self, ctx: PluginContext) -> None:
        """* → STOPPED."""
        if self.state == PluginState.STOPPED:
            return

        if self.metrics:
            with self.metrics.measure("shutdown"):
                self.shutdown(ctx)
        else:
            self.shutdown(ctx)

        self.state = PluginState.STOPPED

    def _auto_register_commands(self, ctx: PluginContext) -> None:
        """Автоматически зарегистрировать команды плагина в CommandManager.

        commands = {"set_hsv_range": "set_range"} → ищет метод self.set_range,
        регистрирует как команду "set_hsv_range" в CommandManager.

        Плюс: если плагин имеет register_class и не определил свою команду
        "set_config", автоматически регистрируется generic cmd_set_config —
        bridge.on_field_set → set_config → setattr(self._reg, field, value).
        """
        if not ctx.command_manager:
            return

        for cmd_name, method_name in self.commands.items():
            method = getattr(self, method_name, None)
            if method is None:
                ctx.log_error(f"Plugin '{self.name}': команда '{cmd_name}' → метод '{method_name}' не найден")
                continue

            ctx.command_manager.register_command(cmd_name, method)

        # Generic set_config — поднимает boilerplate из плагинов с register_class.
        # Регистрируется только если у плагина есть register_class и команда
        # set_config не была переопределена явно в self.commands.
        has_register = getattr(self, "register_class", None) is not None
        explicit_set_config = "set_config" in self.commands
        if has_register and not explicit_set_config:
            ctx.command_manager.register_command("set_config", self.cmd_set_config)

    def cmd_set_config(self, data: dict) -> dict:
        """Generic handler для bridge.on_field_set → applied dict из GUI.

        Применяет {field: value} к self._reg через setattr. Поля без
        соответствующего атрибута игнорируются (graceful skip с логом).

        Плагин может переопределить, добавив "set_config" в self.commands —
        тогда этот generic не регистрируется (см. _auto_register_commands).

        Returns:
            {"status": "ok", "applied": {...}, "skipped": [...]}
        """
        reg = getattr(self, "_reg", None)
        if reg is None:
            return {"status": "error", "error": "_reg not initialized"}

        applied: dict[str, Any] = {}
        skipped: list[str] = []
        for field_name, value in data.items():
            if hasattr(reg, field_name):
                setattr(reg, field_name, value)
                applied[field_name] = value
            else:
                skipped.append(field_name)

        ctx = getattr(self, "_ctx", None)
        if ctx is not None and hasattr(ctx, "log_info"):
            ctx.log_info(f"[{self.name} set_config] applied={applied}" + (f" skipped={skipped}" if skipped else ""))

        result: dict[str, Any] = {"status": "ok", "applied": applied}
        if skipped:
            result["skipped"] = skipped
        return result
