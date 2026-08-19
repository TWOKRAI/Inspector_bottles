# -*- coding: utf-8 -*-
"""Авторские hazard-тесты к ремонту четырёх дефектов (Ф0 Task 0.2 плана
``plans/observation-port/plan.md``).

Это НЕ приёмка — приёмку от критериев пишет независимый тестер
(``test_plugin_levels_defect_quartet_acceptance.py``). Здесь то, что видно
только автору правки: швы, которые правка сдвинула, и интерливинги, до которых
критерий не дотягивается.

Что сторожится и почему именно это:

1. **Боевая дорога Д4.** У стенда тестера записано в «недостижимо»: форму
   ``plugin_defs`` для ``PluginOrchestrator.load_and_configure_managers()`` он
   чёрным ящиком не подобрал, поэтому решение ОРКЕСТРАТОРА («подключать ли
   рабочий поток упавшему плагину») там не проверялось вовсе — проверялся
   этаж ниже, state machine. Здесь честный boot: упавший configure() + целый
   сосед, и дальше — настоящая проводка ``GenericProcess._init_data_pipeline``,
   которая и раздаёт воркеры.
2. **Равенство двух дорог сборщика.** Правка 3 собирает уровни ОДИН раз без
   гейта и фильтрует результат на месте. Это верно ровно пока гейт в
   ``build_plugin_levels`` — чистый фильтр имени ПОСЛЕ отбора по владению.
   Разойдись это — расхождение push/poll было бы видно только на стенде.
3. **Интерливинги снятия:** гонка publish/retract, переподъём между снятием и
   исчерпанием запаса, объявление имени ПОСЛЕ публикации, отказ ``proxy.merge``
   на такте снятия.

У каждого теста — якорь существования: при X значение ЕСТЬ и равно литералу.
Всё блокирующее — в daemon-потоке с ``join(timeout)``.
"""

from __future__ import annotations

import threading
import time

import pytest

from multiprocess_framework.modules.observability_declarations import (
    KIND_METRIC,
    declare_metric,
    forget_declarations,
)
from multiprocess_framework.modules.process_module.generic.generic_process import GenericProcess
from multiprocess_framework.modules.process_module.generic.plugin_orchestrator import (
    PluginOrchestrator,
)
from multiprocess_framework.modules.process_module.heartbeat.process_heartbeat import (
    ProcessHeartbeat,
)
from multiprocess_framework.modules.process_module.heartbeat.telemetry import (
    RETRACTION_REASSERT_TICKS,
    PluginLevels,
)
from multiprocess_framework.modules.process_module.plugins.base import (
    PluginContext,
    PluginState,
    ProcessModulePlugin,
)
from multiprocess_framework.modules.process_module.plugins.testing import MockProcessServices


# =========================================================================== #
# 1. Боевая дорога Д4: boot оркестратора + раздача воркеров
# =========================================================================== #


class BadConfigureSource(ProcessModulePlugin):
    """Source-плагин, чей ``configure()`` бросает ПОСЛЕ захвата «ресурса».

    Загружается оркестратором по dotted path, поэтому класс — на уровне модуля.
    ``_do_start`` переопределён СЧЁТЧИКОМ (с делегированием в базу): «фаза 2 не
    звала старт» — утверждение про вызов, и мерить его состоянием нельзя,
    состояние одинаково и при «не звали», и при «позвали, а база отказала».
    """

    name = "hazard_bad_source"
    category = "source"

    def __init__(self) -> None:
        super().__init__()
        self.do_start_calls = 0
        self.produce_calls = 0

    def _do_start(self, ctx: PluginContext) -> None:  # spy, не подмена поведения
        self.do_start_calls += 1
        super()._do_start(ctx)

    def configure(self, ctx: PluginContext) -> None:
        self._resource_acquired = True
        raise RuntimeError("нарочный сбой configure() — боевая дорога Д4")

    def start(self, ctx: PluginContext) -> None: ...

    def produce(self) -> list[dict]:
        self.produce_calls += 1
        return [{"frame": "bad"}]


class GoodSource(ProcessModulePlugin):
    """Целый сосед по тому же запуску — якорь существования боевой дороги."""

    name = "hazard_good_source"
    category = "source"

    def __init__(self) -> None:
        super().__init__()
        self.do_start_calls = 0
        self.produce_calls = 0

    def _do_start(self, ctx: PluginContext) -> None:  # spy
        self.do_start_calls += 1
        super()._do_start(ctx)

    def configure(self, ctx: PluginContext) -> None: ...

    def start(self, ctx: PluginContext) -> None: ...

    def produce(self) -> list[dict]:
        self.produce_calls += 1
        return [{"frame": "good", "camera_id": 0}]


_MODULE = "multiprocess_framework.modules.process_module.tests.test_plugin_levels_defect_quartet_hazards"
_BAD_PATH = f"{_MODULE}.BadConfigureSource"
_GOOD_PATH = f"{_MODULE}.GoodSource"


def _boot_orchestrator() -> tuple[PluginOrchestrator, MockProcessServices]:
    services = MockProcessServices(name="hazard_proc")
    orch = PluginOrchestrator(services=services)
    orch.load_and_configure_managers(
        [
            {"plugin_class": _BAD_PATH, "plugin_name": "hazard_bad_source"},
            {"plugin_class": _GOOD_PATH, "plugin_name": "hazard_good_source"},
        ]
    )
    orch.boot()
    return orch, services


def _wire_data_pipeline(orch: PluginOrchestrator, services: MockProcessServices):
    """Позвать НАСТОЯЩИЙ ``GenericProcess._init_data_pipeline`` на заглушке процесса.

    Заглушка, а не живой процесс: поднимать IPC/SHM ради вопроса «кому раздали
    воркеров» дороже, чем сам вопрос. Метод при этом настоящий — именно он
    решает, кто попадёт в ``SourceProducer``.
    """
    proc = object.__new__(GenericProcess)
    proc.name = "hazard_proc"
    proc._orchestrator = orch
    proc.worker_manager = services.worker_manager
    proc.router_manager = None
    proc.memory_manager = None
    proc.get_config = lambda key, default=None: {"chain_targets": ["out"]} if key == "config" else default
    proc.send_message = lambda target, msg: None
    proc.receive_message = lambda *a, **k: None
    proc._log_info = lambda *a, **k: None
    proc._log_error = lambda *a, **k: None
    proc._log_debug = lambda *a, **k: None
    proc._init_data_pipeline()
    return proc


def test_failed_configure_gets_neither_start_nor_a_worker_on_the_production_road() -> None:
    """Боевая дорога Д4: упавший на configure() не стартует и НЕ получает воркер.

    Дословно то, чего не достаёт стенд тестера: решение принимает оркестратор
    (фаза 2) и проводка (``_init_data_pipeline``), а не state machine плагина.

    Якорь существования — сосед: он стартовал (литеральное число вызовов старта),
    получил ровно один воркер и его ``produce()`` реально зовётся (литеральный
    минимум). Без якоря «ноль воркеров у упавшего» удовлетворялся бы и полностью
    мёртвой проводкой.
    """
    orch, services = _boot_orchestrator()
    bad = next(p for p in orch.plugins if p.name == "hazard_bad_source")
    good = next(p for p in orch.plugins if p.name == "hazard_good_source")

    # H-2 сохранён буквально: упавший ОСТАЛСЯ в списках ради shutdown.
    assert bad in orch.plugins, "H-2 нарушен: упавший на configure() выпал из списка плагинов"
    assert bad.state == PluginState.IDLE, f"упавший обязан остаться в IDLE, получено {bad.state!r}"
    assert good.state == PluginState.RUNNING, f"ЯКОРЬ: сосед обязан дойти до RUNNING, получено {good.state!r}"

    assert bad.do_start_calls == 0, (
        f"фаза 2 позвала _do_start у плагина в IDLE {bad.do_start_calls} раз(а) — "
        f"решение «не поднимаем» принимается не там, где известна причина"
    )
    assert good.do_start_calls == 1, (
        f"ЯКОРЬ: сосед обязан получить ровно 1 вызов старта, получено {good.do_start_calls}"
    )

    proc = _wire_data_pipeline(orch, services)

    workers = [call[0] for call in services.worker_manager.calls["create_worker"]]
    assert workers == ["source_producer_hazard_good_source"], (
        f"проводка раздала воркеры не тем: {workers!r} (упавший плагин обязан остаться без потока)"
    )

    producers = {p._plugin.name: p for p in proc._source_producers}
    assert set(producers) == {"hazard_good_source"}, f"SourceProducer построен не только соседу: {sorted(producers)}"

    # ЯКОРЬ: воркер соседа реально работает — produce() зовётся.
    stop, pause = threading.Event(), threading.Event()
    t = threading.Thread(target=producers["hazard_good_source"].run_loop, args=(stop, pause), daemon=True)
    t.start()
    time.sleep(0.2)
    stop.set()
    t.join(timeout=2.0)
    assert not t.is_alive(), "run_loop соседа не остановился по stop_event за 2с"

    assert good.produce_calls >= 1, "ЯКОРЬ: у соседа не позвали produce() ни разу — проводка мертва целиком"
    assert bad.produce_calls == 0, (
        f"плагин с упавшим configure() отдал {bad.produce_calls} вызовов produce() — "
        f"рабочий поток всё-таки подключили к неподнятому плагину"
    )


# =========================================================================== #
# 2. Стенд плоскости уровней (общий для остальных тестов)
# =========================================================================== #


class _TreeProxy:
    """Дубль ``state_proxy``: копит листья ``state`` и умеет ОТКАЗЫВАТЬ в merge.

    Отказ — не украшение: запас переутверждений снятия обязан тратиться только
    на успешной отправке, и без отказывающего дубля этот путь недостижим.
    """

    def __init__(self) -> None:
        self.state: dict = {}
        self.merges: list[tuple[str, dict]] = []
        self.fail_next = 0

    def set(self, path: str, value) -> None: ...

    def merge(self, path: str, data: dict) -> None:
        if self.fail_next > 0:
            self.fail_next -= 1
            raise RuntimeError("нарочный отказ доставки merge")
        self.merges.append((path, dict(data)))
        leaf = data.get("state")
        if isinstance(leaf, dict):
            self.state.update(leaf)


class _Services:
    def __init__(self, *, config: dict | None = None) -> None:
        self.name = "hazard_levels"
        self.worker_manager = None
        self.command_manager = None
        self.router_manager = None
        self.memory_manager = None
        self._state_proxy = _TreeProxy()
        self._config = config or {}

    def get_config(self, key: str, default=None):
        return self._config.get(key, default)

    def log_debug(self, *a, **k) -> None: ...
    def log_info(self, *a, **k) -> None: ...
    def log_warning(self, *a, **k) -> None: ...
    def log_error(self, *a, **k) -> None: ...
    def log_critical(self, *a, **k) -> None: ...


class _LevelPlugin(ProcessModulePlugin):
    category = "utility"

    def __init__(self, name: str) -> None:
        super().__init__()
        self.name = name

    def configure(self, ctx) -> None: ...
    def start(self, ctx) -> None: ...
    def shutdown(self, ctx) -> None: ...


def _boot(plugin: ProcessModulePlugin, ctx: PluginContext) -> None:
    plugin._do_configure(ctx)
    plugin._do_start(ctx)


# =========================================================================== #
# 3. Шов сборки: один вызов без гейта + фильтр == вызов с гейтом
# =========================================================================== #


def test_pre_gate_collection_filtered_equals_gated_collection() -> None:
    """Правка 3 держится на равенстве двух дорог сборщика — сторожим его.

    ``_collect_plugin_levels(None)`` + фильтр по разрешённым именам обязан дать
    БИТ-В-БИТ то же, что ``_collect_plugin_levels(allowed)``. Иначе публикация
    поехала бы по одной дороге, а опрос — по другой, и расхождение было бы
    видно только на стенде.

    Якорь: при пустом фильтре в срезе НЕТ имени, а при полном оно ЕСТЬ и равно
    литералу — «оба среза пусты» тест не удовлетворяет.
    """
    a, b = "hazard_seam_a", "hazard_seam_b"
    svc = _Services()
    owner_a, owner_b = _LevelPlugin("seam_owner_a"), _LevelPlugin("seam_owner_b")
    ctx_a = PluginContext(services=svc, plugin_name=owner_a.name)
    ctx_b = PluginContext(services=svc, plugin_name=owner_b.name)
    _boot(owner_a, ctx_a)
    _boot(owner_b, ctx_b)
    try:
        ctx_a.declare_metric(a)
        ctx_b.declare_metric(b)
        ctx_a.publish_metric(a, 1.5)
        ctx_b.publish_metric(b, 2.5)

        hb = ProcessHeartbeat(svc, clock=lambda: 0.0)
        full = hb._collect_plugin_levels(None, voice=False)
        assert full == {a: 1.5, b: 2.5}, f"ЯКОРЬ: без гейта обязаны быть оба литерала, получено {full!r}"

        for allowed in ({a}, {b}, {a, b}, set()):
            gated = hb._collect_plugin_levels(allowed, voice=False)
            derived = {name: value for name, value in full.items() if name in allowed}
            assert gated == derived, (
                f"дороги сборщика разошлись на allowed={sorted(allowed)!r}: "
                f"с гейтом {gated!r}, из до-гейтового среза {derived!r}"
            )
        assert hb._collect_plugin_levels(set(), voice=False) == {}, "пустой гейт обязан давать пустой срез"
    finally:
        forget_declarations(KIND_METRIC, names={a, b})


# =========================================================================== #
# 4. Интерливинги снятия
# =========================================================================== #


def test_impostor_departure_defers_nothing_owner_departure_does() -> None:
    """Правка 1 на уровне хранилища: откладывает снятие только ВЛАДЕЛЕЦ имени.

    Прямая проверка хранилища (не через тик) — она отделяет «надгробие не
    доехало» от «надгробие вообще не заказано». Якорь в том же тесте: уход
    владельца запас ЗАКАЗЫВАЕТ, и он равен литеральному
    ``RETRACTION_REASSERT_TICKS``.
    """
    metric = "hazard_defer_scope"
    declare_metric(metric, owner="the_owner")
    try:
        store = PluginLevels()
        store.publish(metric, 10.0, "the_owner")
        store.publish(metric, 999.0, "the_impostor")

        assert store.retract("the_impostor") == 1, "у самозванца была ровно одна запись — снять обязаны её"
        assert store.pending_retractions() == set(), (
            f"уход самозванца заказал надгробие на чужой лист: {store.pending_retractions()!r}"
        )
        assert store.publications() == {(metric, "the_owner"): 10.0}, (
            f"ЯКОРЬ: запись владельца обязана пережить уход самозванца, получено {store.publications()!r}"
        )

        assert store.retract("the_owner") == 1
        assert store.pending_retractions() == {metric}, (
            "ЯКОРЬ: уход ВЛАДЕЛЬЦА обязан заказать надгробие — иначе тест зелен и при полностью снятом механизме"
        )
        assert store._retracted[metric] == RETRACTION_REASSERT_TICKS, (
            f"запас утверждений не полон: {store._retracted[metric]!r}"
        )
    finally:
        forget_declarations(KIND_METRIC, names={metric})


def test_impostor_publish_does_not_cancel_the_owners_pending_retraction() -> None:
    """Правка 2 на уровне хранилища: чужая публикация запас НЕ отменяет.

    Якорь: публикация САМОГО владельца — отменяет (переподнятый плагин не
    должен получить ``None`` вдогонку).
    """
    metric = "hazard_cancel_scope"
    declare_metric(metric, owner="the_owner")
    try:
        store = PluginLevels()
        store.publish(metric, 10.0, "the_owner")
        store.retract("the_owner")
        assert store.pending_retractions() == {metric}

        store.publish(metric, 999.0, "the_impostor")
        assert store.pending_retractions() == {metric}, "публикация самозванца утопила чужое снятие"

        store.publish(metric, 11.0, "the_owner")
        assert store.pending_retractions() == set(), (
            "ЯКОРЬ: живая публикация ВЛАДЕЛЬЦА обязана отменить снятие — иначе переподнятый плагин получит None"
        )
        assert store.publications()[(metric, "the_owner")] == 11.0
    finally:
        forget_declarations(KIND_METRIC, names={metric})


def test_replug_between_retraction_and_reserve_exhaustion_keeps_the_live_leaf() -> None:
    """Переподъём между снятием и исчерпанием запаса: лист остаётся ЖИВЫМ.

    Кванторный (≥2 тика): надгробие с запасом ``RETRACTION_REASSERT_TICKS``
    обязано не догнать плагин, поднятый заново. Якорь: до переподъёма надгробие
    доезжает (``None``), после — литерал и он держится все оставшиеся такты
    запаса.
    """
    metric = "hazard_replug"
    svc = _Services()
    plugin = _LevelPlugin("replug_owner")
    ctx = PluginContext(services=svc, plugin_name=plugin.name)
    _boot(plugin, ctx)
    try:
        ctx.declare_metric(metric)
        ctx.publish_metric(metric, 4.0)

        clock = {"t": 0.0}
        hb = ProcessHeartbeat(svc, clock=lambda: clock["t"])
        hb._publish_telemetry_to_tree({}, allowed_metrics=None)
        assert svc._state_proxy.state[metric] == 4.0, "ЯКОРЬ: до снятия лист обязан быть 4.0"

        plugin._do_shutdown(ctx)
        clock["t"] = 1.0
        hb._publish_telemetry_to_tree({}, allowed_metrics=None)
        assert svc._state_proxy.state[metric] is None, (
            f"ЯКОРЬ: снятие обязано доехать первым же тиком, получено {svc._state_proxy.state[metric]!r}"
        )

        # Плагин поднят заново и снова публикует — запас надгробия ещё не исчерпан.
        replug = _LevelPlugin("replug_owner")
        ctx2 = PluginContext(services=svc, plugin_name=replug.name)
        _boot(replug, ctx2)
        ctx2.declare_metric(metric)
        ctx2.publish_metric(metric, 6.0)

        for i, t in enumerate((2.0, 3.0, 4.0), start=1):
            clock["t"] = t
            hb._publish_telemetry_to_tree({}, allowed_metrics=None)
            assert svc._state_proxy.state[metric] == 6.0, (
                f"тик {i} после переподъёма: отложенное надгробие догнало живой лист — "
                f"{svc._state_proxy.state[metric]!r}"
            )
    finally:
        forget_declarations(KIND_METRIC, names={metric})


def test_name_declared_after_the_value_was_published_still_reaches_the_tree() -> None:
    """Имя объявлено ПОСЛЕ публикации: значение ждёт в ячейке и доезжает.

    Правка 2 спрашивает каталог владения на публикации — на этот момент
    владельца ещё нет. Порядок «отдал → объявил» обязан остаться рабочим (это
    зафиксированное поведение, а не случайность), и надгробий он не наводит.

    Якорь: до объявления листа НЕТ, после — есть и равен литералу.
    """
    metric = "hazard_declare_after"
    svc = _Services()
    plugin = _LevelPlugin("late_declarer")
    ctx = PluginContext(services=svc, plugin_name=plugin.name)
    _boot(plugin, ctx)
    try:
        ctx.publish_metric(metric, 3.0)  # объявления ещё нет
        hb = ProcessHeartbeat(svc, clock=lambda: 0.0)
        hb._publish_telemetry_to_tree({}, allowed_metrics=None)
        assert metric not in svc._state_proxy.state, (
            f"ЯКОРЬ: до объявления имя ехать не должно, получено {svc._state_proxy.state.get(metric)!r}"
        )

        ctx.declare_metric(metric)  # объявил тем же плагином — он и владелец
        hb._publish_telemetry_to_tree({}, allowed_metrics=None)
        assert svc._state_proxy.state[metric] == 3.0, (
            f"значение, отданное ДО объявления, потерялось: {svc._state_proxy.state.get(metric)!r}"
        )

        store = getattr(svc, "plugin_levels", None)
        assert store is not None and store.pending_retractions() == set(), (
            "публикация до объявления наплодила надгробий — механизм снятия сработал там, где снимать нечего"
        )
    finally:
        forget_declarations(KIND_METRIC, names={metric})


def test_failed_merge_on_the_retraction_tick_does_not_spend_the_reserve() -> None:
    """Отказ ``proxy.merge`` на такте снятия: запас НЕ тратится, надгробие доезжает позже.

    Кванторный (≥2 тика). Якорь: на успешном такте надгробие реально доезжает
    (``None`` в дереве), то есть тест отличает «не потратили запас» от «снятия
    не было вовсе».
    """
    metric = "hazard_merge_fail"
    svc = _Services()
    plugin = _LevelPlugin("failing_merge_owner")
    ctx = PluginContext(services=svc, plugin_name=plugin.name)
    _boot(plugin, ctx)
    try:
        ctx.declare_metric(metric)
        ctx.publish_metric(metric, 8.0)

        clock = {"t": 0.0}
        hb = ProcessHeartbeat(svc, clock=lambda: clock["t"])
        hb._publish_telemetry_to_tree({}, allowed_metrics=None)
        assert svc._state_proxy.state[metric] == 8.0, "ЯКОРЬ: до снятия лист обязан быть 8.0"

        plugin._do_shutdown(ctx)
        store = getattr(svc, "plugin_levels")
        assert store.pending_retractions() == {metric}

        # Такт 2: доставка отказала — запас обязан остаться полным.
        svc._state_proxy.fail_next = 1
        clock["t"] = 1.0
        hb._publish_telemetry_to_tree({}, allowed_metrics=None)
        assert svc._state_proxy.state[metric] == 8.0, "провалившийся merge не имел права изменить дерево"
        assert store._retracted[metric] == RETRACTION_REASSERT_TICKS, (
            f"провалившийся такт съел запас переутверждений: {store._retracted[metric]!r}"
        )

        # Такт 3: доставка прошла — надгробие доехало, запас списан ровно на один.
        clock["t"] = 2.0
        hb._publish_telemetry_to_tree({}, allowed_metrics=None)
        assert svc._state_proxy.state[metric] is None, (
            f"ЯКОРЬ: после успешного такта снятие обязано доехать, получено {svc._state_proxy.state[metric]!r}"
        )
        assert store._retracted.get(metric) == RETRACTION_REASSERT_TICKS - 1, (
            f"успешный такт списал не один такт запаса: {store._retracted.get(metric)!r}"
        )
    finally:
        forget_declarations(KIND_METRIC, names={metric})


def test_publish_and_retract_never_leave_a_value_with_a_pending_tombstone() -> None:
    """Гонка publish/retract: у одного имени не бывает «и значение, и надгробие».

    Обе критические секции целиком под локом, поэтому наблюдаемых исходов ровно
    два: «ушёл» (значения нет, надгробие заказано) и «переподнялся» (значение
    есть, надгробие отменено). Пара «значение живо И надгробие висит» —
    признак того, что секции разъехались.

    ЧЕСТНАЯ ГРАНИЦА: GIL 3.12 может не дать вклиниться, поэтому это дымовая
    проверка инварианта, а не доказательство лока. Вес несут детерминированные
    тесты выше. Якорь: контрольный владелец, в гонке не участвующий, держит
    свой литерал до конца.
    """
    metric, control = "hazard_race", "hazard_race_control"
    declare_metric(metric, owner="racer")
    declare_metric(control, owner="bystander")
    try:
        store = PluginLevels()
        store.publish(control, 42.0, "bystander")
        errors: list[BaseException] = []
        stop = threading.Event()

        def _publisher() -> None:
            try:
                while not stop.is_set():
                    store.publish(metric, 1.0, "racer")
            except BaseException as exc:  # noqa: BLE001 — падение потока обязано стать красным
                errors.append(exc)

        def _retractor() -> None:
            try:
                while not stop.is_set():
                    store.retract("racer")
            except BaseException as exc:  # noqa: BLE001
                errors.append(exc)

        def _reader() -> None:
            try:
                while not stop.is_set():
                    store.publications()
                    store.pending_retractions()
            except BaseException as exc:  # noqa: BLE001
                errors.append(exc)

        threads = [threading.Thread(target=fn, daemon=True) for fn in (_publisher, _retractor, _reader)]
        for t in threads:
            t.start()
        time.sleep(0.3)
        stop.set()
        for t in threads:
            t.join(timeout=2.0)
            assert not t.is_alive(), "поток гонки не завершился за 2с"
        assert not errors, f"гонка подняла исключение: {errors[0]!r}"

        alive = (metric, "racer") in store.publications()
        pending = metric in store.pending_retractions()
        assert not (alive and pending), (
            "хранилище осталось в противоречивом состоянии: значение живо и надгробие заказано одновременно"
        )
        assert store.publications()[(control, "bystander")] == 42.0, (
            "ЯКОРЬ: посторонний владелец потерял значение в чужой гонке"
        )
    finally:
        forget_declarations(KIND_METRIC, names={metric, control})


def test_a_gate_held_leaf_is_not_buried_while_its_owner_still_has_a_reading() -> None:
    """Правка 3 в чистом виде: страж «живое побеждает» смотрит на ПОКАЗАНИЕ, а не на payload.

    Пара «живая публикация владельца + отложенное снятие того же имени» сегодня
    БОЛЬШЕ НЕДОСТИЖИМА снаружи: правка 2 снимает запас на публикации владельца,
    правка 1 не даёт заказать его чужим уходом. Поэтому состояние ставится
    РУКАМИ, прямо в хранилище, и это осознанно: правка, которую нельзя убить
    откатом, не сторожится ничем — а страж, который «и так не сработает»,
    сработает молча и неправильно при первой же правке соседа. Ровно этим
    механизм и обжигался (см. ADR-PM-038, дополнение 2026-08-19).

    Кванторный (2 тика) и с парой-контролем в том же тесте: пока показание есть,
    надгробие не кладётся; как только владелец действительно ушёл — кладётся,
    и на том же закрытом гейте.
    """
    metric = "hazard_gate_held"
    svc = _Services()
    owner = _LevelPlugin("gate_held_owner")
    ctx = PluginContext(services=svc, plugin_name=owner.name)
    _boot(owner, ctx)
    try:
        ctx.declare_metric(metric)
        ctx.publish_metric(metric, 20.0)

        clock = {"t": 0.0}
        hb = ProcessHeartbeat(svc, clock=lambda: clock["t"])
        hb._publish_telemetry_to_tree({}, allowed_metrics=None)
        assert svc._state_proxy.state[metric] == 20.0, "ЯКОРЬ: тик 1 обязан дать литерал владельца"

        store = getattr(svc, "plugin_levels")
        store._retracted[metric] = RETRACTION_REASSERT_TICKS  # состояние ставится руками, см. докстринг

        clock["t"] = 1.0
        hb._publish_telemetry_to_tree({}, allowed_metrics=set())  # гейт закрыт для ВСЕГО
        assert svc._state_proxy.state[metric] == 20.0, (
            f"лист, придержанный гейтом, прочитан как «показания нет» и похоронен: {svc._state_proxy.state[metric]!r}"
        )

        # ПАРА-КОНТРОЛЬ: показания действительно не стало — надгробие обязано доехать.
        owner._do_shutdown(ctx)
        clock["t"] = 2.0
        hb._publish_telemetry_to_tree({}, allowed_metrics=set())
        assert svc._state_proxy.state[metric] is None, (
            f"после ухода владельца надгробие не доехало при закрытом гейте: "
            f"{svc._state_proxy.state[metric]!r} — тест зелен и при полностью снятом снятии"
        )
    finally:
        forget_declarations(KIND_METRIC, names={metric})


@pytest.mark.parametrize("gate_closed", [True, False])
def test_gate_never_turns_a_live_owner_leaf_into_a_tombstone(gate_closed: bool) -> None:
    """Правка 3, обе половины пары: при закрытом гейте лист владельца жив.

    Пара-контроль параметром: при открытом гейте лист тоже жив, но ЕЩЁ и
    обновляется. Так «жив» не удовлетворяется тем, что до дерева вообще ничего
    не доехало.
    """
    owned, foreign = "hazard_gate_owned", "hazard_gate_foreign"
    svc = _Services()
    owner = _LevelPlugin("gate_owner")
    leaver = _LevelPlugin("gate_leaver")
    ctx_owner = PluginContext(services=svc, plugin_name=owner.name)
    ctx_leaver = PluginContext(services=svc, plugin_name=leaver.name)
    _boot(owner, ctx_owner)
    _boot(leaver, ctx_leaver)
    try:
        ctx_owner.declare_metric(owned)
        ctx_leaver.declare_metric(foreign)
        ctx_owner.publish_metric(owned, 12.0)
        ctx_leaver.publish_metric(foreign, 77.0)
        ctx_leaver.publish_metric(owned, 999.0)  # перехват чужого имени

        hb = ProcessHeartbeat(svc, clock=lambda: 0.0)
        hb._publish_telemetry_to_tree({}, allowed_metrics=None)
        assert svc._state_proxy.state[owned] == 12.0, "ЯКОРЬ: тик 1 обязан дать литерал владельца"
        assert svc._state_proxy.state[foreign] == 77.0, "ЯКОРЬ: тик 1 обязан дать литерал уходящего"

        leaver._do_shutdown(ctx_leaver)
        ctx_owner.publish_metric(owned, 13.0)

        allowed = set() if gate_closed else None
        hb._publish_telemetry_to_tree({}, allowed_metrics=allowed)

        assert svc._state_proxy.state[owned] == (12.0 if gate_closed else 13.0), (
            f"gate_closed={gate_closed}: лист живого владельца испорчен уходом перехватчика — "
            f"{svc._state_proxy.state[owned]!r}"
        )
        assert svc._state_proxy.state[foreign] is None, (
            f"своё имя уходящего обязано получить надгробие независимо от гейта, "
            f"получено {svc._state_proxy.state[foreign]!r}"
        )
    finally:
        forget_declarations(KIND_METRIC, names={owned, foreign})
