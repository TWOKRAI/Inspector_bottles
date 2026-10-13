"""
BaseManager — абстрактный базовый класс для всех менеджеров системы.
"""

import threading
from typing import Dict, Any, Optional, List
from abc import abstractmethod

from ..._fallback import FallbackLogger
from ..interfaces import IBaseManager, IScope
from ..utils.name_utils import get_adapter_name_from_class
from .lifetime import _manager_scope_view

# Строки шаблона shutdown() — сообщение оператору: дом — вид (FallbackLogger), не emergency_log.
_logger = FallbackLogger(__name__)


class _ManagerLife:
    """Состояние шаблона ``shutdown()`` одного менеджера (Task 1.2b-1, ADR-BM-009).

    Живёт в ``__dict__`` менеджера под ключом ``_bm_life`` (Р7 (в), вердикт CTO):
    цикл менеджер <-> область — обычный мусор для gc, глобального якоря нет.
    pickle (в том числе через чужие ``__getstate__`` — ``__dict__.copy()`` минус
    свой список) кладёт вместо записи ``__reduce__`` -> новую пустую запись:
    у копии после распаковки ``scope is None`` и свой, чистый останов.
    """

    __slots__ = ("scope", "lock", "state", "thread", "done", "result")

    def __init__(self) -> None:
        self.scope: IScope | None = None
        self.lock = threading.Lock()
        self.state = "idle"  # idle -> running -> done
        self.thread: int | None = None
        self.done = threading.Event()
        self.result = False

    def __reduce__(self):
        # Ни лок, ни событие, ни область через pickle не идут: копия получает пустую запись.
        return (type(self), ())


_LIFE_KEY = "_bm_life"


def _life_of(manager: "BaseManager", *, create: bool) -> _ManagerLife | None:
    """Запись жизни менеджера; ``setdefault`` атомарен под GIL (работает и после ``cls.__new__``)."""
    if create:
        return manager.__dict__.setdefault(_LIFE_KEY, _ManagerLife())
    return manager.__dict__.get(_LIFE_KEY)


class BaseManager(IBaseManager):
    """
    Абстрактный базовый класс для всех менеджеров системы.

    Реализует контракт IBaseManager и предоставляет:
    - Управление жизненным циклом (initialize / shutdown)
    - Подключение адаптеров (attach_adapter / get_adapter / detach_adapter)
    - Диагностику (get_stats / get_debug_info)

    Типичное использование совместно с ObservableMixin:

        class LoggerManager(BaseManager, ObservableMixin):
            def __init__(self, name, logger=None):
                BaseManager.__init__(self, name)
                ObservableMixin.__init__(self, managers={'logger': logger})

            def initialize(self) -> bool:
                self.is_initialized = True
                return True

            def _on_shutdown(self) -> bool:
                self.is_initialized = False
                return True

    Attributes:
        manager_name (str):      Уникальное имя менеджера
        process (Optional[Any]): Ссылка на родительский процесс (если есть)
        is_initialized (bool):   Флаг инициализации
    """

    # Срок тела ``_on_shutdown`` во втором вызове ``shutdown()``: срок ожидания =
    # член области + это значение (Task 1.2b-2, ADR-BM-009). Класс со своим
    # сроком join/wait в теле ставит не меньше; экземпляр может переопределить.
    _ON_SHUTDOWN_WAIT_S: float = 5.0

    def __init__(self, manager_name: str, process: Optional[Any] = None):
        """
        Args:
            manager_name: Уникальное имя менеджера
            process:      Ссылка на родительский процесс
        """
        self.manager_name = manager_name
        self.process = process
        self.is_initialized = False
        self._adapters: Dict[str, Any] = {}

    # =========================================================================
    # ПУБЛИЧНЫЙ API — ЖИЗНЕННЫЙ ЦИКЛ (abstractmethod из IBaseManager)
    # =========================================================================

    @abstractmethod
    def initialize(self) -> bool:
        """
        Инициализация менеджера. Реализуется в подклассах.

        Returns:
            True если инициализация успешна
        """

    def shutdown(self) -> bool:
        """
        Шаблон останова (Task 1.2b-1, ADR-BM-009). Подклассы определяют
        ``_on_shutdown``, а не ``shutdown`` (мягкий режим: свои ``shutdown``
        у подклассов пока разрешены и шаблон обходят — до 1.2b-2/1.2b-3).

        Первый вызов: ставит «идёт» и запоминает поток, закрывает привязанную
        ``scope``, затем один раз зовёт ``_on_shutdown()``; результат
        ``bool(...)`` кэшируется. Исключение в ``_on_shutdown`` -> ``False``
        и строка лога. Вызов из потока, который сейчас выполняет ``shutdown()``
        (реентрантный), и вызов из потока поддерева ``scope`` -> ``False`` сразу.
        Вызов из другого потока ждёт первый не дольше срока области
        (``budget_s + kill_reserve_s``; без ``Scope`` — 5,0 с) плюс
        ``_ON_SHUTDOWN_WAIT_S`` (класс — 5,0 с, экземпляр может переопределить);
        на сроке — ``False`` и строка лога. После завершения — кэшированный результат.

        Returns:
            True если завершение успешно
        """
        scope = self.scope
        in_subtree, scope_wait_s = _manager_scope_view(scope)
        wait_s = scope_wait_s + self._ON_SHUTDOWN_WAIT_S
        if in_subtree:
            # Поток области сам себя не дождётся: close области ждёт его выхода.
            return False
        life = _life_of(self, create=True)
        assert life is not None
        me = threading.get_ident()
        with life.lock:
            if life.state == "done":
                return life.result
            if life.state == "running":
                if life.thread == me:
                    return False
                waiting = True
            else:
                waiting = False
                life.state = "running"
                life.thread = me
        if waiting:
            if life.done.wait(wait_s):
                return life.result
            self._shutdown_log(
                f"shutdown {self.manager_name}: первый вызов не завершился за {wait_s:g} с — второй вызов вернул False"
            )
            return False

        result = False
        try:
            if scope is not None:
                try:
                    scope.close()
                except Exception as exc:
                    self._shutdown_log(f"shutdown {self.manager_name}: scope.close упал: {type(exc).__name__}: {exc}")
            try:
                result = bool(self._on_shutdown())
            except Exception as exc:
                result = False
                self._shutdown_log(f"shutdown {self.manager_name}: _on_shutdown упал: {type(exc).__name__}: {exc}")
        finally:
            # BaseException (KeyboardInterrupt) уходит наверх, но ждущие не висят.
            with life.lock:
                life.result = result
                life.state = "done"
            life.done.set()
        return result

    def _on_shutdown(self) -> bool:
        """
        Тело останова подкласса; зовётся шаблоном ``shutdown()`` один раз,
        после закрытия ``scope``. По умолчанию ничего не делает (мягкий режим).

        Returns:
            True если завершение успешно
        """
        return True

    @property
    def scope(self) -> IScope | None:
        """Область менеджера; ``None`` до ``attach_scope``. Только чтение."""
        life = _life_of(self, create=False)
        return None if life is None else life.scope

    def attach_scope(self, scope: IScope) -> None:
        """
        Привязать область (проводка корня, вызывает ``ProcessModule``).
        Область закрывается первым шагом ``shutdown()``.

        Raises:
            TypeError:    ``scope is None``
            RuntimeError: область уже привязана
        """
        if scope is None:
            raise TypeError(f"attach_scope {self.manager_name}: нужна область, получено None")
        life = _life_of(self, create=True)
        assert life is not None
        with life.lock:
            if life.scope is not None:
                raise RuntimeError(f"attach_scope {self.manager_name}: область уже привязана ({life.scope.path})")
            life.scope = scope

    def _shutdown_log(self, message: str) -> None:
        """Строка шаблона ``shutdown()`` — только вид модуля (решение CTO 2026-10-12).

        Слот-дорога ``_log_error`` теряет строку у миксина без логгера и после
        ``LoggerManager.shutdown()`` и удваивает её у ``ProcessModule`` (карта путей 1.2b-1).
        Вид сам идёт в ``LoggerManager``, если он поднят, иначе — stdlib.
        """
        _logger.error("%s", message)

    # =========================================================================
    # ПУБЛИЧНЫЙ API — УПРАВЛЕНИЕ АДАПТЕРАМИ
    # =========================================================================

    def attach_adapter(self, adapter: Any, name: Optional[str] = None) -> bool:
        """
        Подключить адаптер к менеджеру.

        Адаптер предоставляет дополнительную функциональность (интеграция
        с процессом, упрощённый API и т.д.).

        Args:
            adapter: Экземпляр адаптера (наследник BaseAdapter)
            name:    Имя адаптера. Рекомендуется указывать явно.
                     Если не указано — определяется из имени класса.

        Returns:
            True если адаптер успешно подключён

        Example:
            >>> manager.attach_adapter(CommandAdapter(manager, process), name="command")
            >>> adapter = manager.get_adapter("command")
        """
        if adapter is None:
            return False

        if name is None:
            name = get_adapter_name_from_class(adapter.__class__.__name__)

        self._adapters[name] = adapter

        if hasattr(adapter, "manager"):
            adapter.manager = self

        return True

    def get_adapter(self, name: Optional[str] = None) -> Optional[Any]:
        """
        Получить адаптер по имени (РЕКОМЕНДУЕМЫЙ способ доступа).

        Args:
            name: Имя адаптера. Если не указано — возвращается первый адаптер.

        Returns:
            Адаптер или None если не найден
        """
        if name is None:
            for adapter in self._adapters.values():
                if adapter is not None:
                    return adapter
            return None

        return self._adapters.get(name) or None

    def has_adapter(self, name: str) -> bool:
        """Проверить наличие адаптера по имени."""
        return name in self._adapters

    def list_adapters(self) -> List[str]:
        """Список имён подключённых адаптеров."""
        return list(self._adapters.keys())

    def detach_adapter(self, name: str) -> bool:
        """
        Отключить адаптер от менеджера.

        Args:
            name: Имя адаптера

        Returns:
            True если адаптер был подключён и отключён, False если не найден
        """
        if name in self._adapters:
            del self._adapters[name]
            return True
        return False

    # =========================================================================
    # ПУБЛИЧНЫЙ API — СТАТИСТИКА
    # =========================================================================

    def get_stats(self) -> Dict[str, Any]:
        """
        Статистика менеджера: имя, статус, список адаптеров.

        Returns:
            dict с ключами: manager_name, is_initialized, process_name, adapters
        """
        stats: Dict[str, Any] = {
            "manager_name": self.manager_name,
            "is_initialized": self.is_initialized,
            "process_name": (getattr(self.process, "name", "unknown") if self.process else "standalone"),
            "adapters": list(self._adapters.keys()),
        }

        if self._adapters:
            adapters_info: Dict[str, Any] = {}
            for adapter_name, adapter in self._adapters.items():
                if adapter is None:
                    adapters_info[adapter_name] = {}
                elif hasattr(adapter, "get_stats"):
                    try:
                        adapters_info[adapter_name] = adapter.get_stats()
                    except Exception:
                        adapters_info[adapter_name] = {}
                else:
                    adapters_info[adapter_name] = {}
            stats["adapters_info"] = adapters_info

        return stats

    # =========================================================================
    # ПУБЛИЧНЫЙ API — ДИАГНОСТИКА
    # =========================================================================

    def get_debug_info(self) -> Dict[str, Any]:
        """
        Подробная информация для отладки.

        Returns:
            dict с ключами: manager_name, is_initialized, process_name,
            adapters, adapter_details, available_methods,
            observable_managers (если ObservableMixin подключён)
        """
        info: Dict[str, Any] = {
            "manager_name": self.manager_name,
            "is_initialized": self.is_initialized,
            "process_name": (getattr(self.process, "name", "unknown") if self.process else "standalone"),
            "adapters": list(self._adapters.keys()),
            "adapter_details": {n: type(a).__name__ if a is not None else None for n, a in self._adapters.items()},
            "available_methods": [m for m in dir(self) if not m.startswith("__") and callable(getattr(self, m, None))],
        }

        if hasattr(self, "get_available_methods"):
            try:
                obs = self.get_available_methods()
                info["observable_managers"] = obs.get("managers", [])
                info["observable_methods"] = {
                    "private": len(obs.get("private", [])),
                    "public": len(obs.get("public", [])),
                }
            except Exception:
                pass

        return info

    def print_debug_info(self) -> None:
        """Вывести диагностическую информацию через логгер."""
        import json

        info = self.get_debug_info()
        self._log_debug(f"Debug Info: {self.__class__.__name__}\n{json.dumps(info, indent=2, ensure_ascii=False)}")

    def __str__(self) -> str:
        return f"{self.__class__.__name__}(name={self.manager_name!r}, initialized={self.is_initialized})"

    def __repr__(self) -> str:
        return self.__str__()
