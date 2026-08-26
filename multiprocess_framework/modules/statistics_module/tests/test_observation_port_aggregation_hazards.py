# -*- coding: utf-8 -*-
"""Авторские hazard-тесты Ф5 (Task 5.2/5.3) — механизм «StatsManager как вид поверх порта».

Дополняют независимую приёмку (``test_f5_independent_acceptance.py``), но не
заменяют её. Цель — опасности, которые видит только автор МЕХАНИЗМА, а не
acceptance-критерии плана: гонки, реентерабельность, дисциплина локов,
поведение при отсутствующем/выключенном порте, идемпотентность подключения,
одновременная публикация из двух потоков.

**История спора с независимой приёмкой — разобрана, абзац переписан
2026-08-26 (владелец).** Первая редакция этого докстринга утверждала, что
``test_f5_independent_acceptance.py::test_m5_...`` пройти НЕ МОЖЕТ. Это было
верно только про его тогдашнюю КОНСТРУКЦИЮ: тестер (работавший вслепую, до
реализации) строил ``StatsManager`` без ``attach_observation_port`` и ждал,
что состояние двух несвязанных объектов ``ObservationPort`` повлияет на
агрегаты менеджера, с которым они не встречаются ни разу. Это потребовало бы
процесс-широкого синглтона — механизма, чужого архитектуре
``ObservableMixin``/CRM (обе базы — explicit-injection).

Синглтон отвергнут, стенд приёмки приведён к БОЕВОЙ проводке
(``ProcessManagers.create_all`` → ``attach_observation_port``), и М5 теперь
зелёный вместе с S-4. Утверждение «пройти не может» больше не соответствует
коду, и оставлять его нельзя: уверенное неверное объяснение живёт дольше
дефекта.

Ценность красноты тестера при этом сохранилась, и она была не в том, о чём он
писал: его тест вскрыл, что «единственный писатель» вышел свойством ПРОВОДКИ,
а не построения — ``attach`` был опциональным и не сторожился ничем. Отсюда
счётчик и голос обхода (``observation_bypasses``) и файл
``process_module/tests/test_observation_port_boot_wiring_acceptance.py``.
"""

from __future__ import annotations

import threading
from typing import Any, Dict, Optional

from ...channel_routing_module.observability import STATS_AGGREGATE_KEY
from ...channel_routing_module.observability.observability_hub import ObservabilityHub
from ...base_manager.mixins.observable_mixin import ObservableMixin
from .. import StatsManager
from ..observation.observation_manager import ObservationManager


def _make_manager(name: str, hub: Optional[ObservabilityHub] = None) -> StatsManager:
    """StatsManager без файлового шума — тот же рецепт, что у независимой приёмки."""
    mgr = StatsManager(
        manager_name=name,
        config={
            "enable_logging": False,
            "aggregation_interval": 300.0,
            "flush_interval": 300.0,
            "channels": {"file_stats": {"enabled": False}},
        },
    )
    assert mgr.initialize(), f"{name}: initialize() вернул False"
    if hub is not None:
        assert mgr.attach_observability_hub(hub), f"{name}: hub-канал не поднялся"
    return mgr


def _make_port(process: Any = None) -> ObservationManager:
    port = ObservationManager(manager_name="ObservationManager", process=process)
    assert port.initialize()
    return port


class _MutedAfterAttachPort(ObservationManager):
    """Порт, у которого доставка чисел ОТКЛЮЧЕНА — М5 при ЯВНОМ подключении.

    В отличие от ``_MutedObservationPort`` независимой приёмки (муте
    ``publish`` — плоскость УРОВНЕЙ), здесь заглушена именно
    ``_deliver_number`` — единственный шов, которым Ф5 передаёт числа tap'ам
    (см. докстринг ``ObservationManager._deliver_number``). Заглушенный ЗДЕСЬ,
    а не подменой объекта целиком, чтобы явно доказать: «мьютинг» — это
    свойство ОДНОГО шва, а не второй код рядом.
    """

    def _deliver_number(self, record: Dict[str, Any]) -> None:  # noqa: D401
        pass


def test_attach_makes_the_facade_and_the_direct_call_land_in_one_aggregate():
    """Единственность писателя: дорога 1 (facade-стиль) и дорога 3 (слот-стиль)
    через ОДИН явно подключённый порт сходятся в ОДНОМ счётчике.

    Что может сломаться именно здесь: если бы `StatsManager.record_metric`
    (дорога 3) продолжал писать напрямую МИМО порта даже при подключённом
    порте, а только НОВЫЙ вызывающий (порт.record_metric, дорога 1) писал
    через tap — здесь бы получилось ДВА разных счётчика вместо одного слитого
    (двойной подсчёт при пересечении имён или потеря паритета). Проверяем
    литералом: 2 (прямой call дороги 3) + 3 (через порт, дорога 1) = 5, а не
    2 и не 3 по отдельности.
    """
    port = _make_port()
    mgr = _make_manager("unify")
    try:
        assert mgr.attach_observation_port(port) is True

        # Дорога 3 — StatsManager.record_metric() вызван НАПРЯМУЮ (как это
        # делают 57 боевых вызывающих слота "stats").
        for _ in range(2):
            mgr.record_metric("unified.ops", 1)

        # Дорога 1 — PluginContext писал бы через порт напрямую; здесь —
        # порт.record_metric(...) без посредника StatsManager.
        for _ in range(3):
            port.record_metric("unified.ops", 1)

        mgr.flush()
        metric = mgr.get_metric("unified.ops")
        assert metric is not None, "метрика не найдена — обе дороги потерялись"
        assert metric["count"] == 5.0, f"ожидалось 2+3=5.0 в ОДНОМ счётчике, получено {metric['count']!r}"
    finally:
        mgr.shutdown()
        port.shutdown()


def test_muted_delivery_after_explicit_attach_silences_the_aggregate_m5():
    """М5 буквально — но с ЯВНЫМ подключением (в отличие от независимой приёмки).

    Пара-контроль: тот же сценарий с ЖИВЫМ портом обязан дать 3.0 — иначе
    «молчание» могло бы объясняться сломанной проводкой вообще, а не
    заглушенной доставкой конкретно.
    """
    # ---- mute
    muted_port = _MutedAfterAttachPort(manager_name="MutedPort")
    assert muted_port.initialize()
    mgr_mute = _make_manager("m5_mute")
    try:
        assert mgr_mute.attach_observation_port(muted_port) is True
        for _ in range(3):
            mgr_mute.record_metric("m5.ops", 1)
        mgr_mute.flush()
        assert mgr_mute.get_metric("m5.ops") is None, (
            f"М5: заглушенная доставка обязана молчать, а метрика доехала: {mgr_mute.get_metric('m5.ops')!r}"
        )
    finally:
        mgr_mute.shutdown()
        muted_port.shutdown()

    # ---- live (пара-контроль)
    live_port = _make_port()
    mgr_live = _make_manager("m5_live")
    try:
        assert mgr_live.attach_observation_port(live_port) is True
        for _ in range(3):
            mgr_live.record_metric("m5.ops", 1)
        mgr_live.flush()
        metric = mgr_live.get_metric("m5.ops")
        assert metric is not None and metric["count"] == 3.0, (
            f"пара-контроль (живой порт): ожидалось 3.0, получено {metric!r}"
        )
    finally:
        mgr_live.shutdown()
        live_port.shutdown()


def test_no_port_attached_keeps_the_legacy_direct_write_s4_premise():
    """Без attach — старая прямая дорога жива (то же, что доказывает S-4-тест).

    Хазард здесь не в самом факте доставки (это уже дословно проверяет S-4),
    а в ГРАНИЦЕ: подключение порта к ОДНОМУ менеджеру не должно задеть
    поведение ВТОРОГО, ни разу не тронутого attach'ем — иначе «фолбэк для 57
    боевых вызывающих» был бы фолбэком до первого attach КОГО УГОДНО в
    процессе, а не per-instance свойством.
    """
    port = _make_port()
    attached = _make_manager("attached")
    untouched = _make_manager("untouched")
    try:
        assert attached.attach_observation_port(port) is True
        attached.record_metric("x", 1)  # уходит через порт

        # untouched НИКОГДА не видел attach — обязан остаться на прямой дороге.
        untouched.record_metric("y", 7)
        untouched.flush()
        metric = untouched.get_metric("y")
        assert metric is not None and metric["count"] == 7.0, (
            f"менеджер без attach обязан писать напрямую независимо от соседей: {metric!r}"
        )
    finally:
        attached.shutdown()
        untouched.shutdown()
        port.shutdown()


def test_reattaching_a_different_port_removes_the_old_tap_no_double_delivery():
    """Переключение порта не оставляет мёртвую подписку на старом (утечка/дубль-счёт).

    Что может сломаться: если старый tap не снимается при ``attach`` на новый
    порт, публикация ЧЕРЕЗ СТАРЫЙ порт (кем-то ещё держащим на него ссылку)
    продолжала бы долетать до этого же менеджера — счётчик рос бы ДВАЖДЫ на
    одно значение при последующей публикации через НОВЫЙ порт, если бы кто-то
    по ошибке всё ещё писал в старый.
    """
    port_a = _make_port()
    port_b = _make_port()
    mgr = _make_manager("reattach")
    try:
        assert mgr.attach_observation_port(port_a) is True
        assert mgr.attach_observation_port(port_b) is True  # переключение

        # Публикация через СТАРЫЙ порт после переключения — не должна доехать.
        port_a.record_metric("leak.check", 100)
        mgr.flush()
        assert mgr.get_metric("leak.check") is None, (
            "старый порт после reattach не отписан — запись доехала мимо активной подписки"
        )

        # Публикация через НОВЫЙ порт — обязана доехать ровно один раз.
        port_b.record_metric("leak.check", 1)
        mgr.flush()
        metric = mgr.get_metric("leak.check")
        assert metric is not None and metric["count"] == 1.0, (
            f"ожидалась ровно одна доставка через активный порт, получено {metric!r}"
        )
    finally:
        mgr.shutdown()
        port_a.shutdown()
        port_b.shutdown()


def test_reattaching_the_same_port_is_idempotent_no_duplicate_tap():
    """Повторный attach ТЕМ ЖЕ портом — не удваивает tap (иначе запись пришла бы дважды)."""
    port = _make_port()
    mgr = _make_manager("idempotent")
    try:
        assert mgr.attach_observation_port(port) is True
        assert mgr.attach_observation_port(port) is True  # повтор — не должен добавить второй tap

        port.record_metric("dup.check", 1)
        mgr.flush()
        metric = mgr.get_metric("dup.check")
        assert metric is not None and metric["count"] == 1.0, (
            f"повторный attach тем же портом продублировал доставку: {metric!r}"
        )
    finally:
        mgr.shutdown()
        port.shutdown()


def test_concurrent_publish_from_two_threads_no_lost_increments():
    """Гонка: два потока пишут в ОДИН порт одновременно — сумма обязана сойтись точно.

    Опасность именно ЭТОГО механизма: доставка идёт СИНХРОННО в потоке
    эмитента (``_emit_to_taps`` не буферизует), то есть ДВА потока могут
    одновременно попасть в ``_on_port_record`` → ``_apply_metric`` →
    ``_ensure_record`` этого же менеджера. Если бы блокировка
    ``_metrics_lock`` не покрывала весь путь чтения-изменения записи,
    инкременты терялись бы под конкуренцией (классический lost update).

    Поток, который может заблокироваться, — в daemon-потоке с join-дедлайном
    (правило проекта): здесь блокировки в штатной работе нет, но дедлайн
    всё равно стоит — тест обязан УПАСТЬ по таймауту, а не повиснуть, если
    что-то в цепочке синхронизации всё же приобретёт лок и не отпустит.
    """
    port = _make_port()
    mgr = _make_manager("race")
    N_PER_THREAD = 500
    try:
        assert mgr.attach_observation_port(port) is True

        def _hammer() -> None:
            for _ in range(N_PER_THREAD):
                port.record_metric("race.ops", 1)

        threads = [threading.Thread(target=_hammer, daemon=True) for _ in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=30.0)
            assert not t.is_alive(), "поток не завершился за 30с — подозрение на дедлок в доставке"

        mgr.flush()
        metric = mgr.get_metric("race.ops")
        expected = 4 * N_PER_THREAD
        assert metric is not None and metric["count"] == float(expected), (
            f"под конкуренцией потеряны инкременты: ожидалось {expected}.0, получено {metric!r}"
        )
    finally:
        mgr.shutdown()
        port.shutdown()


def test_hub_sink_still_receives_the_aggregate_snapshot_not_the_port_raw_stream():
    """Сток в hub — снапшот ОКНА (как сегодня), а не сырые числа порта по одному.

    Опасность: перепутать ДВЕ независимые дороги — «tap порта → агрегация» и
    «flush окна → HubStatsChannel». Если бы (по ошибке) числа порта ТОЖЕ
    писались в hub поштучно (kind=stats, не агрегат), число сырых записей в
    hub росло бы с каждым вызовом ``record_metric``, а не оставалось нулевым
    до первого ``flush()``. Кванторно — минимум два такта (``flush`` дважды):
    оба раза в hub'е ровно ОДНА агрегатная запись за такт, не по одной на
    вызов.
    """
    hub = ObservabilityHub("sink-check")
    port = _make_port()
    mgr = _make_manager("sink_check", hub=hub)
    try:
        assert mgr.attach_observation_port(port) is True

        for _ in range(5):
            port.record_metric("sink.ops", 1)
        assert hub.drain_stats() == [], (
            "до flush() в hub уже что-то лежит — порт пишет напрямую в hub, а не только в tap"
        )

        mgr.flush()
        first = hub.drain_stats()
        aggregates_1 = [r for r in first if r.get(STATS_AGGREGATE_KEY)]
        assert len(aggregates_1) == 1, f"такт 1: ожидалась ровно одна агрегатная запись, получено {len(aggregates_1)}"

        for _ in range(3):
            port.record_metric("sink.ops", 1)
        mgr.flush()
        second = hub.drain_stats()
        aggregates_2 = [r for r in second if r.get(STATS_AGGREGATE_KEY)]
        assert len(aggregates_2) == 1, f"такт 2: ожидалась ровно одна агрегатная запись, получено {len(aggregates_2)}"
    finally:
        mgr.shutdown()
        port.shutdown()


def test_slot_route_doroga_3_style_reaches_the_port_when_attached():
    """Дорога 3 (слот ``ObservableMixin``) не переписана (57 сайтов), но её АДРЕСАТ
    (менеджер за слотом) корректно уходит в порт, когда порт подключён к НЕМУ.

    Инвентарь Task 5.1 называет именно эту дорогу — 57 боевых вызовов через
    ``self._record_metric(...)``. Здесь — не боевой сайт, а воспроизведение
    того же вызова через ``ObservableMixin`` с духк-тайп слотом "stats",
    ровно как это делают ``dispatcher.py``/``command_manager.py`` и другие.
    """
    port = _make_port()
    mgr = _make_manager("slot_route")
    try:
        assert mgr.attach_observation_port(port) is True
        writer = ObservableMixin(managers={"stats": mgr})
        for _ in range(4):
            writer._record_metric("slot.ops", 1)
        mgr.flush()
        metric = mgr.get_metric("slot.ops")
        assert metric is not None and metric["count"] == 4.0, f"дорога 3 через подключённый порт: {metric!r}"
    finally:
        mgr.shutdown()
        port.shutdown()


# --------------------------------------------------------------------------- #
# Дыры матрицы инъекций Ф5 (владелец, 2026-08-26): две заплаты не покрасили
# ничего по существу — их предсказал слепой генератор инъекций.
# --------------------------------------------------------------------------- #


def test_unknown_metric_kind_is_DROPPED_not_silently_counted():
    """Незнакомый род значения обязан быть отброшен, а не стать счётчиком.

    Заплата P5 матрицы: ``_METRIC_KIND_TO_TYPE.get(kind)`` →
    ``.get(kind, MetricType.COUNTER)``. Она не покрасила по существу ничего
    (единственный красный был тестом ЦЕНЫ горячей дороги, к смыслу отношения
    не имеющим). А класс дефекта настоящий: таблица родов продублирована в
    двух файлах и держится синхронной РУКАМИ — разъедься она, и запись тихо
    вливалась бы не в ту серию вместо того, чтобы быть отброшенной.

    Пара:

    * **отрицание** — род ``"не-существует"`` не создаёт метрики вовсе;
    * **якорь существования** — тот же путь, тот же менеджер, но род
      ``"counter"``: метрика есть и равна литералу ``2.0``.
    """
    mgr = _make_manager("unknown_kind_probe")
    try:
        mgr._on_port_record({"metric_kind": "не-существует", "name": "ghost.ops", "value": 7, "tags": {}})
        assert mgr.get_metric("ghost.ops") is None, (
            "незнакомый род тихо создал метрику: "
            f"{mgr.get_metric('ghost.ops')!r}. Отбрасывание — единственный безопасный "
            "исход при рассинхроне таблицы родов между двумя файлами."
        )

        for _ in range(2):
            mgr._on_port_record({"metric_kind": "counter", "name": "real.ops", "value": 1, "tags": {}})
        landed = mgr.get_metric("real.ops")
        assert landed is not None, "якорь существования: известный род обязан доехать, а его нет"
        assert landed["count"] == 2.0, f"якорь существования: ожидалось 2.0, отдано {landed['count']!r}"
    finally:
        mgr.shutdown()


def test_the_bypass_voice_is_actually_HEARD_once_per_method(caplog):
    """Голос об обходе порта обязан ЗВУЧАТЬ — счётчика без голоса недостаточно.

    Заплата P6 матрицы (перестановка ``first``/инкремент так, что голос не
    звучит никогда) не покрасила по существу ничего. Разбор показал худшее:
    голос молчал и БЕЗ всякой заплаты. Первая редакция звала
    ``self._log_warning``, то есть ``_call_manager("logger", ...)`` с тремя
    тихими допусками, а обход случается ровно у менеджера, построенного вне
    сборки, — у которого слота ``logger`` обычно нет.

    Воспроизведено 2026-08-26: три обхода дали
    ``observation_bypasses == {'record_metric': 2, 'gauge': 1}`` при НУЛЕ строк
    лога. Счётчик был жив, контрол — мёртв.

    Кванторная часть (голос ровно один раз на метод, а не на вызов) меряется
    на ДВУХ вызовах одного метода, как требует правило.
    """
    import logging

    mgr = _make_manager("voice_probe")
    try:
        with caplog.at_level(
            logging.WARNING, logger="multiprocess_framework.modules.statistics_module.core.stats_manager"
        ):
            mgr.record_metric("v.ops", 1)
            mgr.record_metric("v.ops", 1)
            mgr.gauge("v.level", 5)

        said = [r.getMessage() for r in caplog.records if "МИМО порта" in r.getMessage()]
        assert len(said) == 2, (
            f"голос обхода прозвучал {len(said)} раз, ожидалось 2 (по одному на МЕТОД: "
            f"record_metric и gauge, при трёх вызовах). Сказанное: {said!r}"
        )
        assert any("record_metric()" in m for m in said), f"голос не назвал record_metric: {said!r}"
        assert any("gauge()" in m for m in said), f"голос не назвал gauge: {said!r}"

        # Якорь существования счётчика рядом с голосом: одно без другого — половина.
        assert mgr.observation_bypasses == {"record_metric": 2, "gauge": 1}, (
            f"счётчик разошёлся с голосом: {mgr.observation_bypasses!r}"
        )
    finally:
        mgr.shutdown()
