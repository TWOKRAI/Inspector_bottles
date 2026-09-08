# -*- coding: utf-8 -*-
"""Независимая приёмка Task 2.1 плана ``observability-closure`` (Ф2, «одна политика»).

**RED-набор, написан ДО реализации.** Тестер работал в отдельном worktree на
пред-имплементационном коммите (``0b2d5b15``), не видел diff/реализацию Task 2.1,
не читал ничего в ``_impl/`` (директории с таким именем в этом дереве и нет).
Источник критериев — текст, переданный оркестратором, сверенный с текстом самого
Task 2.1 в ``plans/observability-closure/phase-2-one-policy.md`` (это ТЗ задачи,
а не реализация — читать его тестеру можно и нужно, как читают ``interface.py``).

**Цель механизма.** Любая метрика плоскости ЧИСЕЛ (``StatsManager`` /
``ObservationManager.record_metric``/``increment``/``gauge``/``record_timing``/
``histogram``) включается, выключается и троттлится ТЕМ ЖЕ glob-правилом
политики ``observation.rules``, что и УРОВНИ (``ObservationPolicy``,
``process_module/configs/observation_policy.py`` — этот файл уже существует и
не трогается), а решение принимается ДО сборки числовой записи.

======================================================================
ЯВНО НАЗВАННОЕ ДОПУЩЕНИЕ — единственный придуманный тестером символ
======================================================================

Механизма подключения политики к ПОРТУ ЧИСЕЛ (``ObservationManager``) в коде
нет нигде (проверено grep'ом по всему дереву — ни ``attach_numbers_policy``,
ни ``numbers_policy``, ни ``plane_disabled`` не встречаются). План называет
ТОЛЬКО поведение («порт спрашивает ``policy.resolve(path)`` до
``NumberRecord``»), а не имя метода. Все тесты, проверяющие ГЛОБ-ПРАВИЛА
(критерии 1, 2, 6, 8 ниже), поэтому заводят политику через ОДИН придуманный
хук, по образцу уже существующих в этом же файле ``attach_observation_port``/
``attach_observability_hub``:

    port = ObservationManager(manager_name=..., process=SimpleNamespace(name="cam1"))
    port.attach_numbers_policy(policy)   # <-- ИМЯ ПРИДУМАНО, не подтверждено планом

Сегодня это падает ``AttributeError`` на первой же попытке — эти четыре теста
СЕГОДНЯ КРАСНЫЕ ОДНОЙ И ТОЙ ЖЕ строкой, и это ЧЕСТНО: у них общий блокирующий
шаг, и разойтись по разным причинам они смогут только после того, как хук (под
этим или другим именем) появится. См. отчёт тестера — раздел «что ненадёжно» —
за прямым текстом об этом риске.

Критерии 3, 4, 7 сознательно устроены НЕЗАВИСИМО от этого допущения — они бьют
по ``ObservabilityStatsConfig``/``expand_observability``/``StatsManager``
напрямую, без похода через порт.

======================================================================
Что здесь НЕ проверяется (сознательно, не забыто)
======================================================================

* Живой стенд (``config_reload_verified``, TTL, два реальных ``flush`` по
  расписанию heartbeat'а) — у тестера нет доступа к запущенному backend'у.
* Бенч «выключенная метрика ≤ 0.5 мкс» — плановый шаг 5 Task 2.1, но не входит
  в список критериев, переданный тестеру этой сессии.
* Полный паритетный обход ВСЕХ путей ``multiprocess_prototype/backend/config/
  system.yaml`` до/после правки (критерий 7, первая половина) — на
  пред-имплементационном коммите нет «после», с чем сравнивать; смысловая
  сверка decisions без живого diff превратилась бы в пересказ той же логики,
  которую критерий проверяет. ``system.yaml`` сегодня несёт ``stats.enabled:
  true`` (строка 149) — при такой семантике старое и новое поведение СОВПАДАЮТ
  тривиально (true→true), так что этот конкретный файл даже не обнажил бы
  расхождение. Закрыта только вторая половина критерия 7 — громкое
  предупреждение при чтении ``stats.enabled: false``.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any, Dict, Optional, Set

from ...base_manager.mixins.observable_mixin import ObservableMixin
from ...channel_routing_module.observability import STATS_AGGREGATE_KEY
from ...channel_routing_module.observability.observability_hub import ObservabilityHub
from ...process_module.configs.observability_config import ObservabilityConfig, expand_observability
from ...process_module.configs.observation_policy import ObservationPolicy, ObservationPolicyConfig
from ...process_module.configs.telemetry_publish_config import MetricRule
from ...process_module.managers.observability_reload import compose_managers_payload
from .. import StatsManager
from ..observation.observation_manager import ObservationManager


# ====================================================================== #
#  Харнесс — только реальные классы фреймворка.                          #
# ====================================================================== #


def _make_gated_pair(process_name: str, policy: ObservationPolicy, hub: ObservabilityHub):
    """Реальный ``StatsManager`` + реальный ``ObservationManager`` (порт), связанные
    ``attach_observation_port`` — ровно как это делает ``ProcessManagers.create_all`` —
    плюс политика, подключённая к порту ЕДИНСТВЕННЫМ придуманным тестером хуком
    (см. докстринг файла). Ни файлового, ни лог-канала: тесты не должны писать на
    диск рабочего дерева тестера. Темп агрегации задран, чтобы фоновый таймер не
    сбросил окно САМ во время теста — снапшот берётся детерминированно, вызовом
    ``mgr.flush()``.
    """
    port = ObservationManager(manager_name=f"port_{process_name}", process=SimpleNamespace(name=process_name))
    assert port.initialize(), f"{process_name}: порт не поднялся — стенд сломан ДО нагрузки"
    port.attach_numbers_policy(policy)

    mgr = StatsManager(
        manager_name=f"stats_{process_name}",
        config={
            "enable_logging": False,
            "aggregation_interval": 300.0,
            "flush_interval": 300.0,
            "channels": {"file_stats": {"enabled": False}},
        },
    )
    assert mgr.initialize(), f"{process_name}: StatsManager не поднялся — стенд сломан ДО нагрузки"
    assert mgr.attach_observability_hub(hub), f"{process_name}: hub-канал не поднялся"
    assert mgr.attach_observation_port(port) is True, f"{process_name}: attach_observation_port вернул False"
    return mgr, port


def _hub_metric_names(hub: ObservabilityHub) -> Set[str]:
    """Имена метрик, доехавших до hub'а — и в СЫРОЙ форме (``metric``), и в
    АГРЕГАТНОЙ (``metrics: [...]``, маркер ``STATS_AGGREGATE_KEY``). Разрушающий
    дренаж (``drain_stats``) — зовётся один раз на проверку.
    """
    names: Set[str] = set()
    for rec in hub.drain_stats():
        if rec.get(STATS_AGGREGATE_KEY):
            for m in rec.get("metrics") or []:
                name = m.get("name")
                if name:
                    names.add(str(name))
        else:
            name = rec.get("metric")
            if name:
                names.add(str(name))
    return names


def _policy_dropped_view(mgr: StatsManager, port: ObservationManager) -> Dict[str, int]:
    """``numbers_policy_dropped`` — ОДИН адрес чтения: ``StatsManager.get_stats()``.

    Хедж тестера (сумма по двум кандидатам, ``mgr`` и ``port``) снят исполнителем:
    решение о правиле действительно принимает порт, но СПРАШИВАТЬ разрешено в одном
    месте — плоскость складывает свои дропы (выключенная плоскость) с дропами гейта
    порта сама (см. ``StatsManager.numbers_policy_dropped``). Два счётчика с одним
    именем в двух объектах читатель складывал бы вручную и ошибался бы молча;
    ``port.get_stats()`` ключа ``numbers_policy_dropped`` не несёт вовсе.

    ``port`` остаётся в сигнатуре как явный маркер: он в тесте есть, и именно его
    гейт наполняет читаемое здесь число.
    """
    raw = mgr.get_stats().get("numbers_policy_dropped")
    assert "numbers_policy_dropped" not in port.get_stats(), (
        "адрес обязан быть ОДИН: порт не должен нести ключ с тем же именем — "
        "иначе читатель складывает два счётчика вручную"
    )
    return {} if not isinstance(raw, dict) else {str(k): int(v) for k, v in raw.items()}


# ====================================================================== #
#  Критерий 1 — правило по ПУТИ режет ОДНУ метрику, соседи живы.          #
# ====================================================================== #


def test_c1_rule_disables_one_metric_path_others_survive_with_literal_drop_count():
    """``processes.cam1.stats.capture.frames: {enabled: false}`` (Р-2а: путь без тегов).

    Проверяются ОБЕ оси специфичности ОДНИМ правилом (одна и та же политика на
    обоих процессах — важно: специфичность обязана резать по ПУТИ, не по
    ссылке на объект правила):

    * ось МЕТРИКИ: ``capture.drops`` того же процесса cam1 жив;
    * ось ПРОЦЕССА: ``capture.frames`` ДРУГОГО процесса (cam2) жив.

    ``numbers_policy_dropped`` для ``capture.frames`` — ЛИТЕРАЛ 5 (пять
    заблокированных вызовов), не выражение от кода.
    """
    policy = ObservationPolicy(
        ObservationPolicyConfig(rules={"processes.cam1.stats.capture.frames": MetricRule(enabled=False)}),
        legacy=None,
    )
    hub1 = ObservabilityHub("cam1-c1")
    hub2 = ObservabilityHub("cam2-c1")
    mgr1, port1 = _make_gated_pair("cam1", policy, hub1)
    mgr2, port2 = _make_gated_pair("cam2", policy, hub2)
    try:
        for _ in range(5):
            mgr1.record_metric("capture.frames", 1)  # запрещено правилом
        for _ in range(3):
            mgr1.record_metric("capture.drops", 1)  # тот же процесс, другое имя — жив
        for _ in range(4):
            mgr2.record_metric("capture.frames", 1)  # то же имя, ДРУГОЙ процесс — жив

        mgr1.flush()
        mgr2.flush()

        assert mgr1.get_metric("capture.frames") is None, (
            "capture.frames процесса cam1 обязан отсутствовать в окне — правило его запретило"
        )
        drops = mgr1.get_metric("capture.drops")
        assert drops is not None and drops["count"] == 3.0, (
            f"capture.drops (тот же процесс, другое имя) обязан быть жив с count=3.0, получено {drops!r}"
        )
        frames_cam2 = mgr2.get_metric("capture.frames")
        assert frames_cam2 is not None and frames_cam2["count"] == 4.0, (
            f"capture.frames ДРУГОГО процесса (cam2) обязан быть жив с count=4.0, получено {frames_cam2!r}"
        )

        hub1_names = _hub_metric_names(hub1)
        assert "capture.frames" not in hub1_names, f"capture.frames долетел до hub cam1: {hub1_names!r}"
        assert "capture.drops" in hub1_names, f"capture.drops обязан быть в hub cam1: {hub1_names!r}"
        hub2_names = _hub_metric_names(hub2)
        assert "capture.frames" in hub2_names, f"capture.frames cam2 обязан быть в hub cam2: {hub2_names!r}"

        dropped = _policy_dropped_view(mgr1, port1)
        assert dropped.get("capture.frames") == 5, (
            f"numbers_policy_dropped['capture.frames'] обязан быть ЛИТЕРАЛОМ 5 (столько раз позвали "
            f"заблокированный record_metric), получено {dropped!r}"
        )
    finally:
        mgr1.shutdown()
        mgr2.shutdown()
        port1.shutdown()
        port2.shutdown()


# ====================================================================== #
#  Критерий 2 — interval_sec троттлит публикацию.                        #
# ====================================================================== #


def test_c2_interval_sec_throttles_publication_by_schedule():
    """Правило с ``interval_sec=1000.0`` пропускает ПЕРВЫЙ вызов и придерживает
    остальные — пять вызовов подряд (доли секунды реального времени, << 1000 с)
    обязаны дать ровно ОДНО попадание в окно, а не пять.

    Реальное время, без инъекции часов: интервал взят заведомо огромным
    относительно любой возможной задержки между вызовами в тесте (разрешение
    часов Windows — 15.6 мс, план — секунды между вызовами теста не набегут).
    """
    policy = ObservationPolicy(
        ObservationPolicyConfig(
            rules={"processes.cam1.stats.heartbeat.count": MetricRule(enabled=True, interval_sec=1000.0)}
        ),
        legacy=None,
    )
    hub = ObservabilityHub("cam1-c2")
    mgr, port = _make_gated_pair("cam1", policy, hub)
    try:
        for _ in range(5):
            mgr.record_metric("heartbeat.count", 1)
        mgr.flush()

        rec = mgr.get_metric("heartbeat.count")
        assert rec is not None, "первый вызов обязан пройти — метрика не появилась вовсе"
        assert rec["count"] == 1.0, (
            f"интервал 1000с обязан пропустить только ПЕРВЫЙ вызов из пяти, "
            f"получено count={rec['count']!r} (пять означало бы отсутствие троттлинга)"
        )
    finally:
        mgr.shutdown()
        port.shutdown()


# ====================================================================== #
#  Критерий 3 — stats.enabled = ПЛОСКОСТЬ (Р-3а). Независим от порта.     #
# ====================================================================== #


def test_c3_stats_enabled_false_disables_the_whole_numbers_plane():
    """``stats.enabled: false`` → readback ``plane_disabled: true``, НОЛЬ записей
    рода ``stats`` в hub за окно, И ``numbers_policy_dropped > 0`` — ПАРА:
    тишина без растущего счётчика не была бы результатом («выключено и не
    считаем»), а была бы неотличима от «никто просто не писал».

    Тест НЕ проходит через порт/политику (критерии 1/2/6/8) — он бьёт по
    конфигу ``StatsManager`` напрямую, тем самым независим от придуманного
    хука ``attach_numbers_policy`` (см. докстринг файла).
    """
    expanded = expand_observability({"stats": {"enabled": False}})["stats"]
    cfg = {
        **expanded,
        "aggregation_interval": 300.0,
        "flush_interval": 300.0,
        "channels": {**(expanded.get("channels") or {}), "file_stats": {"enabled": False}},
    }
    hub = ObservabilityHub("cam1-c3")
    mgr = StatsManager(manager_name="stats_plane_disabled", config=cfg)
    try:
        assert mgr.initialize(), "StatsManager не поднялся — стенд сломан ДО нагрузки"
        assert mgr.attach_observability_hub(hub), "hub-канал не поднялся"

        for _ in range(5):
            mgr.record_metric("capture.frames", 1)
        mgr.flush()

        readback = mgr.observability_readback()
        assert readback.get("plane_disabled") is True, (
            f"observability_readback() обязан показывать plane_disabled=True при stats.enabled=false, "
            f"получено {readback!r}"
        )
        assert mgr.get_all_metrics() == {}, (
            f"плоскость выключена — окно обязано остаться пустым, получено {mgr.get_all_metrics()!r}"
        )
        hub_names = _hub_metric_names(hub)
        assert hub_names == set(), f"НОЛЬ записей рода stats за окно ожидалось, доехало: {hub_names!r}"

        dropped = mgr.get_stats().get("numbers_policy_dropped")
        assert dropped, (
            "ПАРА к тишине: numbers_policy_dropped обязан быть НЕПУСТЫМ/растущим — иначе "
            "'выключено' неотличимо от 'никто не писал'. Получено: " + repr(dropped)
        )
    finally:
        mgr.shutdown()


# ====================================================================== #
#  Критерий 4 — stats.log_snapshots управляет лог-каналом НЕЗАВИСИМО      #
#  от stats.enabled.                                                     #
# ====================================================================== #


def test_c4a_schema_has_log_snapshots_field_separate_from_enabled():
    """Новое поле ``ObservabilityStatsConfig.log_snapshots`` обязано существовать.

    Pydantic-модели проекта не запрещают лишние ключи (``extra`` не задан →
    дефолт v2 ``ignore``) — конструктор с незнакомым полем НЕ бросает, поле
    просто молча теряется. Поэтому проверяется ПРЯМОЙ доступ к атрибуту, а не
    факт успешного конструирования (памятка проекта: «Pydantic extra=ignore
    прячет RED»).
    """
    cfg = ObservabilityConfig.model_validate({"stats": {"log_snapshots": False}})
    assert cfg.stats.log_snapshots is False, "ObservabilityStatsConfig.log_snapshots обязано существовать"


def test_c4b_facade_maps_log_snapshots_not_enabled_to_log_channel():
    """``log_snapshots`` — единственный ключ, решающий судьбу лог-канала статистики;
    ``enabled`` (плоскость, критерий 3) на лог-канал больше НЕ влияет.
    """
    off_by_snapshots = expand_observability({"stats": {"log_snapshots": False}})["stats"]
    assert off_by_snapshots.get("enable_logging") is False, (
        f"log_snapshots=False обязан выключать лог-канал (enable_logging), получено {off_by_snapshots!r}"
    )

    plane_off_but_snapshots_on = expand_observability({"stats": {"enabled": False, "log_snapshots": True}})["stats"]
    assert plane_off_but_snapshots_on.get("enable_logging") is True, (
        "stats.enabled=False (плоскость выключена) НЕ обязан гасить лог-канал сам по себе — "
        f"только log_snapshots решает судьбу канала; получено {plane_off_but_snapshots_on!r}"
    )


# ====================================================================== #
#  Критерий 5 — readback introspect.observability.stats.policy.          #
# ====================================================================== #


def test_c5_readback_shows_policy_rules_hits_and_dropped_by_rule():
    """``introspect.observability.stats.policy`` обязан показывать: правила,
    попадания на правило, ``dropped_by_rule``.

    Хедж тестера (два правдоподобных адреса) снят исполнителем в пользу
    ``stats_plane_report(svc)['stats']['policy']`` — это ДОСЛОВНО адрес,
    названный планом (``introspect.observability.stats.policy``), тогда как
    ``observability_readback()`` уезжает на этаж ниже, в
    ``introspect.observability.effective.stats``. В readback'е остался
    ``plane_disabled`` — состояние КОНФИГА плоскости, которое обязан
    подтверждать ``config_reload_verified``; политика правил — диагностика, и
    живёт она в своей секции.
    """
    policy = ObservationPolicy(
        ObservationPolicyConfig(rules={"processes.cam1.stats.capture.frames": MetricRule(enabled=False)}),
        legacy=None,
    )
    hub = ObservabilityHub("cam1-c5")
    mgr, port = _make_gated_pair("cam1", policy, hub)
    try:
        mgr.record_metric("capture.frames", 1)
        mgr.flush()

        readback = mgr.observability_readback()
        policy_view: Optional[Dict[str, Any]] = readback.get("policy")
        if policy_view is None:
            from ...process_module.managers.observability_wiring import stats_plane_report

            fake_svc = SimpleNamespace(name="cam1", stats_manager=mgr)
            policy_view = (stats_plane_report(fake_svc).get("stats") or {}).get("policy")

        assert policy_view is not None, (
            "ни StatsManager.observability_readback()['policy'], ни "
            "stats_plane_report(svc)['stats']['policy'] не отдали секцию политики — "
            "критерий 5 не закрыт ни по одному из двух правдоподобных адресов"
        )
        assert "rules" in policy_view, f"нет ключа 'rules' в {policy_view!r}"
        assert "hits" in policy_view, f"нет ключа 'hits' в {policy_view!r}"
        assert "dropped_by_rule" in policy_view, f"нет ключа 'dropped_by_rule' в {policy_view!r}"
        dropped_by_rule = policy_view["dropped_by_rule"]
        assert dropped_by_rule.get("processes.cam1.stats.capture.frames") == 1, (
            f"правило поймало ровно 1 попадание — dropped_by_rule обязан это показать: {dropped_by_rule!r}"
        )
    finally:
        mgr.shutdown()
        port.shutdown()


# ====================================================================== #
#  Критерий 6 — пересборка политики на config.reload доставляется в порт. #
# ====================================================================== #


def test_c6_policy_rebuild_reaches_the_port_new_rule_takes_effect_after_reload():
    """«Та же ``apply_observation_policy``, второй потребитель — не второй механизм.»

    Полную дорогу ``config.reload → apply_observation_policy(heartbeat, section)``
    здесь не поднять без живого процесса — эмулируется её НАБЛЮДАЕМЫЙ эффект:
    повторное присоединение НОВОЙ политики к УЖЕ ЖИВОМУ порту обязано
    действовать немедленно (ровно так уже ведёт себя ``_make_gate`` для
    уровней — новый ``ObservationPolicy`` подменяет ссылку целиком, без
    пересоздания гейта/порта). Правило v1 запрещает 'a', правило v2 (после
    «reload») запрещает 'b' и снимает запрет с 'a'.
    """
    policy_v1 = ObservationPolicy(
        ObservationPolicyConfig(rules={"processes.cam1.stats.a": MetricRule(enabled=False)}),
        legacy=None,
    )
    hub = ObservabilityHub("cam1-c6")
    mgr, port = _make_gated_pair("cam1", policy_v1, hub)
    try:
        mgr.record_metric("a", 1)
        mgr.record_metric("b", 1)
        mgr.flush()
        assert mgr.get_metric("a") is None, "правило v1 обязано было запретить 'a'"
        b_before = mgr.get_metric("b")
        assert b_before is not None and b_before["count"] == 1.0

        policy_v2 = ObservationPolicy(
            ObservationPolicyConfig(rules={"processes.cam1.stats.b": MetricRule(enabled=False)}),
            legacy=None,
        )
        port.attach_numbers_policy(policy_v2)

        mgr.record_metric("a", 1)  # v2 разрешает
        mgr.record_metric("b", 1)  # v2 запрещает — не должно доехать
        mgr.flush()

        rec_a = mgr.get_metric("a")
        assert rec_a is not None and rec_a["count"] == 1.0, (
            f"после 'reload' новая политика обязана СНЯТЬ запрет с 'a' — получено {rec_a!r}"
        )
        rec_b = mgr.get_metric("b")
        assert rec_b is not None and rec_b["count"] == 1.0, (
            f"после 'reload' 'b' обязан быть НОВЫМ запретом — второй вызов не долетел, "
            f"count не должен был вырасти сверх 1.0: {rec_b!r}"
        )
    finally:
        mgr.shutdown()
        port.shutdown()


# ====================================================================== #
#  Критерий 7 — громкое предупреждение при чтении старого                #
#  stats.enabled: false (вторая половина критерия; парность — см.         #
#  докстринг файла, раздел «что НЕ проверяется»).                        #
# ====================================================================== #


def test_c7_reading_old_stats_enabled_false_warns_loudly_about_meaning_change(tmp_path, caplog):
    """Старый смысл ``stats.enabled: false`` — «не логировать снапшоты»; новый —
    «плоскость выключена целиком» (Р-3а). Конфиг, написанный ДО этой задачи,
    обязан быть замечен и назван вслух.

    **Дверь — Task 4.11, а не ``ObservabilityConfig.model_validate``.** До
    задачи 4.11 голос жил в валидаторе схемы и звучал на каждый разбор секции
    (три раза на один ``config.reload`` — дефект, который 4.11 и закрыла). Он
    переехал на стадию «применяю»
    (:func:`~process_module.managers.observability_reload.compose_managers_payload`,
    :func:`~process_module.managers.observability_reload._voice_repurposed_stats_enabled`);
    прямой ``model_validate`` больше не голосит — валидатор стал чистым
    парсером (см. его докстринг).

    **Сброс окна голоса — не косметика, а условие осмысленности теста (Task 2.12,
    m1).** С задачи 2.12 это предупреждение дросселируется окном по ключу
    ``stats.enabled.repurposed`` (окно процесса, L0-дефолт 5.0 с), и держатель —
    процессный синглтон. Соседи по ЭТОМУ ЖЕ файлу (``test_c3_*``, ``test_c4b_*``)
    сами прогоняют конфиг со ``stats.enabled: false`` и съедают окно раньше:
    измерено — без сброса файл даёт ``1 failed, 8 passed`` даже в изоляции, и
    красным оказывается именно этот тест. Тест про голос обязан владеть окном
    голоса ровно так же, как тест про время обязан владеть часами; без сброса он
    проверял бы порядок сбора pytest, а не свойство.
    """
    from multiprocess_framework.modules.logger_module.core.windowed_voice import reset_process_voices

    reset_process_voices()
    with caplog.at_level("WARNING"):
        compose_managers_payload({"stats": {"enabled": False}}, log_dir=str(tmp_path))

    messages = "\n".join(r.message for r in caplog.records)
    assert "stats.enabled" in messages or "log_snapshots" in messages, (
        "ожидалось ОДНОКРАТНОЕ громкое предупреждение о смене смысла stats.enabled "
        f"при чтении старого конфига; захваченные WARNING-записи: {caplog.text!r}"
    )


# ====================================================================== #
#  Критерий 8 — М5 (observation-port §3) не нарушен новым гейтом.        #
# ====================================================================== #


def test_c8_single_writer_property_m5_holds_across_both_entry_roads():
    """«Единственность писателя плоскости не нарушена — числа по-прежнему
    доставляет ОДИН путь.»

    Гейт обязан быть ФИЛЬТРОМ внутри единственного пути доставки
    (``attach_observation_port`` → tap → ``_on_port_record``), а не ВТОРЫМ
    путём мимо него. Проверяется ДВАЖДЫ:

    1. запрет действует одинаково и на прямом вызове (``mgr.record_metric``),
       и на слот-дороге ``ObservableMixin._record_metric`` (дорога 3 из
       инвентаря Ф5 Task 5.1) — если бы гейт стоял ТОЛЬКО на одной из дорог,
       вторая тихо обошла бы его;
    2. ``StatsManager.observation_bypasses`` (уже существующий, Ф5) обязан
       остаться ПУСТЫМ — если бы новая политика завела где-то второй путь
       доставки мимо ``attach_observation_port``, этот счётчик вырос бы.
    """
    policy = ObservationPolicy(
        ObservationPolicyConfig(rules={"processes.cam1.stats.gated.metric": MetricRule(enabled=False)}),
        legacy=None,
    )
    hub = ObservabilityHub("cam1-c8")
    mgr, port = _make_gated_pair("cam1", policy, hub)
    try:
        writer = ObservableMixin(managers={"stats": mgr})
        for _ in range(3):
            writer._record_metric("gated.metric", 1)  # дорога 3 (слот-мидлварь)
        for _ in range(3):
            writer._record_metric("open.metric", 1)
        mgr.flush()

        assert mgr.get_metric("gated.metric") is None, (
            "M5/гейт: правило обязано резать метрику независимо от ВХОДНОЙ дороги — "
            "слот-дорога ObservableMixin тоже обязана идти через порт и его политику"
        )
        open_rec = mgr.get_metric("open.metric")
        assert open_rec is not None and open_rec["count"] == 3.0

        assert mgr.observation_bypasses == {}, (
            "M5: гейт обязан быть ФИЛЬТРОМ внутри ЕДИНСТВЕННОГО пути доставки, а не "
            f"вторым путём — observation_bypasses вырос: {mgr.observation_bypasses!r}"
        )
    finally:
        mgr.shutdown()
        port.shutdown()
