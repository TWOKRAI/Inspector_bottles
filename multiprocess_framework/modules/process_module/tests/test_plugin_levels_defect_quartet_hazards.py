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
Пункты про плоскость УРОВНЕЙ (равенство двух дорог сборщика, интерливинги
поимённого снятия) удалены вместе с механизмом: Ф1 «порт наблюдений» срезала
арбитраж владения и поимённое снятие целиком (§9 плана, блок Ф1). Осталась
ровно та часть, которую Ф1 НЕ трогает, — жизненный цикл плагина (Д4): Ф1 меняет,
ГДЕ лежит число, а не кому его производить. Уровни в новой форме сторожит
``test_writer_subtree_hazards.py``.

У каждого теста — якорь существования: при X значение ЕСТЬ и равно литералу.
"""

from __future__ import annotations

import threading
import time


from multiprocess_framework.modules.process_module.generic.generic_process import GenericProcess
from multiprocess_framework.modules.process_module.generic.plugin_orchestrator import (
    PluginOrchestrator,
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


class CriticalBrokenProcessing(ProcessModulePlugin):
    """Критический processing-плагин: ``configure()`` бросает, ``process()`` — тоже.

    Не выдумка: ресурс инспекции (модель, соединение) раскладывается в
    ``configure``, и без него обработка отказывает каждый батч. Именно на таком
    плагине живёт предохранитель конвейера — тег ``not_inspected`` и, после
    открытия breaker'а, ``suspect`` на его ПОЗИЦИИ.
    """

    name = "hazard_critical_inspector"
    category = "processing"

    def __init__(self) -> None:
        super().__init__()
        self._ready = False

    def configure(self, ctx: PluginContext) -> None:
        raise RuntimeError("нарочный сбой configure() критического инспектора")

    def start(self, ctx: PluginContext) -> None: ...

    def process(self, items: list[dict]) -> list[dict]:
        if not self._ready:
            raise RuntimeError("инспектор не сконфигурирован")
        return items


class PassthroughProcessing(ProcessModulePlugin):
    """Целый сосед по конвейеру — якорь существования."""

    name = "hazard_passthrough"
    category = "processing"

    def configure(self, ctx: PluginContext) -> None: ...

    def start(self, ctx: PluginContext) -> None: ...

    def process(self, items: list[dict]) -> list[dict]:
        return items


_MODULE = "multiprocess_framework.modules.process_module.tests.test_plugin_levels_defect_quartet_hazards"
_BAD_PATH = f"{_MODULE}.BadConfigureSource"
_GOOD_PATH = f"{_MODULE}.GoodSource"
_CRITICAL_PATH = f"{_MODULE}.CriticalBrokenProcessing"
_PASSTHROUGH_PATH = f"{_MODULE}.PassthroughProcessing"


def _boot_orchestrator(defs: list[dict] | None = None) -> tuple[PluginOrchestrator, MockProcessServices]:
    services = MockProcessServices(name="hazard_proc")
    orch = PluginOrchestrator(services=services)
    orch.load_and_configure_managers(
        defs
        if defs is not None
        else [
            {"plugin_class": _BAD_PATH, "plugin_name": "hazard_bad_source"},
            {"plugin_class": _GOOD_PATH, "plugin_name": "hazard_good_source"},
        ]
    )
    orch.boot()
    return orch, services


def _wire_data_pipeline(orch: PluginOrchestrator, services: MockProcessServices, app_cfg: dict | None = None):
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
    cfg = {"chain_targets": ["out"], **(app_cfg or {})}
    proc.get_config = lambda key, default=None: cfg if key == "config" else default
    proc.send_message = lambda target, msg: None
    proc.receive_message = lambda *a, **k: None
    proc._log_info = lambda *a, **k: None
    proc.errors = []  # журнал проводки: выпадение плагина обязано быть слышно
    proc._log_error = lambda msg, *a, **k: proc.errors.append(str(msg))
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

    said = [line for line in proc.errors if "hazard_bad_source" in line]
    assert len(said) == 1 and "не поднят" in said[0], (
        f"выпадение источника прошло молча — оператор увидит только «камера не отдаёт кадры»: {proc.errors!r}"
    )
    assert not [line for line in proc.errors if "hazard_good_source" in line], (
        f"ЯКОРЬ: про поднятый источник проводка жаловаться не имеет права: {proc.errors!r}"
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


def test_a_broken_critical_processing_plugin_keeps_its_position_and_its_tag() -> None:
    """Граница фильтра: processing-плагин остаётся в конвейере, даже не поднявшись.

    Найдено ревью Ф0 Task 0.2 (блокер). Фильтр «только RUNNING» стоял ДО
    разделения на source/processing и снимал механизм фреймворка: у критического
    processing-плагина позиция в списке — это дорога предохранителя
    (``PipelineExecutor._build_active_steps`` ставит ``SuspectTagStep`` НА ЕГО
    ПОЗИЦИЮ, а ``PluginOperationStep`` тегирует ``inspection_status``). Убрав
    плагин, мы убрали и позицию, и тег — батч уезжал молча, как будто инспекция
    была.

    Кванторный (2 прохода): проход 1 — ``not_inspected`` (плагин отказал),
    проход 2 — ``suspect`` (breaker открылся при ``max_consecutive_fails=1``).
    Якорь существования — литералы в самом item'е и целый сосед, чей вклад
    доезжает на обоих проходах.
    """
    orch, services = _boot_orchestrator(
        [
            {"plugin_class": _CRITICAL_PATH, "plugin_name": "hazard_critical_inspector"},
            {"plugin_class": _PASSTHROUGH_PATH, "plugin_name": "hazard_passthrough"},
        ]
    )
    broken = next(p for p in orch.plugins if p.name == "hazard_critical_inspector")
    neighbour = next(p for p in orch.plugins if p.name == "hazard_passthrough")
    assert broken.state == PluginState.IDLE, f"предпосылка: инспектор не поднят, получено {broken.state!r}"
    assert neighbour.state == PluginState.RUNNING, f"ЯКОРЬ: сосед поднят, получено {neighbour.state!r}"

    proc = _wire_data_pipeline(
        orch,
        services,
        {"error_critical_plugins": ["hazard_critical_inspector"], "error_max_consecutive_fails": 1},
    )
    executor = proc._pipeline_executor
    assert [p.name for p in executor._plugins] == ["hazard_critical_inspector", "hazard_passthrough"], (
        f"неподнятый processing-плагин выпал из конвейера вместе со своей позицией: "
        f"{[p.name for p in executor._plugins]}"
    )

    first = executor._execute_chain([{"bottle_id": 1, "frame": "f"}])
    assert first and first[0].get("inspection_status") == "not_inspected", (
        f"проход 1: отказ критического инспектора не оставил тега — батч уехал как инспектированный: {first!r}"
    )
    assert first[0]["bottle_id"] == 1, f"ЯКОРЬ: сосед потерял содержимое item'а: {first!r}"

    second = executor._execute_chain([{"bottle_id": 2, "frame": "f"}])
    assert second and second[0].get("inspection_status") == "suspect", (
        f"проход 2: breaker открыт, но SuspectTagStep на позиции не отработал: {second!r}"
    )
    assert second[0]["bottle_id"] == 2, f"ЯКОРЬ: сосед потерял содержимое item'а: {second!r}"
