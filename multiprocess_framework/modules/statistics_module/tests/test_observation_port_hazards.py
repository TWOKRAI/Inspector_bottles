# -*- coding: utf-8 -*-
"""Авторские hazard-тесты порта наблюдений (Ф3, задача 3.1).

**Что может сломаться в ЭТОМ механизме, учитывая, как он построен.** Приёмка
(``process_module/tests/test_observation_manager_slot_acceptance.py``, написана
вслепую и до реализации) сторожит КОНТРАКТ: один и тот же лист по обеим дорогам,
отсутствие менеджера не роняет плагина, слот виден рядом с тремя братьями,
heartbeat не держит копии. Здесь — опасности УСТРОЙСТВА, которых из критериев не
видно, потому что они следуют из трёх конкретных решений реализации:

1. **Хранилище резолвится на КАЖДОМ обращении, а не кэшируется** (``одна
   правда``: держатель — атрибут ``services.plugin_levels``). Отсюда классы:
   кэш, незаметно вернувшийся в ``__init__`` (:class:`TestResolveIsNotCached`);
   хендл, захвативший хранилище вместо порта (там же); ленивое создание
   локального хранилища ДВУМЯ потоками сразу (:class:`TestLocalStoreRace`).

2. **Дорога выбирается по состоянию слота, и состояние это меняется на ходу.**
   Слот регистрируется позже первых публикаций и может быть снят, перезаписан
   или занят посторонним объектом. Отсюда: снятие слота на полпути
   (:class:`TestSlotDisappearsMidFlight`), вторая регистрация
   (:class:`TestDoubleRegistration`), чужой объект под именем ``observation``
   (:class:`TestForeignObjectInSlot`).

3. **Порт встал МЕЖДУ двумя потоками, которые и раньше делили хранилище** —
   воркер плагина пишет, воркер heartbeat читает. Лок остался у хранилища, и
   порт обязан не увести читателя мимо него (:class:`TestConcurrentTickAndWriter`),
   а решение «телеметрия не критична для такта» обязано остаться у публикатора,
   а не расползтись в порт (:class:`TestBrokenPortDoesNotKillTheTick`).

Плюс два узла жизненного цикла, у которых до Ф3 не было владельца:
``shutdown`` менеджера НЕ обязан уносить состояние процесса
(:class:`TestLifecycleEdges`), а менеджер без держателя обслуживает своё
хранилище — названное расхождение, которое здесь ЗАФИКСИРОВАНО поведением, а не
обещано прозой (:class:`TestDetachedManagerDivergence`).

Потоки везде daemon с дедлайном на ``join``: тест, который вместо падения
ВИСНЕТ, хуже отсутствующего — он прячет регресс за таймаутом прогона.
"""

from __future__ import annotations

import threading
import time
from types import SimpleNamespace
from typing import Any

import pytest

from ...base_manager import ObservableMixin
from ...process_module.heartbeat import telemetry as _telemetry_mod
from ...process_module.heartbeat.process_heartbeat import ProcessHeartbeat
from ...process_module.heartbeat.telemetry import (
    PLUGIN_LEVELS_ATTR,
    PluginLevels,
    get_or_create_plugin_levels,
)
from ...process_module.plugins.base import PluginContext
from ..observation.observation_manager import (
    OBSERVATION_SLOT,
    ObservationManager,
    ObservationPort,
    observation_port,
)

#: Дедлайн join'а. Порядок «доли секунды», а не минуты: любая из проверок ниже
#: либо отвечает сразу, либо не ответит никогда.
JOIN_DEADLINE_SEC = 5.0


class _Host(ObservableMixin):
    """Сервисы процесса в объёме, который трогает порт.

    ``ObservableMixin`` подмешан НАСТОЯЩИЙ, а не самодельный dict-реестр: слот —
    это его реестр, и подделка реестра доказывала бы подделку.
    """

    def __init__(self, name: str = "camera_0") -> None:
        ObservableMixin.__init__(self)
        self.name = name
        self.worker_manager = None
        self.router_manager = None
        self.command_manager = None
        self.memory_manager = None
        self.warnings: list[str] = []

    def get_config(self, key: str, default: Any = None) -> Any:
        return default

    def log_debug(self, *a, **k) -> None: ...
    def log_info(self, *a, **k) -> None: ...

    def log_warning(self, message: str = "", *a, **k) -> None:
        self.warnings.append(str(message))

    def log_error(self, *a, **k) -> None: ...
    def log_critical(self, *a, **k) -> None: ...


def _registered_manager(host: _Host, name: str = "observation_camera_0") -> ObservationManager:
    """Менеджер, поднятый и положенный в слот, — как это делает ``register_all``."""
    manager = ObservationManager(manager_name=name, process=host)
    manager.initialize()
    host.register_manager(OBSERVATION_SLOT, manager, enabled=True)
    return manager


def _run_in_daemons(target, count: int) -> None:
    """Запустить ``count`` демонов и дождаться их с дедлайном.

    Живой поток после дедлайна — ОТКАЗ теста, а не «подождём ещё»: механизм,
    который здесь блокируется, обязан быть виден как красный, а не как долгий.
    """
    threads = [threading.Thread(target=target, daemon=True) for _ in range(count)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(JOIN_DEADLINE_SEC)
    alive = [t.name for t in threads if t.is_alive()]
    assert not alive, f"потоки не завершились за {JOIN_DEADLINE_SEC} с: {alive}"


# --------------------------------------------------------------------------- #
# 1. Резолв не кэшируется
# --------------------------------------------------------------------------- #


class TestResolveIsNotCached:
    """``levels()`` обязан спрашивать держателя КАЖДЫЙ раз, а не помнить ответ.

    Кэш в конструкторе — самая дешёвая «оптимизация», которую сюда внесут: одна
    строка, все тесты приёмки зелёные, и ровно один класс отказов, который она
    рождает, — два расходящихся ответа на «сколько сейчас». Расхождение
    молчаливое: обе стороны отвечают числом, просто разным.
    """

    def test_store_swapped_on_the_host_is_seen_by_the_port(self) -> None:
        """Ломается, если порт запомнил ссылку на хранилище (в ``__init__`` или
        первым обращением): после подмены атрибута он продолжил бы отвечать из
        старого хранилища, а прямой читатель — из нового."""
        host = _Host()
        manager = _registered_manager(host)

        manager.publish("fps", 1.0, "P")
        assert manager.publications() == {"P": {"fps": 1.0}}

        fresh = PluginLevels()
        fresh.publish("fps", 2.0, "P")
        setattr(host, PLUGIN_LEVELS_ATTR, fresh)

        assert manager.levels() is fresh, "порт отвечает из хранилища, которого на процессе уже нет"
        assert manager.publications() == {"P": {"fps": 2.0}}

    def test_a_handle_taken_before_the_swap_writes_into_the_new_store(self) -> None:
        """Хендл обязан делегировать в ПОРТ, а не держать хранилище.

        Ломается, если ``for_plugin`` захватит ``levels()`` в момент создания:
        хендл, взятый в ``configure()`` плагина и переживший подмену/пересоздание
        хранилища, писал бы в объект, которого никто не читает, — публикации
        исчезали бы, а вызов возвращал бы то же самое, что и на здоровом пути.
        """
        host = _Host()
        manager = _registered_manager(host)
        handle = manager.for_plugin("capture")
        handle.publish("fps", 10.0)

        fresh = PluginLevels()
        setattr(host, PLUGIN_LEVELS_ATTR, fresh)

        handle.publish("fps", 20.0)

        assert fresh.publications() == {"capture": {"fps": 20.0}}, (
            "публикация старым хендлом не доехала до текущего хранилища процесса"
        )


# --------------------------------------------------------------------------- #
# 2. Ленивое локальное хранилище и гонка первого доступа
# --------------------------------------------------------------------------- #


class TestLocalStoreRace:
    """Локальное хранилище создаётся ЛЕНИВО — значит есть окно первого доступа."""

    def test_first_access_from_four_threads_yields_exactly_one_store(self, monkeypatch) -> None:
        """Ломается, если снять лок в ``ObservationManager.levels``.

        Окно расширено НАМЕРЕННО (``PluginLevels.__init__`` со сном), а не
        оставлено на удачу планировщика: под GIL 3.12 три строки без сна почти
        не дают вклиниться, и «шторм потоков» зелёный без лока — то есть
        доказывал бы не лок, а расписание. Со сном окно шире планировщика, и
        версия без лока отдаёт четыре РАЗНЫХ хранилища.

        Цена расхождения, если бы оно проехало: половина публикаций легла бы в
        экземпляр, которого никто не читает, — без исключения и без голоса.
        """

        class SlowLevels(PluginLevels):
            def __init__(self) -> None:
                time.sleep(0.05)
                super().__init__()

        monkeypatch.setattr(_telemetry_mod, "PluginLevels", SlowLevels)

        # process=None — ветка локального хранилища (держателя нет вовсе).
        manager = ObservationManager(manager_name="observation_race")
        manager.initialize()

        seen: list[Any] = []
        seen_lock = threading.Lock()
        gate = threading.Barrier(4, timeout=JOIN_DEADLINE_SEC)

        def probe() -> None:
            gate.wait()
            # ``create=True`` — дорога ПИСАТЕЛЯ: только она заводит хранилище, и
            # только на ней есть гонка первого создания. Читательский
            # ``levels()`` вернул бы четыре ``None``, и «одно хранилище на всех»
            # выполнилось бы тождеством ``id(None) == id(None)`` — сторож,
            # зелёный и без лока, и без хранилища вовсе.
            store = manager.levels(create=True)
            with seen_lock:
                seen.append(store)

        _run_in_daemons(probe, 4)

        assert len(seen) == 4, f"не все пробы отчитались: {len(seen)}"
        assert all(isinstance(store, PluginLevels) for store in seen), (
            f"проба получила не хранилище: {[type(s).__name__ for s in seen]}"
        )
        assert len({id(store) for store in seen}) == 1, (
            f"первый доступ из четырёх потоков породил {len({id(s) for s in seen})} хранилищ вместо одного"
        )

    def test_local_store_keeps_what_was_published_into_it(self) -> None:
        """Контроль к тесту выше: локальная ветка — рабочее хранилище, а не заглушка.

        Без него «одно хранилище» удовлетворялось бы и версией, которая
        возвращает один и тот же пустой объект, ничего не запоминающий.
        """
        manager = ObservationManager(manager_name="observation_detached")
        manager.initialize()
        manager.for_plugin("P").publish("fps", 7.0)
        assert manager.publications() == {"P": {"fps": 7.0}}
        assert manager.collect_subtree() == {"plugins": {"P": {"fps": 7.0}}}


# --------------------------------------------------------------------------- #
# 3. Слот меняется на ходу
# --------------------------------------------------------------------------- #


class TestSlotDisappearsMidFlight:
    """Слот регистрируется позже публикаций и может быть снят посреди работы."""

    def test_unregistering_the_slot_keeps_the_same_store(self) -> None:
        """Ломается, если менеджер держит СВОЁ хранилище при живом держателе:
        снятие слота (``unregister_manager``) обнулило бы показания процесса,
        хотя ни один плагин ничего не снимал. Сегодня резолвер проваливается на
        вид над тем же атрибутом — и значение остаётся на месте."""
        host = _Host()
        manager = _registered_manager(host)
        manager.for_plugin("P").publish("fps", 42.0)

        before = observation_port(host)
        assert before is manager, "предпосылка: пока слот есть, дорога идёт через менеджер"

        host.unregister_manager(OBSERVATION_SLOT)

        after = observation_port(host)
        assert after is not None, "снятие слота увело читателя в пустоту"
        assert isinstance(after, ObservationPort) and not isinstance(after, ObservationManager)
        assert after.publications() == {"P": {"fps": 42.0}}, (
            "значение исчезло вместе со слотом — порт держал собственное хранилище"
        )
        assert after.levels() is get_or_create_plugin_levels(host)

    def test_slot_appearing_between_two_publications_does_not_fork_the_state(self) -> None:
        """Порядок «публикация → регистрация → публикация» на ОДНОМ писателе.

        Ломается, если менеджер начинает с чистого листа: первое значение стало
        бы невидимым ровно в момент, когда процесс дошёл до ``register_all``, —
        то есть на каждом боевом старте, и только для метрик, отданных из
        ``configure()``.
        """
        host = _Host()
        ctx = PluginContext(services=host, plugin_name="P")

        ctx.publish_metric("early", 1.0)  # раньше start(), слота ещё нет
        _registered_manager(host)
        ctx.publish_metric("late", 2.0)

        assert get_or_create_plugin_levels(host).publications() == {"P": {"early": 1.0, "late": 2.0}}


class TestDoubleRegistration:
    """Второй менеджер в тот же слот — не второе состояние."""

    def test_two_managers_over_one_host_share_the_state(self) -> None:
        """Ломается, если хранилище принадлежит менеджеру: перерегистрация
        (пересборка процесса, hot-reload, тест, поднявший второй менеджер) дала
        бы двух держателей, и «сколько сейчас» зависело бы от того, кого
        спросили."""
        host = _Host()
        first = _registered_manager(host, name="observation_first")
        first.for_plugin("P").publish("fps", 3.0)

        second = _registered_manager(host, name="observation_second")

        assert host.get_manager(OBSERVATION_SLOT) is second, "предпосылка: в слоте второй менеджер"
        assert second.publications() == {"P": {"fps": 3.0}}, "второй менеджер не видит того, что писали в первый"

        second.for_plugin("P").publish("fps", 4.0)
        assert first.publications() == {"P": {"fps": 4.0}}, "первый менеджер отстал — состояние раздвоилось"
        assert first.levels() is second.levels()


class TestForeignObjectInSlot:
    """Под именем ``observation`` может оказаться что угодно."""

    def test_a_sentinel_in_the_slot_does_not_hijack_the_road(self) -> None:
        """Резолвер принимает слот ПО ПРОТОКОЛУ (вызываемый ``collect_subtree``).

        Ломается, если проверку протокола снять: посторонний объект (ровно такой
        сентинел кладёт в слот тест проводки ``register_all``) уехал бы наружу
        как порт, и первый же ``collect_subtree`` на тике упал бы
        ``AttributeError`` — то есть отказ проводки маскировался бы под отказ
        телеметрии, в другом файле и на другом такте.
        """
        host = _Host()
        get_or_create_plugin_levels(host).publish("fps", 5.0, "P")
        host.register_manager(OBSERVATION_SLOT, object(), enabled=True)

        port = observation_port(host)

        assert port is not None
        assert isinstance(port, ObservationPort), "посторонний объект из слота уехал наружу как порт"
        assert port.publications() == {"P": {"fps": 5.0}}

    def test_a_none_in_the_slot_falls_through_to_the_store(self) -> None:
        """``register_all`` кладёт в слот и ``None`` — bundle, собранный вручную
        без поля ``observation`` (тесты соседних модулей). Ломается, если
        резолвер вернёт этот ``None`` как «порта нет» при живом хранилище."""
        host = _Host()
        get_or_create_plugin_levels(host).publish("fps", 6.0, "P")
        host.register_manager(OBSERVATION_SLOT, None, enabled=True)

        port = observation_port(host)

        assert port is not None, "None в слоте отменил уровни, которые лежат в хранилище"
        assert port.publications() == {"P": {"fps": 6.0}}


# --------------------------------------------------------------------------- #
# 4. Флаг create
# --------------------------------------------------------------------------- #


class TestCreateFlagIsNotDecoration:
    """``create`` разделяет читателя и писателя, и разница наблюдаема.

    **Читательская половина спрашивает через настоящий ``ProcessHeartbeat``, а
    не через резолвер напрямую, и это ремонт по ревью 2026-08-25.** Прежняя
    редакция звала ``observation_port(host)`` по хосту БЕЗ слота — то есть
    проверяла ступень 2 резолвера, а не читателя. Заплата, которую сторож обязан
    был ловить (``observation_port(services, create=True)`` в
    ``process_heartbeat.py``), не задевала его вовсе: он этой строки не
    исполнял. Красный, которым тогда отчитались, был получен ДРУГОЙ заплатой —
    переворотом дефолта в сигнатуре, — то есть инъекцией тем же объективом, что
    и сам тест.

    Два теста, и первый второго не заменяет: заводить хранилище можно с ДВУХ
    сторон, и каждая живёт на своей раскладке.

    * слот ЗАРЕГИСТРИРОВАН (боевая сборка) — резолвер отдаёт менеджера первой же
      ступенью, и создаёт или нет уже он, своим ``levels(create=…)``;
    * слота НЕТ (публикация из ``configure()``, дубли сервисов) — решает сам
      резолвер, ступенью 2.

    Заплата в одной стороне другую не красит, поэтому сторожей тоже двое.
    """

    @staticmethod
    def _ask_the_reader_questions(host: _Host) -> None:
        """Три вопроса тика — теми же методами, которыми их задаёт heartbeat.

        Не ``observation_port(host)``: точка наблюдения обязана отличаться от
        точки инъекции, иначе красный доказывает согласие двух копий одной
        модели. Заплата ставится в ``_observation_port_of`` и в ``levels`` — и
        обе лежат ПОД этими тремя вызовами, а не рядом с ними.
        """
        hb = ProcessHeartbeat(host)
        proxy = SimpleNamespace(delete=lambda path: (_ for _ in ()).throw(AssertionError("нечего снимать")))
        hb._level_names()
        hb._collect_plugin_levels()
        hb._delete_departed_subtrees(proxy)

    def test_reader_does_not_create_the_store_with_the_slot_registered(self) -> None:
        """БОЕВАЯ раскладка: слот зарегистрирован, тик прошёл, хранилища нет.

        Ломается, если хоть одна читательская дорога порта позовёт
        ``levels(create=True)``: у процесса без единой публикации появился бы
        пустой ``plugin_levels``, и «атрибута нет» (плагины уровней не отдавали)
        перестало бы отличаться от «атрибут пуст» (отдавали, но всё сняли или
        придержал гейт) — различие, по которому этот атрибут и читают.

        Это ровно тот дефект, который ревью воспроизвело на настоящем
        ``ProcessModule``: после ``initialize()`` — ``None``, после ОДНОГО
        ``_level_names()`` — готовый ``PluginLevels``.
        """
        host = _Host()
        _registered_manager(host)
        assert getattr(host, PLUGIN_LEVELS_ATTR, None) is None, "предпосылка: хранилища нет"

        self._ask_the_reader_questions(host)

        assert getattr(host, PLUGIN_LEVELS_ATTR, None) is None, (
            "тик завёл хранилище при зарегистрированном слоте — create=False соблюдается только там, где порта нет"
        )

    def test_reader_does_not_create_the_store_without_the_slot(self) -> None:
        """Вторая сторона: слота нет, решает резолвер.

        Ломается, если ``_observation_port_of`` начнёт звать резолвер с
        ``create=True`` — заплата, на которую прежняя редакция этого класса была
        слепа.
        """
        host = _Host()
        assert host.get_manager(OBSERVATION_SLOT) is None, "предпосылка: слота нет"
        assert getattr(host, PLUGIN_LEVELS_ATTR, None) is None, "предпосылка: хранилища нет"

        self._ask_the_reader_questions(host)

        assert getattr(host, PLUGIN_LEVELS_ATTR, None) is None, "читатель завёл хранилище"

    def test_writer_creates_the_store_without_the_slot(self) -> None:
        """Пара-контроль: без него «не создаёт» удовлетворялось бы версией,
        которая не создаёт НИКОГДА, — то есть публикация из ``configure()``
        исчезала бы молча."""
        host = _Host()
        port = observation_port(host, create=True)

        assert port is not None
        assert isinstance(getattr(host, PLUGIN_LEVELS_ATTR, None), PluginLevels)

    def test_writer_creates_the_store_with_the_slot_registered(self) -> None:
        """Пара-контроль на БОЕВОЙ раскладке — там же, где живёт первый тест.

        Без него читательский сторож удовлетворялся бы менеджером, который не
        заводит хранилище никогда: публикация ушла бы в никуда, а тик отдавал бы
        пустоту — и оба теста остались бы зелёными.
        """
        host = _Host()
        _registered_manager(host)
        assert getattr(host, PLUGIN_LEVELS_ATTR, None) is None, "предпосылка: хранилища нет"

        PluginContext(services=host, plugin_name="P").publish_metric("fps", 44.0)

        store = getattr(host, PLUGIN_LEVELS_ATTR, None)
        assert isinstance(store, PluginLevels), "публикация через слот не завела хранилище процесса"
        assert store.publications() == {"P": {"fps": 44.0}}

    def test_readers_return_an_empty_projection_when_there_is_no_store(self) -> None:
        """Цена ``create=False``: читатель обязан пережить ОТСУТСТВИЕ хранилища.

        ``levels()`` теперь может вернуть ``None``, и каждая читательская дорога
        отвечает пустой проекцией СВОЕЙ формы — множество, dict, кортеж, no-op.
        Отказ здесь означал бы, что тик процесса без плагинов падает по штатной
        конфигурации.

        Спрашивается У ПОРТА НАПРЯМУЮ, а не через heartbeat, и это существенно:
        у тика стоит собственный предохранитель («телеметрия не критична для
        такта»), который проглотил бы ``AttributeError: 'NoneType' …`` и вернул
        ту же пустоту. Сквозь него отсутствие guard'а не видно вовсе — свойство
        проверяется там, где оно живёт.
        """
        host = _Host()
        manager = _registered_manager(host)
        assert getattr(host, PLUGIN_LEVELS_ATTR, None) is None, "предпосылка: хранилища нет"
        assert manager.levels() is None, "предпосылка: резолв читателя отдаёт «показаний нет»"

        assert manager.level_names() == set()
        assert manager.collect_subtree() == {}
        assert manager.publications() == {}
        assert manager.departed_writers() == ()
        manager.note_delete_delivered("P")  # no-op, не отказ

        assert getattr(host, PLUGIN_LEVELS_ATTR, None) is None, "читательский вопрос завёл хранилище"

    def test_retraction_does_not_create_the_store(self) -> None:
        """Снятие — дорога пишущая, но ``create=False``, и вот почему.

        ``PluginContext._retract_metrics`` резолвит порт с ``create=False``.
        Заведи снятие хранилище на стороне менеджера — остановка плагина, ни
        разу ничего не опубликовавшего, оставляла бы пустой ``plugin_levels``
        ПРИ слоте и не оставляла бы БЕЗ него: один сценарий, два разных следа.
        Ровно то, что запрещает приёмочный П1 «маршрут не меняет наблюдаемое».

        Ломается, если ``ObservationPort.retract`` позовёт ``levels(create=True)``.
        """
        host = _Host()
        _registered_manager(host)
        ctx = PluginContext(services=host, plugin_name="P")

        assert ctx._retract_metrics() == 0, "снятие с пустого места отчиталось не нулём"
        assert getattr(host, PLUGIN_LEVELS_ATTR, None) is None, "снятие завело хранилище"


# --------------------------------------------------------------------------- #
# 5. Два потока вокруг одного хранилища
# --------------------------------------------------------------------------- #


class TestConcurrentTickAndWriter:
    """Порт встал между потоком воркера и потоком heartbeat."""

    def test_collect_subtree_hands_the_projector_a_copy(self, monkeypatch) -> None:
        """Ломается, если порт начнёт отдавать проектору ВНУТРЕННОСТИ хранилища
        (``levels()._values`` вместо ``levels().publications()``) — ради экономии
        копии. Симптом в проде: ``RuntimeError: dictionary changed size during
        iteration`` на тике, редкий и не воспроизводимый по требованию.

        **Взаимодействие двух потоков здесь сыграно ДЕТЕРМИНИРОВАННО, а не
        штормом.** Проектор подменён на такой, который вклинивается ровно
        посреди обхода того, что ему дали: растит хранилище, пока итерирует
        полученный объект. Дали копию — обход проходит; дали живой словарь —
        ``RuntimeError`` на первой же вставке. Планировщик в ответе не участвует
        вовсе, и красный воспроизводится каждым прогоном, а не одним из
        двадцати. Измерено: потоковая редакция этого теста (шторм из писателя и
        читателя) под ровно этой заплатой оставалась ЗЕЛЁНОЙ — то есть
        сторожила расписание, а не свойство.

        Подмена проектора по ИМЕНИ — это точка вклинивания, а не утверждение о
        нём: ``called`` сторожит, что подмена вообще сработала, иначе
        переименование проектора сделало бы тест вакуумным.
        """
        host = _Host()
        manager = _registered_manager(host)
        for i in range(5):
            manager.publish("fps", float(i), f"w{i}")

        real = _telemetry_mod.build_plugin_levels
        called = [0]

        def wedging_projector(levels: Any, allowed_metrics: Any = None) -> dict:
            called[0] += 1
            for writer in levels:
                # Второй поток «пишет» ровно во время обхода. Лок хранилища
                # берётся внутри publish — свой мы не держим, взаимной
                # блокировки здесь нет.
                manager.levels().publish("late", 1.0, f"late_{writer}")
            return real(levels, allowed_metrics)

        monkeypatch.setattr(_telemetry_mod, "build_plugin_levels", wedging_projector)

        result = manager.collect_subtree()

        assert called[0] == 1, "проектор не был вызван — подмена не сработала, тест ничего не проверил"
        assert "w0" in result["plugins"], f"проекция потеряла писателя: {result!r}"

    def test_two_threads_through_the_port_do_not_break_each_other(self) -> None:
        """Смоук на два потока: порт не завёл собственной небезопасной бухгалтерии.

        **Что этот тест НЕ ловит, сказано прямо:** заплату «отдать проектору
        живой словарь» он оставляет зелёной (измерено на матрице инъекций Ф3) —
        под GIL писатель и читатель успевают разойтись. Её сторожит тест выше.
        Здесь сторожится другое и более широкое: что у порта нет СВОЕГО
        состояния, которое два потока могли бы порвать, — сегодня его нет, и
        появление такого состояния (счётчик публикаций, кэш имён, буфер записей
        3.2) этот тест увидит.

        Утверждение — про отсутствие исключения в потоках, а не про число
        проходов: счёт итераций мерил бы планировщик.
        """
        host = _Host()
        manager = _registered_manager(host)
        stop = threading.Event()
        errors: list[BaseException] = []
        reads = [0]

        def writer() -> None:
            try:
                i = 0
                while not stop.is_set() and i < 4000:
                    manager.publish(f"m{i}", float(i), f"w{i % 17}")
                    i += 1
            except BaseException as exc:  # noqa: BLE001 — ловим ВСЁ: тест про отказ потока
                errors.append(exc)

        def reader() -> None:
            try:
                while not stop.is_set() and reads[0] < 400:
                    manager.collect_subtree()
                    manager.level_names()
                    reads[0] += 1
            except BaseException as exc:  # noqa: BLE001
                errors.append(exc)

        threads = [
            threading.Thread(target=writer, daemon=True),
            threading.Thread(target=reader, daemon=True),
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join(JOIN_DEADLINE_SEC)
        stop.set()
        alive = [t.name for t in threads if t.is_alive()]

        assert not alive, f"потоки не завершились за {JOIN_DEADLINE_SEC} с: {alive}"
        assert not errors, f"порт уронил поток: {errors!r}"
        # Якорь существования: проверка что-то намерила, а не выродилась в ноль
        # проходов («ноль наблюдений — не результат наблюдения»).
        assert reads[0] > 0, "читатель не сделал ни одного прохода — тест ничего не проверил"
        assert manager.publications(), "писатель не оставил ни одной записи"


# --------------------------------------------------------------------------- #
# 6. Отказ порта не решает за публикатора
# --------------------------------------------------------------------------- #


class _BrokenPort:
    """Порт по протоколу, падающий на каждом вопросе."""

    def collect_subtree(self, allowed_metrics: Any = None) -> dict:
        raise RuntimeError("хранилище отказало")

    def level_names(self) -> set:
        raise RuntimeError("хранилище отказало")

    def departed_writers(self) -> tuple:
        raise RuntimeError("хранилище отказало")

    def note_delete_delivered(self, writer: str) -> None:  # pragma: no cover — сюда не доходит
        raise AssertionError("не должно быть вызвано")


class TestBrokenPortDoesNotKillTheTick:
    """Решение «телеметрия не критична для такта» осталось у публикатора.

    Ф3 передвинула шов: раньше heartbeat сам доставал хранилище и сам ловил его
    отказ. Теперь достаёт порт — и заманчиво поставить ``try/except`` внутри
    порта «чтобы наверняка». Тогда предохранителей стало бы ДВА, а отказ
    хранилища не увидел бы никто: порт вернул бы пустоту, публикатор счёл бы её
    штатной, и симптом («метрики пропали») искали бы в плагине.

    Здесь сторожится внешняя половина: отказ порта не выносится наружу тика.
    Внутренняя (порт НЕ глушит) сторожится тем, что ``_BrokenPort`` виден как
    отказ именно публикатору — если бы порт глушил, ``_collect_plugin_levels``
    вернул бы пустоту и без исключения, и этот тест остался бы зелёным, а вот
    ``test_port_itself_does_not_swallow`` ниже покраснел бы.
    """

    def _carrier(self, host: _Host) -> Any:
        return SimpleNamespace(_services=host)

    def test_collect_survives_a_broken_port(self) -> None:
        host = _Host()
        host.register_manager(OBSERVATION_SLOT, _BrokenPort(), enabled=True)

        assert ProcessHeartbeat._collect_plugin_levels(self._carrier(host)) == {}

    def test_level_names_survive_a_broken_port(self) -> None:
        host = _Host()
        host.register_manager(OBSERVATION_SLOT, _BrokenPort(), enabled=True)

        assert ProcessHeartbeat._level_names(self._carrier(host)) == set()

    def test_departed_step_survives_a_broken_port(self) -> None:
        host = _Host()
        host.register_manager(OBSERVATION_SLOT, _BrokenPort(), enabled=True)
        proxy = SimpleNamespace(delete=lambda path: (_ for _ in ()).throw(AssertionError("не должно быть вызвано")))

        ProcessHeartbeat._delete_departed_subtrees(self._carrier(host), proxy)

    def test_port_itself_does_not_swallow(self) -> None:
        """Вторая половина: настоящий порт над отказавшим хранилищем ПРОПУСКАЕТ
        исключение. Ломается, если в порт добавят собственный ``try/except``.

        Дубль отказывает по ОБОИМ сегодняшним именам — и по ``publications()``,
        и по ``_values``. Не для полноты: без второго имени этот тест краснел бы
        на заплате «проектор получает живой словарь» (``AttributeError`` вместо
        ``RuntimeError``), то есть приписывал бы чужой инъекции свой красный —
        а вина досталась бы не тому месту.
        """

        class _BrokenStore:
            @property
            def _values(self) -> dict:
                raise RuntimeError("хранилище отказало")

            def publications(self) -> dict:
                raise RuntimeError("хранилище отказало")

        port = ObservationPort(_BrokenStore())

        with pytest.raises(RuntimeError):
            port.collect_subtree()


# --------------------------------------------------------------------------- #
# 7. Жизненный цикл
# --------------------------------------------------------------------------- #


class TestLifecycleEdges:
    """Узлы, у которых до Ф3 не было владельца."""

    def test_shutdown_without_initialize_is_not_a_failure(self) -> None:
        """Порядок ``shutdown`` без ``initialize`` штатен: сборка процесса
        падает между созданием менеджеров и их подъёмом, и уборка проходит по
        всем слотам подряд. Ломается, если менеджер начнёт что-то предполагать о
        том, что ``initialize`` уже был."""
        manager = ObservationManager(manager_name="observation_cold")
        assert manager.is_initialized is False
        assert manager.shutdown() is True
        assert manager.is_initialized is False

    def test_shutdown_is_idempotent(self) -> None:
        manager = ObservationManager(manager_name="observation_twice")
        manager.initialize()
        assert manager.shutdown() is True
        assert manager.shutdown() is True
        assert manager.is_initialized is False

    def test_shutdown_does_not_take_the_process_state_with_it(self) -> None:
        """Состояние уровней принадлежит ПРОЦЕССУ, а не менеджеру.

        Ломается, если ``shutdown`` начнёт чистить хранилище «за собой»: тик
        heartbeat живёт своим воркером и на teardown ещё идёт, поэтому последние
        показания исчезли бы ровно в тот момент, когда по ним разбирают, как
        процесс завершался.
        """
        host = _Host()
        manager = _registered_manager(host)
        manager.for_plugin("P").publish("fps", 8.0)

        assert manager.shutdown() is True

        assert get_or_create_plugin_levels(host).publications() == {"P": {"fps": 8.0}}
        # И порт после shutdown остаётся дорогой к тому же хранилищу: слот
        # снимают не здесь, а heartbeat может спросить ещё раз.
        assert observation_port(host).publications() == {"P": {"fps": 8.0}}


# --------------------------------------------------------------------------- #
# 8. Названное расхождение
# --------------------------------------------------------------------------- #


class TestDetachedManagerDivergence:
    """Менеджер без держателя, положенный в чужой слот, обслуживает СВОЁ хранилище.

    В сборке это не достижимо (``_create_observation_manager`` всегда передаёт
    процесс), поэтому отказом не оформлено. Но описанным в докстринге оно
    остаётся ровно до тех пор, пока никто не проверял; здесь оно ЗАФИКСИРОВАНО
    поведением — и если завтра кто-то решит, что порт обязан подхватывать
    держателя из слота, этот тест скажет, что поведение поменялось, а не оставит
    расхождение всплывать на стенде.
    """

    def test_publication_through_a_detached_manager_is_invisible_to_the_lazy_fallback(self) -> None:
        host = _Host()
        detached = ObservationManager(manager_name="observation_detached")  # process=None
        detached.initialize()
        host.register_manager(OBSERVATION_SLOT, detached, enabled=True)

        detached.for_plugin("P").publish("fps", 9.0)

        assert detached.publications() == {"P": {"fps": 9.0}}, "порт не видит собственной публикации"
        assert getattr(host, PLUGIN_LEVELS_ATTR, None) is None, (
            "менеджер без держателя всё-таки завёл хранилище на чужих сервисах — "
            "поведение изменилось, докстринг устарел"
        )


# --------------------------------------------------------------------------- #
# 9. Три дороги контекста называют ОДИН сегмент пути
# --------------------------------------------------------------------------- #


class TestWriterSegmentIsOneAcrossRoads:
    """Публикация и снятие обязаны прийти в один и тот же порт и к одному писателю.

    До Ф3 снятие ходило сырым ``getattr``, а публикация — через
    ``get_or_create_plugin_levels``; обе упирались в один атрибут, и разойтись им
    было негде. Ф3 развела маршруты (слот против фолбэка) — и снятие, оставленное
    на сыром пути, чистило бы хранилище, в которое никто не писал.

    **Два теста, и первый второго не заменяет.** На обычном держателе обе дороги
    сходятся в один атрибут, поэтому там разъезд МАРШРУТОВ не наблюдаем — виден
    только разъезд СЕГМЕНТА (сняли не того писателя). Разъезд маршрутов виден
    ровно там, где маршруты ведут в разные места: у порта, чьё хранилище не лежит
    на держателе. Первая редакция этого класса имела только тест на обычном
    держателе и обещала в докстринге ловить оба — обещание было ложным, тест
    оставался бы зелёным при откате снятия на сырой ``getattr``.
    """

    def test_publish_through_the_slot_is_retracted_for_the_right_writer(self) -> None:
        """Сегмент пути: снимается СВОЙ писатель, сосед под тем же именем цел."""
        host = _Host()
        manager = _registered_manager(host)
        ctx = PluginContext(services=host, plugin_name="P")
        neighbour = PluginContext(services=host, plugin_name="Q")

        ctx.publish_metric("fps", 11.0)
        neighbour.publish_metric("fps", 22.0)
        assert manager.publications() == {"P": {"fps": 11.0}, "Q": {"fps": 22.0}}

        assert ctx._retract_metrics() == 1

        assert manager.publications() == {"Q": {"fps": 22.0}}, "снятие ушло не к тому писателю"

    def test_retract_reaches_the_same_port_as_publish(self) -> None:
        """Маршрут: снятие идёт ТУДА ЖЕ, куда ушла публикация.

        Различающая конструкция — порт, чьё хранилище НЕ лежит на держателе
        (менеджер без ``process``, см. :class:`TestDetachedManagerDivergence`).
        Публикация через слот попадает в его хранилище; снятие через слот —
        оттуда же. Верни снятие на сырой ``getattr(services, PLUGIN_LEVELS_ATTR)``
        — и оно не найдёт ничего (атрибута на держателе нет), вернёт ``0``, а
        уровень остановленного плагина продолжит ехать в дерево.
        """
        host = _Host()
        detached = ObservationManager(manager_name="observation_detached")  # process=None
        detached.initialize()
        host.register_manager(OBSERVATION_SLOT, detached, enabled=True)
        ctx = PluginContext(services=host, plugin_name="P")

        ctx.publish_metric("fps", 33.0)
        assert detached.publications() == {"P": {"fps": 33.0}}, "предпосылка: публикация ушла в порт слота"
        assert getattr(host, PLUGIN_LEVELS_ATTR, None) is None, "предпосылка: на держателе хранилища нет"

        assert ctx._retract_metrics() == 1, "снятие не нашло того, что опубликовала публикация"
        assert detached.publications() == {}, "снятие ушло мимо порта, в который писала публикация"

    def test_declare_through_the_slot_lands_in_the_shared_catalogue(self) -> None:
        """Объявление через порт и напрямую — один каталог.

        Ломается, если порт заведёт свой каталог имён: гейт публикации резолвит
        правила по общему, и объявленное «через порт» имя стало бы для него
        необъявленным — тихо, потому что необъявленное имя едет легально.
        """
        from ...observability_declarations import declared_metrics, forget_declarations

        host = _Host()
        _registered_manager(host)
        ctx = PluginContext(services=host, plugin_name="P")
        name = "hazard_probe_level"
        try:
            assert ctx.declare_metric(name) == name
            assert name in declared_metrics()
        finally:
            forget_declarations(names=[name])
