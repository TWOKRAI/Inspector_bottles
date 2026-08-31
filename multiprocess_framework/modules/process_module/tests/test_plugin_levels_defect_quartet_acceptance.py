# -*- coding: utf-8 -*-
"""Независимая приёмка дефекта Д4 — жизненный цикл плагина (Ф0 Task 0.1/0.2).

Файл был приёмкой ЧЕТЫРЁХ дефектов (Д1–Д4). Три первых — Д1 (самозванец пишет в
чужое имя), Д2′ (уход соседа хоронит живой лист владельца) и Д3 (снятие владельца
топится самозванцем) — стояли на АРБИТРАЖЕ ВЛАДЕНИЯ и поимённом снятии. Ф1 «порт
наблюдений» срезала оба механизма целиком: писатель стал сегментом пути
(``state.plugins.<писатель>.<имя>``), спорить за имя синтаксически не о чем, а
поимённых ``None``-надгробий больше нет. Сторожа удалены вместе с механизмом —
§9 плана, блок Ф1; правило FREEZE-не-KILL здесь не применяется (это не мёртвый код
на будущее, а машинерия исчезнувшего класса задач).

Уцелел Д4 — и это решение, а не остаток: Ф1 меняет, ГДЕ лежит число, а не кому его
производить. ``SourceProducer`` создавался плагину, застрявшему в IDLE; фильтр
``state == RUNNING`` — про жизненный цикл, а не про адресацию.

НЕДОСТИЖИМО НА СТЕНДЕ (актуальное для Д4)
------------------------------------------
1. Полный боевой boot через ``PluginOrchestrator.load_and_configure_managers()``.
   Форму ``plugin_defs`` чёрным ящиком подобрать не удалось, поэтому Д4 здесь
   проверяет нижний этаж — state machine ``plugins/base.py``. Боевую дорогу
   (оркестратор + раздача воркеров) сторожит авторский
   ``test_plugin_levels_defect_quartet_hazards.py``.
2. Для Д4 прогоняется настоящий ``SourceProducer.run_loop`` (не фейк), но
   подключается он к плагину напрямую, в обход оркестратора: под-проверка отвечает
   на вопрос «если воркер всё-таки подключат, сработает ли защита внутри самого
   воркера».

ПРЕДСКАЗАНИЯ ДО ПЕРВОГО ПРОГОНА (сохранены дословно, как след честного предсказания)
------------------------------------------------------------------------------------
* ``test_d4_configure_exception_blocks_running_transition`` — **GREEN** на уровне
  state machine (``_do_configure``/``_do_start``: упавший плагин остаётся в IDLE,
  сосед доходит до RUNNING).
* ``test_d4_source_producer_still_calls_produce_without_state_gate`` — **RED**
  (это НЕ дублирует Д4 дословно, а фиксирует находку: ``SourceProducer.run_loop``
  не проверяет ``plugin.state`` вообще и зовёт ``produce()`` даже для плагина,
  застрявшего в IDLE, если поток всё-таки подключить).
"""

from __future__ import annotations

import threading
import time

import pytest

from multiprocess_framework.modules.process_module.generic.source_producer import SourceProducer
from multiprocess_framework.modules.process_module.plugins.base import (
    PluginContext,
    PluginState,
    ProcessModulePlugin,
)


# --------------------------------------------------------------------------- #
# Стенд: фейки services + дерево + плагины-двойники
# --------------------------------------------------------------------------- #


class _TreeProxy:
    """Фейк ``state_proxy`` — тот же контракт ``.set``/``.merge``, что у
    ``_CountingProxy`` (``test_telemetry_gate.py``), плюс накопление "дерева" через
    ``dict.update`` подсловаря ``state`` (см. «НЕДОСТИЖИМО НА СТЕНДЕ», п.2 —
    предположение о семантике слияния, не проверенное против настоящего TreeStore).
    """

    def __init__(self) -> None:
        self.state: dict = {}
        self.merge_log: list[tuple[str, dict]] = []

    def set(self, path: str, value) -> None:  # не используется сборщиком тика уровней
        pass

    def merge(self, path: str, data: dict) -> None:
        self.merge_log.append((path, dict(data)))
        leaf = data.get("state")
        if isinstance(leaf, dict):
            self.state.update(leaf)


class _Services:
    """Минимальные services процесса — по прецеденту ``_FakeServices`` из
    ``test_telemetry_gate.py``/``test_introspect_telemetry.py``."""

    def __init__(self, *, config: dict | None = None) -> None:
        self.name = "camera_quartet"
        self.worker_manager = None
        self.command_manager = None
        self.router_manager = None
        self.memory_manager = None
        self._state_proxy = _TreeProxy()
        self._config = config or {}
        self.warnings: list[tuple[tuple, dict]] = []

    def get_config(self, key: str, default=None):
        return self._config.get(key, default)

    def log_debug(self, *a, **k) -> None: ...
    def log_info(self, *a, **k) -> None: ...

    def log_warning(self, *a, **k) -> None:
        self.warnings.append((a, k))

    def log_error(self, *a, **k) -> None: ...
    def log_critical(self, *a, **k) -> None: ...


def _boot(plugin: ProcessModulePlugin, ctx: PluginContext) -> None:
    """Штатный подъём плагина: configure() -> READY -> start() -> RUNNING.

    Важно гонять ЧЕРЕЗ ЭТО, а не просто конструировать плагин: ``_do_shutdown``
    у необученного (IDLE) плагина — во время разведки было подтверждено — тихо
    не выполняет свою работу (retract не вызывается), и без полного подъёма
    сценарии Д1/Д3 давали ложную картину, не отражающую боевой цикл жизни.
    """
    plugin._do_configure(ctx)
    plugin._do_start(ctx)


# --------------------------------------------------------------------------- #
# Д4 — configure() бросает исключение -> плагин не в RUNNING, produce не зовётся
# --------------------------------------------------------------------------- #


class _BadConfigure(ProcessModulePlugin):
    name = "quartet_d4_bad"
    category = "source"

    def __init__(self) -> None:
        super().__init__()
        self.produce_calls = 0

    def configure(self, ctx) -> None:
        raise ValueError("нарочный сбой configure() для Д4")

    def start(self, ctx) -> None: ...

    def produce(self) -> list[dict]:
        self.produce_calls += 1
        return [{"x": 1}]


class _GoodNeighbor(ProcessModulePlugin):
    name = "quartet_d4_neighbor"
    category = "source"

    def __init__(self) -> None:
        super().__init__()
        self.produce_calls = 0

    def configure(self, ctx) -> None: ...
    def start(self, ctx) -> None: ...

    def produce(self) -> list[dict]:
        self.produce_calls += 1
        return [{"x": 1}]


def test_d4_configure_exception_blocks_running_transition() -> None:
    """Д4 (state machine, plugins/base.py — не под запретом): плагин с падающим
    configure() не переходит в RUNNING. Якорь (в этом же тесте): сосед по тому же
    запуску с целым configure() переходит в RUNNING.
    """
    svc = _Services()
    bad = _BadConfigure()
    neighbor = _GoodNeighbor()
    ctx_bad = PluginContext(services=svc, plugin_name=bad.name)
    ctx_neighbor = PluginContext(services=svc, plugin_name=neighbor.name)

    with pytest.raises(ValueError):
        bad._do_configure(ctx_bad)
    assert bad.state == PluginState.IDLE, (
        f"после падения configure() плагин обязан остаться вне RUNNING, получено {bad.state!r}"
    )

    # оркестратор (не читан здесь) мог бы всё равно позвать _do_start — проверяем защиту уровня state machine
    bad._do_start(ctx_bad)
    assert bad.state != PluginState.RUNNING, f"_do_start после упавшего configure() перевёл плагин в {bad.state!r}"

    # ЯКОРЬ: сосед по тому же запуску с целым configure() доходит до RUNNING
    _boot(neighbor, ctx_neighbor)
    assert neighbor.state == PluginState.RUNNING, (
        f"сосед с исправным configure() обязан дойти до RUNNING, получено {neighbor.state!r}"
    )


@pytest.mark.xfail(
    strict=True,
    reason=(
        "Свойство есть, но живёт НЕ на этом слое (разбор Task 0.2, ветка «НЕТ» брифа). "
        "ПРОВЕРЕНО воспроизведением: боевая проводка (PluginOrchestrator.boot + "
        "GenericProcess._init_data_pipeline) до ремонта ДЕЙСТВИТЕЛЬНО раздавала воркер "
        "неподнятому плагину — в реестре create_worker стояло "
        "['source_producer_hazard_bad_source', 'source_producer_hazard_good_source']. "
        "Починено на проводке: список оркестратора — реестр для shutdown (H-2), а не "
        "«живые», и берутся из него только плагины в RUNNING; теперь остаётся один "
        "воркер соседа (test_plugin_levels_defect_quartet_hazards.py::"
        "test_failed_configure_gets_neither_start_nor_a_worker_on_the_production_road). "
        "Сам SourceProducer НАМЕРЕННО остался тупым циклом над переданным плагином: "
        "его контракт «дали плагин — зову produce» запинен двумя боевыми тестами "
        "(test_cycle_metrics.py::test_source_producer_reports_hz и "
        "test_frame_log_correlation.py::test_source_records_carry_the_freshly_born_trace — "
        "оба гоняют цикл на плагине в IDLE, а второй вообще на утином объекте БЕЗ "
        "атрибута state, для которого проверка состояния стала бы молчаливой дырой). "
        "Остаток — S-долг в plans/QUEUE.md: перенести решение о годности плагина в "
        "единый шов вызова (PluginRunner), где его увидят и produce, и process."
    ),
)
def test_d4_source_producer_still_calls_produce_without_state_gate() -> None:
    """Находка сверх дословного Д4 (см. «НЕДОСТИЖИМО НА СТЕНДЕ», п.4): реальный
    производственный воркер ``SourceProducer.run_loop`` НЕ проверяет
    ``plugin.state`` сам — если поток к упавшему плагину всё-таки подключат
    (решение об этом принимает оркестратор, который здесь не проверяется),
    ``produce()`` будет вызван, несмотря на то что плагин застрял в IDLE.

    Гонится в daemon-потоке с ``join(timeout)`` — цикл воркера иначе не
    остановить без ``stop_event``.
    """
    svc = _Services()
    bad = _BadConfigure()
    ctx_bad = PluginContext(services=svc, plugin_name=bad.name)
    with pytest.raises(ValueError):
        bad._do_configure(ctx_bad)
    assert bad.state == PluginState.IDLE  # предпосылка сценария — плагин действительно не поднят

    producer = SourceProducer(
        plugin=bad,
        shm_middleware=None,
        send_fn=lambda t, m: None,
        chain_targets=["out"],
        target_fps=50.0,
    )
    stop, pause = threading.Event(), threading.Event()
    t = threading.Thread(target=producer.run_loop, args=(stop, pause), daemon=True)
    t.start()
    time.sleep(0.2)
    stop.set()
    t.join(timeout=2.0)
    if t.is_alive():
        pytest.fail(
            "SourceProducer.run_loop не остановился по stop_event за 2с — тест сам не завис, отмечаем как провал"
        )

    assert bad.produce_calls == 0, (
        f"плагин с упавшим configure() ({bad.state!r}) отдал {bad.produce_calls} вызовов produce() "
        f"через SourceProducer.run_loop — воркер не проверяет plugin.state"
    )
