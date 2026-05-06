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
from enum import Enum
from typing import TYPE_CHECKING, Any, Callable, ClassVar

if TYPE_CHECKING:
    from ..io import ProcessIO


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
    IDLE = "idle"        # Зарегистрирован, не инициализирован
    READY = "ready"      # configure() выполнен, ресурсы выделены
    RUNNING = "running"  # start() выполнен, данные текут
    PAUSED = "paused"    # Приостановлен, ресурсы удерживаются
    STOPPED = "stopped"  # shutdown() выполнен, ресурсы освобождены


class PluginContext:
    """Фасад над ProcessModule — всё что нужно плагину, без прямой связи с кишками.

    Создаётся GenericProcess'ом и передаётся в каждый плагин.
    Для каждого плагина создаётся копия с plugin-specific config.
    """

    def __init__(
        self,
        process_name: str,
        config: dict[str, Any],
        process: Any,
        io: ProcessIO,
        registers: Any | None = None,
    ) -> None:
        self.process_name = process_name
        self.config = config

        # Менеджеры — прямые ссылки (без обёртки, плагин сам решает что использовать)
        self.worker_manager = process.worker_manager
        self.command_manager = process.command_manager
        self.router_manager = process.router_manager
        self.memory_manager = process.memory_manager

        # IPC facade
        self.io = io

        # Registers (Phase 5.9) — RegistersManager | None
        # Плагин читает self._reg = ctx.registers.get_register("plugin_name")
        self.registers = registers

        # Logging
        self.log_info: Callable[[str], None] = process._log_info
        self.log_error: Callable[[str], None] = process._log_error

        # Доступ к низкоуровневым методам процесса (send/receive)
        self.send_message: Callable = process.send_message
        self.receive_message: Callable = process.receive_message

        # Ссылка на процесс для продвинутых плагинов (SHM middleware и т.д.)
        self._process = process

    def with_config(
        self,
        plugin_config: dict[str, Any],
        registers: Any | None = None,
    ) -> PluginContext:
        """Создать копию контекста с plugin-specific конфигом."""
        return PluginContext(
            process_name=self.process_name,
            config=plugin_config,
            process=self._process,
            io=self.io,
            registers=registers,
        )


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
    """

    name: str = ""
    category: str = ""  # "source" | "processing" | "output"

    # Контракт портов — переопределяется в подклассах
    inputs: list = []   # list[Port]
    outputs: list = []  # list[Port]

    # Команды — {command_name: method_name}
    # Автоматически регистрируются в CommandManager при configure
    commands: dict[str, str] = {}

    # Thread-safety контракт (Q8):
    # False (default) — sequential, safe by default.
    # True — разрешает параллельный вызов process() (для stateless плагинов).
    thread_safe: ClassVar[bool] = False

    def __init__(self) -> None:
        self.state: PluginState = PluginState.IDLE
        self.metrics: PluginMetrics | None = None

    # --- Data pipeline контракт (Phase 5) ---

    @property
    def is_source(self) -> bool:
        """True если плагин — источник данных (category == 'source')."""
        return self.category == "source"

    def register_schema(self) -> Any | None:
        """Опциональный регистр плагина (SchemaBase instance).

        Если None — плагин на defaults из config (graceful degradation).
        Convention: возвращённая схема маппится на plugin.name
        в RegistersManager процесса.

        Returns:
            SchemaBase instance с FieldMeta полями или None.
        """
        return None

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
        raise NotImplementedError(
            f"Plugin '{self.name}' does not implement produce()"
        )

    @abstractmethod
    def configure(self, ctx: PluginContext) -> None:
        """Объявить ресурсы: SHM, middleware, обработчики сообщений.

        Transition: IDLE → READY.
        Команды из self.commands регистрируются автоматически (GenericProcess).
        """

    @abstractmethod
    def start(self, ctx: PluginContext) -> None:
        """Запуск после configure всех плагинов. Создание воркеров.

        Transition: READY → RUNNING.
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
        """
        if not self.commands or not ctx.command_manager:
            return

        for cmd_name, method_name in self.commands.items():
            method = getattr(self, method_name, None)
            if method is None:
                ctx.log_error(
                    f"Plugin '{self.name}': команда '{cmd_name}' → "
                    f"метод '{method_name}' не найден"
                )
                continue

            ctx.command_manager.register_command(cmd_name, method)
