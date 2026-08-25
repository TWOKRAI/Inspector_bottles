# -*- coding: utf-8 -*-
"""Авторские hazard-тесты записей порта наблюдений в хаб (Ф3, задача 3.2).

**Что может сломаться в ЭТОМ механизме, учитывая, как он построен.** Приёмка
(``process_module/tests/test_observation_records_acceptance.py``, написана
вслепую и до реализации) сторожит КОНТРАКТ: писатель ⇒ запись с литералом,
парный гейт, одна запись на тик, идентичность+pickle, хаб отсутствует —
именованный no-op, ``introspect.observability`` называет плоскость, верхняя
граница стоимости. Здесь — опасности УСТРОЙСТВА, которых из критериев не
видно, потому что они следуют из КОНКРЕТНЫХ решений реализации:

1. **Четвёртый канал делит хаб с тремя старыми** (``ObservabilityHub._channels``,
   ``KIND_OBSERVATION``). Отсюда: переполнение канала обязано расти СВОИМ
   счётчиком, не чужим (:class:`TestChannelOverflowHasItsOwnCounter`); запись
   обязана попасть РОВНО в один канал, не расплескаться по трём старым
   (:class:`TestRecordDoesNotLeakIntoOtherKinds`) — тот же вопрос, что уже
   проверен на уровне ``hub`` в ``test_observability_hub.py``, здесь смотрится
   ДРУГИМ объективом: через боевой тик ``ProcessHeartbeat``, а не прямым
   вызовом ``emit_observation_record``.

2. **Дренаж — общий с log/stats, и адаптер один на все kind'ы.**
   ``ObservabilityDrainAdapter.apply_drained`` читает ``drained`` по ИМЕНИ
   ключа (``KIND_LOG``/``KIND_ERROR``/``KIND_STATS``) — четвёртый ключ он не
   спрашивал НИКОГДА, но словарь ``drain_all()`` теперь несёт его всегда.
   Опасность: запись, попавшая обратно в sink-менеджер (петля, тот же класс,
   что ``STATS_AGGREGATE_KEY`` уже чинил для агрегатов) —
   :class:`TestDrainDoesNotLoopIntoAManager`.

3. **Порядок внутри тика: снятие поддерева и сбор уровней — не одна
   операция.** ``_delete_departed_subtrees`` бежит ДО сбора; писатель мог уйти
   (``retract``) МЕЖДУ двумя тиками. Опасность: запись-призрак ушедшего
   писателя в хабе тем же тиком, что дерево уже стёрло его узел —
   :class:`TestDepartedWriterProducesNoGhostRecord`.

4. **Нормализатор/стор — общая труба с log/stats, а не украшение по касанию.**
   Записи ``kind=observation`` доезжают до ЖИВОГО хвоста и до стора ЧЕРЕЗ
   ``hub_record_to_display`` (задача 3.2, wiring в
   ``drain_process_observability``) — то же, что видит оператор, а не
   диагностика самой по себе. Первая редакция этого файла проверяла только
   «не падает» и тем самым ЗАФИКСИРОВАЛА дефект, который нашло ревью
   2026-08-25 запуском, не чтением: незнакомый ``kind`` действительно не
   падает, но падает в общий ``else`` и выходит ПУСТОЙ строкой
   (``message=""``, ``severity=""``) — ровно тот класс, что этот же файл
   (``record_display.py``) уже документирует для stats-агрегата. Теперь
   здесь два разных вопроса, и они не совпадают:
   :class:`TestObservationRecordRendersAReadableRow` пинит НАБЛЮДАЕМОЕ
   свойство литералами — что реально увидит оператор в строке хвоста/истории
   для уровня с известным значением (имя листа в ``message``, значение и
   писатель в ``extra``, число важности вне порога ошибки), плюс стор находит
   её полнотекстовым поиском ПО ИМЕНИ МЕТРИКИ — то, ради чего ``message``
   вообще смотрят; :class:`TestGenuinelyUnknownKindStillSurvives` держит узкое
   свойство «не падает» для kind'а, который НИКТО не готовился рендерить (не
   ``observation`` — тот теперь первоклассный, а произвольная строка).

   **Правка по инъекции I4 (ревью, итерация 2, 2026-08-25).** Первая редакция
   класса выше строила payload РУКАМИ (``hub.emit_observation_record({"writer":
   ..., "metric": ..., "value": ...})``) вместо того, чтобы взять запись,
   которую реально произвёл боевой путь (порт → тик → канал). Заплата I4
   («выбросить ``writer`` из ``records_for_hub``») красила ровно A4 приёмки и
   НИ ОДНОГО теста этого файла — тест про читаемую строку собирал запись сам
   и потому не мог увидеть дефект в том, что СОБИРАЕТ ``records_for_hub``.
   Обе проверки теперь читают запись из канала ПОСЛЕ реального тика.

5. **Дорога хаб → стор → живой хвост не проверялась вовсе.** Оба существующих
   теста (приёмка и класс 4 выше) касаются стора/хаба каждый со своей
   стороны — приёмка дренирует канал хаба НАПРЯМУЮ, класс 4 кладёт запись в
   стор РУКАМИ — и ни один не проходит через ``drain_process_observability``,
   строку, ради которой задача существует (обещание Task 3.1 «хвост и стор
   видят уровни без второго механизма»). Инъекция I8 (снять
   ``KIND_OBSERVATION`` из объединения в ``drain_process_observability``) дала
   0 красных на всей матрице при подтверждённом контролем разрыве дороги
   (стор: 1→0 строк, хвост: 1→0 записей) —
   :class:`TestHubToStoreAndLiveTailWiringIsNotBypassed` закрывает это.

6. **Критерий A6 «без нового словаря команд» — вакуумен ровно наполовину.**
   Приёмочный тест снимает ``commands_before`` ПОСЛЕ регистрации, поэтому
   сравнение ``commands_after == commands_before`` доказывает только, что
   ПОВТОРНЫЙ вызов команды ничего не регистрирует — не то, что регистрация
   САМОЙ секции обошлась без новой команды. Инъекция I7 (зарегистрировать
   ``observability.observation.introspect`` рядом с ``introspect.observability``)
   дала 0 красных при подтверждённом контролем составе словаря (10 → 11).
   :class:`TestIntrospectCommandDictionaryStaysAtExactlyTenNames` сверяет
   состав с ЛИТЕРАЛЬНЫМ списком имён (не пересчётом из кода — производный
   список согласился бы с любым ответом).

Потоков здесь нет — механизм синхронный (один тик, один поток), поэтому
дедлайн join'а не требуется; хазарды этого файла — про ФОРМУ данных и путь
записи, не про гонки (гонки резолвера уже покрыты
``test_observation_port_hazards.py``).

**Две измеренные границы приёмки, НЕ починенные здесь** (записаны, не
закрыты — ADR-SM-013, «разрешающая способность приёмки — измерена»):

- **I5** (снять ``if hub is None: return`` в ``_emit_observation_hub_records``)
  → 0 красных. Собственный ``except Exception`` метода гасит ``AttributeError``
  от ``None.get_channel`` тем же жестом, что и любой другой сбой хаба —
  половина A5 «хаб отсутствует» неотличима от «хаб отказал», и это
  СТРУКТУРНОЕ свойство обработки ошибок метода, а не дыра теста: сторожить
  здесь нечего без изобретения проверки на конкретное исключение, которая
  проверяла бы текст сообщения, а не поведение.
- **I10** (снять ``KIND_OBSERVATION`` из явной ветки ``severity_number_for``)
  → 0 красных. ``severity_number_for('observation', 'level')`` даёт ``0``
  что через объявленную ветку («у плоскости нет оси важности»), что через
  побочную (``severity_of('level')`` не опознаёт строку → ``UNSPECIFIED``) —
  по ЗНАЧЕНИЮ пути неразличимы, разница только в ПРИЧИНЕ. Свойство «через
  объявленную ветку, а не совпадением» проверяется чтением кода, не прогоном.
"""

from __future__ import annotations

from typing import Any, Dict, List, Tuple

from ...channel_routing_module.observability import (
    KIND_ERROR,
    KIND_LOG,
    KIND_OBSERVATION,
    KIND_STATS,
    ObservabilityDrainAdapter,
    ObservabilityHub,
    ObservabilityStore,
    hub_record_to_display,
)
from ...process_module.commands.builtin_commands import BuiltinCommands
from ...process_module.heartbeat.process_heartbeat import ProcessHeartbeat
from ...process_module.managers.observability_wiring import drain_process_observability
from ..observation.observation_manager import ObservationManager, observation_port


class _FakeStateProxy:
    """Хвост IPC до дерева StateStore — тот же минимальный носитель, что у приёмки."""

    def __init__(self) -> None:
        self.merged: List[Tuple[str, dict]] = []
        self.deleted: List[str] = []

    def merge(self, path: str, data: dict) -> None:
        self.merged.append((path, data))

    def delete(self, path: str) -> None:
        self.deleted.append(path)


class _HeartbeatServices:
    """Минимальный носитель тика heartbeat — форма дословна приёмке (тот же контракт)."""

    def __init__(self, *, hub: Any = None) -> None:
        self.name = "proc_hz"
        self._state_proxy = _FakeStateProxy()
        self.router_manager = None
        self.worker_manager = None
        self._observability_hub = hub
        self._managers: Dict[str, Any] = {}

    def get_config(self, key: str, default: Any = None) -> Any:
        return default

    def get_manager(self, slot: str) -> Any:
        return self._managers.get(slot)

    def log_debug(self, *a: Any, **k: Any) -> None:
        pass

    def log_info(self, *a: Any, **k: Any) -> None:
        pass


def _wired(hub: Any = None) -> Tuple[_HeartbeatServices, Any, ProcessHeartbeat]:
    """Процесс с боевым слотом ``observation`` (не lazy-фолбэком) + heartbeat."""
    services = _HeartbeatServices(hub=hub)
    manager = ObservationManager(process=services)
    services._managers["observation"] = manager
    port = observation_port(services, create=True)
    return services, port, ProcessHeartbeat(services)


# =============================================================== #
# 1. Переполнение канала — свой счётчик, а не чужой                #
# =============================================================== #


class TestChannelOverflowHasItsOwnCounter:
    """Переполнение observation-канала не считается в log/error/stats и наоборот.

    Ломается, если реализация когда-нибудь заведёт ОДИН общий счётчик потерь на
    хаб вместо счётчика НА КАНАЛ (``BoundedChannel._dropped`` у каждого канала
    свой) — тогда шумный писатель наблюдений тушил бы «здоровье» лог-плоскости
    молча, и `introspect.observability -> hub.dropped` начал бы врать про то,
    что теряется.
    """

    def test_observation_overflow_leaves_other_channels_counters_at_zero(self) -> None:
        hub = ObservabilityHub("proc_overflow", capacity=4)
        services, port, heartbeat = _wired(hub)

        # Один писатель, одна метрика — но 20 ТИКОВ подряд с меняющимся значением,
        # то есть 20 записей в канал ёмкостью 4: переполнение гарантировано.
        handle = port.for_plugin("capture")
        for i in range(20):
            handle.publish("fps", float(i))
            heartbeat._publish_telemetry_to_tree({}, None)

        assert hub.dropped[KIND_OBSERVATION] == 16, hub.dropped
        assert hub.dropped[KIND_LOG] == 0
        assert hub.dropped[KIND_ERROR] == 0
        assert hub.dropped[KIND_STATS] == 0
        # Переполнение хаба НЕ ронячет такт и НЕ мешает последнему значению
        # доехать до дерева — потеря локализована в наблюдаемости, а не в
        # самой телеметрии (A5 того же духа: hub теряет, дерево — нет).
        leaf = services._state_proxy.merged[-1][1]["state"]["plugins"]["capture"]["fps"]
        assert leaf == 19.0


# =============================================================== #
# 2. Запись не расплёскивается по чужим каналам (другой объектив)  #
# =============================================================== #


class TestRecordDoesNotLeakIntoOtherKinds:
    """Через БОЕВОЙ тик (не прямой ``emit_observation_record``) — запись едет
    РОВНО в канал ``observation`` и ни в один из трёх старых.

    Другой объектив, чем ``test_observability_hub.py::TestObservationChannel``:
    там дёргают hub напрямую, здесь — весь путь ``ObservationManager.publish``
    → ``ProcessHeartbeat._publish_telemetry_to_tree`` →
    ``_emit_observation_hub_records``. Совпадение точки наблюдения с тем тестом
    сделало бы зелёное здесь согласием ДВУХ копий одной и той же модели, а не
    независимой проверкой (урок [[feedback_injection_must_use_a_different_lens_than_the_test]]).
    """

    def test_tick_puts_the_record_only_in_the_observation_channel(self) -> None:
        hub = ObservabilityHub("proc_lens", capacity=16)
        services, port, heartbeat = _wired(hub)
        port.for_plugin("capture").publish("fps", 42.0)

        heartbeat._publish_telemetry_to_tree({}, None)

        assert hub.drain_logs() == []
        assert hub.drain_errors() == []
        assert hub.drain_stats() == []
        obs = hub.get_channel(KIND_OBSERVATION).drain()
        assert len(obs) == 1
        assert obs[0]["kind"] == KIND_OBSERVATION
        assert 42.0 in obs[0].values()


# =============================================================== #
# 3. Дренаж не переигрывает observation-запись в sink-менеджер     #
# =============================================================== #


class _RecordingSink:
    """Мок-sink: перехватывает любой вызов метода в ``self.calls``."""

    def __init__(self) -> None:
        self.calls: List[Tuple[str, tuple, dict]] = []

    def __getattr__(self, name: str) -> Any:
        def _rec(*args: Any, **kwargs: Any) -> bool:
            self.calls.append((name, args, kwargs))
            return True

        return _rec


class TestDrainDoesNotLoopIntoAManager:
    """``apply_drained`` не заводит четвёртого sink'а и не переигрывает
    observation-запись ни в один из трёх существующих.

    Ломается, если кто-нибудь однажды добавит в ``apply_drained`` цикл
    ``for rec in drained.get(KIND_OBSERVATION, ()): self.apply_stat(rec)`` «для
    единообразия» — запись порта не метрика StatsManager'а (нет
    ``metric_type``), и она легла бы туда как ``record_metric("", ...)`` —
    ровно тот класс петли, что уже описан у ``STATS_AGGREGATE_KEY``.
    """

    def test_observation_record_reaches_no_sink_method(self) -> None:
        hub = ObservabilityHub("proc_loop", capacity=16)
        logger, stats, error = _RecordingSink(), _RecordingSink(), _RecordingSink()
        adapter = ObservabilityDrainAdapter(logger=logger, stats=stats, error=error)

        hub.emit_observation_record({"writer": "capture", "metric": "fps", "value": 9.0})
        adapter.apply_drained(hub.drain_all())

        assert logger.calls == []
        assert stats.calls == []
        assert error.calls == []


# =============================================================== #
# 4. Ушедший писатель не оставляет запись-призрак                  #
# =============================================================== #


class TestDepartedWriterProducesNoGhostRecord:
    """Писатель, снятый МЕЖДУ тиками, не оставляет запись в хабе следующим тиком —
    ровно тем же тиком, что уже стирает его узел дерева.

    Ломается, если сборщик записей хаба когда-нибудь начнёт читать не то же
    поддерево, что легло в ``state`` (см. докстринг
    ``ProcessHeartbeat._emit_observation_hub_records``: «вход — ТО ЖЕ поддерево»),
    а собственный снимок ДО удаления — тогда лист дерева исчезнет, а хаб ещё
    один тик продолжит рапортовать метрику ушедшего плагина.
    """

    def test_retracted_writer_gives_zero_records_and_tree_delete_fires(self) -> None:
        hub = ObservabilityHub("proc_departed", capacity=16)
        services, port, heartbeat = _wired(hub)
        handle = port.for_plugin("capture")
        handle.publish("fps", 30.0)

        # Тик 1: писатель жив — запись есть, лист в дереве есть.
        heartbeat._publish_telemetry_to_tree({}, None)
        first = hub.get_channel(KIND_OBSERVATION).drain()
        assert len(first) == 1 and 30.0 in first[0].values()

        # Писатель уходит МЕЖДУ тиками (плагин остановлен) — retract() снимает
        # значения из хранилища немедленно (не ждёт тика).
        removed = handle.retract()
        assert removed == 1

        # Тик 2: ни одной observation-записи, а узел дерева писателя удалён
        # той же дорогой ``proxy.delete``.
        heartbeat._publish_telemetry_to_tree({}, None)
        second = hub.get_channel(KIND_OBSERVATION).drain()
        assert second == [], f"призрак ушедшего писателя: {second!r}"
        assert any(p.endswith(".state.plugins.capture") for p in services._state_proxy.deleted), (
            services._state_proxy.deleted
        )


# =============================================================== #
# 5a. observation рендерится ЧИТАЕМОЙ строкой — не пустой           #
# =============================================================== #


class TestObservationRecordRendersAReadableRow:
    """То, что реально увидит оператор в хвосте/истории для уровня с известным
    значением — литералами, а не «не упало».

    Реальные объекты: ``ObservabilityHub``, ``hub_record_to_display``,
    ``ObservabilityStore`` — ровно те классы, что работают на живом стенде
    (та же дорога, что у log/stats). Найдено ревью 2026-08-25 ЗАПУСКОМ этого
    самого сценария: до branch'а ``KIND_OBSERVATION`` в ``record_display.py``
    строка была пустой (``message=""``, ``severity=""``) при зелёном «запись
    есть» — ровно тот класс, что модуль уже документирует для stats-агрегата.
    """

    def test_hub_record_to_display_names_the_leaf_and_keeps_the_value(self) -> None:
        # Запись — ПРОИЗВЕДЕНА боевым путём (порт → тик → канал), не собрана
        # руками: сцепка «что кладёт тик» → «что читает оператор» обязана
        # проверяться на записи ИЗ тика, иначе тест доказывает форму, которую
        # сам же и придумал (найдено ревью, инъекция I4).
        hub = ObservabilityHub("proc_display", capacity=16)
        services, port, heartbeat = _wired(hub)
        port.for_plugin("capture").publish("fps", 7.0)
        heartbeat._publish_telemetry_to_tree({}, None)
        record = hub.get_channel(KIND_OBSERVATION).drain()[0]

        display = hub_record_to_display(record)

        assert display["kind"] == KIND_OBSERVATION
        # Строка обязана называть ЛИСТ (ту же identity, что несёт путь дерева
        # `state.plugins.<writer>.<metric>`) — не пустую строку и не repr записи.
        assert display["message"] == "capture.fps", display
        # Severity — ОСОЗНАННОЕ имя класса записи (у уровня нет оси важности —
        # тот же довод, что у stats), не пустая строка, провалившаяся сквозь
        # ранжирование. И число важности НЕ поднимается до порога ошибки (иначе
        # каждый уровень плагина красил бы вкладку «Ошибки»).
        assert display["severity"] == "level", display
        from multiprocess_framework.modules.channel_routing_module.levels import ERROR_SEVERITY

        assert display["severity_number"] < ERROR_SEVERITY, display
        assert display["extra"]["writer"] == "capture"
        assert display["extra"]["metric"] == "fps"
        assert display["extra"]["value"] == 7.0

    def test_store_round_trip_finds_the_record_by_metric_name(self, tmp_path) -> None:
        """Стор — ЧИТАЕМОЙ строкой на чтении (``list_records``) И находимой
        полнотекстовым поиском по имени метрики (``search``), а не только
        «вставка не упала». Поиск смотрит в ``message``/``module``/``process``
        и НЕ смотрит в ``extra`` (см. докстринг ``snapshot_message`` в
        ``record_display.py``) — если бы имя метрики осталось только в
        ``extra``, эта проверка честно бы не нашла ничего.

        Запись — ПРОИЗВЕДЕНА боевым путём (порт → тик → канал), той же
        причиной, что у соседнего теста (инъекция I4)."""
        db_path = str(tmp_path / "obs_store_hazard.sqlite3")
        store = ObservabilityStore(db_path)
        try:
            hub = ObservabilityHub("proc_store", capacity=16)
            services, port, heartbeat = _wired(hub)
            port.for_plugin("capture").publish("fps", 15.5)
            heartbeat._publish_telemetry_to_tree({}, None)
            record = hub.get_channel(KIND_OBSERVATION).drain()[0]

            inserted = store.append_records([record])
            assert inserted == 1

            rows = store.list_records(kind=KIND_OBSERVATION)
            assert len(rows) == 1, rows
            row = rows[0]
            assert row["message"] == "capture.fps", row
            assert row["severity"] == "level", row
            assert row["extra"]["writer"] == "capture"
            assert row["extra"]["value"] == 15.5

            assert store.search_available, store.search_unavailable_reason
            found = store.search("fps")
            assert len(found) == 1, f"полнотекстовый поиск по имени метрики не нашёл запись: {found!r}"
            assert found[0]["id"] == row["id"]
            assert found[0]["message"] == "capture.fps"
        finally:
            close = getattr(store, "close", None)
            if callable(close):
                close()


# =============================================================== #
# 5b. По-настоящему НЕЗНАКОМЫЙ kind не роняет нормализатор/стор     #
# =============================================================== #


class TestGenuinelyUnknownKindStillSurvives:
    """Узкое свойство «не падает» — для kind'а, который ДЕЙСТВИТЕЛЬНО никто не
    готовился рендерить (не ``observation``: тот теперь первоклассный член
    транспорта со своей веткой, см. класс выше). Держит инвариант общего
    ``else`` нормализатора на будущее — четвёртый kind появится снова
    когда-нибудь, и его тоже нельзя ронять до того, как для него напишут ветку.
    """

    _UNFAMILIAR_KIND = "widget_zzz_unfamiliar"

    def test_hub_record_to_display_does_not_raise_on_unknown_kind(self) -> None:
        hub = ObservabilityHub("proc_unfamiliar", capacity=16)
        # Прямая запись мимо hub'а — эмиттера этого kind'а не существует
        # (заведён только ради теста), поэтому конверт собираем руками, тем же
        # приёмом, что и `hub._envelope`.
        record = {
            "kind": self._UNFAMILIAR_KIND,
            "module": hub.module_name,
            "ts": 0.0,
            "payload_field": "x",
        }

        display = hub_record_to_display(record)  # не должно поднять исключение

        assert display["kind"] == self._UNFAMILIAR_KIND
        # Общий ``else`` честно не знает эту форму — пустая строка, а не
        # KeyError/AttributeError. Это ожидаемо и допустимо ИМЕННО потому, что
        # для этого kind'а никто не заявлял «оператор должен это прочитать»;
        # observation такое заявление уже сделало (класс выше).
        assert display["message"] == ""
        assert display["extra"]["payload_field"] == "x"

    def test_store_appends_an_unfamiliar_kind_without_raising(self, tmp_path) -> None:
        db_path = str(tmp_path / "unfamiliar_store_hazard.sqlite3")
        store = ObservabilityStore(db_path)
        try:
            record = {"kind": self._UNFAMILIAR_KIND, "module": "m", "ts": 0.0, "payload_field": "x"}

            inserted = store.append_records([record])  # не должно поднять исключение

            assert inserted == 1
            rows = store.list_records(kind=self._UNFAMILIAR_KIND)
            assert len(rows) == 1
            assert rows[0]["extra"]["payload_field"] == "x"
        finally:
            close = getattr(store, "close", None)
            if callable(close):
                close()


# =============================================================== #
# 6. Дорога хаб → стор → живой хвост — не байпассится               #
# =============================================================== #


class TestHubToStoreAndLiveTailWiringIsNotBypassed:
    """Та строка, ради которой задача существует: ``drain_process_observability``
    несёт ``kind=observation`` И в стор, И живому подписчику — ТЕМ ЖЕ вызовом,
    что дренирует такт heartbeat на живом стенде.

    Найдено ревью 2026-08-25 (итерация 2), инъекция I8 (снять
    ``drained.get(KIND_OBSERVATION, [])`` из объединения ``records`` в
    ``drain_process_observability``): 0 красных на всей матрице, при этом
    контроль (реальные объекты, без матрицы) показал разрыв дороги дословно:

        чисто   -> строк в сторе: 1 | в хвост уехало: 1
        заплата -> строк в сторе: 0 | в хвост уехало: 0

    Ни приёмка (дренирует канал хаба НАПРЯМУЮ, ``hub.get_channel(...).drain()``),
    ни соседний класс этого файла (кладёт запись в стор РУКАМИ,
    ``store.append_records([record])``) эту строку не проходят — оба
    заходят В стор/хаб каждый со своей стороны провода, минуя разъём между
    ними. Здесь — весь путь: писатель → тик → ``drain_process_observability``
    → стор И форвардер, читается ОБРАТНО из обоих.
    """

    def test_tick_reaches_the_store_and_the_forwarder_through_drain(self, tmp_path) -> None:
        hub = ObservabilityHub("proc_wiring", capacity=16)
        services, port, heartbeat = _wired(hub)
        port.for_plugin("capture").publish("fps", 55.0)
        heartbeat._publish_telemetry_to_tree({}, None)

        db_path = str(tmp_path / "wiring_hazard.sqlite3")
        store = ObservabilityStore(db_path)
        forwarded: List[dict] = []
        try:
            # adapter=None — та же форма контроля, каким это свойство мерил
            # ревьюер: adapter не участвует в этой дороге (он бьёт в
            # logger/error/stats sink'и, а observation-записи туда не идут,
            # см. TestDrainDoesNotLoopIntoAManager), проверяется только store+forwarders.
            drain_process_observability(hub, None, store, [forwarded.extend])

            store_rows = store.list_records(kind=KIND_OBSERVATION)
            assert len(store_rows) == 1, f"дорога до стора разорвана: {store_rows!r}"
            assert store_rows[0]["message"] == "capture.fps", store_rows[0]
            assert store_rows[0]["extra"]["value"] == 55.0

            observation_forwarded = [r for r in forwarded if r.get("kind") == KIND_OBSERVATION]
            assert len(observation_forwarded) == 1, f"дорога до живого хвоста разорвана: {forwarded!r}"
            assert observation_forwarded[0]["value"] == 55.0
            assert observation_forwarded[0]["writer"] == "capture"
        finally:
            close = getattr(store, "close", None)
            if callable(close):
                close()


# =============================================================== #
# 7. Словарь introspect.* не растёт секцией порта                  #
# =============================================================== #


#: Литерал, а не пересчёт из кода (найдено ревью 2026-08-25, итерация 2):
#: производный список (например ``set(specs)`` изнутри
#: ``_register_introspect_commands``) согласился бы с ЛЮБЫМ числом команд —
#: он не может увидеть 11-ю команду, потому что 11-я команда УЖЕ была бы в
#: нём, случись такая правка. Приёмочный тест A6 сравнивает состав ДО и
#: ПОСЛЕ повторного вызова той же регистрации (``commands_before`` снят
#: ПОСЛЕ ``_register_introspect_commands()``) — это доказывает «повторный
#: вызов идемпотентен», а не «сама регистрация не завела нового имени».
_EXPECTED_INTROSPECT_COMMANDS = frozenset(
    {
        "introspect.handlers",
        "introspect.registers",
        "introspect.status",
        "introspect.router_stats",
        "introspect.queues",
        "introspect.memory",
        "introspect.capabilities",
        "introspect.plugins",
        "introspect.telemetry",
        "introspect.observability",
    }
)


class _FakeCommandManager:
    """Минимальный CommandManager: хранит хендлеры по имени, как в приёмке."""

    def __init__(self) -> None:
        self.handlers: Dict[str, Any] = {}

    def register_command(self, name: str, handler: Any, metadata: Any = None, tags: Any = None) -> None:
        self.handlers[name] = handler


class _IntrospectServices:
    """Минимальный носитель для регистрации ``introspect.*`` — форма приёмки."""

    def __init__(self) -> None:
        self.command_manager = _FakeCommandManager()
        self.name = "proc_intro_hazard"
        self._current_process_status = "running"

    def _log_debug(self, *a: Any, **k: Any) -> None:
        pass

    def _log_info(self, *a: Any, **k: Any) -> None:
        pass

    def _log_warning(self, *a: Any, **k: Any) -> None:
        pass


class TestIntrospectCommandDictionaryStaysAtExactlyTenNames:
    """A6 «секция порта — без нового словаря команд» держится ЛИТЕРАЛОМ.

    Найдено ревью 2026-08-25 (итерация 2), инъекция I7 (зарегистрировать
    ``observability.observation.introspect`` рядом с ``introspect.observability``
    внутри ``_register_introspect_commands``): 0 красных при подтверждённом
    контролем составе словаря (10 → 11 команд, новая на месте). Причина —
    приёмочный тест снимает ``commands_before`` ПОСЛЕ регистрации и потому
    доказывает только идемпотентность повторного вызова, не состав самой
    регистрации.
    """

    def test_registering_introspect_commands_yields_exactly_the_known_ten(self) -> None:
        services = _IntrospectServices()

        BuiltinCommands(services)._register_introspect_commands()

        registered = set(services.command_manager.handlers)
        assert registered == _EXPECTED_INTROSPECT_COMMANDS, (
            f"словарь introspect.* разошёлся с ожидаемыми 10 именами: "
            f"лишние={sorted(registered - _EXPECTED_INTROSPECT_COMMANDS)!r}, "
            f"пропавшие={sorted(_EXPECTED_INTROSPECT_COMMANDS - registered)!r}"
        )


# =============================================================== #
# 8. Ноль в диагностике обязан уметь сказать, ноль ли это           #
# =============================================================== #


class TestSectionDistinguishesNoHubFromEmptyHub:
    """``counters`` секции ``observation`` отличает «писать некуда» от «записей не было».

    Найдено ревью 2026-08-25 запуском: ``observation_plane_report(svc)`` для
    процесса БЕЗ ``_observability_hub`` и для процесса С пустым хабом отдавал
    два байт-в-байт одинаковых ответа, оба ``{"records": 0, "dropped": 0}``.
    Оператор читает такой ноль как показание («механизм есть, записей не
    было»), тогда как это могло значить «механизма нет вовсе» — два разных
    факта одним числом, класс «ноль наблюдений выглядит как результат
    наблюдения».

    Довод, почему это дефект, а не вкус: соседняя секция ``history`` в ответе
    ТОЙ ЖЕ команды этот случай различает (``builtin_commands._history_report``
    отдаёт ``{"enabled": False, "reason": …}``). Две секции одного ответа,
    трактующие «механизма нет» противоположно, — это и был дефект.

    Инъекция, которая красит ЭТОТ тест: убрать ключ ``hub`` из ``counters``
    (предсказание записано до прогона — ровно 1 красный, приёмка зелёная,
    потому что её носитель хаба не имеет и ноль её устраивает).
    """

    def test_no_hub_and_empty_hub_are_two_different_answers(self) -> None:
        from ...process_module.managers.observability_wiring import observation_plane_report

        without_hub, port_a, _ = _wired(None)
        port_a.for_plugin("capture").publish("fps", 1.0)
        with_empty_hub, port_b, _ = _wired(ObservabilityHub("proc_empty", capacity=8))
        port_b.for_plugin("capture").publish("fps", 1.0)

        absent = observation_plane_report(without_hub)["observation"]["counters"]
        empty = observation_plane_report(with_empty_hub)["observation"]["counters"]

        # Оба показывают ноль записей — и это правда в обоих случаях.
        assert absent["records"] == 0 and empty["records"] == 0, (absent, empty)
        # Но ответы обязаны РАЗЛИЧАТЬСЯ: без этого ноль неотличим от показания.
        assert absent != empty, f"«хаба нет» и «хаб пуст» отвечают одинаково: {absent!r}"
        assert absent["hub"] is False, absent
        assert empty["hub"] is True, empty
        assert "reason" in absent, absent
        assert "reason" not in empty, empty


class TestHistoryRowsCountsTheWholeTable:
    """``history.rows`` считает ЧЕТЫРЕ рода, а не буквальную тройку.

    Найдено ревью 2026-08-25 на живом стенде: секция называла
    ``{"log": 16252, "error": 661, "stats": 1911}`` = 18 824, тогда как в том
    же файле лежало 18 938 строк — двадцать три ``observation`` не считал никто.

    Не косметика витрины: ``ObservabilityStore.purge`` режет по ``id`` БЕЗ
    разбора рода, бюджет ``max_rows`` общий на все роды и все процессы, и эта
    секция — единственное место, откуда оператор видит, кто его съедает.

    Инъекция, которая красит ЭТОТ тест: вернуть перечень в ``("log", "error",
    "stats")`` (предсказание до прогона — ровно 1 красный).
    """

    def test_rows_sum_equals_the_row_count_of_the_table(self, tmp_path) -> None:
        db_path = str(tmp_path / "history_rows_hazard.sqlite3")
        store = ObservabilityStore(db_path)
        try:
            hub = ObservabilityHub("proc_rows", capacity=16)
            hub.info("строка лога")
            hub.record_metric("fps", 1.0)
            hub.emit_observation_record({"writer": "capture", "metric": "fps", "value": 2.0})
            drained = hub.drain_all()
            store.append_records(drained["log"] + drained["stats"] + drained[KIND_OBSERVATION])

            services = _IntrospectServices()
            services._observability_store = store
            services._observability_history_policy = {"level": "INFO", "max_rows": 1000}
            report = BuiltinCommands(services)._history_report()["history"]

            rows = report["rows"]
            assert rows.get(KIND_OBSERVATION) == 1, f"род observation не считается вовсе: {rows!r}"
            # Сумма секции обязана совпасть с числом строк ТАБЛИЦЫ: литерал 3 —
            # ровно то, что мы положили (лог + метрика + уровень).
            assert sum(rows.values()) == 3, f"секция недосчитывает строки таблицы: {rows!r}"
        finally:
            store.close()
