# -*- coding: utf-8 -*-
"""Сторожа находок РЕВЬЮ фазы Ф4 плана «порт наблюдений» (итерация 1).

Отдельный файл, а не дописка к ``test_observation_policy_hazards.py``, по одной
причине: там сторожа МЕХАНИЗМА, поставленные автором до ревью, а здесь —
свойства, которых механизм не имел и которые названы снаружи. Смешав их, через
месяц нельзя ответить на вопрос «что именно нашло ревью», а матрица инъекций в
этом проекте и есть доказательство.

Каждый класс называет находку, воспроизведение и вторую половину пары:

* **Б1 / З2** — явное заявление оператора проигрывало УМОЛЧАНИЮ. Порядок стал
  «явность → longest-prefix»; критерий М1 обязан выжить и сторожится тут же;
* **Б2** — отчёт «нет молчаливых потолков» считался и выбрасывался; сторож
  читает ОТВЕТ КОМАНДЫ, а не внутренний словарь;
* **З1** — сверщик потолков был слеп к целым классам правил, включая
  назначенный предохранитель (дефолт поддерева);
* **З3** — диагностика меняла показание, а чужая правка стирала улику.
"""

from __future__ import annotations

import pytest
import yaml

from multiprocess_framework.modules.process_module.commands.builtin_commands import BuiltinCommands
from multiprocess_framework.modules.process_module.configs.observability_layers import (
    process_observability_layers,
)
from multiprocess_framework.modules.process_module.configs.observation_policy import (
    PORT_SUBTREE_PATTERN,
    SOURCE_RULE,
    SOURCE_SUBTREE_DEFAULT,
    SOURCE_WHITELIST,
    TIER_LEGACY_ENTRY,
    TIER_RULE,
    TIER_SUBTREE_DEFAULT,
    TIER_UMBRELLA,
    ObservationPolicy,
    ObservationPolicyConfig,
    cap_candidates,
    resolution_key,
)
from multiprocess_framework.modules.process_module.configs.telemetry_publish_config import (
    TelemetryPublishConfig,
)
from multiprocess_framework.modules.process_module.heartbeat.telemetry import capped_metrics
from multiprocess_framework.modules.process_module.managers.observability_reload import (
    apply_observation_policy,
)
from multiprocess_framework.modules.process_module.managers.telemetry_reload import detect_throttle_caps

from .test_telemetry_commands import _FakeLogger, _FakeServices
from .test_telemetry_layers import BOOT_PUBLISH

PROC = "cam1"


def _policy(observation: dict | None = None, publish: dict | None = None) -> ObservationPolicy:
    legacy = None if publish is None else TelemetryPublishConfig.from_dict(publish)
    return ObservationPolicy(ObservationPolicyConfig.from_dict(observation), legacy)


def _wired(tmp_path):
    """Процесс с настоящим ``ProcessHeartbeat``, живым гейтом и командами."""
    svc = _FakeServices(logger=_FakeLogger())
    svc._config["telemetry"] = {"publish": BOOT_PUBLISH}
    svc._heartbeat._services._config["telemetry"] = {"publish": BOOT_PUBLISH}
    svc._heartbeat._telemetry_gate = svc._heartbeat._build_telemetry_gate()

    cfg_path = tmp_path / "system.yaml"
    cfg_path.write_text(yaml.safe_dump({"observability": {"log_level": "INFO"}}), encoding="utf-8")
    svc._config["observability_config_path"] = str(cfg_path)

    bc = BuiltinCommands(svc)
    bc._register_observability_commands()
    process_observability_layers(svc)
    return svc, svc.command_manager.handlers


class _Throttle:
    """Центральный троттл оркестратора: одно правило на плагинный fps."""

    rules = {"processes.**.state.plugins.*.fps": 2.0}


# =========================================================================== #
# Б1 + З2 — ЯВНОЕ заявление оператора против УМОЛЧАНИЯ
# =========================================================================== #
class TestExplicitOperatorEntryBeatsADefault:
    """Порядок разрешения: явность старше специфичности.

    Воспроизведение до правки (ревью Ф4): оператор запретил ``fps`` записью
    ``telemetry.publish.metrics.fps.enabled: false``, а плагинный лист
    ``…state.plugins.capture.fps`` резолвился ``enabled=True`` источником
    ``subtree_default`` — у дефолта поддерева (3 литерала, 5 сегментов)
    специфичность выше суффиксной формы ``**.fps`` (1 литерал, 2 сегмента).
    Живое следствие: чекбокс и частота ПЛАГИННЫХ строк пульта не делали ничего,
    а команда отвечала ``success``.

    Владелец согласился на «два умолчания в одной секции», но НЕ на «умолчание
    перебивает явное заявление оператора» (решение 2026-08-25).
    """

    #: Оператор ЗАПРЕТИЛ имя руками — и запретил при закрытом общем умолчании.
    LEGACY = {"default_enabled": False, "metrics": {"fps": {"enabled": False}}}
    PLUGIN_FPS = f"processes.{PROC}.state.plugins.capture.fps"
    #: Метрика, которой нет НИГДЕ: ни в белом списке, ни в правилах (критерий М1).
    PLUGIN_NEW = f"processes.{PROC}.state.plugins.capture.brand_new_metric"

    def test_an_explicit_legacy_entry_wins_over_the_subtree_default(self) -> None:
        decision = _policy({}, publish=self.LEGACY).resolve(self.PLUGIN_FPS)
        assert decision.enabled is False, (
            f"оператор ЗАПРЕТИЛ fps, а лист порта едет: {decision} — умолчание перебило заявление"
        )
        assert decision.source == SOURCE_WHITELIST, decision
        assert decision.pattern == "**.fps", decision

    def test_a_brand_new_metric_still_travels_on_the_subtree_default(self) -> None:
        """Вторая половина пары: критерий М1 цел — ноль правок конфига.

        Без неё «явность старше» можно было бы исполнить, вернув всё поддерево
        под deny-by-default, и тест выше остался бы зелёным.
        """
        decision = _policy({}, publish=self.LEGACY).resolve(self.PLUGIN_NEW)
        assert decision.enabled is True, (
            f"новая метрика плагина не поехала при НУЛЕВЫХ правках конфига: {decision} — критерий М1 сломан"
        )
        assert decision.source == SOURCE_SUBTREE_DEFAULT, decision
        assert decision.interval_sec == 1.0, decision

    def test_the_legacy_umbrella_does_not_leak_onto_the_framework_plane(self) -> None:
        """Пара-контроль плоскостей: тот же конфиг, другой путь — другой ответ.

        Зонтик ``default_enabled: false`` на фреймворковой плоскости остаётся
        единственным кандидатом и решает; переворот варианта «в» ограничен
        поддеревом писателей.
        """
        framework = _policy({}, publish=self.LEGACY).resolve(f"processes.{PROC}.state.brand_new_metric")
        assert framework.enabled is False, f"переворот протёк на плоскость фреймворка: {framework}"
        assert framework.pattern == "**", framework

    def test_a_path_rule_still_beats_the_explicit_legacy_entry(self) -> None:
        """Верхняя ступень цела: правило по ПУТИ старше явной записи белого списка."""
        policy = _policy(
            {"rules": {"processes.*.state.plugins.*.fps": {"enabled": True, "interval_sec": 0.5}}},
            publish=self.LEGACY,
        )
        decision = policy.resolve(self.PLUGIN_FPS)
        assert (decision.enabled, decision.interval_sec, decision.source) == (True, 0.5, SOURCE_RULE), decision

    def test_the_order_lives_in_one_key_not_in_branches(self) -> None:
        """Ступени сравнимы ОДНИМ ключом — иначе порядок не проверить одним местом."""
        assert resolution_key(TIER_RULE, "**") > resolution_key(TIER_LEGACY_ENTRY, PORT_SUBTREE_PATTERN)
        assert resolution_key(TIER_LEGACY_ENTRY, "**.fps") > resolution_key(TIER_SUBTREE_DEFAULT, PORT_SUBTREE_PATTERN)
        assert resolution_key(TIER_SUBTREE_DEFAULT, PORT_SUBTREE_PATTERN) > resolution_key(TIER_UMBRELLA, "**")
        # Внутри ОДНОЙ ступени порядок прежний — longest-prefix (ADR-PM-042).
        assert resolution_key(TIER_RULE, "processes.*.state.plugins.capture.fps") > resolution_key(
            TIER_RULE, "processes.*.state.plugins.*.fps"
        )


# =========================================================================== #
# Б2 — отчёт о потолках доезжает до ОТВЕТА КОМАНДЫ
# =========================================================================== #
class TestCapReportReachesTheCommandAnswer:
    """Сторож читает ответ ``config.reload``, а не внутренний ``expanded``.

    Прежний сторож (``test_observation_policy_hazards.py``) смотрел в словарь,
    который команда не отдаёт наружу, — то есть доказывал харнесс. Воспроизведение
    ревью: ответ ``config.reload`` не содержал НИ ``observation_applied``, НИ
    ``throttle_checked``, НИ ``capped_by_throttle``.
    """

    def test_observation_applied_is_a_key_of_the_answer(self, tmp_path) -> None:
        svc, handlers = _wired(tmp_path)
        res = handlers["config.reload"]({"observability": {"observation": {"subtree_interval_sec": 0.5}}})
        assert res["success"] is True, res
        assert "observation_applied" in res, sorted(res)
        applied = res["observation_applied"]
        assert applied["subtree_interval_sec"] == 0.5, applied
        assert applied["subtree"] == PORT_SUBTREE_PATTERN, applied
        # «Сверять было не с чем» — тоже показание, и оно тоже в ОТВЕТЕ.
        assert applied["throttle_checked"] is False, applied
        assert "capped_by_throttle" not in applied, applied

    def test_a_silent_cap_is_named_in_the_answer(self, tmp_path) -> None:
        """Пара к предыдущему: есть троттл — отчёт непустой и лежит там же.

        Без этой половины «ключ есть» доказано только на случае, когда сверять
        не с чем, и всеядный ноль прошёл бы за показание.
        """
        svc, handlers = _wired(tmp_path)
        svc._state_store_manager = _FakeStoreManager(_Throttle())
        res = handlers["config.reload"](
            {"observability": {"observation": {"rules": {"processes.*.state.plugins.*.fps": {"interval_sec": 0.02}}}}}
        )
        assert res["success"] is True, res
        applied = res["observation_applied"]
        assert applied["throttle_checked"] is True, applied
        # Оба кандидата: правило оператора И дефолт поддерева. Второй попал сюда
        # находкой З1 — этот синтетический троттл (2.0 с) строже и его дефолтной
        # секунды. В бою предохранитель мягкий (0.05 с, `manager_setup.py`), и
        # дефолт поддерева в отчёт не попадает — ложной тревоги нет.
        assert applied["capped_by_throttle"] == {
            "processes.*.state.plugins.*.fps": {"publisher_interval_sec": 0.02, "throttle_interval_sec": 2.0},
            PORT_SUBTREE_PATTERN: {"publisher_interval_sec": 1.0, "throttle_interval_sec": 2.0},
        }, applied


class _FakeStoreManager:
    """Держатель central-троттла (у обычного процесса его нет — он у оркестратора)."""

    def __init__(self, throttle) -> None:
        self._throttle = throttle

    def get_middleware(self, name: str):
        return self._throttle if name == "throttle" else None


# =========================================================================== #
# З1 — охват сверщиков потолков
# =========================================================================== #
class TestThrottleCapsSeeEveryRuleClass:
    """Сверка правила по ПУТИ с central-правилом — ПЕРЕСЕЧЕНИЕМ глобов.

    Измерено на прежней редакции (суффикс ``pattern.rsplit(".", 1)[-1]``):
    ``…plugins.*.fps`` судилось, а ``…plugins.capture.*``, ``…plugins.**`` и
    ``…plugins.*.f*`` возвращали ``{}`` МОЛЧА. Дефолт поддерева не судился
    вовсе — он не лежит в ``rules``, — при том что соседний ``capped_metrics``
    его учитывал: два отчёта о потолках расходились в охвате, и несовпавшей
    половиной был назначенный предохранитель варианта «в».
    """

    @pytest.mark.parametrize(
        "pattern",
        [
            "processes.*.state.plugins.*.fps",
            "processes.*.state.plugins.capture.*",
            "processes.*.state.plugins.**",
            "processes.**",
        ],
        ids=["leaf-literal", "wildcard-leaf", "double-star-tail", "everything"],
    )
    def test_a_wildcard_leaf_is_judged_too(self, pattern: str) -> None:
        caps = detect_throttle_caps(
            None,
            _Throttle(),
            observation_rules={pattern: {"enabled": True, "interval_sec": 0.05}},
        )
        assert caps == {pattern: {"publisher_interval_sec": 0.05, "throttle_interval_sec": 2.0}}, caps

    def test_a_rule_that_cannot_touch_the_throttled_paths_is_not_reported(self) -> None:
        """Пара-контроль: матчер не всеяден — иначе «судится» доказано только «да»."""
        caps = detect_throttle_caps(
            None,
            _Throttle(),
            observation_rules={"processes.*.workers.*.fps": {"enabled": True, "interval_sec": 0.05}},
        )
        assert caps == {}, caps

    def test_the_subtree_default_reaches_the_throttle_report(self, tmp_path) -> None:
        """Назначенный предохранитель судится ТЕМ ЖЕ отчётом, что и правила оператора."""
        svc, _handlers = _wired(tmp_path)
        applied = apply_observation_policy(svc._heartbeat, {"subtree_interval_sec": 0.05}, store_throttle=_Throttle())
        assert applied["throttle_checked"] is True, applied
        assert applied["capped_by_throttle"] == {
            PORT_SUBTREE_PATTERN: {"publisher_interval_sec": 0.05, "throttle_interval_sec": 2.0}
        }, applied

    def test_both_cap_reports_agree_on_the_subtree_default(self) -> None:
        """Один сборщик кандидатов — один охват у ОБОИХ сверщиков."""
        legacy = TelemetryPublishConfig.from_dict({})
        policy = _policy({"subtree_interval_sec": 0.05})
        tick_caps = dict(capped_metrics(legacy, 5.0, policy))
        throttle_caps = detect_throttle_caps(
            None, _Throttle(), observation_rules=cap_candidates(policy.effective_view())
        )
        assert PORT_SUBTREE_PATTERN in tick_caps, tick_caps
        assert PORT_SUBTREE_PATTERN in throttle_caps, throttle_caps


# =========================================================================== #
# З3 — диагностика не смеет менять показание, чужая правка не стирает улику
# =========================================================================== #
class TestRuleHitsSurviveDiagnosticsAndRebuilds:
    RULE = "processes.*.state.plugins.*.fps"
    PATH = f"processes.{PROC}.state.plugins.capture.fps"

    def test_provenance_does_not_count_hits(self) -> None:
        """Два подряд диагностических чтения не двигают счёт ни на единицу.

        Воспроизведено на стенде: два ``introspect.observability`` с разницей
        0.3 с БЕЗ единого такта процесса между ними убирали работающее правило
        из списка «не совпало ни с чем» — наблюдатель менял то, что наблюдает.
        """
        policy = _policy({"rules": {self.RULE: {"interval_sec": 1.0}}}, publish={})
        assert policy.rules_matched_nothing() == [self.RULE], "предпосылка: правило ещё ни с чем не совпало"

        policy.provenance_for([self.PATH])
        policy.provenance_for([self.PATH])

        assert policy.rule_hits() == {self.RULE: 0}, policy.rule_hits()
        assert policy.rules_matched_nothing() == [self.RULE], (
            "диагностическое чтение засчиталось попаданием — правило исчезло из списка само собой"
        )

    def test_a_real_resolve_does_count(self) -> None:
        """Якорь существования: боевой резолв счёт ВЕДЁТ, иначе тест выше вакуумен."""
        policy = _policy({"rules": {self.RULE: {"interval_sec": 1.0}}}, publish={})
        policy.resolve(self.PATH)
        policy.resolve(self.PATH)
        assert policy.rule_hits() == {self.RULE: 2}, policy.rule_hits()
        assert policy.rules_matched_nothing() == []

    def test_a_foreign_edit_does_not_erase_the_evidence(self, tmp_path) -> None:
        """Пересборка гейта ЧУЖОЙ правкой не возвращает здоровое правило в «не совпало».

        ``telemetry.reconfigure`` (любое движение пульта) зовёт ``_make_gate``,
        а тот собирает НОВЫЙ ``ObservationPolicy``. До правки счёт обнулялся, и
        единственный голос про опечатку в ПУТИ начинал кричать на работающие
        правила.
        """
        svc, handlers = _wired(tmp_path)
        hb = svc._heartbeat
        hb.apply_observation_policy({"rules": {self.RULE: {"interval_sec": 1.0}}})
        hb._observation_policy.resolve(f"processes.{svc.name}.state.plugins.capture.fps")
        assert hb.current_observation_policy()["rules_matched_nothing"] == [], "предпосылка: правило уже совпало"

        res = handlers["telemetry.reconfigure"]({"publish": {"metrics": {"fps": {"enabled": True}}}})
        assert res["success"] is True, res

        view = hb.current_observation_policy()
        assert view["rules_matched_nothing"] == [], (
            f"чужая правка стёрла улику — правило вернулось в «ни разу не совпало»: {view}"
        )
        assert view["rule_hits"][self.RULE] >= 1, view

    def test_a_rewritten_rule_starts_from_zero(self) -> None:
        """Пара-контроль: перенос не всеяден — другой текст правила = другое правило."""
        first = ObservationPolicy(ObservationPolicyConfig.from_dict({"rules": {self.RULE: {"interval_sec": 1.0}}}))
        first.resolve(self.PATH)
        second = ObservationPolicy(
            ObservationPolicyConfig.from_dict({"rules": {"processes.*.state.plugins.*.drops": {}}}),
            hits=first.rule_hits(),
        )
        assert second.rule_hits() == {"processes.*.state.plugins.*.drops": 0}, second.rule_hits()


# =========================================================================== #
# Б1, третий заход — вердикт о ПУТИ, которого не существует
# =========================================================================== #
class TestResolvedNamesThePathsWhereTheMetricActuallyLives:
    """Имя из каталога может не жить в плоскости, о которой отвечает ``resolved``.

    Найдено ЖИВЫМ СТЕНДОМ 2026-08-26, уже после ремонта Б1. Ответ
    ``introspect.telemetry`` нёс ``capture_fps: {enabled: false, path:
    processes.camera_0.state.capture_fps}`` — по этому пути не пишет никто, —
    в то время как в дереве по пути ``processes.camera_0.state.plugins.capture.
    capture_fps`` стояло живое 21.3. Первый ремонт добавил путь и предупреждение
    ``resolved_plane``; предупреждение — не ответ, и отрицательный вердикт рядом
    с работающим числом продолжал читаться как «метрика погашена».

    Пара обязательна: имя, живущее у писателя, несёт вердикты по РЕАЛЬНЫМ путям,
    а имя, у писателей не живущее, их НЕ несёт — иначе тест зелен и у реализации,
    которая приписывает ``port_paths`` каждому имени подряд.
    """

    @staticmethod
    @pytest.fixture
    def wired_with_port(tmp_path):
        """Процесс, у которого метрика ОБЪЯВЛЕНА плагином и ПУБЛИКУЕТСЯ писателем.

        Каталог наполняется объявлением (``declare_metric``), а не литералом —
        иначе имени не будет в ``gated_metrics()`` и тест доказывал бы отсутствие
        имени, а не форму вердикта. Объявление снимается по имени
        (``forget_declarations(names=...)``): сплошная очистка унесла бы чужие.
        """
        from multiprocess_framework.modules.observability_declarations import (
            declare_metric,
            forget_declarations,
        )
        from multiprocess_framework.modules.statistics_module.observation.observation_manager import (
            observation_port,
        )

        declare_metric("capture_fps", owner="tests.review_f4")
        try:
            svc, handlers = _wired(tmp_path)
            # БОЕВАЯ форма секции: `default_enabled: false` + белый список из двух
            # имён (`system.yaml` прототипа). Без неё зонтик легаси разрешает всё,
            # плоскость и порт отвечают одинаково — и расхождение, ради которого
            # тест написан, не воспроизводится вовсе.
            prod = {
                "default_enabled": False,
                "default_interval_sec": 1.0,
                "metrics": {
                    "fps": {"enabled": True, "interval_sec": 1.0},
                    "latency_ms": {"enabled": True, "interval_sec": 1.0},
                },
            }
            svc._config["telemetry"] = {"publish": prod}
            svc._heartbeat._services._config["telemetry"] = {"publish": prod}
            svc._heartbeat._telemetry_gate = svc._heartbeat._build_telemetry_gate()
            port = observation_port(svc._heartbeat._services, create=True)
            port.publish("capture_fps", 21.3, "capture")
            yield svc, handlers
        finally:
            forget_declarations(names=["capture_fps"])

    def test_a_writer_owned_name_carries_verdicts_for_its_real_paths(self, wired_with_port) -> None:
        svc, _handlers = wired_with_port
        resolved = svc._heartbeat.current_resolved_metrics()

        entry = resolved["capture_fps"]
        assert entry["path"] == "processes.camera_0.state.capture_fps", entry
        assert entry.get("also_decided_by_port") is True, entry
        port_paths = entry.get("port_paths") or {}
        real = "processes.camera_0.state.plugins.capture.capture_fps"
        assert real in port_paths, f"вердикт по реальному пути отсутствует: {entry}"
        # Дефолт поддерева порта разрешает лист — ровно то, что видно в дереве.
        assert port_paths[real]["enabled"] is True, port_paths
        assert port_paths[real]["interval_sec"] == 1.0, port_paths
        # И вердикты РАЗНЫЕ — иначе находка не воспроизведена: именно расхождение
        # «плоскость молчит / путь работает» вводило оператора в заблуждение.
        assert entry["enabled"] is False, entry
        assert entry["enabled"] != port_paths[real]["enabled"], entry

    def test_a_name_no_writer_owns_carries_no_port_paths(self, wired_with_port) -> None:
        svc, _handlers = wired_with_port
        resolved = svc._heartbeat.current_resolved_metrics()

        # `shm` объявлен фреймворком и ни одним писателем порта не публикуется.
        entry = resolved["shm"]
        assert "port_paths" not in entry, entry
        assert "also_decided_by_port" not in entry, entry
        # Якорь существования: запись жива и несёт вердикт своей плоскости.
        assert entry["path"] == "processes.camera_0.state.shm", entry
        assert isinstance(entry["enabled"], bool), entry


# =========================================================================== #
# Итерация 2 ревью — правило БЕЗ явной частоты и утвердительный ноль
# =========================================================================== #
class TestInheritedIntervalIsJudgedToo:
    """``interval_sec: None`` — это «возьми дефолт», а не «неизвестно».

    Блокер итерации 2. Сверщик делал ``continue`` на правиле без явной частоты,
    и ответ команды отдавал ``throttle_checked: true`` с ПУСТЫМ списком — то
    есть утверждал «сверено, потолков нет» там, где троттл резал 0.05 с до
    2.0 с. Сосед (``capped_metrics``) ту же форму судил, подставляя
    ``default_interval_sec``: два сверщика снова расходились, теперь не охватом
    кандидатов, а разрешением частоты.

    Форма не экзотическая: ``{"enabled": true}`` — обычный способ переоткрыть
    лист при ``subtree_enabled: false``, и ``MetricRule.interval_sec`` по схеме
    равен ``None``.
    """

    def test_a_rule_without_an_explicit_interval_is_judged_by_the_inherited_one(self) -> None:
        caps = detect_throttle_caps(
            {"default_interval_sec": 0.05},
            _Throttle(),
            observation_rules={"processes.*.state.plugins.*.fps": {"enabled": True}},
        )
        assert caps == {
            "processes.*.state.plugins.*.fps": {
                "publisher_interval_sec": 0.05,
                "throttle_interval_sec": 2.0,
            }
        }, caps

    def test_a_disabled_rule_is_still_not_judged(self) -> None:
        """Пара: выключенное правило ничего не публикует — потолок ему не нужен."""
        caps = detect_throttle_caps(
            {"default_interval_sec": 0.05},
            _Throttle(),
            observation_rules={"processes.*.state.plugins.*.fps": {"enabled": False}},
        )
        assert caps == {}, caps

    def test_inherited_interval_matches_the_schema_default(self) -> None:
        """Литерал сверщика и схемный дефолт — одно число, и это проверяется.

        Сверщик не импортирует схему ради одного значения; расхождение было бы
        молчаливым, поэтому оно пришпилено здесь.
        """
        from multiprocess_framework.modules.process_module.configs.telemetry_publish_config import (
            TelemetryPublishConfig,
        )

        schema_default = TelemetryPublishConfig.from_dict({}).default_interval_sec
        assert schema_default == 1.0, schema_default
        # Секции нет вовсе → сверщик обязан взять то же число.
        caps = detect_throttle_caps(
            None,
            _Throttle(),
            observation_rules={"processes.*.state.plugins.*.fps": {"enabled": True}},
        )
        assert caps["processes.*.state.plugins.*.fps"]["publisher_interval_sec"] == schema_default, caps


class TestAWhitelistEntryOutranksTheSubtreeFrequencyToo:
    """Зеркало Б1: запись имени перекрывает дефолт поддерева и по ЧАСТОТЕ.

    Названо ревью (итерация 2) и измерено на БОЕВОЙ секции прототипа
    (`system.yaml`: `default_enabled: false`, белый список `{fps, latency_ms}`).
    Ступень явности решала блокер про `enabled`, но действует она на весь
    кандидат целиком — значит `subtree_interval_sec`, назначенный предохранителем
    варианта «в», не управляет листьями, чьи ИМЕНА попали в белый список.

    Это цена решения владельца, а не дефект, — и потому она пришпилена
    литералами: молчаливое изменение здесь выглядело бы как «предохранитель
    работает», пока кто-нибудь не замерит темп.
    """

    PROD = {
        "default_enabled": False,
        "default_interval_sec": 1.0,
        "metrics": {
            "fps": {"enabled": True, "interval_sec": 1.0},
            "latency_ms": {"enabled": True, "interval_sec": 1.0},
        },
    }

    def test_the_subtree_frequency_does_not_reach_a_whitelisted_name(self) -> None:
        policy = _policy({"subtree_interval_sec": 0.2}, publish=self.PROD)

        listed = policy.resolve(f"processes.{PROC}.state.plugins.capture.fps")
        assert (listed.interval_sec, listed.source) == (1.0, SOURCE_WHITELIST), listed

        # Якорь существования той же ручки: имя ВНЕ белого списка ускоряется.
        free = policy.resolve(f"processes.{PROC}.state.plugins.capture.drops")
        assert (free.interval_sec, free.source) == (0.2, SOURCE_SUBTREE_DEFAULT), free

    def test_a_path_rule_is_the_named_way_out(self) -> None:
        """Выход выразим существующим языком — ступень 3 перекрывает запись имени."""
        policy = _policy(
            {"subtree_interval_sec": 0.2, "rules": {"processes.*.state.plugins.*.fps": {"interval_sec": 0.2}}},
            publish=self.PROD,
        )
        listed = policy.resolve(f"processes.{PROC}.state.plugins.capture.fps")
        assert (listed.interval_sec, listed.source) == (0.2, SOURCE_RULE), listed
