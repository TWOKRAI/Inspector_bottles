"""Inspector-реестр — DI-шов между generic-движком и доменным корреляционным буфером.

C6 рычаг/шаг (b): доменные буферы fan-in (`InspectorManager`, region fan-in по count)
и join (`JoinInspectorManager`, корреляция именованных входов) — это НЕ механизм, а
vision-inspection словарь (camera_id/region_name/seq_id/data_type). Они переехали в
`Plugins/_shared/fanin/` (уровень 2 «Платформа»). Framework (уровень 1 «Механизмы») их
по имени не знает и НЕ импортирует (правило слоёв: framework не зависит от Plugins).

Связь — через этот реестр:
- ``ItemInspector`` — структурный Protocol, по которому ``DataReceiver`` типизирует буфер
  (DI, конкретный класс не импортируется).
- ``register_inspector_factory`` — Plugins-слой регистрирует фабрику при импорте
  (``Plugins/__init__`` тянет ``Plugins._shared.fanin`` → self-register). Любой процесс с
  processing-плагинами грузит плагин из ``Plugins.*`` → регистрация срабатывает ДО
  ``_init_data_pipeline`` (плагины бутятся раньше).
- ``build_inspector`` — generic-движок зовёт его; при отсутствии зарегистрированной
  фабрики (чистый framework без Plugins) — безопасный fallback ``PassThroughInspector``
  (каждый item сразу готов, без fan-in).
"""

from __future__ import annotations

from typing import Any, Callable, Protocol, runtime_checkable


@runtime_checkable
class ItemInspector(Protocol):
    """Контракт корреляционного буфера DataReceiver (fan-in / join / pass-through).

    Публичный контракт (не менялся при переносе в Plugins):
    - ``on_item(item)`` — принять один item; при готовности коллекции зовёт ``_on_ready``.
    - ``check_timeouts()`` — периодический flush просроченных коллекций.
    - ``pending_count`` — число незавершённых коллекций в буфере (телеметрия).

    ``_on_ready`` (callback доставки готовой коллекции) выставляется вызывающим извне
    (``GenericProcess._init_data_pipeline``: ``inspector._on_ready = receiver.on_items_ready``)
    — приватный атрибут, в Protocol не включён (структурная типизация по методам).
    """

    def on_item(self, item: dict) -> None: ...

    def check_timeouts(self) -> None: ...

    @property
    def pending_count(self) -> int: ...


class PassThroughInspector:
    """Тривиальный ItemInspector: каждый item сразу отдаётся как готовая коллекция.

    Fallback, когда фабрика не зарегистрирована (чистый framework без Plugins-слоя).
    Fan-in/join семантики нет — но реальный процесс, которому нужна корреляция, грузит
    доменные плагины из ``Plugins.*`` → фабрика регистрируется → используется настоящий
    буфер. Также служит конкретным буфером в юнит-тестах ``DataReceiver`` (framework не
    может импортировать доменный InspectorManager из Plugins).
    """

    def __init__(self, on_ready: Callable[[list[dict]], None] | None = None) -> None:
        self._on_ready = on_ready or (lambda items: None)

    def on_item(self, item: dict) -> None:
        self._on_ready([item])

    def check_timeouts(self) -> None:  # noqa: D401 — нечего чистить, буфера нет
        return None

    @property
    def pending_count(self) -> int:
        return 0


# Фабрика: (app_cfg, log_info, log_error, log_debug) -> ItemInspector.
InspectorFactory = Callable[..., ItemInspector]

_factory: InspectorFactory | None = None


def register_inspector_factory(factory: InspectorFactory) -> None:
    """Зарегистрировать доменную фабрику inspector'ов (зовёт Plugins-слой при импорте)."""
    global _factory
    _factory = factory


def build_inspector(
    app_cfg: dict[str, Any],
    log_info: Callable[[str], None] | None = None,
    log_error: Callable[[str], None] | None = None,
    log_debug: Callable[[str], None] | None = None,
) -> ItemInspector:
    """Построить корреляционный буфер по конфигу процесса.

    Делегирует зарегистрированной доменной фабрике (``Plugins/_shared/fanin``). Без
    фабрики — безопасный ``PassThroughInspector`` (без fan-in).
    """
    if _factory is None:
        return PassThroughInspector()
    return _factory(app_cfg, log_info=log_info, log_error=log_error, log_debug=log_debug)
