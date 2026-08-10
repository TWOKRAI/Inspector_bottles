"""Реестр коллекторов — DI-шов между generic-движком и доменным корреляционным буфером.

**Почему «коллектор», а не «инспектор» (D4).** Механизм универсален: буфер копит
входящие items и отдаёт ГОТОВУЮ КОЛЛЕКЦИЮ, когда корреляция сложилась — по счёту
(``fanin``) либо по именованным входам (``join``). Инспекцией он не занимается ни в
каком режиме; имя ``inspector`` было наследством прикладного домена (проверка бутылки
из нескольких регионов) и делало конструктор привязанным к одному продукту. Словарь
самого кода всегда говорил «коллекция» — теперь так же называется и то, что её
собирает.

C6 рычаг/шаг (b): доменные буферы fan-in (region fan-in по count) и join (корреляция
именованных входов) — это НЕ механизм, а vision-inspection словарь
(camera_id/region_name/seq_id/data_type). Они живут в `Plugins/_shared/fanin/`
(уровень 2 «Платформа»). Framework (уровень 1 «Механизмы») их по имени не знает и НЕ
импортирует (правило слоёв: framework не зависит от Plugins).

Связь — через этот реестр:
- ``ItemCollector`` — структурный Protocol, по которому ``DataReceiver`` типизирует буфер
  (DI, конкретный класс не импортируется).
- ``register_collector_factory`` — Plugins-слой регистрирует фабрику при импорте
  (``Plugins/__init__`` тянет ``Plugins._shared.fanin`` → self-register). Любой процесс с
  processing-плагинами грузит плагин из ``Plugins.*`` → регистрация срабатывает ДО
  ``_init_data_pipeline`` (плагины бутятся раньше).
- ``build_collector`` — generic-движок зовёт его; при отсутствии зарегистрированной
  фабрики (чистый framework без Plugins) — безопасный fallback ``PassThroughCollector``
  (каждый item сразу готов, без fan-in).
"""

from __future__ import annotations

from typing import Any, Callable, Protocol, runtime_checkable

#: Каноничный ключ секции корреляции в конфиге процесса и его легаси-алиас.
#: Алиас читается ради рецептов, написанных до D4 (см. ``ProcessConfig.collector``).
COLLECTOR_CONFIG_KEY = "collector"
LEGACY_COLLECTOR_CONFIG_KEY = "inspector"


def collector_config(app_cfg: dict[str, Any]) -> dict[str, Any]:
    """Секция корреляции из конфига процесса: ``collector``, иначе легаси ``inspector``.

    Одно место, где читается пара ключей. Разъезд каноничного и легаси чтения — это
    класс «дефолтный путь не совпадает с публикатором»: рецепт до D4 молча перестал бы
    активировать join, а симптом («линия не сольётся») к ключу не отсылает.
    """
    section = app_cfg.get(COLLECTOR_CONFIG_KEY)
    if not section:
        section = app_cfg.get(LEGACY_COLLECTOR_CONFIG_KEY)
    return section or {}


@runtime_checkable
class ItemCollector(Protocol):
    """Контракт корреляционного буфера DataReceiver (fan-in / join / pass-through).

    Публичный контракт (не менялся ни при переносе в Plugins, ни при переименовании D4):
    - ``on_item(item)`` — принять один item; при готовности коллекции зовёт ``_on_ready``.
    - ``check_timeouts()`` — периодический flush просроченных коллекций.
    - ``pending_count`` — число незавершённых коллекций в буфере (телеметрия).

    ``_on_ready`` (callback доставки готовой коллекции) выставляется вызывающим извне
    (``GenericProcess._init_data_pipeline``: ``collector._on_ready = receiver.on_items_ready``)
    — приватный атрибут, в Protocol не включён (структурная типизация по методам).
    """

    def on_item(self, item: dict) -> None: ...

    def check_timeouts(self) -> None: ...

    @property
    def pending_count(self) -> int: ...


class PassThroughCollector:
    """Тривиальный ItemCollector: каждый item сразу отдаётся как готовая коллекция.

    Fallback, когда фабрика не зарегистрирована (чистый framework без Plugins-слоя).
    Fan-in/join семантики нет — но реальный процесс, которому нужна корреляция, грузит
    доменные плагины из ``Plugins.*`` → фабрика регистрируется → используется настоящий
    буфер. Также служит конкретным буфером в юнит-тестах ``DataReceiver`` (framework не
    может импортировать доменный буфер из Plugins).
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


# Фабрика: (app_cfg, log_info, log_error, log_debug) -> ItemCollector.
CollectorFactory = Callable[..., ItemCollector]

_factory: CollectorFactory | None = None


def register_collector_factory(factory: CollectorFactory) -> None:
    """Зарегистрировать доменную фабрику коллекторов (зовёт Plugins-слой при импорте)."""
    global _factory
    _factory = factory


def build_collector(
    app_cfg: dict[str, Any],
    log_info: Callable[[str], None] | None = None,
    log_error: Callable[[str], None] | None = None,
    log_debug: Callable[[str], None] | None = None,
) -> ItemCollector:
    """Построить корреляционный буфер по конфигу процесса.

    Делегирует зарегистрированной доменной фабрике (``Plugins/_shared/fanin``).

    Fail-loud (Fable HIGH-1): если фабрика НЕ зарегистрирована, но секция корреляции
    ЗАДАНА (``mode``/параметры) — это молчаливая потеря корреляции (плагины загружены не
    из ``Plugins.*``, self-register не сработал). Отказываем громко, а не отдаём
    PassThrough, который бы тихо пропускал items без fan-in/join. При ПУСТОЙ секции
    корреляция не нужна → PassThrough-fallback с явной записью в лог (не тихо).
    """
    if _factory is None:
        cfg = collector_config(app_cfg)
        if cfg:
            raise RuntimeError(
                "build_collector: задана секция корреляции "
                f"(mode={cfg.get('mode', 'fanin')!r}), но фабрика fan-in/join НЕ "
                "зарегистрирована — плагины загружены не из пакета Plugins.* (напр. "
                "Services.*), self-register Plugins._shared.fanin не сработал. Импортируй "
                "Plugins._shared.fanin в composition root или зарегистрируй фабрику через "
                "register_collector_factory. Отказ вместо молчаливого PassThrough (иначе "
                "items летят без корреляции — потеря fan-in/join)."
            )
        if log_info is not None:
            log_info(
                "build_collector: фабрика коллектора не зарегистрирована и секция пуста — "
                "PassThrough-fallback (без fan-in; корреляция не требуется)."
            )
        return PassThroughCollector()
    return _factory(app_cfg, log_info=log_info, log_error=log_error, log_debug=log_debug)
