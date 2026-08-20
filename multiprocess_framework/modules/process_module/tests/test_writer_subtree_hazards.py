# -*- coding: utf-8 -*-
"""Опасности НОВОЙ формы уровней — авторский набор Ф1 Task 1.2 (`plans/observation-port/plan.md`).

Дополнение к независимой приёмке (`test_writer_subtree_acceptance.py`, тестер от
критериев) и к перенесённому набору `test_plugin_levels_hazards.py` (там — свойства,
которые Ф1 НЕ трогала, в новой форме пути). Здесь — то, что видно только автору
переезда: чем именно новая конструкция отличается от старой и где эта разница может
проколоться.

Что сторожится, если сформулировать ДО прогона — «что может сломаться в ЭТОМ
механизме, учитывая как он построен»:

1. **Хранилище стало двухуровневым, а лок остался один.** Старая форма была плоским
   `dict[(имя, писатель)] -> значение`: одна вставка, одна операция. Новая —
   `setdefault(писатель, {})[имя] = значение`, то есть ДВА шага, между которыми поток
   может смениться. Без лока два потока, впервые публикующие под ОДНИМ писателем,
   каждый создали бы свой внутренний словарь, и один из них молча пропал бы вместе со
   всеми своими именами. Плоский ключ такого класса не имел вовсе — он появился
   вместе с поддеревом. Копия тоже стала двухуровневой: внешний обход и внутренний —
   две разные гонки, и обе накрыты тем же локом.

2. **Писатель стал СЕГМЕНТОМ ПУТИ — со всеми обязанностями сегмента.** До Ф1 имя
   плагина не попадало в дерево вовсе и могло быть любым. Теперь `my.plugin` даёт
   ровно тот лист-двойник, ради которого точка запрещена в имени уровня: тик 1 кладёт
   ключ литералом (узла ещё нет), тик 2 — вложенным путём. Дыра открыта самой Ф1 и
   закрыта в `publish_metric`; здесь она сторожится ЭФФЕКТОМ на дубле резолва.

3. **Гейт матчит по имени ЛИСТА, а не по пути.** Отсюда два следствия, которые надо
   назвать вслух, а не обнаружить на стенде: правило `metrics.fps` действует и на
   агрегат фреймворка, и на `fps` КАЖДОГО плагина сразу (одно правило — все писатели,
   это и есть М3 плана, но с обратной стороны); а `_next_due` у одноимённых листьев
   разных писателей ОДИН — интервал общий, не per-писатель. Glob по пути, которым это
   можно будет разделить, приходит в Ф4.

4. **Гейт обязан быть ТОТАЛЕН.** Он обходит каталог объявлений ∪ имена из хранилища.
   Забудь про второе слагаемое — и необъявленное имя не попадёт в `allowed` никогда,
   то есть «едет легально» превратится в тихий отказ: ту самую форму, которую Ф1
   хоронит, только без голоса. Сторожится ПАРОЙ: дефолт пропускает / дефолт не
   пропускает, оба с литералами.

5. **Пустое поддерево — это запись, которая ничего не сообщает.** Писатель, у
   которого гейт придержал все листья, не имеет права оставить `{"plugins": {"он": {}}}`:
   узел и дельта на каждом тике при нуле показаний.

Всё блокирующее — в daemon-потоке с `join(timeout)`: тест, который висит вместо того,
чтобы упасть, хуже отсутствующего.
"""

from __future__ import annotations

import threading
from typing import Any

import pytest

from multiprocess_framework.modules.observability_declarations import (
    KIND_METRIC,
    declared_metrics,
    forget_declarations,
)
from multiprocess_framework.modules.process_module.configs import TelemetryPublishConfig
from multiprocess_framework.modules.process_module.heartbeat.telemetry import (
    PLUGIN_LEVELS_ATTR,
    PluginLevels,
    TelemetryGate,
    build_plugin_levels,
)
from multiprocess_framework.modules.process_module.plugins.base import PluginContext

from .test_plugin_levels_hazards import _boot, _level, _tick_levels


@pytest.fixture(autouse=True)
def _metric_registry_guard():
    """Забыть ТОЛЬКО имена, объявленные этим файлом.

    Не сплошная очистка плоскости: она невосстановима (производители уже
    импортированы, объявлять некому) и красит соседей ТОЛЬКО в полном прогоне.
    """
    before = set(declared_metrics())
    yield
    forget_declarations(KIND_METRIC, names=set(declared_metrics()) - before)


# =========================================================================== #
# 1. Двухуровневое хранилище: гонка, которой у плоского ключа не было
# =========================================================================== #
class TestWriterBranchIsThreadSafe:
    def test_publish_is_mutually_exclusive(self):
        """Взаимное исключение — БАРЬЕРОМ ВНУТРИ критической секции, не штормом.

        **Написано после провалившейся инъекции, а не до неё.** Первая редакция
        этого класса гоняла восемь потоков по 400 публикаций и сверяла, что ни одно
        имя не потерялось. Инъекция «снять ``with self._lock`` с ``publish``»
        оставила её ЗЕЛЁНОЙ: под CPython 3.12 GIL не даёт вклиниться между
        ``setdefault`` и присваиванием, и шторм потоков доказывает пропускную
        способность, а не лок. Тест, который не краснеет от снятия того, что он
        якобы сторожит, не существует.

        Здесь лок судится напрямую: ``_lock`` подменяется зондом, который ВНУТРИ
        критической секции ждёт на барьере, рассчитанном на ДВА потока. Если
        взаимное исключение работает, второй поток до барьера не доходит — он
        стоит на входе, — и барьер обязан СЛОМАТЬСЯ по таймауту. Ожидаемый исход
        успеха — ``BrokenBarrierError`` у обоих; собравшийся барьер означал бы, что
        в секции одновременно оказались двое.

        Чего тест НЕ ловит (назвать обязательно): он привязан к ИМЕНИ атрибута
        ``_lock`` и к тому, что лок один на хранилище. Замени механизм на
        per-писательские локи — тест упадёт ``AttributeError``, то есть громко, а
        не молча; это осознанная цена белого ящика на месте, где чёрный ящик
        бессилен.
        """
        store = PluginLevels()
        entered = threading.Barrier(2, timeout=0.3)
        state = {"broken": 0, "overlapped": 0}
        real = store._lock

        class _Probe:
            def __enter__(self):
                real.acquire()
                try:
                    entered.wait()
                    state["overlapped"] += 1  # барьер собрался — в секции были двое
                except threading.BrokenBarrierError:
                    state["broken"] += 1
                return self

            def __exit__(self, *exc: Any) -> None:
                real.release()

        store._lock = _Probe()  # type: ignore[assignment]
        threads = [
            threading.Thread(target=store.publish, args=(f"leaf_{i}", float(i), "one_writer"), daemon=True)
            for i in range(2)
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=5.0)
        store._lock = real  # type: ignore[assignment]

        assert not any(t.is_alive() for t in threads), "поток-писатель не завершился — тест повис бы"
        assert state["broken"] >= 1, (
            f"ни один поток не вошёл в критическую секцию через лок хранилища "
            f"(broken={state['broken']}, overlapped={state['overlapped']}) — publish пишет мимо лока"
        )
        assert state["overlapped"] == 0, (
            "два потока оказались ВНУТРИ критической секции одновременно — взаимного исключения нет"
        )
        assert store.publications() == {"one_writer": {"leaf_0": 0.0, "leaf_1": 1.0}}, "ЯКОРЬ: обе записи легли"

    def test_the_branch_is_extended_not_replaced(self):
        """Вторая публикация ДОПОЛНЯЕТ ветку писателя, а не заменяет её.

        Отдельно от лока и отдельно от «ничего не потерялось»: тут не про потоки, а
        про то, что ветка растёт. ``self._values[writer] = {name: value}`` вместо
        ``setdefault`` дало бы плагину ровно ОДНУ метрику — последнюю, — и симптом
        («у плагина видно только одно число») искали бы в плагине.
        """
        store = PluginLevels()
        store.publish("a", 1.0, "w")
        store.publish("b", 2.0, "w")
        store.publish("a", 3.0, "w")  # перезапись своего же имени — не потеря соседа
        assert store.publications() == {"w": {"a": 3.0, "b": 2.0}}

    def test_publications_hands_out_copies_of_the_branches(self):
        """Копия ДВУХУРОВНЕВАЯ: внутренние словари тоже копии.

        Отдай ``publications`` внутренние словари ссылкой — и читатель тика
        итерировал бы ЖИВОЙ словарь, в который пишет поток воркера; это ровно та
        ``RuntimeError: dictionary changed size during iteration``, ради которой
        здесь лок, только лок её уже не накрывает: он отпущен на выходе из метода.
        """
        store = PluginLevels()
        store.publish("x", 1.0, "w")
        out = store.publications()
        out["w"]["x"] = 999.0
        out["injected"] = {"y": 1.0}
        assert store.publications() == {"w": {"x": 1.0}}, store.publications()

    def test_concurrent_publications_of_one_writer_lose_nothing(self):
        """Сквозная проверка пропускной способности — НЕ доказательство лока.

        Названо прямо, потому что выглядит обратным: инъекция «снять лок» оставляет
        этот тест зелёным (GIL, см. :meth:`test_publish_is_mutually_exclusive`).
        Что он ловит на самом деле — грубую поломку хранилища под нагрузкой
        (замена ветки вместо дополнения, обрыв по исключению в чужом потоке) и то,
        что 3200 публикаций доходят до одной ветки целиком.

        Ожидание — ЛИТЕРАЛ (``_THREADS * _PER_THREAD`` имён), а не пересчёт из
        хранилища: выведенное из проверяемого согласилось бы с любым ответом.
        """
        _THREADS = 8
        _PER_THREAD = 400
        store = PluginLevels()
        start = threading.Barrier(_THREADS)
        errors: list[BaseException] = []

        def publisher(tid: int) -> None:
            try:
                start.wait(timeout=5.0)
                for i in range(_PER_THREAD):
                    store.publish(f"t{tid}_level_{i}", float(i), "one_writer")
            except BaseException as exc:  # noqa: BLE001 — поднимем в главном потоке
                errors.append(exc)

        threads = [threading.Thread(target=publisher, args=(t,), daemon=True) for t in range(_THREADS)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=10.0)
        assert not any(t.is_alive() for t in threads), "поток-писатель не завершился — тест повис бы"
        assert not errors, f"писатели упали: {errors!r}"

        branch = store.publications()["one_writer"]
        assert len(branch) == _THREADS * _PER_THREAD, (
            f"ветка писателя потеряла имена: ожидали {_THREADS * _PER_THREAD}, лежит {len(branch)} "
            f"— ветка пересоздавалась параллельно, и часть публикаций ушла в потерянный словарь"
        )
        assert branch["t0_level_0"] == 0.0 and branch[f"t{_THREADS - 1}_level_1"] == 1.0, "ЯКОРЬ: значения на месте"

    def test_publish_after_retract_recreates_the_branch(self):
        """Снятие ``pop``-ает ветку целиком — следующая публикация обязана её вернуть.

        Иначе плагин, поднятый заново после остановки (штатный сценарий рецепта),
        молча перестал бы публиковать: ветки нет, а ``setdefault`` не позвали бы.
        """
        store = PluginLevels()
        store.publish("x", 1.0, "phoenix")
        assert store.retract("phoenix") == 1
        assert store.publications() == {}

        store.publish("x", 2.0, "phoenix")
        assert store.publications() == {"phoenix": {"x": 2.0}}

    def test_retract_of_one_writer_does_not_touch_the_neighbour(self):
        """Соседи не задеваются ПО ПОСТРОЕНИЮ (``pop`` ветки), а не по фильтру.

        Отдельным тестом от «снятие вернуло N», потому что это разные отказы:
        число может быть верным, а задет — сосед.
        """
        store = PluginLevels()
        store.publish("shared", 1.0, "a")
        store.publish("shared", 2.0, "b")
        assert store.retract("a") == 1
        assert store.publications() == {"b": {"shared": 2.0}}

    def test_names_sees_every_writer_not_just_the_first(self):
        """``names()`` кормит ГЕЙТ, и обход у него свой — два уровня, не один.

        Сложи он имена только первого писателя (или только внешние ключи) — гейт
        не узнал бы про часть листьев, и они молча не поехали бы. Одноимённые
        листья схлопываются в одно имя намеренно: гейт матчит по ИМЕНИ.
        """
        store = PluginLevels()
        store.publish("shared", 1.0, "a")
        store.publish("only_b", 2.0, "b")
        store.publish("shared", 3.0, "b")
        assert store.names() == {"shared", "only_b"}


# =========================================================================== #
# 2. Писатель — сегмент пути, со всеми обязанностями сегмента
# =========================================================================== #
class TestWriterNameIsAPathSegment:
    def test_a_dotted_plugin_name_never_reaches_the_tree(self):
        """Дыра, открытую самой Ф1: до неё имя плагина в путь не попадало вовсе.

        Воспроизведено на дубле ``TreeStore._merge_recursive`` (тот же резолв, что
        у настоящего стора) ДО правки::

            тик 1: {'plugins': {'my.plugin': {'fps': 1.0}}}
            тик 2: {'plugins': {'my.plugin': {'fps': 1.0}, 'my': {'plugin': {'fps': 2.0}}}}
                                 ^^^^^^^^^^^ заморожен навсегда

        Два тика, а не один: на одном ветка резолва «узел уже есть» недостижима, и
        двойника не видно.

        ЯКОРЬ в том же тесте — плагин с годным именем публикует тот же лист и
        доезжает: без него тест зелен и у механизма, который не публикует вовсе.
        """
        services, hb = _boot(name="dotw")
        bad = PluginContext(services=services, config={}, plugin_name="my.plugin")
        good = PluginContext(services=services, config={}, plugin_name="my_plugin")
        bad.publish_metric("fps", 1.0)
        good.publish_metric("fps", 5.0)
        _tick_levels(hb)
        bad.publish_metric("fps", 2.0)
        _tick_levels(hb)

        assert _level(services, "my_plugin", "fps") == 5.0, "ЯКОРЬ: годное имя писателя едет"
        assert services._state_proxy.get("processes.dotw.state.plugins.my") is None, (
            f"точечное имя писателя развернулось в путь: {services._state_proxy.tree}"
        )
        assert "my.plugin" not in (services._state_proxy.get("processes.dotw.state.plugins") or {}), (
            f"точечное имя писателя легло литеральным ключом: {services._state_proxy.tree}"
        )
        said = [msg for msg in services.warnings() if "my.plugin" in msg]
        assert len(said) == 1, f"ожидали ОДИН голос про писателя, получили {len(said)}: {said}"

    def test_a_leaf_named_like_a_path_segment_is_ordinary(self):
        """Лист по имени ``plugins``/``state``/``shm`` — обычный лист, не коллизия.

        Сегменты пути ставит СБОРЩИК, а имя листа приходит от плагина; спутать их
        нельзя, потому что имя листа всегда на дне. Тест существует, чтобы это было
        проверено, а не заявлено: интуиция здесь подсказывает обратное.
        """
        services, hb = _boot(name="segnames")
        ctx = PluginContext(services=services, config={}, plugin_name="segment_plugin")
        for leaf in ("plugins", "state", "shm", "workers"):
            ctx.publish_metric(leaf, 1.0)
        _tick_levels(hb)

        for leaf in ("plugins", "state", "shm", "workers"):
            assert _level(services, "segment_plugin", leaf) == 1.0, (
                f"лист {leaf!r} потерялся — имя листа спутано с сегментом пути"
            )
        assert services._state_proxy.get("processes.segnames.state.shm") is None, (
            "лист плагина по имени 'shm' протёк в секцию агрегатов фреймворка"
        )


# =========================================================================== #
# 3. Гейт матчит по ИМЕНИ ЛИСТА — два следствия, названные вслух
# =========================================================================== #
class TestGateMatchesTheLeafNotThePath:
    def test_one_rule_switches_the_same_leaf_of_every_writer(self):
        """Одно правило — все писатели. Это М3 плана, увиденный с обратной стороны.

        Сила: чтобы поменять частоту ``fps`` у всех плагинов, правило пишут один
        раз. Цена: выключить ``fps`` ОДНОМУ писателю правилом ``metrics.fps``
        нельзя — до glob'а по пути (Ф4) такого адреса просто нет. Свойство парное:
        при закрытом правиле молчат ОБА, при открытом — говорят ОБА.
        """
        services, hb = _boot(name="gate_all")
        a = PluginContext(services=services, config={}, plugin_name="writer_a")
        b = PluginContext(services=services, config={}, plugin_name="writer_b")
        a.publish_metric("shared_leaf", 1.0)
        b.publish_metric("shared_leaf", 2.0)

        _tick_levels(hb, allowed_metrics=set())  # правило закрыто
        assert _level(services, "writer_a", "shared_leaf") is None
        assert _level(services, "writer_b", "shared_leaf") is None

        _tick_levels(hb, allowed_metrics={"shared_leaf"})  # то же правило открыто
        assert _level(services, "writer_a", "shared_leaf") == 1.0
        assert _level(services, "writer_b", "shared_leaf") == 2.0

    def test_the_rate_limit_is_shared_by_the_same_leaf_of_all_writers(self):
        """``_next_due`` ключуется ИМЕНЕМ — интервал общий, не per-писатель.

        Названо тестом, а не комментарием: свойство неочевидное и на стенде
        выглядело бы как «второй плагин почему-то реже». Разделить интервалы
        сможет только glob по пути (Ф4).
        """
        config = TelemetryPublishConfig.from_dict({"default_enabled": True, "default_interval_sec": 10.0})
        gate = TelemetryGate(config)
        assert "shared_leaf" in gate.due_metrics(now=0.0, extra={"shared_leaf"})
        # Тот же лист второго писателя в том же окне — уже не созрел: окно ОДНО.
        assert "shared_leaf" not in gate.due_metrics(now=0.1, extra={"shared_leaf"})
        assert "shared_leaf" in gate.due_metrics(now=10.0, extra={"shared_leaf"}), "ЯКОРЬ: окно истекает"


# =========================================================================== #
# 4. Гейт обязан быть тотален — иначе «легально» стало тихим отказом
# =========================================================================== #
class TestGateIsTotalOverUndeclaredNames:
    """Пара, а не одиночный ноль: «не приехало» одинаково выглядит и у отказа,
    и у механизма, которого нет. Здесь дефолт конфига переключается, и
    наблюдаемый результат обязан переключиться вместе с ним.

    Отдельно от приёмки тестера: его сценарии строят гейт (`_build_telemetry_gate`),
    но НЕ ставят его на heartbeat (`hb._telemetry_gate = ...`), поэтому `_loop` у
    него идёт вовсе без гейта — и обе половины пары там зелены/красны по причине,
    не связанной с гейтом. Здесь гейт установлен.
    """

    LEAF = "never_declared_leaf_xyz"

    def _run(self, *, default_enabled: bool) -> Any:
        services, hb = _boot(name=f"total_{int(default_enabled)}")
        config = TelemetryPublishConfig.from_dict({"default_enabled": default_enabled, "default_interval_sec": 0.0})
        hb._telemetry_gate = TelemetryGate(config)
        ctx = PluginContext(services=services, config={}, plugin_name="undeclared_writer")
        ctx.publish_metric(self.LEAF, 444.5)
        assert self.LEAF not in declared_metrics(), "предпосылка: имя НЕ объявлено"

        gate = hb._telemetry_gate
        _tick_levels(hb, gate.due_metrics(extra=hb._level_names()))
        return services

    def test_default_open_lets_the_undeclared_leaf_through_without_a_word(self):
        services = self._run(default_enabled=True)
        assert _level(services, "undeclared_writer", self.LEAF) == 444.5, (
            "необъявленное имя не доехало под ОТКРЫТЫМ дефолтом — гейт обходит только "
            "каталог, и «легально едет» стало тихим отказом"
        )
        assert services.warnings() == [], f"голос про необъявленное имя воскрес: {services.warnings()}"

    def test_default_closed_blocks_the_same_leaf(self):
        services = self._run(default_enabled=False)
        assert _level(services, "undeclared_writer", self.LEAF) is None, (
            "белый список пропустил имя, которого в нём нет — гейт перестал быть гейтом"
        )

    def test_the_gate_forgets_nothing_from_the_catalog_when_extra_is_given(self):
        """``extra`` ДОБАВЛЯЕТ кандидатов, а не заменяет каталог.

        Замени — и метрики фреймворка (``fps``, ``shm``), которых в хранилище
        уровней нет и быть не может, выпали бы из гейта целиком: он перестал бы
        их выключать, то есть выключенная метрика поехала бы.
        """
        config = TelemetryPublishConfig.from_dict({"default_enabled": True, "default_interval_sec": 0.0})
        allowed = TelemetryGate(config).due_metrics(now=0.0, extra={"чужой_лист"})
        assert {"fps", "latency_ms", "shm"}.issubset(allowed), sorted(allowed)
        assert "чужой_лист" in allowed


# =========================================================================== #
# 5. Проекция: пустых веток не бывает, вход не мутируется
# =========================================================================== #
class TestProjectionShape:
    def test_a_writer_gated_to_nothing_leaves_no_branch(self):
        """Пустая ветка — узел и дельта на каждом тике при нуле показаний."""
        out = build_plugin_levels({"тихий": {"off": 1}, "громкий": {"on": 2}}, {"on"})
        assert out == {"plugins": {"громкий": {"on": 2}}}, out

    def test_the_publisher_sends_no_merge_when_every_writer_is_gated_out(self):
        """Тот же ноль ЭФФЕКТОМ, а не формой: merge не уходит вовсе.

        Форму сторожит тест выше; здесь — что публикатор этажом выше её понял.
        ЯКОРЬ: тот же вход при открытом гейте даёт ровно один merge.
        """
        services, hb = _boot(name="void_branch")
        PluginContext(services=services, config={}, plugin_name="w").publish_metric("x", 1.0)

        _tick_levels(hb, allowed_metrics=set())
        assert services._state_proxy.merges == [], services._state_proxy.merges

        _tick_levels(hb, allowed_metrics=None)
        assert len(services._state_proxy.merges) == 1
        assert _level(services, "w", "x") == 1.0

    def test_the_projection_copies_the_branches_it_returns(self):
        """Мутация результата не имеет права дотянуться до хранилища.

        Payload уходит в ``proxy.merge`` и дальше живёт своей жизнью (сериализация,
        дельты, сток). Отдай сборщик ЖИВЫЕ внутренние словари — и правка payload'а
        по дороге переписала бы показания процесса.
        """
        store = PluginLevels()
        store.publish("x", 1.0, "w")
        out = build_plugin_levels(store.publications(), None)
        out["plugins"]["w"]["x"] = 999.0
        out["plugins"]["injected"] = {"y": 1.0}
        assert store.publications() == {"w": {"x": 1.0}}, store.publications()


# =========================================================================== #
# 6. Провод: тик и опрос читают ОДНО хранилище через ОДИН сборщик
# =========================================================================== #
class TestPushAndPollShareTheStore:
    def test_a_writer_added_between_two_ticks_appears_without_any_wiring(self):
        """М1/М2: новый писатель = ноль правок механизма и ноль правок конфига.

        Судится ЭФФЕКТОМ на боевом пути: второй плагин заводится ПОСЛЕ первого
        тика и появляется на втором, рядом с первым, оба со своими литералами.
        Механизм с реестром писателей провалил бы это по построению.
        """
        services, hb = _boot(name="grow")
        first = PluginContext(services=services, config={}, plugin_name="first_writer")
        first.publish_metric("a", 1.0)
        _tick_levels(hb)
        assert _level(services, "first_writer", "a") == 1.0
        assert services._state_proxy.get("processes.grow.state.plugins.late_writer") is None, "предпосылка"

        PluginContext(services=services, config={}, plugin_name="late_writer").publish_metric("b", 2.0)
        _tick_levels(hb)

        assert _level(services, "late_writer", "b") == 2.0, "новый писатель не появился — где-то есть реестр"
        assert _level(services, "first_writer", "a") == 1.0, "ЯКОРЬ: соседа не задело"

    def test_the_store_is_the_single_source_for_both_roads(self):
        """Опрос читает ТО ЖЕ хранилище, а не свою копию.

        Снятие писателя обязано стереть его и из снимка опроса — разойдись дороги,
        оператор видел бы показания остановленного плагина, и увидеть это можно
        было бы только на стенде.
        """
        services, hb = _boot(name="single")
        ctx = PluginContext(services=services, config={}, plugin_name="single_writer")
        ctx.publish_metric("v", 3.0)
        snapshot = hb.current_levels_snapshot() or {}
        assert snapshot["state"]["plugins"]["single_writer"]["v"] == 3.0

        assert getattr(services, PLUGIN_LEVELS_ATTR).retract("single_writer") == 1
        after = hb.current_levels_snapshot() or {}
        assert "plugins" not in (after.get("state") or {}), after


# =========================================================================== #
# 7. Боевые правила гейта — БЕЗ единой правки конфига (критерий 3 задачи)
# =========================================================================== #
class TestProdGateSectionWorksUnedited:
    """Секция ``telemetry.publish`` берётся из настоящего ``system.yaml`` и
    отдаётся гейту дословно.

    Почему это авторский тест, а не «дубль приёмки». У тестера сценарий на том же
    боевом конфиге есть, но он вакуумен по причине, которую тестер видеть не мог:
    ``_build_telemetry_gate`` — ЧИСТЫЙ СТРОИТЕЛЬ, он возвращает гейт и ничего не
    взводит; взводит его единственный вызывающий — ``start()``
    (``self._telemetry_gate = self._build_telemetry_gate()``). Харнесс тестера
    строит гейт, проверяет что тот не ``None``, и дальше зовёт ``_loop`` — где
    ``self._telemetry_gate`` всё ещё ``None``, то есть ``allowed_metrics=None`` и
    гейта нет вовсе. Так было и до Ф1: не регресс, а свойство метода. Здесь гейт
    ВЗВЕДЁН, и потому суждение о нём вообще имеет смысл.

    Строитель намеренно оставлен чистым: сделай его самовзводящимся — и
    диагностический вызов «а какой гейт собрался бы из загрузочного конфига»
    молча затёр бы гейт, поставленный рантайм-командой
    (``reconfigure_telemetry`` кладёт свой ``TelemetryGate`` в то же поле).
    Рантайм-правка, отменённая чтением, — отдельный класс дефекта, и заводить его
    ради удобства харнесса нельзя.
    """

    def _prod_publish_section(self) -> dict:
        import yaml
        from pathlib import Path

        path = Path(__file__).resolve().parents[4] / "multiprocess_prototype" / "backend" / "config" / "system.yaml"
        assert path.is_file(), (
            f"боевой конфиг не найден: {path}. Критерий 3 — про ПРОД-правила; "
            f"подменить их синтетическими значило бы проверить другой сценарий"
        )
        publish = yaml.safe_load(path.read_text(encoding="utf-8"))["telemetry"]["publish"]
        # Якорь сценария: тест судит БЕЛЫЙ СПИСОК (закрытый дефолт + явное правило
        # на fps). Изменись боевой конфиг — упасть обязано ЗДЕСЬ и громко, а не
        # молча превратиться в проверку другого расклада.
        assert publish.get("default_enabled") is False, publish
        assert publish["metrics"]["fps"]["enabled"] is True, publish
        assert "unlisted_prod_leaf" not in publish.get("metrics", {}), publish
        return publish

    def test_prod_whitelist_matches_the_leaf_of_every_writer(self):
        """Одно боевое правило ``metrics.fps`` действует на лист ``fps`` ОБОИХ
        писателей в их поддеревьях — суффиксный матч переезд пережил.

        Пара, а не одиночное отрицание: имя из белого списка доезжает с литералом,
        имя вне списка — не доезжает, и оба вердикта выносит ОДИН и тот же
        нетронутый конфиг.
        """
        publish = self._prod_publish_section()
        services, hb = _boot(name="prod_gate")
        hb._telemetry_gate = TelemetryGate(TelemetryPublishConfig.from_dict(publish))

        a = PluginContext(services=services, config={}, plugin_name="prod_writer_a")
        b = PluginContext(services=services, config={}, plugin_name="prod_writer_b")
        a.publish_metric("fps", 41.5)
        b.publish_metric("fps", 17.5)
        a.publish_metric("unlisted_prod_leaf", 88.5)

        gate = hb._telemetry_gate
        _tick_levels(hb, gate.due_metrics(extra=hb._level_names()))

        assert _level(services, "prod_writer_a", "fps") == 41.5, (
            "боевое правило metrics.fps не пропустило лист fps первого писателя — "
            "гейт матчит уже не по имени листа, и прод-конфиг требует миграции"
        )
        assert _level(services, "prod_writer_b", "fps") == 17.5, (
            "то же правило не пропустило одноимённый лист ВТОРОГО писателя — матч поехал по пути, а не по имени листа"
        )
        assert _level(services, "prod_writer_a", "unlisted_prod_leaf") is None, (
            "закрытый дефолт боевого конфига пропустил имя, которого в белом списке нет — гейт перестал быть гейтом"
        )
