"""
Публичные контракты (интерфейсы) модуля base_manager.

Используются для:
- Аннотаций типов и статической проверки (pyright)
- Создания моков в тестах
- Документации ожидаемого поведения

Пример использования в type hints:
    from typing import TYPE_CHECKING
    if TYPE_CHECKING:
        from multiprocess_framework.modules.base_manager.interfaces import IBaseManager
"""

from __future__ import annotations

import threading
from abc import ABC, abstractmethod
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Optional, Dict, Set, List, Protocol, runtime_checkable

# =============================================================================
# IBaseManager
# =============================================================================


class IBaseManager(ABC):
    """
    Контракт базового менеджера.

    Все менеджеры системы наследуют BaseManager, который реализует
    этот интерфейс. Используйте IBaseManager для type hints и проверки
    isinstance() там, где важна принадлежность к иерархии менеджеров.
    """

    # ---- Жизненный цикл ----

    @abstractmethod
    def initialize(self) -> bool:
        """Инициализировать менеджер. True — успех."""

    @abstractmethod
    def shutdown(self) -> bool:
        """Корректно завершить работу. True — успех."""

    # ---- Адаптеры ----

    @abstractmethod
    def attach_adapter(self, adapter: Any, name: Optional[str] = None) -> bool:
        """
        Подключить адаптер.

        Args:
            adapter: Экземпляр адаптера
            name:    Имя адаптера (рекомендуется указывать явно)

        Returns:
            True если подключён успешно
        """

    @abstractmethod
    def get_adapter(self, name: Optional[str] = None) -> Optional[Any]:
        """
        Получить адаптер по имени.

        Returns:
            Адаптер или None
        """

    @abstractmethod
    def has_adapter(self, name: str) -> bool:
        """True если адаптер с таким именем подключён."""

    @abstractmethod
    def list_adapters(self) -> List[str]:
        """Список имён подключённых адаптеров."""

    @abstractmethod
    def detach_adapter(self, name: str) -> bool:
        """Отключить адаптер. True если он был подключён."""

    # ---- Статистика / диагностика ----

    @abstractmethod
    def get_stats(self) -> Dict[str, Any]:
        """Статистика менеджера."""

    @abstractmethod
    def get_debug_info(self) -> Dict[str, Any]:
        """Подробная диагностическая информация."""


# =============================================================================
# IBaseAdapter
# =============================================================================


class IBaseAdapter(ABC):
    """
    Контракт базового адаптера.

    Адаптер инкапсулирует логику взаимодействия менеджера с процессом
    или внешним ресурсом.
    """

    @abstractmethod
    def setup(self) -> bool:
        """Настроить адаптер. True — успех."""

    @abstractmethod
    def is_initialized(self) -> bool:
        """True если адаптер готов к работе."""


# =============================================================================
# IObservableMixin
# =============================================================================


class IObservableMixin(ABC):
    """
    Контракт ObservableMixin.

    Определяет полный публичный API для наблюдаемости менеджеров:
    регистрация внешних сервисов (logger, stats, error …), управление
    их состоянием и получение диагностики.
    """

    # ---- Управление менеджерами ----

    @abstractmethod
    def register_manager(self, name: str, manager: Any, enabled: bool = True) -> None:
        """Зарегистрировать менеджер под именем name."""

    @abstractmethod
    def unregister_manager(self, name: str) -> None:
        """Удалить менеджер из реестра."""

    @abstractmethod
    def get_manager(self, name: str) -> Optional[Any]:
        """Получить менеджер по имени."""

    @abstractmethod
    def has_manager(self, name: str) -> bool:
        """True если менеджер зарегистрирован."""

    # ---- Состояние ----

    @abstractmethod
    def enable(self, manager_name: str, enabled: bool = True) -> None:
        """Включить или выключить менеджер."""

    @abstractmethod
    def disable(self, manager_name: str) -> None:
        """Выключить менеджер."""

    @abstractmethod
    def is_enabled(self, manager_name: str) -> bool:
        """True если менеджер включён."""

    @abstractmethod
    def get_enabled_managers(self) -> Set[str]:
        """Множество имён включённых менеджеров."""

    @abstractmethod
    def context(self, manager_name: str, enabled: bool = True):
        """Контекстный менеджер для временного изменения состояния."""

    # ---- Конфигурация ----

    @abstractmethod
    def update_config(self, config: Dict[str, Any]) -> None:
        """Обновить конфигурацию."""

    @abstractmethod
    def get_config(self) -> Dict[str, Any]:
        """Текущая конфигурация."""

    @abstractmethod
    def get_state(self) -> Dict[str, Any]:
        """Полный снимок состояния."""

    # ---- Встроенные методы наблюдаемости ----

    @abstractmethod
    def _log(self, level: str, message: str, **kwargs) -> None:
        """Логирование через logger manager."""

    @abstractmethod
    def _log_debug(self, message: str, **kwargs) -> None:
        """Логирование уровня DEBUG."""

    @abstractmethod
    def _log_info(self, message: str, **kwargs) -> bool:
        """Логирование уровня INFO."""

    @abstractmethod
    def _log_warning(self, message: str, **kwargs) -> bool:
        """Логирование уровня WARNING."""

    @abstractmethod
    def _log_error(self, message: str, **kwargs) -> bool:
        """Логирование уровня ERROR."""

    @abstractmethod
    def _log_critical(self, message: str, **kwargs) -> bool:
        """Логирование уровня CRITICAL."""

    @abstractmethod
    def _record_metric(self, metric_name: str, value: Any = 1, tags: Optional[Dict[str, str]] = None) -> None:
        """Запись метрики."""

    @abstractmethod
    def _record_timing(self, metric_name: str, duration: float, tags: Optional[Dict[str, str]] = None) -> None:
        """Запись времени выполнения."""

    @abstractmethod
    def _track_error(self, error: Exception, context: Optional[Dict[str, Any]] = None) -> None:
        """Отслеживание ошибки."""


# =============================================================================
# Контракт владения (ADR-BM-008, Task 0.1 плана lifecycle-owner-scope)
# =============================================================================
#
# Здесь только контракт: протоколы, DTO отчёта и исключение. Реализация
# (`Scope`, `Handle`, фабрика `open_scope`, `unclosed_roots`) — Task 0.2,
# файл `base_manager/core/lifetime.py` (DESIGN D1). Новые контракты — `typing.Protocol`, а не
# ABC: адаптеры потоков, процессов и пулов не наследуют базу фреймворка.
#
# Корень области создаёт ТОЛЬКО фабрика пакета (решение CTO 2026-10-04, Q2):
#     from multiprocess_framework.modules.base_manager import open_scope
#     root = open_scope(f"proc/{name}", budget_s=..., kill_reserve_s=..., reporter=...)
# Снаружи область аннотируется только как `IScope`, запись — как `IHandle`.


@runtime_checkable
class Stoppable(Protocol):
    """Ресурс со своим потоком управления: поток, процесс, QThread, пул, блокирующее устройство, сток.

    Останов в две обязательные фазы: запрос → ожидание к абсолютному сроку.

    Обязательные члены:

    - ``request_stop()`` — фаза 1. Не блокирует, идемпотентно, любой поток.
      Прерывает блокирующие вызовы. Для стока: закрыть вход; дренирование и
      выход — его дело до ``join_until`` (★5б).
    - ``join_until(deadline)`` — фаза 2. ``deadline`` — абсолютное значение
      ``time.monotonic()``, а не относительный таймаут. ``True`` = ресурс
      остановлен. На таймауте возвращает ``False`` и не бросает.

    Имя намеренно не ``join`` (вердикт CTO 2026-10-04, Q1). У
    ``threading.Thread``, ``multiprocessing.Process`` и ``QThread`` есть
    ``join(timeout)`` с ОТНОСИТЕЛЬНЫМ таймаутом и без результата. Подкласс
    такого класса с добавленным ``request_stop`` прошёл бы проверку на
    ``Stoppable`` и ждал бы абсолютное значение как секунды (зонд: 2.00 с при
    бюджете 0.1 с, возврат ``None``). С ``join_until`` такой объект не
    ``Stoppable``.

    Необязательные члены (Protocol не умеет «необязательный метод», поэтому
    они не входят в протокол; ``Scope`` в Task 0.2 ищет их через ``getattr``):

    - ``kill()`` — фаза 3, только после ``join_until() == False``. **Не
      блокирует**: отправить сигнал (terminate / ``cancel_futures``) и
      вернуться. Ожидание смерти — повторный ``join_until`` к сроку резерва
      kill. Причина (зонд CTO): блокирующий ``kill()`` на 0.3 с при двух
      застрявших дал 0.80 с — резерв умножается на число застрявших.
    - ``close()`` — освобождение после успешного ``join_until`` или ``kill``.

    Порядок различения ресурса в ``IScope.own`` (реализация — Task 0.2):
    сначала ``isinstance(res, Stoppable)``, иначе ``callable(res)``, иначе
    ``TypeError``. Объект, который одновременно ``Stoppable`` и вызываемый,
    считается ``Stoppable``: так он получает фазу 2 к сроку.

    ``@runtime_checkable`` проверяет только наличие имён (``getattr_static``),
    не сигнатуру и не смысл. Поэтому проверка не через ``hasattr``:
    ``hasattr`` вызывает ``__getattr__``, и прокси или ``Mock()`` проходили бы
    как ``Stoppable``.
    """

    def request_stop(self) -> None:
        """Фаза 1. Не блокирует, идемпотентно, любой поток. Прерывает блокирующие вызовы.

        Для стока: закрыть вход; дренирование и выход — его дело до join_until (★5б).
        """
        ...

    def join_until(self, deadline: float) -> bool:
        """Фаза 2. Ждать до абсолютного time.monotonic(). True = остановлен. На таймауте не бросает.

        На таймауте возвращает ``False``. Не ``join``: у Thread/Process/QThread
        join(timeout) относительный и без результата (Q1, ред. 3.1).
        """
        ...


Resource = Stoppable | Callable[[], object]
"""Что принимает ``IScope.own``: ``Stoppable`` или вызываемое без аргументов.

Вызываемое — подписка, сокет, файл, хук плагина: функция освобождения, её
зовут один раз при закрытии, фазы 2 у неё нет.

Псевдоним только для аннотаций, не для ``isinstance``: ``isinstance(x, Resource)``
бросает ``TypeError`` (parameterized generic). Различать через ``Stoppable`` /
``callable`` — в этом порядке.
"""


def _sequence_as_tuple(field_name: str, value: object) -> tuple:
    """Привести последовательность поля ``CloseReport`` к кортежу.

    Строка на месте последовательности — ``TypeError``: ``tuple("proc/x")``
    молча режет строку на символы. ``set``/``frozenset`` — ``TypeError``:
    порядок путей в отчёте значим. ``None`` и прочее неитерируемое —
    ``TypeError`` с именем поля (Task 0.2, код-ревью 0.1 р2).
    """
    if isinstance(value, (str, bytes, set, frozenset)) or value is None:
        raise TypeError(
            f"CloseReport.{field_name}: ожидается упорядоченная последовательность, получено {type(value).__name__}"
        )
    try:
        return tuple(value)  # type: ignore[call-overload]
    except TypeError:
        raise TypeError(
            f"CloseReport.{field_name}: ожидается последовательность, получено {type(value).__name__}"
        ) from None


def _str_tuple(field_name: str, value: object) -> tuple[str, ...]:
    """Последовательность строк → кортеж; элемент не ``str`` — ``TypeError`` с именем поля."""
    items = _sequence_as_tuple(field_name, value)
    for index, item in enumerate(items):
        _require_type(f"{field_name}[{index}]", item, str, "str")
    return items


def _error_pair(index: int, value: object) -> tuple[str, str]:
    """Привести одну пару ``errors`` к кортежу ровно из двух строк."""
    field_name = f"errors[{index}]"
    pair = _sequence_as_tuple(field_name, value)
    if len(pair) != 2:
        raise TypeError(
            f"CloseReport.{field_name}: ожидается пара (путь, текст ошибки), получено элементов: {len(pair)}"
        )
    _require_type(f"{field_name}[0]", pair[0], str, "str")
    _require_type(f"{field_name}[1]", pair[1], str, "str")
    return pair  # type: ignore[return-value]


def _require_type(field_name: str, value: object, expected: type | tuple[type, ...], label: str) -> None:
    """``TypeError`` с именем поля, если ``value`` не того типа.

    ``bool`` — подкласс ``int``, поэтому для числовых полей он отвергается
    явно: ``emits_after_close=True`` или ``elapsed_s=False`` — ошибка вызывающего.
    """
    is_bool_in_number = isinstance(value, bool) and expected is not bool
    if is_bool_in_number or not isinstance(value, expected):
        raise TypeError(f"CloseReport.{field_name}: ожидается {label}, получено {type(value).__name__}")


@dataclass(frozen=True)
class CloseReport:
    """Отчёт о закрытии области или одной записи. Неизменяемый DTO.

    Поля:

    - ``path`` — путь закрытой области или записи.
    - ``elapsed_s`` — сколько длилось закрытие, секунды.
    - ``survivors`` — пути записей, не остановившихся к сроку (и после kill).
      Поток, закрывающий свою же область, помечается литералом
      ``"<path> (self)"``.
    - ``killed`` — пути записей, к которым применена фаза 3 (``kill``).
    - ``errors`` — пары ``(путь записи, текст ошибки)``.
    - ``emits_after_close`` — сколько доставок пришло в закрытого владельца
      (они подавлены и посчитаны, ★5а «никогда молча»). Счётчик видит
      доставки только до сборки отчёта. Отчёт заморожен: поздние доставки в
      него не попадут — куда они идут, решает Task 0.3.
    - ``complete`` — ``False``, если закрытие не выполнено целиком
      (реентрантный вызов).

    ``__post_init__`` приводит ``survivors``, ``killed``, ``errors`` и каждую
    пару внутри ``errors`` к кортежам: отчёт со списками иначе не хэшируется и
    не равен такому же с кортежами. Строка на месте последовательности или
    пары — ``TypeError``; пара не из двух элементов — ``TypeError``.

    Он же проверяет типы, ``TypeError`` называет поле: ``path`` — ``str``;
    ``elapsed_s`` — ``int``/``float``, не ``bool``; элементы ``survivors``,
    ``killed`` и обе части каждой пары ``errors`` — ``str``;
    ``emits_after_close`` — ``int``, не ``bool``; ``complete`` — ``bool``.
    Иначе ``survivors=(b"x",)`` уронил бы ``json.dumps(to_dict())``, а
    ``complete=""`` дал бы ``ok == ""``.

    Граница процесса — ``to_dict`` / ``from_dict`` (правило Dict at Boundary).
    """

    path: str
    elapsed_s: float
    survivors: tuple[str, ...]
    killed: tuple[str, ...]
    errors: tuple[tuple[str, str], ...]
    emits_after_close: int = 0
    complete: bool = True

    def __post_init__(self) -> None:
        _require_type("path", self.path, str, "str")
        _require_type("elapsed_s", self.elapsed_s, (int, float), "int | float")
        # NaN/inf дали бы нестрогий JSON (`NaN`) на границе процесса. Без `math`:
        # interfaces.py импортирует только литеральный список stdlib (Task 0.1).
        # NaN не равен себе; x - x не ноль ровно для NaN и ±inf.
        if self.elapsed_s - self.elapsed_s != 0:
            raise ValueError(f"CloseReport.elapsed_s: ожидается конечное число, получено {self.elapsed_s!r}")
        _require_type("emits_after_close", self.emits_after_close, int, "int")
        _require_type("complete", self.complete, bool, "bool")
        object.__setattr__(self, "survivors", _str_tuple("survivors", self.survivors))
        object.__setattr__(self, "killed", _str_tuple("killed", self.killed))
        errors = _sequence_as_tuple("errors", self.errors)
        object.__setattr__(self, "errors", tuple(_error_pair(i, item) for i, item in enumerate(errors)))

    @property
    def ok(self) -> bool:
        """Закрытие прошло чисто: целиком, без выживших, убитых и ошибок.

        ``emits_after_close`` в ``ok`` не входит (ADR-BM-008): доставка в
        закрытого владельца — сигнал для отчёта, не провал закрытия.
        """
        return self.complete and not self.survivors and not self.killed and not self.errors

    def to_dict(self) -> dict:
        """Словарь только из ``dict``/``list``/``str``/``int``/``float``/``bool``.

        Ключи ровно: ``path``, ``elapsed_s``, ``survivors``, ``killed``,
        ``errors``, ``emits_after_close``, ``complete``, ``ok``. ``errors`` —
        список ``{"path": ..., "error": ...}``: потребитель читает по ключу.
        Результат проходит ``json.dumps`` без ``default=``.
        """
        return {
            "path": self.path,
            "elapsed_s": self.elapsed_s,
            "survivors": list(self.survivors),
            "killed": list(self.killed),
            "errors": [{"path": entry_path, "error": text} for entry_path, text in self.errors],
            "emits_after_close": self.emits_after_close,
            "complete": self.complete,
            "ok": self.ok,
        }

    @classmethod
    def from_dict(cls, d: dict) -> CloseReport:
        """Обратное к ``to_dict`` преобразование. Строгий край.

        - Вход не ``dict`` → ``TypeError`` с ``type(d).__name__``.
        - Ключ ``"ok"`` игнорируется: он вычисляется.
        - Вход — та же форма, что отдаёт ``to_dict``: ``errors`` — список
          словарей с ключами ровно ``{"path", "error"}``. Элемент не ``dict``,
          без ключа или с лишним ключом → ``ValueError`` с ``errors[i]`` и
          именем ключа. Типы значений проверяет ``__post_init__``.
        - Нет ``emits_after_close`` / ``complete`` → ``0`` / ``True``.
        - Нет ``path``, ``elapsed_s``, ``survivors``, ``killed`` или
          ``errors`` → ``ValueError`` с именем ключа.
        - Лишний ключ → ``ValueError`` с именем ключа. Обе стороны — один код
          одной версии; лишний ключ — опечатка или чужой словарь.

        Текст ошибки называет ключ и не печатает словарь.
        """
        if not isinstance(d, dict):
            raise TypeError(f"CloseReport.from_dict: ожидается dict, получено {type(d).__name__}")
        for key in d:
            if key not in _CLOSE_REPORT_KNOWN_KEYS:
                raise ValueError(f"CloseReport.from_dict: лишний ключ {_key_label(key)}")
        for key in _CLOSE_REPORT_REQUIRED_KEYS:
            if key not in d:
                raise ValueError(f"CloseReport.from_dict: нет обязательного ключа {key!r}")
        return cls(
            path=d["path"],
            elapsed_s=d["elapsed_s"],
            survivors=d["survivors"],
            killed=d["killed"],
            errors=_errors_from_wire(d["errors"]),
            emits_after_close=d.get("emits_after_close", 0),
            complete=d.get("complete", True),
        )


def _key_label(key: object) -> str:
    """Имя ключа для текста ошибки: строку — ``repr``, иное — только имя типа (не данные)."""
    return repr(key) if isinstance(key, str) else f"<{type(key).__name__}>"


_ERROR_ENTRY_KEYS = frozenset(("path", "error"))


def _errors_from_wire(value: Any) -> Any:
    """Список ``{"path", "error"}`` из ``to_dict`` → список пар для ``__post_init__``.

    Не-список (строку в том числе) не разбираем: его отвергнет
    ``__post_init__`` (``TypeError``); иначе строка развалилась бы на символы
    раньше проверки. Элемент — ``dict`` с ключами ровно ``{"path", "error"}``,
    иначе ``ValueError`` с ``errors[i]`` и именем ключа: лишний ключ молча
    терять нельзя (тот же довод, что у ключей верхнего уровня).
    """
    if not isinstance(value, (list, tuple)):
        return value
    pairs = []
    for index, entry in enumerate(value):
        if not isinstance(entry, dict):
            raise ValueError(
                f"CloseReport.from_dict: errors[{index}] — ожидается dict с ключами 'path', 'error', "
                f"получено {type(entry).__name__}"
            )
        for key in entry:
            if key not in _ERROR_ENTRY_KEYS:
                raise ValueError(f"CloseReport.from_dict: errors[{index}] — лишний ключ {_key_label(key)}")
        for key in ("path", "error"):
            if key not in entry:
                raise ValueError(f"CloseReport.from_dict: errors[{index}] — нет ключа {key!r}")
        pairs.append((entry["path"], entry["error"]))
    return pairs


_CLOSE_REPORT_REQUIRED_KEYS = ("path", "elapsed_s", "survivors", "killed", "errors")
_CLOSE_REPORT_KNOWN_KEYS = frozenset((*_CLOSE_REPORT_REQUIRED_KEYS, "emits_after_close", "complete", "ok"))


Reporter = Callable[[CloseReport], None]
"""Получатель отчёта о закрытии.

Задаётся корню (``open_scope(..., reporter=...)``); дети наследуют. Вызывается
**ровно один раз на каждое закрытие, начатое не изнутри закрытия родителя**:
``close()`` корня — один вызов с итоговым отчётом; досрочный ``child.close()``
или ``IHandle.close()`` — один вызов с отчётом этой записи. Внутри закрытия
родителя отчёты детей сливаются в отчёт родителя, отдельных вызовов нет.

Три вида вызова (ADR-BM-008, «Канал счётчика»):

1. закрытие области — итоговый отчёт ``close()``;
2. досрочное ``IHandle.close()`` — отчёт этой записи;
3. «после закрытия цепочки» — ``IScope.note_emits_after_close(n)`` пришёл,
   когда закрыты область и все её предки: ``elapsed_s == 0.0``, пустые
   ``survivors``/``killed``/``errors``, ``emits_after_close == n`` (≥ 1).

Отчёт досрочно закрытой некорневой области несёт ``emits_after_close == 0``:
её счётчик передан родителю и входит в его отчёт. Полный счётчик — в
возврате ``root.close()`` при ``complete=True``; иначе остаток — в отчёте
третьего вида.

Отчёт уходит в момент возврата ``close`` (до ``os._exit`` раннера), а не по
сборке мусора. Вызов — на потоке закрывающего. Исключение reporter'а
ловится, пишется одной строкой через stdlib ``logging`` и из ``close`` не
выходит (принцип ADR-BM-007: учёт не бросает поверх настоящей ошибки).
``complete=False`` для этого не используется — флаг занят реентрантным
вызовом.
"""


class IHandle(Protocol):
    """Запись области: то, что вернули ``IScope.own``, ``spawn`` или ``child``.

    ``path`` и ``kind`` — только для чтения: путь — идентичность записи в
    отчёте и в переписи потоков; переименование на лету её сломало бы.

    ``kind``: зарезервированы ``"scope"`` (запись ``child``) и ``"thread"``
    (запись ``spawn``); по умолчанию ``"resource"``; остальное — свободная
    строка.
    """

    @property
    def path(self) -> str:
        """Полный путь записи: ``<путь области>/<name>``."""
        ...

    @property
    def kind(self) -> str:
        """Вид записи: ``"resource"``, ``"thread"``, ``"scope"`` или свой."""
        ...

    def close(self, budget_s: float | None = None) -> CloseReport:
        """Досрочно освободить одну запись: отцепить от владельца, затем закрыть тем же кодом, что и область.

        Одноэлементный сегмент (совет 7). Идемпотентно: повторный вызов не
        освобождает ресурс второй раз.
        ``budget_s=None`` — ``budget_s`` области-владельца; резерв kill — её
        ``kill_reserve_s``; правила сроков те же, что у ``IScope.close``.
        Reporter вызывается один раз с отчётом этой записи. После закрытия
        имя записи в области свободно.
        """
        ...


class IScope(Protocol):
    """Область владения: владеет ресурсами, потоками и дочерними областями.

    Закрытие идёт по сегментам (``barrier``) сверху вниз; порядок фаз —
    в docstring ``close``. Реализация (блокировки, LIFO) — Task 0.2.

    Корень создаёт только фабрика пакета ``open_scope``; снаружи область
    аннотируется как ``IScope``.

    Правило имени записи (``own``, ``spawn``, ``child``): непустая строка без
    ``/`` и без суффикса ``" (self)"``, иначе ``ValueError``. Повтор имени
    среди **незакрытых** записей области — ``ValueError``; после
    ``IHandle.close()`` или закрытия ребёнка имя свободно.

    ``own``, ``spawn`` и ``child`` закрытой или закрывающейся области бросают
    ``ScopeClosedError``.
    """

    @property
    def path(self) -> str:
        """Путь области, например ``"proc/camera_0/work"``."""
        ...

    @property
    def closed(self) -> bool:
        """``True`` с НАЧАЛА ``close()``: состояния «закрывается» и «закрыта».

        Как в прототипе (``state != "open"``): ``own``/``spawn``/``child`` в
        закрывающейся области уже отклоняются, и ``closed`` обязан совпадать
        с отказом.
        """
        ...

    @property
    def parent(self) -> IScope | None:
        """Родительская область; ``None`` у корня."""
        ...

    def own(self, res: Resource, *, name: str, kind: str = "resource") -> IHandle:
        """Взять ресурс во владение. После закрытия: освободить res СРАЗУ и бросить ScopeClosedError.

        ``res`` — ``Stoppable`` или вызываемое без аргументов. Различение:
        сначала ``isinstance(res, Stoppable)``, иначе ``callable(res)``, иначе
        ``TypeError``; текст ``TypeError`` называет ``type(res).__name__``, не
        ``repr(res)``. Закрытая область бросает ``ScopeClosedError`` — ресурс
        к этому моменту уже освобождён.
        """
        ...

    def child(
        self,
        name: str,
        *,
        budget_s: float | None = None,
        kill_reserve_s: float | None = None,
    ) -> IScope:
        """Создать дочернюю область (запись вида ``"scope"``).

        ``None`` — значение родителя, копируется при создании. Пример::

            children = work.child(
                "children",
                budget_s=budget["pm_graceful_s"],
                kill_reserve_s=budget["pm_total_s"] - budget["pm_graceful_s"],
            )
        """
        ...

    def barrier(self) -> None:
        """★1. Граница сегментов.

        Всё, зарегистрированное ДО барьера, получает фазу 1 только после того,
        как закрыто всё, зарегистрированное ПОСЛЕ него.
        """
        ...

    def spawn(self, target: Callable[[threading.Event], None], *, name: str) -> IHandle:
        """Поток '<path>/<name>'. В закрытой области не стартует и бросает. Публичен для всех слоёв (★4).

        Запись вида ``"thread"``; бросает ``ScopeClosedError``.
        ``target`` получает ``threading.Event`` — сигнал остановки фазы 1.
        Поток, закрывающий свою же область, попадает в ``survivors`` с
        пометкой ``"<path> (self)"``.
        """
        ...

    def cancel(self) -> None:
        """Фаза 1 по поддереву верхнего сегмента. Не блокирует, любой поток, идемпотентно.

        Верхний сегмент — записи после последнего ``barrier``. Нижние сегменты
        фазу 1 не получают: их останавливает ``close`` по порядку сегментов
        (``stop()`` = ``root.cancel()`` задевает только ``work``).
        """
        ...

    def close(self, budget_s: float | None = None, *, deadline: float | None = None) -> CloseReport:
        """По сегментам сверху вниз: фаза 1 по поддереву сегмента → фаза 2 LIFO вне лока → фаза 3 → следующий сегмент.

        Порядок (DESIGN §2.1): фаза 1 по поддереву сегмента → фаза 2 LIFO вне
        лока (ребёнок к сроку ``min(срок родителя, now + child.budget_s)``) →
        фаза 3 ``kill()`` владельцем записи в СВОЁМ ``kill_reserve_s``, сверх
        срока, родитель резерв не обрезает → следующий сегмент. Выживший — в
        reporter сразу (= в момент возврата ``close``, одним вызовом с итоговым
        отчётом, см. ``Reporter``; не по вызову на каждого выжившего).

        Ошибки собираются, close не бросает. Единственное исключение —
        ``ValueError``, когда заданы оба ``budget_s`` и ``deadline``.

        Повтор: закрыта → тот же отчёт; этот же поток или её spawn-поток →
        complete=False; чужой поток → ждёт первого закрывающего до своего срока.

        Сроки (вердикт CTO 2026-10-04, Q3):

        - Срок фазы 2: ``deadline`` (абсолютный ``time.monotonic()``), если
          задан; иначе ``now + budget_s``; иначе ``now + self.budget_s``.
          **Оба заданы → ``ValueError`` до любого действия.**
        - Дочерняя область, закрываемая родителем, получает срок
          ``min(срок родителя, now + child.budget_s)``: срок фазы 2 ребёнка
          не позже срока фазы 2 родителя, ребёнок не растянет свой сегмент.
          Фаза 3 ребёнка в его резерве может идти после срока родителя.
        - Фазу 3 (kill) выполняет та область, которой принадлежит запись,
          после СВОЕГО срока фазы 2, в пределах СВОЕГО ``kill_reserve_s``.
          Срок родителя резерв не обрезает: бюджет родителя обязан его
          включать (у PM — функция ``stop_budget``, ADR-PMM-031).
        - Ожидание убитых — ``join_until(now + kill_reserve_s)`` по всем
          убитым разом.

        Отчёт: ``elapsed_s`` ≤ ``budget + kill_reserve_s`` своей области, если
        резерв потребовался; ≤ ``budget``, если нет. Оценка верна для области,
        в бюджет которой входят резервы её детей; область, чей ребёнок держит
        свой резерв сверх её бюджета, может закрываться дольше на этот резерв.

        Reporter вызывается один раз, если закрытие начато не изнутри
        закрытия родителя.
        """
        ...

    def note_emits_after_close(self, n: int) -> None:
        """★5а. ``n`` доставок в эту область отклонены — она закрывается или закрыта.

        Не бросает из-за состояния, любой поток, ресурсов не зовёт.

        Цель — первая область цепочки ``self, self.parent, …`` не в состоянии
        ``closed``: ``+n`` идёт в отчёт её идущего или следующего ``close``.
        Вся цепочка закрыта → reporter получает отчёт третьего вида (см.
        ``Reporter``); reporter'а нет → строка ``logging.warning``.

        ``n`` — ``int`` (не ``bool``) → иначе ``TypeError``; ``n < 1`` →
        ``ValueError``.
        """
        ...

    def live(self) -> list[dict]:
        """Незакрытые записи: словари с ключами ровно ``path``, ``kind``, ``state``.

        ``state`` ∈ {``"open"``, ``"stopping"``, ``"survivor"``}. Закрытые
        записи в ``live()`` не попадают. Результат уходит в
        ``introspect.lifetime`` по правилу Dict at Boundary.
        """
        ...


class ScopeClosedError(RuntimeError):
    """``own`` / ``spawn`` / ``child`` вызваны у закрытой или закрывающейся области.

    Ресурс, переданный в ``own``, к моменту броска уже освобождён: владелец
    не держит его и не оставляет вызывающему.

    Текст называет путь области, ``name`` записи и состояние
    (``closing`` / ``closed``).
    """


# Публичный контракт модуля (Ф8 H.1 / NEW-10): перечислен явно, чтобы
# случайный top-level импорт не становился частью API.
__all__ = [
    "IBaseManager",
    "IBaseAdapter",
    "IObservableMixin",
    "Stoppable",
    "Resource",
    "CloseReport",
    "Reporter",
    "IHandle",
    "IScope",
    "ScopeClosedError",
]
