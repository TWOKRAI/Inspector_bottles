# -*- coding: utf-8 -*-
"""Независимая приёмка (вслепую): порт наблюдений → записи в ObservabilityHub.

Задача: сегодня уровни, опубликованные через порт наблюдений
(``ObservationPort``/``ObservationManager``, Ф3.1, уже в репозитории), едут
РОВНО в одно место — дерево StateStore (``processes.<p>.state.plugins.<писатель>.<имя>``),
одним ``merge`` за тик ``ProcessHeartbeat``. Механизм, который эта приёмка
проверяет, ЕЩЁ НЕ СУЩЕСТВУЕТ: те же уровни должны ТАКЖЕ доехать записями в
``ObservabilityHub`` процесса под родом (``kind``), чей ЛИТЕРАЛ — строка
``"observation"`` (это прямо названо в задании и подтверждено докстрингом
``ObservationManager`` в репозитории: «...в который задача 3.2 понесёт записи
уровней (kind=observation)»). Плюс: ``introspect.observability`` обязана назвать
эту плоскость (секция + число писателей), БЕЗ регистрации новой команды.

Источник истины — семь пунктов приёмки (A1..A7) из задания, не код реализации:
реализации нет вовсе, чтения `_impl/` здесь не было.

**Техника анти-угадывания имени поля.** Форма записи (какие ключи несёт payload
кроме конвертных ``kind``/``module``/``ts``) — решение реализации, которого нет.
Поэтому опубликованные литералы (значение уровня, имя писателя, имя метрики)
проверяются ЧЛЕНСТВОМ в ``record.values()``, а не по конкретному имени ключа:
это не ослабляет проверку (буквальное значение по-прежнему требуется), но не
привязывает тест к угаданному имени поля.

**Реальные объекты, не фейки механизма.** ``ObservabilityHub``, ``ObservationPort``
/``ObservationManager``, ``ProcessHeartbeat`` — все настоящие, из репозитория.
Фейковые здесь только края, которых в юните нет по определению: ``StateProxy``
(IPC-хвост дерева) и минимальные носители ``services``/``CommandManager``.
"""

from __future__ import annotations

import pickle
from typing import Any, Dict, List, Optional, Tuple

from multiprocess_framework.modules.channel_routing_module.observability import ObservabilityHub
from multiprocess_framework.modules.process_module.heartbeat.process_heartbeat import ProcessHeartbeat
from multiprocess_framework.modules.statistics_module.observation.observation_manager import (
    ObservationManager,
    observation_port,
)


# ====================================================================== #
#  Минимальные носители края (StateProxy / services) — НЕ фейки механизма #
# ====================================================================== #


class _FakeStateProxy:
    """Хвост IPC до дерева StateStore — единственное, чего в юните нет по-настоящему."""

    def __init__(self) -> None:
        self.merged: List[Tuple[str, dict]] = []

    def merge(self, path: str, data: dict) -> None:
        self.merged.append((path, data))

    def delete(self, path: str) -> None:  # pragma: no cover — не задействуется без ушедших писателей
        pass


class _HeartbeatServices:
    """Минимальный НАСТОЯЩИЙ носитель IProcessServices для тика heartbeat.

    Порт наблюдений и hub — настоящие объекты репозитория; фейковый здесь только
    сам объект-держатель атрибутов и StateProxy (см. ``_FakeStateProxy``).
    """

    def __init__(self, *, hub: Optional[ObservabilityHub] = None, managers: Optional[Dict[str, Any]] = None) -> None:
        self.name = "proc_x"
        self._state_proxy = _FakeStateProxy()
        self.router_manager = None
        self.worker_manager = None
        self._observability_hub = hub
        self._managers = dict(managers or {})

    def get_config(self, key: str, default: Any = None) -> Any:
        return default

    def get_manager(self, slot: str) -> Any:
        return self._managers.get(slot)

    def log_debug(self, *a: Any, **k: Any) -> None:
        pass

    def log_info(self, *a: Any, **k: Any) -> None:
        pass


class _FakeCommandManager:
    """Минимальный CommandManager: хранит хендлеры, диспатчит по имени команды."""

    def __init__(self) -> None:
        self.handlers: Dict[str, Any] = {}

    def register_command(self, name: str, handler: Any, metadata: Any = None, tags: Any = None) -> None:
        self.handlers[name] = handler

    def get_commands(self) -> list:
        return [{"key": k} for k in self.handlers]


class _IntrospectServices:
    """Минимальный носитель для регистрации/вызова ``introspect.observability``."""

    def __init__(self) -> None:
        self.command_manager = _FakeCommandManager()
        self.name = "proc_intro"
        self._current_process_status = "running"

    def _log_info(self, *a: Any, **k: Any) -> None:
        pass

    def _log_debug(self, *a: Any, **k: Any) -> None:
        pass

    def _log_warning(self, *a: Any, **k: Any) -> None:
        pass


def _drain_observation_channel(hub: ObservabilityHub) -> List[dict]:
    """Достать записи рода ``observation`` из hub'а, если канал уже заведён.

    ``get_channel`` — существующий публичный метод ``ObservabilityHub``
    («прямой доступ к каналу по kind — для диагностики/тестов»), а не угаданное
    имя. Канала ``observation`` в hub'е СЕГОДНЯ нет (``_channels`` держит ровно
    log/error/stats) — ``KeyError`` здесь ожидаем и означает «механизма ещё нет»,
    переводится в пустой список, чтобы assert-сообщения были читаемы.
    """
    try:
        channel = hub.get_channel("observation")
    except KeyError:
        return []
    return channel.drain()


# ====================================================================== #
#  A1 — писатель ⇒ хотя бы одна запись, значение сверено с ЛИТЕРАЛОМ     #
# ====================================================================== #


class TestA1PublishProducesRecordWithLiteralValue:
    """A1: писатель, поднятый ЗДЕСЬ, публикует уровень — hub обязан получить ≥1 запись.

    Ноль записей = красный: «число названо» ложно удовлетворяется нулём.
    Слот ``observation`` — НАСТОЯЩИЙ ``ObservationManager`` (ладдер, ступень 1),
    не фолбэк по атрибуту: единственный тест сюиты на боевую дорогу регистрации.
    """

    def test_writer_via_real_slot_manager_produces_one_record_with_literal_value(self) -> None:
        hub = ObservabilityHub("proc_x", capacity=16)
        services = _HeartbeatServices(hub=hub)
        manager = ObservationManager(process=services)
        services._managers["observation"] = manager

        port = observation_port(services, create=True)
        assert port is manager, "ступень 1 ладдера обязана вернуть НАСТОЯЩИЙ менеджер из слота"
        port.for_plugin("capture").publish("fps", 30.0)

        heartbeat = ProcessHeartbeat(services)
        heartbeat._publish_telemetry_to_tree({}, None)

        records = _drain_observation_channel(hub)
        assert len(records) == 1, f"ожидалась ровно 1 запись, получено: {records!r}"
        assert 30.0 in records[0].values(), records[0]


# ====================================================================== #
#  A2 — та же дверь гейта, что и у листа дерева (парный контроль)         #
# ====================================================================== #


class TestA2RecordRidesTheSameGateAsTheTreeLeaf:
    """A2: гейт закрыт ⇒ 0 записей И нет листа; гейт открыт ⇒ ≥1 запись И лист есть.

    Обе половины ОБЯЗАНЫ жить в одном тесте: односторонняя проверка ничего не
    доказывает — «мёртвый hub» тоже даёт 0 записей независимо от гейта.
    """

    def test_paired_gate_closed_then_open(self) -> None:
        hub = ObservabilityHub("proc_gate", capacity=16)
        services = _HeartbeatServices(hub=hub)
        observation_port(services, create=True).for_plugin("capture").publish("fps", 20.0)
        heartbeat = ProcessHeartbeat(services)

        # Фаза 1: гейт закрыт для "fps" (allowed_metrics — пустое множество).
        heartbeat._publish_telemetry_to_tree({}, allowed_metrics=frozenset())
        assert _drain_observation_channel(hub) == [], "гейт закрыт, а запись всё равно ушла в hub"
        assert services._state_proxy.merged == [], "гейт закрыт, а лист всё равно ушёл в дерево"

        # Фаза 2: гейт открыт (allowed_metrics=None — «разрешено всё»).
        heartbeat._publish_telemetry_to_tree({}, allowed_metrics=None)
        records = _drain_observation_channel(hub)
        assert len(records) == 1, f"гейт открыт, ожидалась 1 запись: {records!r}"
        assert 20.0 in records[0].values(), records[0]

        leaf_in_tree = any(
            data.get("state", {}).get("plugins", {}).get("capture", {}).get("fps") == 20.0
            for _path, data in services._state_proxy.merged
        )
        assert leaf_in_tree, f"гейт открыт, а листа в дереве нет: {services._state_proxy.merged!r}"


# ====================================================================== #
#  A3 — одно событие = одна запись, через ≥2 тика                        #
# ====================================================================== #


class TestA3OneEventOneRecordAcrossTicks:
    """A3: тик republish'ит текущий снимок (как и лист дерева) — по ОДНОЙ записи за тик.

    Неизменное значение на двух тиках — по одной записи на каждый (не 0, не 2);
    изменённое значение между тиками отражается в записи СЛЕДУЮЩЕГО тика, а не
    задваивается со старым.
    """

    def test_unchanged_value_gives_exactly_one_record_on_each_of_two_ticks(self) -> None:
        hub = ObservabilityHub("proc_x3a", capacity=16)
        services = _HeartbeatServices(hub=hub)
        observation_port(services, create=True).for_plugin("capture").publish("fps", 5.0)
        heartbeat = ProcessHeartbeat(services)

        heartbeat._publish_telemetry_to_tree({}, None)
        tick1 = _drain_observation_channel(hub)
        assert len(tick1) == 1, f"тик 1: ожидалась ровно 1 запись, получено {tick1!r}"
        assert 5.0 in tick1[0].values(), tick1[0]

        heartbeat._publish_telemetry_to_tree({}, None)  # значение писатель НЕ менял
        tick2 = _drain_observation_channel(hub)
        assert len(tick2) == 1, f"тик 2 (значение не менялось): ожидалась ровно 1 запись, получено {tick2!r}"
        assert 5.0 in tick2[0].values(), tick2[0]

    def test_changed_value_between_ticks_shows_up_in_the_next_ticks_record_only(self) -> None:
        hub = ObservabilityHub("proc_x3b", capacity=16)
        services = _HeartbeatServices(hub=hub)
        handle = observation_port(services, create=True).for_plugin("capture")
        handle.publish("fps", 5.0)
        heartbeat = ProcessHeartbeat(services)

        heartbeat._publish_telemetry_to_tree({}, None)
        _drain_observation_channel(hub)  # тик 1 вычерпан — интересует только тик 2

        handle.publish("fps", 7.5)  # то же имя, тот же писатель, НОВОЕ значение
        heartbeat._publish_telemetry_to_tree({}, None)
        tick2 = _drain_observation_channel(hub)

        assert len(tick2) == 1, f"тик 2 после смены значения: ожидалась ровно 1 запись, получено {tick2!r}"
        assert 7.5 in tick2[0].values(), tick2[0]
        assert 5.0 not in tick2[0].values(), "старое значение задвоилось в записи следующего тика"


# ====================================================================== #
#  A4 — идентичность писателя/метрики как ДАННЫЕ + pickle-safe            #
# ====================================================================== #


class TestA4RecordCarriesIdentityAndIsPickleSafe:
    """A4: запись несёт имя писателя И имя метрики КАК ДАННЫЕ, и переживает pickle."""

    def test_record_contains_writer_and_metric_and_survives_pickle_roundtrip(self) -> None:
        hub = ObservabilityHub("proc_x4", capacity=16)
        services = _HeartbeatServices(hub=hub)
        observation_port(services, create=True).for_plugin("capture").publish("fps", 12.0)
        heartbeat = ProcessHeartbeat(services)
        heartbeat._publish_telemetry_to_tree({}, None)

        records = _drain_observation_channel(hub)
        assert len(records) == 1, records
        record = records[0]

        assert "capture" in record.values(), f"имя писателя не найдено как данные записи: {record!r}"
        assert "fps" in record.values(), f"имя метрики не найдено как данные записи: {record!r}"
        assert 12.0 in record.values(), record

        # Круговой pickle СВОЕГО ЖЕ dict'а, только что созданного в этом же процессе —
        # не десериализация недоверенных данных, а сама проверка Dict at Boundary.
        restored = pickle.loads(pickle.dumps(record))
        assert restored == record, "запись не пережила pickle.dumps/loads без изменений (Dict at Boundary)"


# ====================================================================== #
#  A5 — hub отсутствует: именованный no-op, лист всё равно доезжает      #
# ====================================================================== #


class TestA5HubAbsentIsANamedNoOp:
    """A5: без hub'а лист по-прежнему доезжает и ничего не падает.

    Якорь СУЩЕСТВОВАНИЯ обязателен (фаза 1: hub ЕСТЬ, запись обязана появиться) —
    иначе «ничего не падает» истинно и без единой строки механизма, потому что
    сегодня heartbeat вообще не трогает hub. Без фазы 1 фаза 2 не доказывает
    ничего про НАЗВАННЫЙ no-op — только про код, который hub не видит вовсе.
    """

    def test_hub_present_gets_a_record_hub_absent_still_reaches_the_tree_without_raising(self) -> None:
        # Фаза 1: с hub'ом — предпосылка, что механизм вообще запускается.
        hub = ObservabilityHub("proc_x5", capacity=16)
        services_with_hub = _HeartbeatServices(hub=hub)
        observation_port(services_with_hub, create=True).for_plugin("capture").publish("fps", 4.0)
        ProcessHeartbeat(services_with_hub)._publish_telemetry_to_tree({}, None)
        records = _drain_observation_channel(hub)
        assert len(records) == 1, (
            f"предпосылка A5 не выполнена: с hub'ом механизм обязан произвести запись, получено {records!r}"
        )

        # Фаза 2: без hub'а — лист всё равно доезжает, исключение не поднимается.
        services_no_hub = _HeartbeatServices(hub=None)
        observation_port(services_no_hub, create=True).for_plugin("capture").publish("fps", 4.0)
        ProcessHeartbeat(services_no_hub)._publish_telemetry_to_tree({}, None)  # не должно поднять

        leaf_in_tree = any(
            data.get("state", {}).get("plugins", {}).get("capture", {}).get("fps") == 4.0
            for _path, data in services_no_hub._state_proxy.merged
        )
        assert leaf_in_tree, f"без hub'а лист пропал из дерева: {services_no_hub._state_proxy.merged!r}"


# ====================================================================== #
#  A6 — introspect.observability называет плоскость, БЕЗ новой команды   #
# ====================================================================== #


class TestA6IntrospectNamesThePortWithoutANewCommand:
    """A6: секция плоскости наблюдений с числом писателей (≥1, привязано к живому писателю),
    и ни одна новая команда при этом не регистрируется."""

    def test_introspect_observability_names_the_plane_with_a_writer_count(self) -> None:
        from multiprocess_framework.modules.process_module.commands.builtin_commands import BuiltinCommands

        services = _IntrospectServices()
        BuiltinCommands(services)._register_introspect_commands()
        commands_before = set(services.command_manager.handlers)
        assert "introspect.observability" in commands_before

        observation_port(services, create=True).for_plugin("capture").publish("fps", 1.0)

        result = services.command_manager.handlers["introspect.observability"]()

        assert result["success"] is True, result
        assert "observation" in result, (
            f"ответ introspect.observability не содержит секции плоскости наблюдений: {sorted(result.keys())!r}"
        )
        section = result["observation"]
        writer_count = section.get("writers")
        assert isinstance(writer_count, int) and writer_count >= 1, (
            f"число писателей не названо или равно нулю при живом писателе: {section!r}"
        )

        commands_after = set(services.command_manager.handlers)
        assert commands_after == commands_before, (
            f"секция появилась ценой новой команды — этого требование запрещает: "
            f"новые={commands_after - commands_before!r}"
        )


# ====================================================================== #
#  A7 — верхняя граница стоимости: записей за тик ≤ метрики × писатели   #
# ====================================================================== #


class TestA7CostHasAnUpperBound:
    """A7: за тик — НЕ БОЛЬШЕ, чем (число метрик × число писателей) записей.

    Два писателя по две метрики каждый = 4 опубликованных листа. Проверка на
    равенство (не только "≤") — фан-аут обязан совпасть с числом листьев,
    а не плодить лишнее и не терять.
    """

    def test_two_writers_two_metrics_each_give_at_most_four_records(self) -> None:
        hub = ObservabilityHub("proc_x7", capacity=16)
        services = _HeartbeatServices(hub=hub)
        port = observation_port(services, create=True)
        port.for_plugin("capture").publish("fps", 10.0)
        port.for_plugin("capture").publish("latency_ms", 2.0)
        port.for_plugin("robot").publish("fps", 11.0)
        port.for_plugin("robot").publish("latency_ms", 3.0)

        heartbeat = ProcessHeartbeat(services)
        heartbeat._publish_telemetry_to_tree({}, None)

        records = _drain_observation_channel(hub)
        writers_x_metrics = 2 * 2
        assert len(records) <= writers_x_metrics, (
            f"фан-аут превысил границу writers×metrics={writers_x_metrics}: {len(records)} записей"
        )
        assert len(records) == 4, f"ожидалась запись на КАЖДЫЙ из 4 опубликованных листьев: {records!r}"
