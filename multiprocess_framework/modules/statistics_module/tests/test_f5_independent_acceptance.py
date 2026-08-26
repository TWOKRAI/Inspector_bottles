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

from typing import Any, Dict, Optional

from ...base_manager.mixins.observable_mixin import ObservableMixin
from ...channel_routing_module.observability import STATS_AGGREGATE_KEY
from ...channel_routing_module.observability.observability_hub import ObservabilityHub
from ...process_module.heartbeat import telemetry
from .. import StatsManager
from ..observation.observation_manager import ObservationManager, ObservationPort


# ====================================================================== #
#  Харнесс — только реальные классы фреймворка, ни одного мока СУТи.      #
# ====================================================================== #


class _MutedObservationPort(ObservationPort):
    """Заглушенный порт: и публикация уровня, и числа уходят в никуда («порт нем» из М5).

    Наследник настоящего :class:`ObservationPort`, а не дубль по форме.
    Заглушены ОБА шва: ``publish`` (плоскость УРОВНЕЙ — хранилище остаётся
    ``None`` навсегда, поэтому :meth:`collect_subtree`/:meth:`level_names`
    честно отвечают «показаний нет», а не «пусто, потому что не спросили») и
    ``_deliver_number`` (плоскость ЧИСЕЛ, Ф5 — единственный шов, которым
    :class:`ObservationManager` доставляет числа tap'ам; см. его докстринг).
    До правки итерации 2 здесь была заглушена ТОЛЬКО ``publish`` — числовая
    дорога ещё не существовала на момент, когда тест писался (см. докстринг
    теста ``test_m5_...`` — история и разбор владельца).
    """

    def publish(self, name: str, value: Any, writer: str) -> None:  # noqa: D401
        pass

    def _deliver_number(self, record: Any) -> None:  # noqa: D401
        pass


class _MutedNumberManager(ObservationManager):
    """Заглушенный ЧИСЛОВОЙ порт для ``attach_observation_port`` (Ф5, ревью-блокер B2).

    Правка B2 сделала ``attach_observation_port`` отказывающим у порта БЕЗ
    ``add_tap`` (см. ``StatsManager.attach_observation_port`` — бывший
    ``_MutedObservationPort`` этого файла не проходит: он голый
    :class:`ObservationPort`, ``add_tap`` не имеет вовсе). М5 при этом
    проверяет ДРУГОЕ свойство — «порт ПОДКЛЮЧЁН и молчит на своём шве», а не
    «порт не может подключиться»; для ЭТОГО свойства нужен порт, который
    ``add_tap`` ИМЕЕТ (настоящий :class:`ObservationManager` — подписка
    состоится, ``attach`` вернёт ``True``), но глушит именно
    :meth:`_deliver_number`, ровно как это уже делает ``_MutedAfterAttachPort``
    в соседнем авторском hazard-файле
    (``test_observation_port_aggregation_hazards.py``) — тот же жест, что и
    там, тем же доводом.

    Свойство М5 («заглуши порт — молчат агрегаты ВСЕХ окон») от этой замены не
    меняется ни на бит: mute остаётся mute, просто честнее ОТНОСИТЕЛЬНО B2 —
    он ПОДПИСАН и решает молчать, а не притворяется подключённым, не умея
    подписаться вовсе.
    """

    def _deliver_number(self, record: Any) -> None:  # noqa: D401
        pass


def _make_live_port() -> ObservationPort:
    """Живой порт поверх настоящего ``PluginLevels`` — пара-контроль М5, плоскость УРОВНЕЙ.

    Только для проверки уровней (``publish``/``collect_subtree``) — бесхозный
    вид без CRM, ``add_tap`` у него нет. Для плоскости ЧИСЕЛ (Ф5) нужен
    :func:`_make_number_port` — настоящий ``ObservationManager``.
    """
    return ObservationPort(telemetry.PluginLevels())


def _make_number_port() -> ObservationManager:
    """Живой порт для плоскости ЧИСЕЛ (Ф5) — настоящий ``ObservationManager``.

    В отличие от бесхозного :class:`ObservationPort` (:func:`_make_live_port`,
    только уровни), числа доставляются CRM-tap'ом
    (:meth:`ObservationManager._deliver_number` → ``_emit_to_taps``), которого
    у бесхозного вида нет — доставка требует настоящего менеджера с CRM-базой.
    """
    port = ObservationManager(manager_name="ObservationManager")
    assert port.initialize(), "ObservationManager: initialize() вернул False — стенд сломан ДО нагрузки"
    return port


def _make_stats_manager(name: str, hub: ObservabilityHub, port: Optional[ObservationManager] = None) -> StatsManager:
    """Реальный ``StatsManager`` без файлового/лог-канала — только hub (и, опционально, порт).

    Явно снят fallback-канал (``channels.file_stats.enabled=False``), иначе
    менеджер писал бы JSON на диск рабочего дерева тестера при каждом flush.
    Темп агрегации задран искусственно высоко (300 с), чтобы фоновый таймер
    не сбросил окно САМ во время теста — снапшот берётся детерминированно,
    вызовом ``mgr.flush()``.

    ``port`` — явное подключение (:meth:`StatsManager.attach_observation_port`),
    ровно как это делает ``ProcessManagers.create_all`` в боевой сборке (Ф5,
    задача 5.2/5.3, ADR-SM-014). Без него менеджер работает СТАРОЙ прямой
    дорогой — тот путь по-прежнему существует (фолбэк для менеджера вне
    сборки, S-4-тест этого файла строит его именно так), но плоскость ЧИСЕЛ
    М5 требует явного attach — см. докстринг ``test_m5_...``.
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
    if port is not None:
        assert mgr.attach_observation_port(port) is True, f"{name}: attach_observation_port вернул False"
    return mgr


def _drain_counter_aggregates(hub: ObservabilityHub, metric_names: "list[str]") -> Dict[str, Optional[float]]:
    """Сумма ``count`` агрегатных снапшотов hub'а по НЕСКОЛЬКИМ именам, ОДНИМ дренажом.

    ``ObservabilityHub.drain_stats()`` РАЗРУШАЮЩИЙ — второй вызов после
    первого видит уже пустой канал. Правка итерации 2 (владелец): исходная
    редакция звала однозначный ``_drain_counter_aggregate`` ДВАЖДЫ подряд
    (по разу на писателя), и второй вызов драл уже опустошённый канал —
    дефект был невидим, пока ``mute``-плечо падало на ПЕРВОМ имени раньше,
    чем тест успевал дойти до второго вызова; правка М5 (явный
    ``attach_observation_port``) впервые довела прогон до этой точки и
    обнажила гонку дренажа. Один дренаж, оба имени — по построению не может
    разойтись по порядку вызова.

    ``None`` у имени — метрика НИ РАЗУ не встретилась ни в одном агрегатном
    снапшоте (якорь отсутствия, отличимый от «встретилась, но 0»). Снапшоты
    hub'а — это ВСЕ окна процесса, доехавшие до общего hub'а, а не окно
    одного писателя (критическая оговорка М5, инвентарь Task 5.1 дорога 3).
    """
    totals: Dict[str, Optional[float]] = {name: None for name in metric_names}
    for rec in hub.drain_stats():
        if not rec.get(STATS_AGGREGATE_KEY):
            continue
        for m in rec.get("metrics") or []:
            name = m.get("name")
            if name in totals and m.get("type") == "counter":
                totals[name] = (totals[name] or 0.0) + float(m.get("count") or 0.0)
    return totals


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

    **История правки (владелец, спор разобран, итерация 2 — не переписывать
    под реализацию ещё раз).** Тест написан независимым тестером ДО Task
    5.2/5.3, вслепую, по тексту плана и инвентарю Task 5.1 — в частности, ДО
    того, как появился ``StatsManager.attach_observation_port`` (задача
    5.2/5.3, ADR-SM-014). В первой редакции ``_make_stats_manager`` не
    подключала ЧИСЛОВОЙ порт ни к одному писателю вовсе — оба плеча пары
    (mute/live) строили ``StatsManager`` ОДНИМ И ТЕМ ЖЕ вызовом, различающимся
    только локальными объектами ``muted_port``/``live_port``, которые ни разу
    не передавались менеджеру ни через ``managers=``, ни через ``process``, ни
    через какой-либо attach. TeamLead (задача 5.2/5.3, первая итерация)
    показал, что это делает тест НЕВЫПОЛНИМЫМ одновременно с S-4-тестом этого
    же файла (тот строит менеджер ТЕМ ЖЕ конструктором и требует
    ПРОТИВОПОЛОЖНОГО исхода — доставки, а не тишины) без скрытого
    процесс-широкого синглтона порта, которого нет нигде в архитектуре
    ``ObservableMixin``/CRM (explicit-injection дословно). Владелец разобрал
    спор: конструкция теста была неверна, синглтон — чужой архитектуре
    механизм, тест правится под БОЕВУЮ ПРОВОДКУ (``ProcessManagers.create_all``
    зовёт ``attach_observation_port`` явно) — не под реализацию произвольно.
    Правка ниже: оба писателя получают явно подключённый (мьютом или живой)
    ЧИСЛОВОЙ порт — :func:`_make_number_port`/:class:`_MutedObservationPort`
    (теперь глушащий и ``_deliver_number``, не только ``publish``) — ровно тот
    же жест, что боевая сборка. Замысел стенда — ДВА независимых
    ``StatsManager`` на ОДНОМ общем hub'е, проверка по hub'у (ВСЕ окна
    процесса), а не по окну одного writer'а — эта часть НЕ тронута, она верна
    и она главная (см. ниже).

    Стенд — ДВА независимых ``StatsManager`` (``writer_a`` — «мой» тестовый
    писатель, ``writer_b`` — писатель, представляющий framework-internal
    дорогу 3 из инвентаря Task 5.1, обращающийся через ОТДЕЛЬНЫЙ слот
    ``ObservableMixin``), оба сидят на ОДНОМ общем hub'е — ровно так, как в
    реальном процессе несколько компонентов фреймворка шлют числа в один
    ``ObservabilityHub``. У каждого писателя — СВОЙ числовой порт (в реальной
    сборке порт тоже один на процесс, но здесь два писателя — это ДВА
    отдельных ``StatsManager``, и общий порт с двумя tap'ами удвоил бы счёт
    ЧУЖОГО имени метрики — оба tap'а получили бы ОБЕ публикации). Проверка
    идёт по hub'у (все окна процесса), а НЕ по window одного writer'а — иначе
    тест был бы зелёным и при живом дефекте: слепая зона, названная
    инвентарём Task 5.1 ("аналитика по собственной нагрузке не видит чужую
    дорогу").

    Пара:
    - ``mute``: числовой порт КАЖДОГО писателя заглушен
      (:class:`_MutedNumberManager` — правка B2, ниже); уровень публикуется
      через ОТДЕЛЬНЫЙ, тоже заглушенный БЕСХОЗНЫЙ порт (плоскость уровней
      стенду не нужно смешивать с плоскостью чисел писателей — она
      проверяется тем же классом, но независимо). Целевой контракт М5 —
      заглушенный порт молчит ВЕЗДЕ: ни одна из двух counter-метрик не
      долетает ни до одного окна, а уровень в дереве (``fps``) не появляется
      вовсе.
    - ``live``: числовые порты писателей и порт уровня — живые
      (:func:`_make_number_port`/:func:`_make_live_port`). И уровень
      публикуется литералом, и ОБА окна (``writer_a``/``writer_b``) отдают
      литерал ``count == 3.0``.

    **Правка B2 (ревью Ф5, TeamLead, экспресс-реализация — история продолжена,
    третья запись).** ``attach_observation_port`` стал отказывающим у порта БЕЗ
    ``add_tap`` (см. ``StatsManager.attach_observation_port`` — воспроизведено:
    ``bare = ObservationPort(...); attach(bare) -> True`` докладывал успех,
    хотя число НИКОГДА не возвращалось этому менеджеру обратно). Прежний
    ``muted_port_a``/``muted_port_b`` были голыми :class:`_MutedObservationPort`
    (``ObservationPort`` без CRM, без ``add_tap``) — с правкой B2
    ``attach_observation_port(muted_port_a)`` вернул бы ``False``, и стенд
    остался бы на СТАРОЙ прямой дороге StatsManager, которая как раз ДОСТАВЛЯЕТ
    (не мьютит) — тест противоречил бы сам себе. Свойство, которое здесь
    проверяется («порт ПОДКЛЮЧЁН и молчит»), а не «порт не может
    подключиться» — заменено на :class:`_MutedNumberManager` (настоящий
    ``ObservationManager``, ``add_tap`` есть, подписка СОСТОИТСЯ, глушит
    только ``_deliver_number``) — тот же жест, что уже стоит в соседнем
    авторском hazard-файле (``_MutedAfterAttachPort``,
    ``test_observation_port_aggregation_hazards.py``). ``muted_level_port``
    (плоскость УРОВНЕЙ, не подключается к ``StatsManager`` вовсе) не тронут —
    B2 про ``attach_observation_port``, к нему это не относится.
    """
    hub = ObservabilityHub("f5-tester-process")

    # ---------------------------------------------------------------- mute
    muted_level_port = _MutedObservationPort(None)
    muted_port_a = _MutedNumberManager(manager_name="muted_port_a")
    muted_port_b = _MutedNumberManager(manager_name="muted_port_b")
    assert muted_port_a.initialize() and muted_port_b.initialize(), "стенд сломан ДО нагрузки"

    writer_a_mute = _make_stats_manager("writer_a_mute", hub, port=muted_port_a)
    writer_b_mute = _make_stats_manager("writer_b_mute", hub, port=muted_port_b)
    try:
        # Дорога "уровень": публикация через заглушенный порт.
        muted_level_port.publish("fps", 30.0, "capture")

        # Дорога "числа": обе — прямой вызов И слот-дорога миксина, каждая
        # по три инкремента (S-4/паритет: 3 вызова record_metric(name, 1)).
        # Оба менеджера ЯВНО подключены к своему (заглушенному) числовому
        # порту — записи форвардятся ему и там же глохнут (_deliver_number).
        _drive_counter_load(writer_a_mute, "writer_a.ops", 3)
        _drive_counter_load_via_slot(writer_b_mute, "writer_b.ops", 3)

        writer_a_mute.flush()
        writer_b_mute.flush()

        # Якорь существования: имена метрик заведомо валидны, поэтому "не
        # встретилась ни разу" (None) отличимо от "встретилась и там 0".
        muted_levels = muted_level_port.collect_subtree()
        assert muted_levels == {}, f"М5 (уровни): заглушенный порт обязан молчать в дереве, а отдал {muted_levels!r}"
        muted = _drain_counter_aggregates(hub, ["writer_a.ops", "writer_b.ops"])
        muted_a, muted_b = muted["writer_a.ops"], muted["writer_b.ops"]
        assert muted_a is None, (
            "М5 (агрегаты, писатель A — 'мой'): заглушенный порт обязан молчать И в "
            f"окнах, а агрегат writer_a.ops всё равно доехал: count={muted_a!r}. "
            "Значит счётный вход StatsManager не маршрутизируется через порт."
        )
        assert muted_b is None, (
            "М5 (агрегаты, писатель B — framework-internal дорога 3, критическая "
            f"оговорка инвентаря Task 5.1): агрегат writer_b.ops всё равно доехал: count={muted_b!r}. "
            "Проверка ТОЛЬКО писателя A прошла бы мимо этого дефекта — слот-дорога "
            "миксина так же обязана идти через порт."
        )
    finally:
        writer_a_mute.shutdown()
        writer_b_mute.shutdown()
        # B2: muted_port_a/b теперь настоящие ObservationManager (CRM-база) —
        # в отличие от прежних бесхозных ObservationPort, у них ЕСТЬ shutdown().
        muted_port_a.shutdown()
        muted_port_b.shutdown()

    # ---------------------------------------------------------------- live (пара-контроль)
    live_level_port = _make_live_port()
    live_port_a = _make_number_port()
    live_port_b = _make_number_port()

    writer_a_live = _make_stats_manager("writer_a_live", hub, port=live_port_a)
    writer_b_live = _make_stats_manager("writer_b_live", hub, port=live_port_b)
    try:
        live_level_port.publish("fps", 30.0, "capture")

        _drive_counter_load(writer_a_live, "writer_a_live.ops", 3)
        _drive_counter_load_via_slot(writer_b_live, "writer_b_live.ops", 3)

        writer_a_live.flush()
        writer_b_live.flush()

        live_levels = live_level_port.collect_subtree()
        assert live_levels == {"plugins": {"capture": {"fps": 30.0}}}, (
            f"М5 (уровни, живой порт): ожидался литерал fps=30.0 у capture, отдано {live_levels!r}"
        )
        live = _drain_counter_aggregates(hub, ["writer_a_live.ops", "writer_b_live.ops"])
        live_a, live_b = live["writer_a_live.ops"], live["writer_b_live.ops"]
        assert live_a == 3.0, f"М5/паритет агрегатов (живой порт, писатель A): ожидалось 3.0, отдано {live_a!r}"
        assert live_b == 3.0, f"М5/паритет агрегатов (живой порт, писатель B): ожидалось 3.0, отдано {live_b!r}"
    finally:
        writer_a_live.shutdown()
        writer_b_live.shutdown()
        live_port_a.shutdown()
        live_port_b.shutdown()


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
