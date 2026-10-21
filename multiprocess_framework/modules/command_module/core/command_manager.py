"""
Командный менеджер для обработки и управления командами.

Простая абстракция над диспетчером, упрощающая работу с командами.
Наследуется от BaseManager и использует ObservableMixin для единообразия со всеми менеджерами системы.
"""

from typing import Dict, Any, Callable, Optional, List, TYPE_CHECKING
import time

if TYPE_CHECKING:
    from multiprocessing import Process

    from ...worker_module.interfaces import OrderedExecutor

from ...dispatch_module import Dispatcher, DispatchStrategy
from ...base_manager import BaseManager, ObservableMixin

from ..interfaces import LOG_SOURCE, ICommandManager


class _Deferred:
    """Тип сентинела ``DEFERRED`` (Task 1.9a, ADR-CMD-006). Один экземпляр на процесс."""

    __slots__ = ()

    def __repr__(self) -> str:
        return "DEFERRED"

    def __reduce__(self) -> str:
        # Копия/pickle возвращают тот же объект: проверка ``result is DEFERRED`` не ломается.
        return "DEFERRED"


#: Возврат ``handle_command(..., reply=r)`` для команды с исполнителем: ответ уйдёт через ``r``
#: ровно один раз (позже, с потока исполнителя, или уже ушёл на вызывающем). Без ``reply`` не
#: возвращается никогда — вызывающий без ``reply`` получает результат обработчика.
DEFERRED = _Deferred()

#: Допустимые значения ``targets`` в ``register_command``.
_TARGETS_ALLOWED = (None, "all")


class CommandManager(BaseManager, ObservableMixin, ICommandManager):
    """
    Командный менеджер для обработки и управления командами.

    Наследуется от BaseManager и использует ObservableMixin для:
    - Единообразия со всеми менеджерами системы
    - Автоматического логирования через ObservableMixin
    - Стандартного жизненного цикла (initialize/shutdown)

    Этот класс предоставляет простой интерфейс для регистрации и обработки команд,
    используя универсальный диспетчер для управления обработчиками.

    Attributes:
        manager_name (str): Имя менеджера (синоним process_name для совместимости)
        process_name (str): Имя процесса для идентификации (для обратной совместимости)
        dispatcher (Dispatcher): Внутренний диспетчер для управления обработчиками команд

    Пример использования:
        manager = CommandManager(
            manager_name="my_process",
            # Слот называется 'stats' — канон (CONNECTORS.md §1). Прежняя редакция
            # этой строки учила 'statistics': публичные прокси при нём создаются
            # (proxy_creator принимает оба имени), а встроенный self._record_metric
            # адресует ЖЁСТКО 'stats' — то есть метрики молча уходили в
            # manager_call_failures. Расхождение Н-6-сосед приёмки F1.
            managers={'logger': logger_manager, 'stats': stats_manager}
        )
        manager.initialize()

        manager.register_command("greet", greet_handler)
        result = manager.handle_command({"command": "greet", "data": {"name": "Alice"}})

        manager.shutdown()
    """

    def __init__(
        self,
        manager_name: str,
        process: Optional["Process"] = None,
        default_strategy: DispatchStrategy = DispatchStrategy.EXACT_MATCH,
        managers: Optional[Dict[str, Any]] = None,
        config: Optional[Dict[str, Any]] = None,
        config_manager: Optional[Any] = None,
        **kwargs,
    ):
        """
        Инициализация командного менеджера.

        Args:
            manager_name (str): Имя менеджера (для BaseManager)
            process (Process): Ссылка на родительский процесс (опционально, для BaseManager)
            default_strategy (DispatchStrategy): Стратегия диспетчера по умолчанию
            managers: Словарь менеджеров {имя: менеджер} (logger, stats и т.д.)
            config: Конфигурация включения/выключения функций {имя: bool}
            config_manager: Менеджер конфигурации для динамического обновления
            **kwargs: Дополнительные параметры для BaseManager и ObservableMixin
        """
        # Инициализация BaseManager
        BaseManager.__init__(self, manager_name=manager_name, process=process)

        # Для обратной совместимости
        self.process_name = manager_name

        mgr = managers or {}
        cfg = config or {}

        # Инициализация ObservableMixin
        ObservableMixin.__init__(
            self,
            managers=mgr,
            config=cfg,
        )

        self.dispatcher = Dispatcher(
            manager_name=f"{manager_name}_commands",
            process=process,
            default_strategy=default_strategy,
            managers=mgr,
            config=cfg,
        )

        # Гейт «рутинный успех команды» (observability.commands.log_success,
        # ЗАКРЫТ по умолчанию): успех штатной команды — не INFO-событие, на
        # hot-path это тысячи строк/сек (см. handle_command). Читаем из ТОГО
        # ЖЕ config-словаря, что enable_logging/enable_statistics выше —
        # один механизм переключения, не два (ADR-PM-018/ADR-CRM-006).
        self._log_success_enabled = bool(cfg.get("log_success", False))

        # Task 1.9a (ADR-CMD-006): реестр исполнителей команд — ВНЕ metadata
        # (get_handler_info отдаёт metadata по ссылке; объект исполнителя не должен
        # утекать в карточки и через границу процессов). Имя команды →
        # (исполнитель, key_from, targets). В metadata — только строки.
        self._executors: dict[str, tuple[OrderedExecutor, str | None, str | None]] = {}
        # Имена команд, о внеочередном исполнении которых (вызов без reply) уже
        # сказан WARNING: один на имя за жизнь менеджера.
        self._out_of_queue_warned: set[str] = set()

        # НЕ вызываем initialize() здесь - это делается явно после создания

    # ========================================================================
    # РЕАЛИЗАЦИЯ BaseManager - ЖИЗНЕННЫЙ ЦИКЛ
    # ========================================================================

    def initialize(self) -> bool:
        """
        Инициализация командного менеджера.

        Инициализирует внутренний диспетчер и готовит менеджер к работе.

        Returns:
            bool: True если инициализация успешна
        """
        try:
            # Инициализация диспетчера
            if not self.dispatcher.initialize():
                return False

            self.is_initialized = True
            self._log_info(f"CommandManager '{self.manager_name}' initialized")
            self._record_metric("command_manager.initialization.success", tags={"name": self.manager_name})
            return True
        except Exception as e:
            # Task 1.3b: было `_log_error` + `_track_error("...", error=e)` — второй
            # вызов передавал `error` и позиционно, и по имени (TypeError внутри
            # except). Один коннектор — `report_error` — не ловит и не может
            # поймать это же несоответствие сигнатуры.
            self.report_error(e, context="command_manager.initialize", name=self.manager_name)
            return False

    def _on_shutdown(self) -> bool:
        """
        Завершение работы командного менеджера.

        Завершает внутренний диспетчер и освобождает ресурсы.

        Returns:
            bool: True если завершение успешно
        """
        try:
            # Завершение диспетчера
            if self.dispatcher:
                self.dispatcher.shutdown()

            self.is_initialized = False
            self._log_info(f"CommandManager '{self.manager_name}' shutdown completed")
            self._record_metric("command_manager.shutdown.success", tags={"name": self.manager_name})
            return True
        except Exception as e:
            self.report_error(e, context="command_manager.shutdown", name=self.manager_name)
            return False

    # ========================================================================
    # РЕАЛИЗАЦИЯ BaseCommandManager - РАБОТА С КОМАНДАМИ
    # ========================================================================

    def register_command(
        self,
        command_name: str,
        handler: Callable,
        expects_full_message: bool = False,
        metadata: Dict[str, Any] = None,
        efficiency: int = 0,
        tags: List[str] = None,
        strategy: Optional[DispatchStrategy] = None,
        executor: "OrderedExecutor | None" = None,
        key_from: str | None = None,
        targets: str | None = None,
        **kwargs,
    ) -> bool:
        """
        Регистрация новой команды.

        Args:
            command_name (str): Название команды (ключ для диспетчеризации)
            handler (Callable): Функция-обработчик команды
            expects_full_message (bool): Если True, обработчик получает всё сообщение
            metadata (Dict): Дополнительные метаданные команды
            efficiency (int): Уровень эффективности (для FALLBACK_MATCH)
            tags (List[str]): Список тегов для группировки
            strategy (DispatchStrategy): Стратегия для регистрации (опционально)
            executor: Task 1.9a — исполнитель с порядком по ключу (``OrderedExecutor``).
                ``None`` (умолчание) — команда синхронная, как всегда. С исполнителем команда,
                пришедшая с ``reply``, исполняется на потоке исполнителя (ADR-CMD-006).
            key_from: имя поля ``data``, из которого берётся ключ: ``frozenset({data[key_from]})``.
            targets: ``"all"`` — ключ ``None`` («все ключи»). С ``executor`` задаётся ровно
                один из ``key_from`` / ``targets``.
            **kwargs: Дополнительные аргументы для регистрации обработчика

        Returns:
            bool: Успешность регистрации. ``False`` + WARNING без регистрации, если: ``executor``
            задан не ровно с одним из ``key_from`` / ``targets="all"``; ``targets`` вне
            ``{None, "all"}``; ``key_from`` / ``targets`` без ``executor``; ``executor`` при
            ``metadata["manages_own_reply"]`` (отказы исполнителя ушли бы в no-op ``reply``).

        Example:
            def greet_handler(data):
                return f"Hello, {data.get('name', 'World')}!"

            manager.register_command("greet", greet_handler)
        """
        self._log_debug(f"Registering command: {command_name}", module=LOG_SOURCE)
        self._record_metric("command_manager.command.registration.attempts", tags={"command": command_name})

        refusal = self._executor_refusal(executor, key_from, targets, metadata)
        if refusal is not None:
            self._log_warning(
                f"Command '{command_name}' не зарегистрирована: {refusal}",
                module=LOG_SOURCE,
            )
            self._record_metric("command_manager.command.registration.failed", tags={"command": command_name})
            return False
        if executor is not None:
            # Только строки: metadata отдаётся наружу по ссылке (get_handler_info,
            # introspect). Словарь вызывающего не мутируем — копия.
            metadata = dict(metadata or {})
            metadata["executor"] = str(getattr(executor, "name", None) or type(executor).__name__)
            if key_from is not None:
                metadata["key_from"] = key_from
            if targets is not None:
                metadata["targets"] = targets

        result = self.dispatcher.register_handler(
            key=command_name,
            handler=handler,
            expects_full_message=expects_full_message,
            metadata=metadata,
            efficiency=efficiency,
            tags=tags,
            strategy=strategy,
        )

        if result:
            if executor is not None:
                self._executors[command_name] = (executor, key_from, targets)
            self._log_debug(lambda: f"Command '{command_name}' registered successfully", module=LOG_SOURCE)
            self._record_metric("command_manager.command.registration.success", tags={"command": command_name})
        else:
            self._log_warning(f"Failed to register command '{command_name}'", module=LOG_SOURCE)
            self._record_metric("command_manager.command.registration.failed", tags={"command": command_name})

        return result

    @staticmethod
    def _executor_refusal(
        executor: "OrderedExecutor | None",
        key_from: str | None,
        targets: str | None,
        metadata: Dict[str, Any] | None,
    ) -> str | None:
        """Причина отказа регистрации по аргументам Task 1.9a или ``None``, если сочетание допустимо."""
        if targets not in _TARGETS_ALLOWED:
            return f"targets={targets!r} вне {{None, 'all'}}"
        if executor is None:
            if key_from is not None or targets is not None:
                return "key_from/targets без executor"
            return None
        if not callable(getattr(executor, "submit", None)):
            return "executor без метода submit (ожидается OrderedExecutor)"
        if (key_from is None) == (targets is None):
            return "executor требует ровно одно из key_from / targets='all'"
        if key_from is not None and not (isinstance(key_from, str) and key_from):
            return "key_from должен быть непустой строкой"
        if (metadata or {}).get("manages_own_reply"):
            return "executor несовместим с metadata.manages_own_reply (отказы исполнителя ушли бы в no-op reply)"
        return None

    def log_registration_summary(self) -> None:
        """
        INFO-сводка регистрации — ОДНА строка, снимок таблицы команд НА
        МОМЕНТ ВЫЗОВА, а не «итог бута»: следующий ``register_command()``
        делает эту сводку устаревшей, и это ожидаемо — метод не хранит
        прошлое значение, каждый вызов считает таблицу заново.

        Прод зовёт этот метод РОВНО ОДИН РАЗ за ВОПЛОЩЕНИЕ процесса:
        ``ProcessModule.run()``,
        сразу после последней бутовой регистрации (``BuiltinCommands.register()``).
        Слово «воплощение», а не «процесс», выбрано по находке ревью Task 3.2:
        ``ProcessManagerProcess.restart_process`` поднимает НОВЫЙ OS-процесс, у
        которого свой ``run()``, — значит в каталоге одного логического процесса
        после авто-рестарта окажутся ДВЕ сводки, по одной на воплощение, и это
        правильно. Формулировка «за процесс» отправила бы читателя искать дефект.

        «Ровно один раз» — свойство ТОЙ точки вызова, а не этого метода:
        флага «уже вызывалась» здесь нарочно нет (Task 3.2, К2).

        Вложенный диспетчер этого менеджера (``self.dispatcher``) СВОЙ
        ``log_registration_summary()`` из ``run()`` не получает — вердикт
        CTO: ``register_command`` делегирует РОВНО в один вызов
        ``self.dispatcher.register_handler``, поэтому счётчики обоих
        менеджеров равны по построению (стенд Task 3.2: 71/71, 93/93 на всех
        восьми процессах прототипа). Две INFO-строки с одним и тем же числом
        под разными существительными были бы загадкой для читателя лога, а
        не информацией — см. докстринг ``Dispatcher.log_registration_summary``
        за симметричным объяснением с той стороны.

        Поздняя регистрация (горячая пересборка) сводкой не покрывается —
        о ней по-прежнему говорит построчный DEBUG у ``register_command()``.
        Механизм, который приносит пачку регистраций, обязан сам сказать
        «+N/-M» (только он знает границы своей пачки) и вправе позвать эту
        сводку после неё — в Task 3.2 это не делается.
        """
        count = len(self.get_commands())
        self._log_info(
            f"CommandManager '{self.manager_name}' registration summary: {count} commands",
            module=LOG_SOURCE,
        )

    def handle_command(self, message: Dict, *, reply: Callable[[Any], None] | None = None) -> Any:
        """
        Обработка командного сообщения.

        Args:
            message (Dict): Сообщение для обработки. Ожидается поле 'command' с именем команды.
            reply: Task 1.9a — приёмник результата для команды с исполнителем (ADR-CMD-006).
                Команда без исполнителя исполняется синхронно, ``reply`` не используется.

        Returns:
            Any: Результат выполнения команды или ``{"status": "error", "reason": "..."}``
            (ошибки обрабатываются внутри ``Dispatcher.dispatch()``).

            Команда с исполнителем:
            - ключ не извлечён (``data[key_from]`` нет / не непустая ``str``) → возврат
              ``{"success": False, "error": "key_missing", "command": <имя>}`` + WARNING, обработчик не
              вызван, ``reply`` не вызван (и с ``reply``, и без);
            - с ``reply`` → операция отдана исполнителю, возврат ``DEFERRED``; ``reply`` получит
              результат ровно один раз (или отказ исполнителя ``system_stopping`` / ``executor_busy``);
            - без ``reply`` → исполнение на месте + один WARNING на имя «исполнено вне очереди ключа»;
              без ``reply`` ``DEFERRED`` не возвращается никогда.

        Example:
            message = {
                "command": "greet",
                "data": {"name": "Alice"}
            }
            result = manager.handle_command(message)
        """
        # 2.2 (Р2.2-10): часы длительности — ``perf_counter``, а не ``time``.
        # Одна команда на этом пути живёт десятки-сотни микросекунд, а шаг
        # ``time.time()``/``monotonic`` на Windows ≈ 15.6 мс: все замеры короче
        # шага давали ровно 0.0 либо ровно 0.0156, то есть по бакетам
        # длительностей раскладывались бы двумя столбиками вместо распределения.
        # Значение используется ТОЛЬКО как разность — эпоха ``perf_counter``
        # (произвольная точка отсчёта) роли не играет.
        start_time = time.perf_counter()
        command_name = message.get("command", "unknown")

        self._log_debug(f"Handling command: {command_name}", module=LOG_SOURCE, command=command_name)
        self._record_metric("command_manager.command.execution.attempts", tags={"command": command_name})

        binding = self._executors.get(command_name) if self._executors else None
        if binding is not None:
            executor, key_from, _targets = binding
            if key_from is None:
                key = None  # targets="all": «все ключи»
            else:
                data = message.get("data")
                value = data.get(key_from) if isinstance(data, dict) else None
                if not (isinstance(value, str) and value):
                    # Значение поля в текст не попадает (может быть чем угодно).
                    self._log_warning(
                        f"Command '{command_name}': поле ключа '{key_from}' отсутствует или не непустая строка — "
                        f"отказ key_missing, обработчик не вызван",
                        module=LOG_SOURCE,
                    )
                    self._record_metric("command_manager.command.execution.errors", tags={"command": command_name})
                    return {"success": False, "error": "key_missing", "command": command_name}
                key = frozenset({value})

            if reply is not None:
                ran = [False]  # action стартовала → ответ её; иначе ответ — отказ исполнителя

                def action() -> Any:
                    # Блок после диспетчеризации (лог, метрики, длительность) — ПОСЛЕ
                    # исполнения, на потоке исполнителя: метрика меряет исполнение, не подачу.
                    ran[0] = True
                    t0 = time.perf_counter()
                    try:
                        res = self.dispatcher.dispatch(message, key_field="command", data_field="data")
                    except Exception as exc:  # noqa: BLE001 — тот же конверт, что у роутера
                        res = {"status": "error", "reason": str(exc)}
                    self._finish_command(command_name, res, time.perf_counter() - t0)
                    return res

                def counted_reply(r: Any) -> None:
                    # Отказ исполнителя (system_stopping / executor_busy) без исполнения action —
                    # тоже исход команды: ошибка в логе и метрике errors, без длительности
                    # (исполнения не было). Ревью р.1 п.3.
                    # reply — в finally: сбой учёта исхода не должен отнять у инициатора ответ
                    # (ревью р.2, мелочь Б).
                    try:
                        if not ran[0]:
                            error = r.get("error") if isinstance(r, dict) else r
                            self._finish_command(command_name, {"status": "error", "reason": error}, None)
                    finally:
                        reply(r)

                action.__name__ = command_name
                executor.submit(action, key, counted_reply)
                return DEFERRED

            if command_name not in self._out_of_queue_warned:
                self._out_of_queue_warned.add(command_name)
                self._log_warning(
                    f"Command '{command_name}' вызвана без reply — исполнено вне очереди ключа "
                    f"(на вызывающем потоке, мимо исполнителя); следующий такой вызов — без WARNING",
                    module=LOG_SOURCE,
                )

        result = self.dispatcher.dispatch(message, key_field="command", data_field="data")
        self._finish_command(command_name, result, time.perf_counter() - start_time)
        return result

    def _finish_command(self, command_name: str, result: Any, duration: float | None) -> None:
        """Блок после диспетчеризации: лог ошибки/успеха, метрики, длительность исполнения.

        ``duration=None`` — исполнения не было (отказ исполнителя): длительность не пишется."""
        if isinstance(result, dict) and result.get("status") == "error":
            self._log_warning(
                f"Command '{command_name}' failed: {result.get('reason') or result.get('error')}",
                module=LOG_SOURCE,
            )
            self._record_metric("command_manager.command.execution.errors", tags={"command": command_name})
        else:
            # Рутинный успех — не INFO-событие: на hot-path (тысячи команд/сек,
            # напр. state.merge) именно эта строка топила ротацию логов
            # (messages.log вырос до 645 МБ за один прогон). Гейт у ИСТОЧНИКА:
            # f-string форматируется, только если log_success явно включён
            # (observability.commands.log_success) — по умолчанию запись не
            # производится вовсе, а не просто фильтруется на выходе.
            if self._log_success_enabled:
                self._log_info(
                    f"Command '{command_name}' executed successfully in {duration:.3f}s",
                    module=LOG_SOURCE,
                )
            self._record_metric("command_manager.command.execution.success", tags={"command": command_name})

        if duration is not None:
            self._record_timing("command_manager.command.execution.duration", duration, tags={"command": command_name})

    def set_log_success_enabled(self, enabled: bool) -> None:
        """Включить/выключить лог рутинного успеха команд (observability control plane).

        Дефолт — выключено (см. ``__init__``: ``cfg.get("log_success", False)``):
        успешное выполнение штатной команды — не INFO-событие, на hot-path это
        тысячи строк/сек. Ошибки/неуспех эта настройка не трогает — handle_command
        логирует их всегда, независимо от значения этого флага.
        """
        self._log_success_enabled = bool(enabled)

    def get_commands(self) -> List[Dict]:
        """
        Получение списка всех зарегистрированных команд.

        Returns:
            List[Dict]: Список словарей с информацией о каждом обработчике

        Example:
            commands = manager.get_commands()
            for cmd in commands:
                print(f"Command: {cmd['key']}")
        """
        return self.dispatcher.get_all_handlers()

    # ========================================================================
    # ДОПОЛНИТЕЛЬНЫЕ МЕТОДЫ
    # ========================================================================

    def get_stats(self) -> Dict[str, Any]:
        """
        Получение статистики командного менеджера.

        Returns:
            Dict[str, Any]: Статистика менеджера
        """
        commands = self.get_commands()
        base_stats = super().get_stats()  # Получаем статистику от BaseManager

        return {
            **base_stats,
            "process_name": self.process_name,  # Для обратной совместимости
            "total_commands": len(commands),
            "commands": [cmd.get("key", "") for cmd in commands],
            "dispatcher_strategy": self.dispatcher.default_strategy.value,
        }

    def get_command_info(self, command_name: str) -> Optional[Dict]:
        """
        Получение информации о конкретной команде.

        Args:
            command_name: Название команды

        Returns:
            Словарь с информацией о команде или None
        """
        return self.dispatcher.get_handler_info(command_name)

    def get_commands_by_tag(self, tag: str) -> List[Dict]:
        """
        Получение команд по тегу.

        Args:
            tag: Тег для фильтрации

        Returns:
            Список команд с указанным тегом
        """
        return self.dispatcher.get_handlers_by_tag(tag)

    def update_command_metadata(self, command_name: str, metadata: Dict[str, Any]) -> bool:
        """
        Обновление метаданных команды.

        Args:
            command_name: Название команды
            metadata: Новые метаданные

        Returns:
            True если обновлено, False в случае ошибки
        """
        return self.dispatcher.update_handler_metadata(command_name, metadata)

    def update_command_tags(self, command_name: str, tags: List[str]) -> bool:
        """
        Обновление тегов команды.

        Args:
            command_name: Название команды
            tags: Новые теги

        Returns:
            True если обновлено, False в случае ошибки
        """
        return self.dispatcher.update_handler_tags(command_name, tags)

    def overwrite_command(
        self,
        command_name: str,
        handler: Callable,
        expects_full_message: bool = False,
        metadata: Dict[str, Any] = None,
        efficiency: int = 0,
        tags: List[str] = None,
    ) -> bool:
        """
        Принудительная перезапись команды.

        Args:
            command_name: Название команды
            handler: Новый обработчик
            expects_full_message: Если True, обработчик получает всё сообщение
            metadata: Метаданные команды
            efficiency: Уровень эффективности
            tags: Список тегов

        Returns:
            True если перезаписано, False в случае ошибки

        Task 1.9a (ADR-CMD-006): перезапись снимает запись исполнителя — команда снова синхронная.
        """
        result = self.dispatcher.overwrite_handler(
            key=command_name,
            handler=handler,
            expects_full_message=expects_full_message,
            metadata=metadata,
            efficiency=efficiency,
            tags=tags,
        )
        if result:
            self._executors.pop(command_name, None)
        return result
