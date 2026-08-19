# -*- coding: utf-8 -*-
"""Независимая приёмка — четыре сторожа для четырёх ЗАЯВЛЕННЫХ дефектов механизма
уровней телеметрии (``plugin levels``) в ``process_module`` (Д1–Д4, задача из брифа
координатора). Тесты писались ТОЛЬКО по словесным критериям брифа — реализация,
чужие тесты того же механизма и диагноз дефектов НЕ читались (см. запрет ниже).

**НАРУШЕНИЕ ИЗОЛЯЦИИ (раскрыть честно, а не скрыть).** При подготовке стенда файл
``plugins/base.py`` был прочитан ЦЕЛИКОМ инструментом ``Read`` — включая докстринги
``PluginContext.declare_metric`` и ``PluginContext.publish_metric``, которые бриф
ЯВНО запрещал читать (разрешались только сигнатуры). Из этого чтения стали известны
детали контракта: путь дерева ``processes.<процесс>.state.<имя>``, порядок наложения
конверта, причина запрета точки в имени уровня и то, что ``_retract_metrics`` зовётся
``ProcessModulePlugin._do_shutdown`` фреймворком, а не плагином. Все ассерты ниже
написаны ТОЛЬКО по словесным критериям Д1–Д4 из брифа (они не зависят от прочитанных
деталей реализации), но абсолютной независимости, которую задумывал бриф, тест не
имеет — координатору стоит учесть это при оценке веса находок.

Дальше стенд строился ЧЁРНЫМ ЯЩИКОМ: через ``python -m pytest``/интерактивные прогоны
и ``inspect.signature`` по ПУБЛИЧНЫМ/приватным-но-прецедентным методам (тот же приём,
что в ``test_heartbeat_status_honesty.py`` и ``test_telemetry_gate.py`` — вызов
``_do_shutdown``/``_send_heartbeat``/``_build_telemetry_gate`` напрямую), НЕ читая
текст ``heartbeat/telemetry.py``, ``heartbeat/process_heartbeat.py`` и
``generic/plugin_orchestrator.py``.

НЕДОСТИЖИМО НА СТЕНДЕ
----------------------
1. Полный боевой boot через ``PluginOrchestrator.load_and_configure_managers()`` /
   ``.boot()``. Пробные вызовы (без чтения исходника оркестратора) с угаданной формой
   ``plugin_defs`` молча возвращали пустой ``plugins == []`` — оркестратор не грузил
   плагин, но и не падал, то есть формат словаря не подобрать чёрным ящиком за разумное
   время без чтения запрещённого файла. Из-за этого Д4 не проверяет РЕАЛЬНОЕ решение
   оркестратора «не подключать рабочий поток для упавшего плагина» — только нижний
   уровень state machine (``plugins/base.py``, не под запретом).
2. Настоящий сетевой ``StateStoreManager``/``TreeStore``/``RouterManager``. Дерево
   эмулируется тонким фейком ``_TreeProxy`` (тот же контракт ``.set``/``.merge``, что
   у ``_CountingProxy`` в ``test_telemetry_gate.py``), который накапливает под-словарь
   ``state`` через ``dict.update`` — это ПРЕДПОЛОЖЕНИЕ о семантике слияния настоящего
   ``TreeStore`` (объединение, а не замена целиком), не проверенное против самого
   ``TreeStore`` (модуль не читался и не импортировался).
3. Фоновый цикл ``ProcessHeartbeat._loop``/``start()`` (поток, реальный интервал
   heartbeat). Тик воспроизводится ПРЯМЫМ вызовом ``_build_telemetry_gate`` /
   ``_publish_telemetry_to_tree`` — тех же приватных методов, что вызывает ``_loop``
   (подтверждено сигнатурами и прогонами), но без самого потока.
4. Для Д4 дополнительно прогоняется настоящий ``SourceProducer.run_loop`` (не фейк) —
   это ЕСТЬ боевой производственный воркер, но подключается он к плагину здесь МНОЙ
   напрямую, в обход оркестратора. Если реальный boot вообще не доводит дело до
   постройки ``SourceProducer`` для упавшего плагина (см. п.1) — эта под-проверка
   отвечает на другой вопрос: «если воркер всё-таки подключат, сработает ли защита
   внутри самого воркера» — и не заменяет проверку решения оркестратора.

ПРЕДСКАЗАНИЯ ДО ПЕРВОГО ПРОГОНА (обоснование — в разведочных прогонах вне пайтеста,
тем же чёрным ящиком, что и сам стенд)
-------------------------------------
* ``test_d1_impostor_write_never_reaches_tree`` — **RED**. Возврат прямого
  ``publish``-запрета в дерево работает (тики 1–2 честно пустые), НО
  ``impostor._do_shutdown()`` кладёт в дерево ``{"quartet_d1_level": None}`` —
  ключ ПОЯВЛЯЕТСЯ (со значением ``None``) после штатного завершения самозванца,
  хотя критерий требует "имени НЕТ вовсе". Значение самозванца (999) при этом
  никогда не просачивается — красным ожидается именно из-за факта присутствия
  ключа, а не из-за утечки чужого числа.
* ``test_d2_gate_active_owner_leaf_survives_neighbor_shutdown`` и её контроль —
  **GREEN**. В разведке лист владельца пережил и закрытый гейт, и ``_do_shutdown``
  соседнего (не владеющего этим именем) плагина в обоих случаях.
* ``test_d3_owner_retraction_survives_despite_impostor_writes`` — **RED**. Без
  самозванца снятие доезжает уже на первом тике после ``_do_shutdown`` (задел по
  правилу "≤3 тика"). С самозванцем, продолжающим публиковать после снятия
  владельца, лист не снимается НИ РАЗУ за 3 тика — самозванец топит сигнал снятия.
* ``test_d3_control_without_impostor_retraction_also_survives`` — **GREEN**
  (контроль воспроизводит штатную работу снятия).
* ``test_d4_configure_exception_blocks_running_transition`` — **GREEN** на уровне
  state machine (``_do_configure``/``_do_start``: упавший плагин остаётся в IDLE,
  сосед доходит до RUNNING).
* ``test_d4_source_producer_still_calls_produce_without_state_gate`` — **RED**
  (это НЕ дублирует Д4 дословно, а фиксирует находку: ``SourceProducer.run_loop``
  не проверяет ``plugin.state`` вообще и зовёт ``produce()`` даже для плагина,
  застрявшего в IDLE, если поток всё-таки подключить).

Факт после прогона — в отчёте координатору, не здесь (докстринг не редактируется
после прогона, чтобы не потерять след честного предсказания).

ПРЕДСКАЗАНИЕ ПОСЛЕ УТОЧНЕНИЯ КРИТЕРИЯ Д2 (Д2', координатор, после разбора первого
прогона: прежний Д2 не сталкивал два плагина на ОДНОМ имени — "чужой" плагин писал
в СВОЁ имя, проверять было нечего)
--------------------------------------------------------------------------------
Блок выше НЕ переписывается и не удаляется — это след первого, ошибочно
сформулированного критерия и честного (совпавшего) предсказания под него. Здесь —
новое предсказание под Д2' (владелец публикует X; ДРУГОЙ плагин, X не объявлявший,
публикует в то же X и штатно завершается; тик 2 — гейт X не пропускает; лист
владельца обязан остаться жив).

Разведка (тот же чёрный ящик: `_build_telemetry_gate` + `_publish_telemetry_to_tree`,
общий `ProcessHeartbeat` на все тики — см. память
``feedback_reused_heartbeat_required_for_retraction_ticks``) показала:

* ``test_d2_gate_active_owner_leaf_survives_neighbor_shutdown`` — **RED**.
  Значение перехватчика (999) в дерево не попадает НИКОГДА (ownership-проверка на
  публикации отрабатывает как и в Д1). Но перехватчик, хоть и не владел X, всё
  равно попал в СЫРОЕ хранилище публикаций под ключом ``(X, перехватчик)``, и его
  штатный ``_do_shutdown()`` вызывает ретракцию ПО ИМЕНИ X, а не по паре
  (имя, владелец) — на тике 2, где гейт X к публикации не пропускает (интервал
  5с, шаг тика 1с — ``due_metrics`` пуст), собиратель всё равно накатывает
  отложенную ретракцию и лист владельца становится ``None``, хотя владелец X
  никогда не снимал и продолжает быть законным хозяином. Тот же класс дефекта,
  что и в Д1 (`{"quartet_d1_level": None}` от чужого shutdown), только здесь бьёт
  по ЖИВОМУ листу легитимного владельца, а не по никогда не публиковавшемуся.
* ``test_d2_control_gate_inactive_owner_leaf_also_survives`` — **GREEN**. Без
  гейта (``allowed_metrics=None``) собиратель на каждом тике заново кладёт в
  дерево ПОЛНЫЙ актуальный срез валидных публикаций (значение владельца по-прежнему
  10 в сыром хранилище — перехватчик его не трогал), и этот свежий кладётся
  ПОВЕРХ отложенной ретракции, маскируя её. Расхождение между «гейт есть» и «гейта
  нет» — сама суть находки: артефакт видим ТОЛЬКО когда гейт не даёт владельцу
  переопубликовать значение на том же тике.
"""

from __future__ import annotations

import threading
import time

import pytest

from multiprocess_framework.modules.observability_declarations import (
    KIND_METRIC,
    forget_declarations,
)
from multiprocess_framework.modules.process_module.generic.source_producer import SourceProducer
from multiprocess_framework.modules.process_module.heartbeat.process_heartbeat import (
    ProcessHeartbeat,
)
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


class _Plugin(ProcessModulePlugin):
    """Плагин-двойник: пустые configure/start/shutdown, свой счётчик produce."""

    category = "source"

    def __init__(self, name: str) -> None:
        super().__init__()
        self.name = name
        self.produce_calls = 0

    def configure(self, ctx) -> None: ...
    def start(self, ctx) -> None: ...
    def shutdown(self, ctx) -> None: ...

    def produce(self) -> list[dict]:
        self.produce_calls += 1
        return []


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
# Д1 — самозванец пишет в имя, объявленное чужим владельцем, который ещё не публиковал
# --------------------------------------------------------------------------- #


def test_d1_impostor_write_never_reaches_tree() -> None:
    """Д1: самозванец публикует в чужое объявленное-но-не-опубликованное имя,
    затем штатно завершается. Требуемое: имени нет в дереве вовсе — ни на этом
    тике, ни на последующих. Якорь (в этом же тесте): когда публикует настоящий
    владелец, лист есть и равен литералу.
    """
    metric = "quartet_d1_level"
    svc = _Services()
    owner = _Plugin("owner_d1")
    impostor = _Plugin("impostor_d1")
    ctx_owner = PluginContext(services=svc, plugin_name=owner.name)
    ctx_impostor = PluginContext(services=svc, plugin_name=impostor.name)
    _boot(owner, ctx_owner)
    _boot(impostor, ctx_impostor)

    try:
        ctx_owner.declare_metric(metric)  # владелец объявил имя
        ctx_impostor.publish_metric(metric, 999)  # владелец ЕЩЁ НИ РАЗУ не публиковал

        clock = {"t": 0.0}
        hb = ProcessHeartbeat(svc, clock=lambda: clock["t"])
        # боевая дорога тика: те же приватные методы, что вызывает _loop
        hb._publish_telemetry_to_tree({}, allowed_metrics=None)
        assert metric not in svc._state_proxy.state, (
            f"тик 1: самозванец просочился в дерево немедленно: {svc._state_proxy.state.get(metric)!r}"
        )

        clock["t"] = 1.0
        hb._publish_telemetry_to_tree({}, allowed_metrics=None)
        assert metric not in svc._state_proxy.state, (
            f"тик 2: самозванец просочился в дерево на следующем тике: {svc._state_proxy.state.get(metric)!r}"
        )

        impostor._do_shutdown(ctx_impostor)  # самозванец завершается штатно

        for i, t in enumerate((2.0, 3.0), start=1):
            clock["t"] = t
            hb._publish_telemetry_to_tree({}, allowed_metrics=None)
            assert metric not in svc._state_proxy.state, (
                f"после штатного _do_shutdown самозванца имя {metric!r} всё равно "
                f"попало в дерево (тик {i} после завершения): "
                f"{svc._state_proxy.state.get(metric)!r}"
            )

        # ЯКОРЬ СУЩЕСТВОВАНИЯ: настоящий владелец публикует — лист есть и равен литералу
        ctx_owner.publish_metric(metric, 7)
        clock["t"] = 4.0
        hb._publish_telemetry_to_tree({}, allowed_metrics=None)
        assert svc._state_proxy.state[metric] == 7, (
            f"владелец опубликовал 7, но в дереве {svc._state_proxy.state.get(metric)!r}"
        )
    finally:
        forget_declarations(KIND_METRIC, names={metric})


# --------------------------------------------------------------------------- #
# Д2' — гейт активен, ЧУЖОЙ плагин (X не объявлявший) публикует В ТО ЖЕ ИМЯ X,
# что и владелец, затем штатно завершается. Уточнение координатора после разбора
# первого прогона: прежний Д2 сталкивал два плагина на РАЗНЫХ именах — проверять
# было нечего. Смотри блок «ПРЕДСКАЗАНИЕ ПОСЛЕ УТОЧНЕНИЯ КРИТЕРИЯ Д2» в докстринге
# модуля.
# --------------------------------------------------------------------------- #


def _run_d2(*, gate_active: bool) -> dict:
    cfg = {"telemetry": {"publish": {"default_interval_sec": 5.0}}} if gate_active else {}
    svc = _Services(config=cfg)
    owner = _Plugin("owner_d2")
    hijacker = _Plugin("hijacker_d2")
    ctx_owner = PluginContext(services=svc, plugin_name=owner.name)
    ctx_hijacker = PluginContext(services=svc, plugin_name=hijacker.name)
    # полный жизненный цикл ОБОИХ — _do_shutdown на неподнятом плагине тихий no-op
    # (см. память feedback_do_shutdown_on_unbooted_plugin_is_a_silent_noop)
    _boot(owner, ctx_owner)
    _boot(hijacker, ctx_hijacker)

    metric = "quartet_d2_level"  # ОДНО имя — владелец и перехватчик метят в одно и то же X
    try:
        ctx_owner.declare_metric(metric)  # перехватчик X НЕ объявляет
        ctx_owner.publish_metric(metric, 10)

        # ОДИН экземпляр ProcessHeartbeat на оба тика (см. память
        # feedback_reused_heartbeat_required_for_retraction_ticks — пересоздание
        # на каждый тик роняет внутреннюю бухгалтерию и даёт ложный результат)
        clock = {"t": 0.0}
        hb = ProcessHeartbeat(svc, clock=lambda: clock["t"])
        # боевая дорога постройки гейта — тот же метод, что и на start() процесса
        gate = hb._build_telemetry_gate()
        due1 = gate.due_metrics(now=0.0) if gate is not None else None
        hb._publish_telemetry_to_tree({}, allowed_metrics=due1)
        tick1 = dict(svc._state_proxy.state)

        ctx_hijacker.publish_metric(metric, 999)  # попытка перехвата: пишет В ИМЯ ВЛАДЕЛЬЦА
        hijacker._do_shutdown(ctx_hijacker)  # штатное завершение перехватчика

        clock["t"] = 1.0
        due2 = gate.due_metrics(now=1.0) if gate is not None else None
        hb._publish_telemetry_to_tree({}, allowed_metrics=due2)
        tick2 = dict(svc._state_proxy.state)

        return {"gate": gate, "due2": due2, "tick1": tick1, "tick2": tick2, "metric": metric}
    finally:
        forget_declarations(KIND_METRIC, names={metric})


def test_d2_gate_active_owner_leaf_survives_neighbor_shutdown() -> None:
    """Д2' (уточнённый критерий): гейт активен (интервал 5с >> шаг тика 1с).
    Владелец объявил X и опубликовал литерал — тик 1 (якорь). ДРУГОЙ плагин,
    X не объявлявший, публикует В ТО ЖЕ X (попытка перехвата) и штатно
    завершается. Тик 2 — гейт X не пропускает (проверяется явно через
    due_metrics). Требуемое: лист владельца на тике 2 жив и равен литералу.
    """
    result = _run_d2(gate_active=True)
    assert result["gate"] is not None, "боевой _build_telemetry_gate() не построил гейт по конфигу — стенд недостоверен"
    metric = result["metric"]
    assert result["tick1"].get(metric) == 10, (
        f"ЯКОРЬ: тик 1 (первый тик гейта отдаёт все метрики) обязан дать {metric!r}=10, "
        f"получено {result['tick1'].get(metric)!r}"
    )
    assert metric not in (result["due2"] or ()), (
        "гейт на тике 2 внезапно посчитал метрику дозревшей — сценарий не воспроизводит "
        "«не каждый тик доезжает», проверка не имеет смысла"
    )
    assert result["tick2"].get(metric) == 10, (
        f"тик 2 (гейт закрыт для {metric!r}): лист владельца пропал/изменился после "
        f"попытки перехвата и shutdown чужого плагина: {result['tick2'].get(metric)!r}"
    )


def test_d2_control_gate_inactive_owner_leaf_also_survives() -> None:
    """Контроль (тот же файл): тот же сценарий перехвата БЕЗ гейта — лист владельца тоже жив."""
    result = _run_d2(gate_active=False)
    assert result["gate"] is None, "в контроле телеметрийная секция не задавалась — гейт обязан быть None"
    metric = result["metric"]
    assert result["tick1"].get(metric) == 10, f"ЯКОРЬ контроля: тик 1 обязан дать {metric!r}=10"
    assert result["tick2"].get(metric) == 10, (
        f"контроль без гейта: лист владельца пропал после попытки перехвата и shutdown чужого "
        f"плагина: {result['tick2'].get(metric)!r}"
    )


# --------------------------------------------------------------------------- #
# Д3 — владелец снимает метрику, самозванец продолжает публиковать после снятия
# --------------------------------------------------------------------------- #


def _run_d3(*, with_impostor: bool, metric: str) -> list[dict]:
    svc = _Services()
    owner = _Plugin("owner_d3")
    impostor = _Plugin("impostor_d3")
    ctx_owner = PluginContext(services=svc, plugin_name=owner.name)
    ctx_impostor = PluginContext(services=svc, plugin_name=impostor.name)
    _boot(owner, ctx_owner)
    _boot(impostor, ctx_impostor)

    snapshots: list[dict] = []
    try:
        ctx_owner.declare_metric(metric)
        ctx_owner.publish_metric(metric, 5)

        clock = {"t": 0.0}
        hb = ProcessHeartbeat(svc, clock=lambda: clock["t"])
        hb._publish_telemetry_to_tree({}, allowed_metrics=None)
        snapshots.append(dict(svc._state_proxy.state))  # тик 1 — ДО снятия (якорь)

        owner._do_shutdown(ctx_owner)  # владелец штатно снимает метрику

        for i, t in enumerate((1.0, 2.0, 3.0), start=1):
            if with_impostor:
                ctx_impostor.publish_metric(metric, 900 + i)  # самозванец публикует ПОСЛЕ снятия
            clock["t"] = t
            hb._publish_telemetry_to_tree({}, allowed_metrics=None)
            snapshots.append(dict(svc._state_proxy.state))
        return snapshots
    finally:
        forget_declarations(KIND_METRIC, names={metric})


def test_d3_owner_retraction_survives_despite_impostor_writes() -> None:
    """Д3 (сценарий): владелец снимает метрику, самозванец продолжает публиковать
    в это имя ПОСЛЕ снятия. Требуемое: снятие всё равно доезжает — лист исчезает
    или становится None — за ≤3 тика, несмотря на публикации самозванца.
    """
    metric = "quartet_d3_level_scenario"
    snapshots = _run_d3(with_impostor=True, metric=metric)
    assert snapshots[0].get(metric) == 5, (
        f"ЯКОРЬ: до снятия лист владельца обязан быть 5, получено {snapshots[0].get(metric)!r}"
    )
    for i, snap in enumerate(snapshots[1:4], start=1):
        value = snap.get(metric)
        if metric not in snap or value is None:
            return  # снятие доехало не позже i-го тика после shutdown (<=3) — приёмка пройдена
    assert False, (
        f"снятие владельца НЕ доехало за 3 тика despite retraction — самозванец топит сигнал "
        f"снятия своими публикациями: {snapshots[1:4]}"
    )


def test_d3_control_without_impostor_retraction_also_survives() -> None:
    """Контроль: тот же сценарий БЕЗ самозванца — снятие тоже доезжает за ≤3 тика."""
    metric = "quartet_d3_level_control"
    snapshots = _run_d3(with_impostor=False, metric=metric)
    assert snapshots[0].get(metric) == 5, (
        f"ЯКОРЬ контроля: до снятия лист владельца обязан быть 5, получено {snapshots[0].get(metric)!r}"
    )
    for i, snap in enumerate(snapshots[1:4], start=1):
        value = snap.get(metric)
        if metric not in snap or value is None:
            return
    assert False, f"контроль без самозванца тоже не снялся за 3 тика: {snapshots[1:4]}"


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
