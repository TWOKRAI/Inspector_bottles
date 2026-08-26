# -*- coding: utf-8 -*-
"""Независимая приёмка Ф5 плана «observation-port» — один писатель чисел.

**RED-набор.** Пишется ДО реализации Task 5.2/5.3 (план:
``plans/observation-port/plan.md``, раздел «Ф5»). Тестер работал в отдельном
worktree на пред-имплементационном коммите, не видел diff/реализацию задач
5.2-5.3, новые редакции ``stats_manager.py``/``observation_manager.py`` и
авторские тесты Ф5 — набор построен строго по тексту критериев приёмки плана
и по инвентарю Task 5.1.

Критерии, которые здесь проверяются (дословно из плана):

* **М5 (главный):** «Заглуши порт — молчат И уровни в дереве, И агрегаты
  окон. Пара-контроль: живой порт даёт оба вида с литералами.» Причём
  «агрегаты молчат» измеряется по ВСЕМ окнам процесса, а не только по окну
  тестового писателя (Task 5.1: дорога 3 — 57 боевых вызовов в 11 файлах
  фреймворка, независимая от плагинного фасада).
* **S-4:** ``record_metric`` = counter на ЛЮБОЙ дороге — паритет между двумя
  объектами, что духк-тайпово садятся в слот ``"stats"`` (``StatsManager`` и
  ``ObservabilityHub``, инвентарь Task 5.1).
* **Паритет агрегатов:** та же нагрузка → те же агрегаты числом (литералы).
* Кванторный критерий («порт дублирует каждую публикацию дважды») — см.
  раздел «недостижимо на моём стенде» в отчёте тестера: он не тестируется
  здесь отдельным файлом, обоснование — там же.
"""

from __future__ import annotations

from typing import Any, Optional

from ...base_manager.mixins.observable_mixin import ObservableMixin
from ...channel_routing_module.observability import STATS_AGGREGATE_KEY
from ...channel_routing_module.observability.observability_hub import ObservabilityHub
from ...process_module.heartbeat import telemetry
from .. import StatsManager
from ..observation.observation_manager import ObservationPort


# ====================================================================== #
#  Харнесс — только реальные классы фреймворка, ни одного мока СУТи.      #
# ====================================================================== #


class _MutedObservationPort(ObservationPort):
    """Заглушенный порт: публикация уходит в никуда, как «порт нем» из М5.

    Наследник настоящего :class:`ObservationPort`, а не дубль по форме —
    единственное отличие: ``publish`` ничего не делает. Хранилище остаётся
    ``None`` навсегда, поэтому :meth:`collect_subtree`/:meth:`level_names`
    честно отвечают «показаний нет», а не «пусто, потому что не спросили».
    """

    def publish(self, name: str, value: Any, writer: str) -> None:  # noqa: D401
        pass


def _make_live_port() -> ObservationPort:
    """Живой порт поверх настоящего ``PluginLevels`` — пара-контроль М5."""
    return ObservationPort(telemetry.PluginLevels())


def _make_stats_manager(name: str, hub: ObservabilityHub) -> StatsManager:
    """Реальный ``StatsManager`` без файлового/лог-канала — только hub.

    Явно снят fallback-канал (``channels.file_stats.enabled=False``), иначе
    менеджер писал бы JSON на диск рабочего дерева тестера при каждом flush.
    Темп агрегации задран искусственно высоко (300 с), чтобы фоновый таймер
    не сбросил окно САМ во время теста — снапшот берётся детерминированно,
    вызовом ``mgr.flush()``.
    """
    mgr = StatsManager(
        manager_name=name,
        config={
            "enable_logging": False,
            "aggregation_interval": 300.0,
            "flush_interval": 300.0,
            "channels": {"file_stats": {"enabled": False}},
        },
    )
    assert mgr.initialize(), f"{name}: initialize() вернул False — стенд сломан ДО нагрузки"
    assert mgr.attach_observability_hub(hub), f"{name}: hub-канал не поднялся — стенд сломан ДО нагрузки"
    return mgr


def _drain_counter_aggregate(hub: ObservabilityHub, metric_name: str) -> Optional[float]:
    """Сумма ``count`` агрегатных снапшотов hub'а по имени counter-метрики.

    ``None`` — метрика НИ РАЗУ не встретилась ни в одном агрегатном снапшоте
    (якорь отсутствия, отличимый от «встретилась, но 0»). Снапшоты hub'а —
    это ВСЕ окна процесса, доехавшие до общего hub'а, а не окно одного
    писателя (критическая оговорка М5, инвентарь Task 5.1 дорога 3).
    """
    total: Optional[float] = None
    for rec in hub.drain_stats():
        if not rec.get(STATS_AGGREGATE_KEY):
            continue
        for m in rec.get("metrics") or []:
            if m.get("name") == metric_name and m.get("type") == "counter":
                total = (total or 0.0) + float(m.get("count") or 0.0)
    return total


def _drive_counter_load(mgr: StatsManager, metric_name: str, times: int) -> None:
    """Три вызова record_metric(name, 1) — дорога StatsManager напрямую."""
    for _ in range(times):
        mgr.record_metric(metric_name, 1)


def _drive_counter_load_via_slot(mgr: StatsManager, metric_name: str, times: int) -> None:
    """Та же нагрузка, но через слот-дорогу миксина (Task 5.1, дорога 3).

    ``ObservableMixin._record_metric`` резолвит имя ``"stats"`` через
    ``ManagerRegistry`` и зовёт ``record_metric`` на том, что за ним лежит —
    ровно так, как это делают 57 боевых вызывающих фреймворка
    (``dispatcher.py``, ``command_manager.py``, ``state_proxy.py`` и т.д.).
    """
    writer = ObservableMixin(managers={"stats": mgr})
    for _ in range(times):
        writer._record_metric(metric_name, 1)


# ====================================================================== #
#  М5 + паритет агрегатов                                                 #
# ====================================================================== #


def test_m5_muted_port_silences_levels_and_all_process_windows_live_port_gives_both_with_literals():
    """М5 дословно, с критической оговоркой инвентаря Task 5.1 учтённой в стенде.

    Стенд — ДВА независимых ``StatsManager`` (``writer_a`` — «мой» тестовый
    писатель, ``writer_b`` — писатель, представляющий framework-internal
    дорогу 3 из инвентаря Task 5.1, обращающийся через ОТДЕЛЬНЫЙ слот
    ``ObservableMixin``), оба сидят на ОДНОМ общем hub'е — ровно так, как в
    реальном процессе несколько компонентов фреймворка шлют числа в один
    ``ObservabilityHub``. Проверка идёт по hub'у (все окна процесса), а НЕ
    по window одного writer'а — иначе тест был бы зелёным и при живом
    дефекте: слепая зона, названная инвентарём Task 5.1 ("аналитика по
    собственной нагрузке не видит чужую дорогу").

    Пара:
    - ``mute``: порт заглушен (:class:`_MutedObservationPort`). Целевой
      контракт М5 — заглушенный порт молчит ВЕЗДЕ: ни одна из двух
      counter-метрик не долетает ни до одного окна, а уровень в дереве
      (``level_names``, capture/fps) не появляется вовсе.
    - ``live``: порт живой (:func:`_make_live_port`, настоящий
      ``PluginLevels``). И уровень публикуется литералом, и ОБА окна
      (``writer_a``/``writer_b``) отдают литерал ``count == 3.0``.

    Сегодня (до Task 5.2/5.3) счётный вход ``StatsManager.record_metric`` не
    знает о порте вообще — состояние порта (mute/live) НИКАК не влияет на
    агрегаты, они всегда доезжают. Поэтому ``mute``-плечо теста обязано
    провалиться: числа, вопреки М5, доезжают и при заглушенном порте. Плечо
    уровней (``collect_subtree``) при этом уже сегодня корректно — оно
    существующее свойство Ф3, не то, что чинит Ф5.
    """
    hub = ObservabilityHub("f5-tester-process")

    # ---------------------------------------------------------------- mute
    muted_port = _MutedObservationPort(None)

    writer_a_mute = _make_stats_manager("writer_a_mute", hub)
    writer_b_mute = _make_stats_manager("writer_b_mute", hub)
    try:
        # Дорога "уровень": публикация через заглушенный порт.
        muted_port.publish("fps", 30.0, "capture")

        # Дорога "числа": обе — прямой вызов И слот-дорога миксина, каждая
        # по три инкремента (S-4/паритет: 3 вызова record_metric(name, 1)).
        _drive_counter_load(writer_a_mute, "writer_a.ops", 3)
        _drive_counter_load_via_slot(writer_b_mute, "writer_b.ops", 3)

        writer_a_mute.flush()
        writer_b_mute.flush()

        # Якорь существования: имена метрик заведомо валидны, поэтому "не
        # встретилась ни разу" (None) отличимо от "встретилась и там 0".
        muted_levels = muted_port.collect_subtree()
        assert muted_levels == {}, f"М5 (уровни): заглушенный порт обязан молчать в дереве, а отдал {muted_levels!r}"
        muted_a = _drain_counter_aggregate(hub, "writer_a.ops")
        muted_b = _drain_counter_aggregate(hub, "writer_b.ops")
        assert muted_a is None, (
            "М5 (агрегаты, писатель A — 'мой'): заглушенный порт обязан молчать И в "
            f"окнах, а агрегат writer_a.ops всё равно доехал: count={muted_a!r}. "
            "Значит счётный вход StatsManager сегодня НЕ маршрутизируется через порт."
        )
        assert muted_b is None, (
            "М5 (агрегаты, писатель B — framework-internal дорога 3, критическая "
            f"оговорка инвентаря Task 5.1): агрегат writer_b.ops всё равно доехал: count={muted_b!r}. "
            "Проверка ТОЛЬКО писателя A прошла бы мимо этого дефекта — слот-дорога "
            "миксина сегодня так же не знает о порте."
        )
    finally:
        writer_a_mute.shutdown()
        writer_b_mute.shutdown()

    # ---------------------------------------------------------------- live (пара-контроль)
    live_port = _make_live_port()

    writer_a_live = _make_stats_manager("writer_a_live", hub)
    writer_b_live = _make_stats_manager("writer_b_live", hub)
    try:
        live_port.publish("fps", 30.0, "capture")

        _drive_counter_load(writer_a_live, "writer_a_live.ops", 3)
        _drive_counter_load_via_slot(writer_b_live, "writer_b_live.ops", 3)

        writer_a_live.flush()
        writer_b_live.flush()

        live_levels = live_port.collect_subtree()
        assert live_levels == {"plugins": {"capture": {"fps": 30.0}}}, (
            f"М5 (уровни, живой порт): ожидался литерал fps=30.0 у capture, отдано {live_levels!r}"
        )
        live_a = _drain_counter_aggregate(hub, "writer_a_live.ops")
        live_b = _drain_counter_aggregate(hub, "writer_b_live.ops")
        assert live_a == 3.0, f"М5/паритет агрегатов (живой порт, писатель A): ожидалось 3.0, отдано {live_a!r}"
        assert live_b == 3.0, f"М5/паритет агрегатов (живой порт, писатель B): ожидалось 3.0, отдано {live_b!r}"
    finally:
        writer_a_live.shutdown()
        writer_b_live.shutdown()


# ====================================================================== #
#  S-4 — паритет двух объектов за духк-тайп слотом "stats"                #
# ====================================================================== #


def test_s4_record_metric_means_counter_on_either_object_behind_the_stats_slot():
    """S-4: ``record_metric`` = counter (ПРИБАВИТЬ) независимо от того, кто за слотом.

    Инвентарь Task 5.1 (раздел «дорога 3») называет находку: слот ``"stats"``
    в системе резолвится в ДВА разных объекта в разных точках сборки —
    ``StatsManager`` (``process_managers.py:135``) и ``ObservabilityHub``
    (``observability_wiring.py:134``, ``worker_manager``). Оба духк-тайпово
    принимают ``record_metric(name, value, tags)`` через один и тот же слот
    ``ObservableMixin``, и S-4 требует, чтобы ОБА трактовали его одинаково —
    счётчик, а не перезапись (какой была семантика hub'а ДО правки S-4,
    ``observability_hub.py:192-215``).

    Три вызова ``record_metric(name, 1)`` через слот дают буквально 3, а не
    1 (что было бы у gauge-перезаписи), на ОБЕИХ дорогах — литералы, не
    "примерно".

    Этот тест сегодня ЗЕЛЁНЫЙ — S-4 (семантика ``ObservabilityHub.record_metric``
    = counter) уже закрыта прошлым коммитом (см. докстринг
    ``ObservabilityHub.record_metric``, "Задача S-4: до этой правки метод
    эмитил METRIC_GAUGE..."). Здесь она закрепляется тестом с литералами,
    как того явно требует Task 5.2 шаг 3 ("S-4 закрепляется тестом") и
    Task 5.5 ("S-4-паритет двух слотов") — регрессионный якорь на
    существующее свойство, а не непройденный критерий.
    """
    hub = ObservabilityHub("s4-tester-process")
    mgr = _make_stats_manager("s4_manager_slot", hub)
    try:
        manager_writer = ObservableMixin(managers={"stats": mgr})
        hub_writer = ObservableMixin(managers={"stats": hub})

        for _ in range(3):
            manager_writer._record_metric("s4.parity", 1)
        for _ in range(3):
            hub_writer._record_metric("s4.parity", 1)

        mgr.flush()

        manager_side = mgr.get_metric("s4.parity")
        assert manager_side is not None, "S-4 (StatsManager за слотом): метрика не найдена вовсе"
        assert manager_side["count"] == 3.0, (
            f"S-4 (StatsManager за слотом): ожидалось 3.0, отдано {manager_side['count']!r}"
        )

        hub_records = [
            rec for rec in hub.drain_stats() if not rec.get(STATS_AGGREGATE_KEY) and rec.get("metric") == "s4.parity"
        ]
        assert len(hub_records) == 3, (
            f"S-4 (ObservabilityHub за слотом): ожидалось 3 сырых записи, получено {len(hub_records)}"
        )
        hub_side_sum = sum(float(r.get("value") or 0.0) for r in hub_records)
        assert all(r.get("metric_type") == "counter" for r in hub_records), (
            f"S-4 (ObservabilityHub за слотом): не все записи типа 'counter' — {hub_records!r}"
        )
        assert hub_side_sum == 3.0, (
            f"S-4 (ObservabilityHub за слотом): сумма значений ожидалась 3.0 (было бы 1.0 при "
            f"gauge-перезаписи), отдано {hub_side_sum!r}"
        )
        assert hub_side_sum == manager_side["count"], (
            "S-4 паритет: два объекта за одним духк-тайп слотом разошлись в счёте — "
            f"StatsManager={manager_side['count']!r}, ObservabilityHub={hub_side_sum!r}"
        )
    finally:
        mgr.shutdown()
