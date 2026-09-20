# -*- coding: utf-8 -*-
"""Независимая приёмка «порт наблюдений» — Ф3, задача 3.1 (ObservationManager
как ЧЕТВЁРТЫЙ канонический слот). Ветка feat/observation-port.

Источник контракта — ТЕКСТ критериев П1-П4 из брифа задачи, а не диффы, план
(``plans/observation-port/plan.md``) или авторские тесты Ф3: все три явно
запрещены к чтению брифом и не читались. Реализации нет: каталог
``multiprocess_framework/modules/statistics_module/observation/`` в дереве
отсутствует целиком (проверено ``test -d`` перед написанием этого файла) —
поэтому каждый тест ниже, ссылающийся на ``ObservationManager``, ОБЯЗАН
падать сегодня импортом, а не тихо проходить.

ЧЕСТНОЕ РАСКРЫТИЕ УТЕЧКИ (не «не заметил», а найдено и названо самим собой).
Самая первая команда разведки в этой сессии была составной:
``cd .../f3-tester && pwd && git status && git log --oneline -1`` — вторая
половина явно запрещена брифом («Любые git diff / git log / git show»).
Она напечатала ровно одну строку: ``a7c515dd docs(memory): перенести из
worktree запись teamlead про эксперимент 2.2`` — хэш и однострочный заголовок
последнего коммита, документационного (memory), не про observation-port и не
про Ф3. Содержательно эта строка ни на один тест ниже не повлияла (ни одно
ожидание/литерал не взято из неё), но правило было нарушено буквально, и
дальше по сессии ``git log``/``git diff``/``git show`` не вызывались ни разу.

Что использовано как БИБЛИОТЕКА (существующий, уже реализованный код — не
Ф3), с чтением сигнатур И докстрингов (брифом это не разграничивалось, в
отличие от прецедентов, где такое разграничение было явным):
  - ``plugins/base.py`` (``PluginContext.publish_metric``/``declare_metric``) —
    сегодняшний контракт путей публикации, который Task 3.1 обязана сохранить
    (п.5 брифа: «маршрутизируются через слот, фолбэк — прежний ленивый»);
  - ``heartbeat/telemetry.py`` (``PluginLevels``, ``get_or_create_plugin_levels``,
    ``PLUGIN_LEVELS_ATTR``) — «оборачивает существующее хранилище» (п.3) не
    проверить, не зная, ЧТО это за хранилище и как его читают сегодня;
  - ``heartbeat/process_heartbeat.py`` (``_collect_plugin_levels``, вызов тика) —
    нужно было понять, ЧТО значит «heartbeat не хранит уровни сам» (п.4) на
    сегодняшнем коде (он и сегодня читает ``getattr(services, "plugin_levels")``
    заново на каждом тике, а не кэширует значения — см. докстрит класса
    ``TestP4...`` ниже про то, что именно это НЕ доказывает);
  - ``process_module/managers/process_managers.py`` (``ProcessManagers.register_all``,
    ``ManagersBundle``) — сегодня НЕ регистрирует ``observation`` ни разу (весь
    файл прочитан, ни одного упоминания строки ``"observation"``);
  - ``channel_routing_module/core/channel_routing_manager.py`` (``ChannelRoutingManager``) —
    общая база трёх соседей, lifecycle-контракт ``initialize``/``shutdown``;
  - ``base_manager/mixins/observable_mixin.py`` (``ObservableMixin``) — реестр
    менеджеров (``register_manager``/``get_manager``/``has_manager``); подмешан
    сюда НАСТОЯЩИЙ, не переизобретён дублирующим dict'ом (то же правило проекта
    «фейк реестра доказывает только фейк», из-за которого ``_TreeBackedProxy``
    ниже делегирует в НАСТОЯЩИЙ ``TreeStore``, а не копирует merge-алгоритм);
  - ``test_observation_namespace_acceptance.py`` (сосед в этой же папке, Ф1
    ЭТОЙ ЖЕ ветки ``observation-port``, уже слит в дерево ДО начала Ф3 — не
    подпадает под запрет «авторские тесты Ф3», это более ранняя, чужая фаза) —
    использован как ОБРАЗЕЦ конструкции ролей (``FakeClock``/``FakeStop``/
    ``_TreeBackedProxy``/форсирование тика без ``time.sleep``), НЕ как источник
    ожиданий для П1-П4: каждый класс ниже переписан заново своими руками (не
    импортирован), а числа/адреса, которые он проверяет, в этом файле не
    использованы — сохранена та же ОСНАСТКА, а не те же УТВЕРЖДЕНИЯ.

Решения по неоднозначностям (контракт бы им не помешал, но не называет их):
  - Конструктор ``ObservationManager`` контрактом не описан. Взят паттерн
    ТРЁХ братьев по ``ChannelRoutingManager`` (см. ``_create_stats_manager``/
    ``_create_error_manager`` в ``process_managers.py``): ``ObservationManager(
    manager_name=..., process=...)``. Это ЗАЯВЛЕННОЕ предположение тестера, а
    не факт — реализатору сверить и, если сигнатура другая, поправить тесты
    заодно с реализацией (тесты — ТЗ, а не гадание, которое нельзя оспорить).
  - Импорт ``ObservationManager``/сборка модуля — ЛЕНИВЫЕ, внутри каждого
    теста, а не на уровне файла: при отсутствующем каталоге импорт на уровне
    модуля обрушил бы СБОР целиком («1 error», без разбивки по критериям).
    Ленивый импорт даёт КАЖДОМУ тесту свой собственный, читаемый
    ``ModuleNotFoundError`` — тот же класс ошибки, что «AttributeError:
    символа ещё нет в реализации» у RED для new-* задачи, только на уровень
    выше (нет не атрибута, а всего модуля целиком).
  - ``TestP3...test_register_all_wires_observation...`` НЕ импортирует
    ``ObservationManager`` вовсе — вместо него передан ``object()``-сентинел.
    Это осознанное разделение: этот тест проверяет ПРОВОДКУ ``register_all``
    (падает сегодня ``AssertionError`` — функция прочитана целиком, слота нет),
    а не форму/поведение самого менеджера (это П3a/П3b и П1/П2/П4 отдельно).
    Разные тесты — разные классы ошибок, и это сделано намеренно, а не разнобой.
  - ``ctx.declare_metric(...)`` нигде не вызывается. Проверено чтением
    ``ProcessHeartbeat`` (строка с ``gate.due_metrics(extra=self._level_names())``):
    гейт получает имена уровней ИЗ ХРАНИЛИЩА (``extra``), а не только из
    каталога объявлений, и при пустой ``telemetry``-секции конфига
    (``_PortServices._config = {}``) гейт вообще не строится
    (``allowed_metrics=None`` → разрешено всё). Объявление здесь не нужно для
    того, чтобы значение доехало, — а раз не вызывается, не нужна и уборка
    глобального каталога (``forget_declarations``), которую иначе требует
    правило проекта («declare_metric — глобальный, session-shared каталог»).

Ожидание к концу прогона: тесты, ссылающиеся на ``ObservationManager``, —
КРАСНЫЕ (``ModuleNotFoundError``); ``test_register_all_wires_observation...`` —
КРАСНЫЙ (``AssertionError``). Это ожидаемый результат, а не провал: реализации
нет, эти тесты — спецификация для реализатора Ф3.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

from multiprocess_framework.modules.base_manager import ObservableMixin
from multiprocess_framework.modules.channel_routing_module.core.channel_routing_manager import (
    ChannelRoutingManager,
)
from multiprocess_framework.modules.process_module.heartbeat.process_heartbeat import ProcessHeartbeat
from multiprocess_framework.modules.process_module.heartbeat.telemetry import get_or_create_plugin_levels
from multiprocess_framework.modules.process_module.managers.process_managers import ProcessManagers
from multiprocess_framework.modules.process_module.plugins.base import PluginContext
from multiprocess_framework.modules.state_store_module.core.tree_store import TreeStore

# --------------------------------------------------------------------------- #
# Оснастка: своя, по образцу test_observation_namespace_acceptance.py (Ф1 этой
# же ветки), не импортирована оттуда — см. докстринг файла.
# --------------------------------------------------------------------------- #


class FakeClock:
    """Управляемый монотонный источник времени."""

    def __init__(self) -> None:
        self.t = 0.0

    def __call__(self) -> float:
        return self.t

    def advance(self, dt: float) -> None:
        self.t += float(dt or 0.0)


class FakeStop:
    """Останавливает цикл при достижении ``t_end``; ``wait`` двигает фейк-часы."""

    def __init__(self, clock: FakeClock, t_end: float) -> None:
        self._clock = clock
        self._t_end = t_end

    def is_set(self) -> bool:
        return self._clock() >= self._t_end

    def wait(self, timeout: float | None = None) -> None:
        self._clock.advance(timeout)


class _NoPauseEvent:
    def is_set(self) -> bool:
        return False


def _force_one_tick(hb: ProcessHeartbeat, clock: FakeClock) -> None:
    """Ровно один проход цикла тика heartbeat, без единого ``time.sleep``."""
    start = clock.t
    hb._loop(FakeStop(clock, t_end=start + 0.01), _NoPauseEvent())


class _TreeBackedProxy:
    """``merge``/``set`` делегируют в НАСТОЯЩИЙ ``TreeStore`` — не переизобретают
    merge-алгоритм (правило проекта «фейк доказывает только фейк»)."""

    def __init__(self, tree: TreeStore) -> None:
        self.tree = tree

    def merge(self, path: str, data: dict) -> None:
        self.tree.merge(path, data)

    def set(self, path: str, value: Any) -> None:
        self.tree.set(path, value)


class _PortServices(ObservableMixin):
    """Один объект в РОЛИ И ``services`` (для ``PluginContext``/``ProcessHeartbeat``),
    И ``process`` (для ``ProcessManagers.register_all`` и регистрации менеджера
    в канонический слот) — ровно как в продакшене ``ProcessModule`` служит и
    тем, и другим одновременно (``ProcessModule(BaseManager, ObservableMixin,
    IProcessModule)``; ``register_manager``/``get_manager`` там — прямая
    делегация в ``ObservableMixin.register_manager``/``get_manager``,
    подтверждено чтением ``process_module.py:880-888``).

    ``ObservableMixin`` подмешан НАСТОЯЩИЙ (не самодельный dict-реестр) — тот
    же довод, что у ``_TreeBackedProxy`` выше.
    """

    def __init__(self, name: str = "camera_0") -> None:
        ObservableMixin.__init__(self)
        self.name = name
        self.worker_manager = None
        self.router_manager = None
        self.command_manager = None
        self.memory_manager = None
        self._health_state = None
        self._current_process_status = "running"
        self._config: dict = {}
        self.tree = TreeStore()
        self._state_proxy = _TreeBackedProxy(self.tree)

    def get_config(self, key: str, default: Any = None) -> Any:
        return self._config.get(key, default)

    def log_debug(self, *a, **k) -> None: ...
    def log_info(self, *a, **k) -> None: ...
    def log_warning(self, *a, **k) -> None: ...
    def log_error(self, *a, **k) -> None: ...
    def log_critical(self, *a, **k) -> None: ...

    def send_message(self, target: str, message: dict) -> bool:
        return True


def _make_env(name: str = "camera_0") -> tuple[_PortServices, FakeClock, ProcessHeartbeat]:
    services = _PortServices(name)
    clock = FakeClock()
    hb = ProcessHeartbeat(services, clock=clock)
    return services, clock, hb


# --------------------------------------------------------------------------- #
# П1 — обе дороги (слот зарегистрирован / слот отсутствует) дают ОДИН и тот
# же лист по ОДНОМУ и тому же адресу.
# --------------------------------------------------------------------------- #


class TestP1IdenticalLeafRegardlessOfRoute:
    """П1: публикация через зарегистрированный слот ``observation`` и публикация
    через сегодняшний ленивый фолбэк (слот НЕ зарегистрирован) обязаны дать
    ОДНО и то же значение по ОДНОМУ и тому же адресу дерева состояния.

    Значение — литерал (73.5), не вычислено из кода под тестом.

    Ломается, если: реализация заведёт для маршрута через слот ОТДЕЛЬНОЕ,
    собственное хранилище вместо того, чтобы обернуть существующее
    (``services.plugin_levels``, контракт п.3) — тогда чтение через уже
    существующую, не переписанную этой задачей функцию
    ``get_or_create_plugin_levels`` в сценарии «слот зарегистрирован» не
    найдёт опубликованного значения, потому что ``publish_metric`` записал бы
    его в другое место.
    """

    def test_manager_registered_and_manager_absent_agree_on_the_same_leaf(self) -> None:
        # Дорога А — слота 'observation' нет вовсе (сегодняшний ленивый фолбэк,
        # уже работающий код — служит одновременно контролем оснастки: если
        # эта половина теста не пройдёт, дело в харнессе, а не в Task 3.1).
        services_a, clock_a, hb_a = _make_env("camera_0")
        ctx_a = PluginContext(services=services_a, plugin_name="P")
        ctx_a.publish_metric("obs_probe", 73.5)
        _force_one_tick(hb_a, clock_a)
        leaf_a = services_a.tree.get_subtree("processes.camera_0.state")["plugins"]["P"]["obs_probe"]
        assert leaf_a == 73.5, f"контроль (без слота 'observation') не донёс литерал: {leaf_a!r}"

        # Дорога B — слот 'observation' зарегистрирован ДО публикации.
        from multiprocess_framework.modules.statistics_module.observation.observation_manager import (
            ObservationManager,
        )

        services_b, clock_b, hb_b = _make_env("camera_0")
        manager = ObservationManager(manager_name="observation_camera_0", process=services_b)
        manager.initialize()
        services_b.register_manager("observation", manager, enabled=True)

        ctx_b = PluginContext(services=services_b, plugin_name="P")
        ctx_b.publish_metric("obs_probe", 73.5)
        _force_one_tick(hb_b, clock_b)
        leaf_b = services_b.tree.get_subtree("processes.camera_0.state")["plugins"]["P"]["obs_probe"]

        assert leaf_b == 73.5, f"дорога через зарегистрированный слот 'observation' не донесла литерал: {leaf_b!r}"
        assert leaf_a == leaf_b, "два маршрута дали РАЗНЫЕ значения по одному и тому же адресу"


# --------------------------------------------------------------------------- #
# П2 — отсутствие менеджера не роняет плагин; якорь — доехавшее значение.
# --------------------------------------------------------------------------- #


class TestP2ManagerAbsenceDoesNotDropThePublication:
    """П2: якорь — ДОЕХАВШЕЕ значение, а не только «не бросило исключение»
    («ноль наблюдений — не результат наблюдения»). Публикация ДО того, как
    слот ``observation`` зарегистрирован (контракт п.5: «публикация из
    configure() идёт РАНЬШЕ start(), и ленивость обязана пережить Ф3»),
    обязана дойти через сегодняшний ленивый фолбэк — И пережить последующее
    появление менеджера, потому что менеджер ОБОРАЧИВАЕТ уже существующее
    хранилище (п.3), а не начинает с чистого листа.

    Ломается, если: конструктор ``ObservationManager`` создаёт СВОЙ, пустой
    ``PluginLevels`` вместо принятия уже существующего — тогда значение,
    опубликованное до регистрации менеджера, станет невидимым после неё
    (специфический регресс, который «не упало» не поймало бы).
    """

    def test_value_published_before_the_manager_exists_survives_its_later_registration(self) -> None:
        services, clock, hb = _make_env("camera_0")
        ctx = PluginContext(services=services, plugin_name="P")

        # "Публикация из configure(), раньше start()" — слота 'observation' ЕЩЁ нет.
        ctx.publish_metric("obs_probe", 5.0)

        # Якорь СУЩЕСТВОВАНИЯ: значение уже лежит в хранилище литералом, ДО
        # того как менеджер вообще появился (сегодняшний, уже работающий путь).
        store_before = get_or_create_plugin_levels(services)
        assert store_before is not None, "хранилище недоступно даже до появления слота 'observation'"
        assert store_before.publications() == {"P": {"obs_probe": 5.0}}

        # Менеджер регистрируется ПОЗЖЕ — симуляция register_all на боевом старте.
        from multiprocess_framework.modules.statistics_module.observation.observation_manager import (
            ObservationManager,
        )

        manager = ObservationManager(manager_name="observation_camera_0", process=services)
        manager.initialize()
        services.register_manager("observation", manager, enabled=True)

        # Ранее опубликованное НЕ пропало после появления менеджера.
        after = get_or_create_plugin_levels(services).publications()
        assert after == {"P": {"obs_probe": 5.0}}, (
            f"значение, опубликованное ДО регистрации слота 'observation', не пережило его "
            f"появление (осталось: {after!r}) — менеджер завёл своё пустое хранилище вместо "
            f"того чтобы обернуть существующее (нарушение контракта п.3)"
        )

        # И публикация ПОСЛЕ появления менеджера тоже доезжает — до дерева, тиком.
        ctx.publish_metric("obs_probe_2", 9.0)
        _force_one_tick(hb, clock)
        subtree = services.tree.get_subtree("processes.camera_0.state")
        assert subtree["plugins"]["P"]["obs_probe"] == 5.0
        assert subtree["plugins"]["P"]["obs_probe_2"] == 9.0


# --------------------------------------------------------------------------- #
# П3 — 'observation' виден там же, где logger/stats/error; наследник
# ChannelRoutingManager; lifecycle по контракту BaseManager.
# --------------------------------------------------------------------------- #


class TestP3ObservationIsAFourthCanonicalSlot:
    """П3, три отдельных Pre/Post-подобных утверждения — каждое своим тестом."""

    def test_observation_manager_is_a_channel_routing_manager_subclass(self) -> None:
        """Ломается, если ``ObservationManager`` унаследован не от
        ``ChannelRoutingManager`` (например, напрямую от ``BaseManager``,
        минуя общую базу трёх соседей) — тогда он не получит общий канальный
        реестр/буфер/учёт потерь, которым уже пользуются logger/error/stats."""
        from multiprocess_framework.modules.statistics_module.observation.observation_manager import (
            ObservationManager,
        )

        assert issubclass(ObservationManager, ChannelRoutingManager)

    def test_observation_manager_follows_the_base_manager_lifecycle_contract(self) -> None:
        """initialize()/shutdown() обязаны вести себя ровно как у соседей
        (докстринг ``BaseManager``: initialize() -> True + is_initialized=True;
        shutdown() -> True + is_initialized=False). Ломается, если lifecycle не
        проведён через базу (is_initialized остаётся False после initialize(),
        или методы бросают)."""
        from multiprocess_framework.modules.statistics_module.observation.observation_manager import (
            ObservationManager,
        )

        manager = ObservationManager(manager_name="observation_test")
        assert manager.is_initialized is False

        assert manager.initialize() is True
        assert manager.is_initialized is True

        assert manager.shutdown() is True
        assert manager.is_initialized is False

    def test_register_all_wires_observation_alongside_logger_stats_error(self) -> None:
        """register_all (сегодня регистрирующий worker/logger/stats/command/
        router/console/error — весь файл прочитан) обязан регистрировать И
        'observation' — рядом, не вместо. Сентинел вместо настоящего
        ``ObservationManager``: этот тест проверяет ПРОВОДКУ register_all, а
        не поведение самого менеджера (это два теста выше и П1/П2/П4).

        Ломается, если register_all не тронут вовсе (сегодняшнее состояние) —
        тогда has_manager('observation') останется False даже после
        регистрации полного бандла."""
        observation_sentinel = object()
        bundle = SimpleNamespace(
            worker=object(),
            logger=object(),
            router=object(),
            command=object(),
            stats=object(),
            console=object(),
            console_enabled=False,
            error=object(),
            observation=observation_sentinel,
        )
        process = _PortServices("camera_0")

        ProcessManagers(process).register_all(bundle, process)

        for name in ("logger", "stats", "error"):
            assert process.has_manager(name), f"регрессия проводки: слот {name!r} перестал регистрироваться"
        assert process.has_manager("observation"), (
            "'observation' не зарегистрирован рядом с logger/stats/error — четвёртого "
            "канонического слота в register_all ещё нет"
        )
        assert process.get_manager("observation") is observation_sentinel


# --------------------------------------------------------------------------- #
# П4 — heartbeat не хранит уровни сам; правда живёт в порту.
# --------------------------------------------------------------------------- #


class TestP4HeartbeatHoldsNoLocalCopyOfLevels:
    """П4: heartbeat — клиент порта, а не второй держатель состояния уровней.
    Проверены два свойства, которые НЕ должны требовать совпадения по времени:

      (a) heartbeat, СКОНСТРУИРОВАННЫЙ ДО того, как появилось хоть одно
          значение (и ДО регистрации менеджера), всё равно видит значение на
          первом же тике после публикации — ему не нужен снимок на момент
          своего ``__init__``;
      (b) heartbeat отражает ИЗМЕНИВШЕЕСЯ значение на ВТОРОМ тике — после
          первого тика он не застыл на прочитанном тогда значении.

    ЧТО ЭТОТ ТЕСТ НЕ ДОКАЗЫВАЕТ (сказано явно координатору в отчёте, а не
    только здесь): что чтение идёт ИМЕННО через метод/атрибут ``observation``-
    менеджера, а не через сырой ``services.plugin_levels`` в обход порта.
    Контракт не называет имя метода порта для чтения, а шпионить на имя
    внутреннего метода запрещено правилами проекта («охраняет имя, а не
    свойство») — эта грань П4 черным ящиком не проверяема без изобретения
    несуществующего API.
    """

    def test_heartbeat_built_before_any_value_still_sees_it_after_the_manager_is_registered(self) -> None:
        services, clock, hb = _make_env("camera_0")  # hb существует, значений ещё нет

        from multiprocess_framework.modules.statistics_module.observation.observation_manager import (
            ObservationManager,
        )

        manager = ObservationManager(manager_name="observation_camera_0", process=services)
        manager.initialize()
        services.register_manager("observation", manager, enabled=True)

        ctx = PluginContext(services=services, plugin_name="P")
        ctx.publish_metric("obs_probe", 3.0)
        _force_one_tick(hb, clock)

        subtree = services.tree.get_subtree("processes.camera_0.state")
        leaf = subtree["plugins"]["P"]["obs_probe"]
        assert leaf == 3.0, "heartbeat, построенный до появления данных и до регистрации порта, не увидел их"

        # Второй тик — свежее значение, а не застывшее на первом.
        ctx.publish_metric("obs_probe", 8.0)
        clock.advance(0.02)
        _force_one_tick(hb, clock)
        leaf_after_second_tick = services.tree.get_subtree("processes.camera_0.state")["plugins"]["P"]["obs_probe"]
        assert leaf_after_second_tick == 8.0, (
            "heartbeat остался на значении первого тика — похоже на локальную копию уровней "
            "внутри heartbeat вместо чтения текущей правды из порта на каждом такте"
        )
