# -*- coding: utf-8 -*-
"""Слепая приёмка Task 2.11 плана ``observability-closure`` («достижимый дефолт
поддерева») — коммит ДО реализации, отдельный worktree на ``069ddcf6``.

**Что меняет задача (по брифу, а не по чтению запрещённых файлов).** Дефолт
поддерева порта (``processes.*.state.plugins.**``) сегодня заявляет
``interval_sec=1.0`` — быстрее дефолтного такта (``heartbeat_interval_sec=5.0``,
``tick_sec`` не задан). Значит СЕГОДНЯ, на чистом боевом дефолте, без единой
операторской правки, сверка «что ограничено тиком» уже видит поддерево
зажатым, и голос уже звучит на КАЖДОМ старте процесса — то самое, что критерий
К1 называет нечестной тишиной наоборот («шумит по умолчанию»). Владелец решил
(Р-11, ``plans/observability-closure/``, недоступно этому файлу) — новый дефолт
0.0 («не чаще такта»): поддерево ничего не ЗАЯВЛЯЕТ, поэтому и упереться ему не
во что, и голос при чистом дефолте обязан замолчать.

**Запрещено читать** (по инструкции брифа, соблюдено): ``plans/`` целиком,
``configs/observation_policy.py``, ``heartbeat/process_heartbeat.py``,
``heartbeat/telemetry.py``. Утечек не было — все факты ниже собраны grep'ом по
их СОСЕДЯМ (``managers/observability_reload.py``, ``managers/telemetry_reload.py``,
``commands/builtin_commands.py``, ``statistics_module/observation/numbers_gate.py``
и test-файлам пакета) и импортами их ПУБЛИЧНЫХ имён — так же, как это уже
делают ``test_observation_policy_review_f4.py`` и ``test_f2_task23_honest_tick.py``.

**Гаданный/подтверждённый API, использованный ниже** (см. докстринги отдельных
тестов, где расписано подробнее):

1. ``ProcessHeartbeat.apply_observation_policy(section: dict) -> dict`` —
   СУЩЕСТВУЮЩИЙ метод (не гадание): ``getattr(heartbeat, "apply_observation_policy",
   None)`` в ``managers/observability_reload.py``, а форма ``{"rules": {...}}``
   подтверждена буквальными вызовами в ``test_observation_policy_review_f4.py:331``
   и ``test_introspect_telemetry.py:276``.
2. ``heartbeat.telemetry.capped_metrics(config, tick, policy)`` — СУЩЕСТВУЮЩАЯ
   функция (``test_observation_policy_review_f4.py`` и
   ``test_observation_policy_hazards.py`` уже зовут её ровно так, с ``policy``
   третьим позиционным).
3. ``ProcessHeartbeat._warn_capped_metrics(config)`` — СУЩЕСТВУЮЩИЙ метод
   (``test_f2_task23_honest_tick.py``, ``test_telemetry_tick.py`` уже зовут его
   ровно так, ОДНИМ позиционным ``config``). **Гаданное звено**: что ИМЕННО он
   передаёт третьим параметром в ``capped_metrics()`` внутри себя — сам ли метод
   читает текущую политику порта (``self._telemetry_gate.policy``, атрибут
   ``.policy`` у ``TelemetryGate`` подтверждён ``test_observation_policy_hazards.py``:
   ``hb._telemetry_gate.policy.config.subtree_interval_sec``), или политика
   в голос вообще не долетает. Это ГАДАНИЕ, и К1/К2 ниже написаны ИМЕННО
   ПАРОЙ, чтобы не быть вакуумными в обе стороны (см. докстринг брифа, раздел
   К1): К1 доказывает тишину, К2 — что тот же голос НЕ немой в принципе, тем
   же вызовом с тем же сетапом, только другой политикой.
4. ``TelemetryGate.due_metrics(now, extra={...}) -> set[str]`` и
   ``TelemetryGate._next_due`` — ОБА подтверждены существующими зелёными
   тестами (``test_writer_subtree_hazards.py::test_the_rate_limit_is_shared_...``,
   ``test_f2_numbers_policy_hazards.py::test_the_next_due_back_compat_view_...``).
   К4/К5 используют их НАПРЯМУЮ — ни одного нового имени не гадается.

**Существующие тесты, которым мои критерии ПРОТИВОРЕЧАТ** (см. отчёт тестера,
раздел 4) — оба жёстко пришивают СЕГОДНЯШНИЙ дефолт 1.0 литералом, а не через
константу:

* ``test_observation_policy_glob_acceptance.py::TestProvenanceNamesThreeSources::
  test_three_distinct_source_literals_in_one_resolve_set`` — ``assert
  by_subtree.interval_sec == 1.0``;
* ``test_observation_policy_task25_legacy_adapter.py`` — таблица
  ``PATHS_AND_EXPECTED`` литералит ``1.0`` для ``capture_fps``/``frame_count``/
  ``drops`` (решение поддерева) и докстринг модуля называет
  ``subtree_interval_sec=1.0`` L0-дефолтом текстом.

``test_f2_task23_honest_tick.py::test_the_subtree_defaults_effective_interval_matches_the_tick``
НЕ в списке: он сравнивает с ИМПОРТИРОВАННОЙ константой ``DEFAULT_SUBTREE_INTERVAL_SEC``,
а не с литералом 1.0, и его ``effective_interval_sec == 5.0`` верно при ЛЮБОМ
дефолте ≤ такта (``max(0.0, 5.0) == max(1.0, 5.0) == 5.0``) — эта задача его не красит.
"""

from __future__ import annotations

from multiprocess_framework.modules.process_module.configs.observation_policy import (
    ObservationPolicy,
    ObservationPolicyConfig,
)
from multiprocess_framework.modules.process_module.configs.telemetry_publish_config import (
    MetricRule,
    TelemetryPublishConfig,
)
from multiprocess_framework.modules.process_module.heartbeat.process_heartbeat import (
    ProcessHeartbeat,
)
from multiprocess_framework.modules.process_module.heartbeat.telemetry import (
    TelemetryGate,
    capped_metrics,
)

#: Литерал критерия К1/К3 — паттерн дефолта поддерева порта. НЕ импортирован из
#: ``configs.observation_policy.PORT_SUBTREE_PATTERN`` нарочно: бриф называет
#: его текстом («Паттерн processes.*.state.plugins.** в голосе не упоминается»),
#: и ожидание не должно зависеть от значения константы в проверяемом модуле.
PORT_SUBTREE_PATTERN_LITERAL = "processes.*.state.plugins.**"

#: L0-дефолт heartbeat (см. ``BOOT_HEARTBEAT_INTERVAL`` в ``test_f2_task23_honest_tick.py``,
#: тот же литерал) — ``ProcessHeartbeat.__init__`` до вызова ``.start()``.
BOOT_HEARTBEAT_INTERVAL = 5.0


class _RecordingConfigServices:
    """Своя мини-заглушка для ``ProcessHeartbeat`` — слияние ДВУХ готовых, ни
    одна из которых по отдельности не годится.

    ``_RecordingServices`` (``test_f2_task23_honest_tick.py``) ПОМНИТ голос
    (``log_warning``), но не даёт ``get_config``/``name`` — а
    ``apply_observation_policy`` (см. ``test_observation_policy_hazards.py::
    test_field_still_holds_the_old_gate_while_the_new_one_is_being_built``)
    ПЕРЕСОБИРАЕТ ``_telemetry_gate`` целиком, и цена этого неизвестна без
    чтения запрещённого файла. ``_HeartbeatServices`` (``test_telemetry_commands.py``)
    даёт ``get_config``, но ``log_warning`` у неё нет вовсе — голос молчал бы
    ВСЕГДА, вне зависимости от того, чинит ли эта задача что-то, то есть тест
    на этой заглушке был бы вакуумным по конструкции (см. докстринг
    ``_RecordingServices`` о том же самом). Не правка ни одной из двух чужих
    заглушек (обе используются по имени в других файлах) — своя копия.
    """

    def __init__(self) -> None:
        self.name = "cam1"
        self._config: dict = {}
        self.warnings: list[str] = []

    def get_config(self, key, default=None):
        return self._config.get(key, default)

    def log_warning(self, message, *a, **k) -> None:
        self.warnings.append(message)

    def log_info(self, *a, **k) -> None: ...

    def log_debug(self, *a, **k) -> None: ...


def _default_policy() -> ObservationPolicy:
    """Политика порта в дефолтном состоянии — оператор НИЧЕГО не написал.

    Тот же рецепт, что ``_policy()`` в ``test_observation_policy_review_f4.py``
    (``ObservationPolicy(ObservationPolicyConfig.from_dict(None))``), без
    легаси-конфига (второй позиционный ``None`` по умолчанию) — легаси-плоскость
    к этому критерию не относится.
    """
    return ObservationPolicy(ObservationPolicyConfig.from_dict(None))


def _policy_with_rule(rules: dict) -> ObservationPolicy:
    """Политика порта с ОДНИМ явным правилом оператора — та же форма секции
    ``observability.observation``, что ``{"rules": {...}}`` в
    ``hb.apply_observation_policy(...)`` (см. докстринг модуля, пункт 1).
    """
    return ObservationPolicy(ObservationPolicyConfig.from_dict({"rules": rules}))


# =========================================================================== #
# К1 — чистый дефолт молчит, и молчит ПО СУЩЕСТВУ (политика ПЕРЕДАНА)
# =========================================================================== #
class TestBootStaysHonestlySilentOnACleanDefault:
    """К1: heartbeat_interval_sec=5.0, tick_sec НЕ задан, оператор политику порта
    не трогал — сверка «что ограничено тиком» пуста, и WARNING не звучит.

    Существенно, что политика порта в обоих тестах ПОСТРОЕНА и ПЕРЕДАНА явно
    (``_default_policy()``, третий позиционный аргумент ``capped_metrics``,
    затем ``hb.apply_observation_policy({})`` — та же СЕКЦИЯ, которую боевой
    reload передаёт при пустой ``observability.observation``) — не ``None``,
    иначе тишина ничего не доказывала бы (см. докстринг брифа, критерий К1:
    «тест, который добивается тишины тем, что политику не передаёт, вакуумно
    зелен»). Пара с К2 (тот же сетап, явное правило) закрывает вакуумность
    с другой стороны: если бы голос был немой ВСЕГДА, К2 покраснел бы тоже.
    """

    def test_the_tick_capping_check_is_empty_with_the_default_subtree_rule(self) -> None:
        """Сегодня ``PORT_SUBTREE_PATTERN`` уже в этом отчёте (дефолт 1.0 <
        такта 5.0 = «зажат») — до фикса это КРАСНО. После фикса (дефолт 0.0 —
        заявленной частоты нет) отчёт обязан быть пуст.

        Как падает сегодня: ``PORT_SUBTREE_PATTERN_LITERAL in dict(...)`` —
        True, тест падает ``AssertionError`` на первой же строке.
        """
        policy = _default_policy()
        legacy = TelemetryPublishConfig.from_dict({})

        caps = dict(capped_metrics(legacy, BOOT_HEARTBEAT_INTERVAL, policy))

        assert PORT_SUBTREE_PATTERN_LITERAL not in caps, caps
        assert caps == {}, caps

    def test_no_warning_sounds_with_the_default_subtree_rule_and_policy_passed(self) -> None:
        """Тот же сценарий, но через РЕАЛЬНЫЙ голос ``_warn_capped_metrics`` —
        не через изолированную ``capped_metrics()``, а через метод, который
        реально пишет в лог процесса при боевом ``config.reload``/boot.

        **Вторая половина — якорь достижимости** (см. правило проекта:
        утверждение об отсутствии требует парной проверки, что тот же механизм
        при другом входе заговорить УМЕЕТ). Голая тишина на дефолте ничего не
        доказывает, если голос вообще ослеп к политике порта: ОДИН И ТОТ ЖЕ
        ``hb`` сначала получает дефолтную политику (молчит) и СРАЗУ ЖЕ —
        заведомо перегруженную (интервал 0.001с при такте 5.0с, зажат
        абсолютно бесспорно) и обязан заговорить. Если голос НЕ читает
        политику порта вовсе — вторая половина останется пустой ТОЖЕ, и тест
        упадёт именно там, а не тихо сойдёт за подтверждение.

        Прогон на коммите ДО правки (эмпирически, до фикса теста): первая
        половина (дефолт молчит) зелена уже сегодня, но ПО НЕВЕРНОЙ причине —
        ``_warn_capped_metrics`` при ``config.tick_sec is None`` СЕГОДНЯ не
        читает политику порта вообще (то же самое, что красит К2, ветка
        ``tick_sec=None``), поэтому голая первая половина была бы вакуумной.
        Вторая половина ловит это: перегруженное правило тоже молчит →
        ``AssertionError`` на последней строке.
        """
        services = _RecordingConfigServices()
        hb = ProcessHeartbeat(services)
        hb.apply_observation_policy({})

        hb._warn_capped_metrics(TelemetryPublishConfig.from_dict({}))

        assert services.warnings == [], services.warnings

        # Якорь достижимости: та же политика, теперь заведомо перегруженная.
        overloaded_pattern = PORT_SUBTREE_PATTERN_LITERAL + ".probe"
        hb.apply_observation_policy({"rules": {overloaded_pattern: {"interval_sec": 0.001}}})
        hb._warn_capped_metrics(TelemetryPublishConfig.from_dict({}))

        assert services.warnings, (
            "заведомо перегруженное правило (0.001с при такте 5.0с) промолчало — "
            "голос вообще не слушает политику порта, тишина дефолта выше ничего не доказывает"
        )


# =========================================================================== #
# К2 — тот же голос слышен в ОБЕИХ ветках tick_sec, явным правилом оператора
# =========================================================================== #
class TestOperatorRuleIsHeardInBothTickBranches:
    """К2: явное правило ``{"processes.*.state.plugins.**.fps": {"interval_sec":
    1.0}}`` при heartbeat_interval_sec=5.0 обязано дать голос ДВА раза из двух
    — при tick_sec не заданном (такт 5.0) и при tick_sec=2.0 (такт 2.0).

    Пара тестов, а не один: сегодня ветка ``tick_sec is None`` для ФРЕЙМВОРКОВЫХ
    метрик уже чинилась в Task 2.3 (``test_telemetry_tick.py::
    test_warns_when_tick_sec_none_and_heartbeat_alone_caps_it``), но там
    ПОЛИТИКА ПОРТА не участвовала вовсе — эта задача проверяет её отдельно,
    именно в None-ветке, без отдельного теста которая осталась бы непроверенной
    (см. докстринг брифа, критерий К2).
    """

    RULE_PATTERN = "processes.*.state.plugins.**.fps"

    def test_tick_sec_none_the_effective_tick_is_the_heartbeat_default(self) -> None:
        """tick_sec не задан → эффективный такт = heartbeat_interval (5.0).
        Правило просит 1.0с — быстрее такта, значит зажато, и голос обязан
        назвать паттерн.
        """
        policy = _policy_with_rule({self.RULE_PATTERN: {"interval_sec": 1.0}})
        legacy = TelemetryPublishConfig.from_dict({})
        caps = dict(capped_metrics(legacy, BOOT_HEARTBEAT_INTERVAL, policy))
        assert self.RULE_PATTERN in caps, caps

        services = _RecordingConfigServices()
        hb = ProcessHeartbeat(services)
        hb.apply_observation_policy({"rules": {self.RULE_PATTERN: {"interval_sec": 1.0}}})

        hb._warn_capped_metrics(TelemetryPublishConfig.from_dict({}))

        assert services.warnings, "нет ни одного WARNING — правило просит 1.0с при такте 5.0с"
        assert any(self.RULE_PATTERN in message for message in services.warnings), services.warnings

    def test_tick_sec_explicit_the_effective_tick_is_the_configured_tick(self) -> None:
        """tick_sec=2.0 (явно, быстрее heartbeat_interval=5.0) → эффективный
        такт = 2.0 (``min``). Правило по-прежнему просит 1.0с — быстрее такта,
        значит зажато и в ЭТОЙ ветке тоже, другим числом.

        **Эмпирически (прогон на коммите ДО правки) — этот тест УЖЕ ЗЕЛЁН
        сегодня**, и это ожидаемо, а не находка: бриф прямо называет асимметрию
        («сегодня ветка tick_sec is None политику порта отбрасывает») — читай
        как «а явная ветка, значит, её уже не отбрасывает». Прогон подтвердил
        ровно это: голос слышит паттерн при ``tick_sec=2.0``, но не слышит при
        ``tick_sec=None`` (см. соседний тест этого же класса — падает).
        Оставлен как парный контроль: чинить К2 нужно ТОЛЬКО ветку ``None``, и
        если починка случайно снесёт уже рабочую явную ветку — это тест поймает.
        """
        policy = _policy_with_rule({self.RULE_PATTERN: {"interval_sec": 1.0}})
        explicit_tick = 2.0
        legacy = TelemetryPublishConfig.from_dict({"tick_sec": explicit_tick})
        caps = dict(capped_metrics(legacy, explicit_tick, policy))
        assert self.RULE_PATTERN in caps, caps

        services = _RecordingConfigServices()
        hb = ProcessHeartbeat(services)
        hb.apply_observation_policy({"rules": {self.RULE_PATTERN: {"interval_sec": 1.0}}})

        hb._warn_capped_metrics(TelemetryPublishConfig.from_dict({"tick_sec": explicit_tick}))

        assert services.warnings, "нет ни одного WARNING — правило просит 1.0с при такте 2.0с"
        assert any(self.RULE_PATTERN in message for message in services.warnings), services.warnings


# =========================================================================== #
# К3 — дефолт поддерева достижим при дефолтном такте (readback)
# =========================================================================== #
class TestSubtreeDefaultReachesTheReadback:
    """К3: readback дефолтного правила поддерева при heartbeat_interval_sec=5.0,
    tick_sec НЕ заданном: ``effective_interval_sec == 5.0`` (литерал),
    ``interval_sec == 0.0`` (литерал — заявленная частота дефолта, новый
    контракт Р-11).

    Харнесс — ``_wired_with_introspect`` (``test_f2_task23_honest_tick.py``,
    сама дословная копия ``_wired`` из ``test_observation_policy_review_f4.py``
    + регистрация ``introspect.*``) НЕ подходит буквально: она использует
    ``BOOT_PUBLISH = {"tick_sec": 1.0, ...}`` — а этому критерию нужен
    ``tick_sec`` НЕ заданный вовсе. Ниже — ЕЩЁ ОДНА копия того же тела с ОДНОЙ
    правкой (``publish: {}`` вместо ``BOOT_PUBLISH``), а не правка чужой
    (``_wired_with_introspect`` используется по имени в своём файле).
    """

    @staticmethod
    def _wired_no_tick(tmp_path):

        from multiprocess_framework.modules.process_module.commands.builtin_commands import (
            BuiltinCommands,
        )
        from multiprocess_framework.modules.process_module.configs.observability_layers import (
            process_observability_layers,
        )

        from .test_telemetry_commands import _FakeLogger, _FakeServices

        svc = _FakeServices(logger=_FakeLogger())
        svc._config["telemetry"] = {"publish": {}}
        svc._heartbeat._services._config["telemetry"] = {"publish": {}}
        svc._heartbeat._telemetry_gate = svc._heartbeat._build_telemetry_gate()

        cfg_path = tmp_path / "system.yaml"
        cfg_path.write_text('{"observability": {"log_level": "INFO"}}', encoding="utf-8")
        svc._config["observability_config_path"] = str(cfg_path)

        bc = BuiltinCommands(svc)
        bc._register_introspect_commands()
        bc._register_observability_commands()
        process_observability_layers(svc)
        return svc, svc.command_manager.handlers

    def test_the_default_rules_declared_interval_is_zero_and_the_effective_is_the_tick(self, tmp_path) -> None:
        """Прямое чтение ``introspect.observability`` → ``effective.observation.effective``
        по литеральному паттерну (см. модульный докстринг, почему литерал, а
        не импорт константы).

        Как падает сегодня: ``subtree["interval_sec"]`` — 1.0, не 0.0 →
        ``AssertionError`` на второй проверке ниже.
        """
        svc, handlers = self._wired_no_tick(tmp_path)
        assert svc._heartbeat.is_running() is False, "такт обязан остаться дефолтным (.start() не звался)"

        resp = handlers["introspect.observability"]({})

        assert resp["success"] is True, resp
        observation = resp["effective"]["observation"]
        assert "effective" in observation, sorted(observation)
        effective = observation["effective"]
        assert PORT_SUBTREE_PATTERN_LITERAL in effective, (
            sorted(effective) if isinstance(effective, dict) else effective
        )
        subtree = effective[PORT_SUBTREE_PATTERN_LITERAL]

        assert subtree["interval_sec"] == 0.0, subtree
        assert subtree["effective_interval_sec"] == BOOT_HEARTBEAT_INTERVAL, subtree


# =========================================================================== #
# К4 — нулевой интервал не заводит расписания ни на один путь (TelemetryGate)
# =========================================================================== #
class TestZeroIntervalNeverSchedulesAPath:
    """К4: ``TelemetryGate``, принимая решения по путям с нулевым интервалом,
    не создаёт записей в ``_next_due``. Литералами обе половины — 3 разных
    пути при нулевом интервале дают пустое расписание, те же 3 пути при
    интервале 1.0 дают ровно 3 записи (контроль обязателен — см. докстринг
    брифа, К4: без контроля критерий зелен и у гейта, переставшего вести
    расписание вовсе).

    Механизм — ``due_metrics(now, extra={...})`` (подтверждённый, не гаданный,
    см. докстринг модуля п.4): каталог фреймворка ОТКЛЮЧЁН явно (``metrics=
    {имя: MetricRule(enabled=False) for имя in gated_metrics()}``), чтобы
    единственными кандидатами расписания были ровно три ``extra``-имени — иначе
    ``len(gate._next_due) == 3`` было бы неверно уже из-за каталога.

    **Проверено эмпирически, что ``extra`` — это ИМЕНА, а не готовые пути**:
    ``TelemetryGate`` сам строит из них полный путь (``_next_due`` на прогоне
    показал ключ вида ``processes.-.state.<имя>`` — префикс собирает гейт,
    ``extra`` только называет ЛИСТ). Поэтому ниже — три РАЗЛИЧИМЫХ имени, а не
    три готовых dotted-строки; ``_next_due`` всё равно получит три РАЗНЫХ
    полных пути, ключуясь по построенному адресу, а не по сырому имени —
    это и есть «путь» в формулировке критерия К4.
    """

    LEAF_NAMES = ("k211_probe_a", "k211_probe_b", "k211_probe_c")

    @staticmethod
    def _catalog_disabled_metrics() -> dict:
        from multiprocess_framework.modules.process_module.heartbeat.telemetry import gated_metrics

        return {name: MetricRule(enabled=False) for name in gated_metrics()}

    def test_three_zero_interval_paths_schedule_nothing(self) -> None:
        """Как падает сегодня: если сегодня ``interval_sec == 0`` всё равно
        пишет запись в ``_next_due`` (нет короткого замыкания, аналогичного
        ``NumbersGate.allow``'s ``if interval > 0.0 and ...``) — ``len(...)``
        будет 3, не 0, ``AssertionError``.
        """
        cfg = TelemetryPublishConfig(
            default_enabled=True,
            default_interval_sec=0.0,
            metrics=self._catalog_disabled_metrics(),
        )
        gate = TelemetryGate(cfg)

        gate.due_metrics(now=0.0, extra=set(self.LEAF_NAMES))

        assert len(gate._next_due) == 0, gate._next_due

    def test_control_three_one_second_interval_paths_do_schedule(self) -> None:
        """Контроль (вторая половина пары): те же 3 пути, интервал 1.0 —
        расписание ОБЯЗАНО завестись на все три, иначе первая половина теста
        доказывала бы «гейт вообще ничего не планирует», а не «нулевой
        интервал — особый случай».
        """
        cfg = TelemetryPublishConfig(
            default_enabled=True,
            default_interval_sec=1.0,
            metrics=self._catalog_disabled_metrics(),
        )
        gate = TelemetryGate(cfg)

        gate.due_metrics(now=0.0, extra=set(self.LEAF_NAMES))

        assert len(gate._next_due) == 3, gate._next_due


# =========================================================================== #
# К5 — ненулевой интервал по-прежнему придерживает (страховка от К4)
# =========================================================================== #
class TestNonZeroIntervalStillThrottles:
    """К5: правило с ``interval_sec=1.0`` — два решения по ОДНОМУ пути внутри
    одной секунды дают ``True``, затем ``False``. Страховка от того, что
    короткое замыкание К4 (пропустить ``.due()`` при ``interval == 0``) не
    снесёт троттлинг для НЕНУЛЕВЫХ интервалов заодно (например, если охрана
    получится по ошибке ``interval <= 0`` в другом порядке или зацепит вообще
    любой путь).
    """

    def test_two_grants_within_the_interval_give_true_then_false(self) -> None:
        """Как падает, если К4 «лечится» слишком широко (например, гейт вообще
        перестаёт планировать): второй вызов вернёт ``True`` вместо ``False``,
        ``AssertionError`` на второй строке.
        """
        path = "processes.cam1.state.plugins.a.fps"
        cfg = TelemetryPublishConfig(
            default_enabled=True,
            default_interval_sec=1.0,
            metrics=TestZeroIntervalNeverSchedulesAPath._catalog_disabled_metrics(),
        )
        gate = TelemetryGate(cfg)

        first = path in gate.due_metrics(now=0.0, extra={path})
        second = path in gate.due_metrics(now=0.5, extra={path})

        assert first is True, "первое решение внутри пустого расписания обязано быть True"
        assert second is False, "второе решение внутри 1.0с от первого обязано быть придержано"
