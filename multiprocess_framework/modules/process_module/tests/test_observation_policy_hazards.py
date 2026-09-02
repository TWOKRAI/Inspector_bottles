# -*- coding: utf-8 -*-
"""Авторские сторожа МЕХАНИЗМА политики порта (Ф4, задача 4.1).

Независимая приёмка (``test_observation_policy_glob_acceptance.py``) писана от
критериев и вслепую к реализации; она отвечает на «выполняется ли обещанное».
Здесь — то, что видно только изнутри конструкции и чего в критериях нет:

* **атомарная подмена гейта против такта heartbeat** — ссылка обязана
  переприсваиваться на ПОЛНОСТЬЮ собранный объект;
* **срок L3 и возврат к нижнему слою** — кванторно, ≥2 применения слоёв
  (прямое требование задачи, независимым тестером не покрыто вовсе);
* **порядок при пересечении правил ОДНОЙ СТУПЕНИ** — longest-prefix (ADR-PM-042),
  закреплённый двумя пересекающимися правилами и литералом. Старший разряд ключа —
  СТУПЕНЬ ЯВНОСТИ (ред. по блокеру Б1 ревью Ф4), и его сторожа живут в
  test_observation_policy_review_f4.py;
* **правило против легаси-источника** — кто кого перекрывает;
* **голос про правило, не совпавшее ни с чем** — единственная диагностика
  опечатки в ПУТИ (схема её не судит и судить не может);
* **потолки** — тик публикации и центральный троттл видят правила по пути.
"""

from __future__ import annotations

import yaml

from multiprocess_framework.modules.process_module.commands.builtin_commands import BuiltinCommands
from multiprocess_framework.modules.process_module.configs.observability_layers import (
    LAYER_APP,
    OPAQUE_LAYER_PATHS,
    process_observability_layers,
)
from multiprocess_framework.modules.process_module.configs.observation_policy import (
    OBSERVATION_RULES_PATH,
    PORT_SUBTREE_PATTERN,
    SOURCE_LEGACY,
    SOURCE_RULE,
    SOURCE_SUBTREE_DEFAULT,
    ObservationPolicy,
    ObservationPolicyConfig,
    pattern_specificity,
)
from multiprocess_framework.modules.process_module.configs.telemetry_publish_config import (
    TelemetryPublishConfig,
)
from multiprocess_framework.modules.process_module.heartbeat.telemetry import TelemetryGate, capped_metrics
from multiprocess_framework.modules.process_module.managers.observability_reload import (
    apply_observability_layers,
    observability_effective,
    observability_verified,
    telemetry_targets,
)
from multiprocess_framework.modules.process_module.managers.observability_ttl import sweep_session_ttl
from multiprocess_framework.modules.process_module.managers.telemetry_reload import detect_throttle_caps

from .test_telemetry_commands import _FakeLogger, _FakeServices
from .test_telemetry_layers import BOOT_PUBLISH, _Clock

PROC = "cam1"


def _policy(observation: dict | None = None, publish: dict | None = None) -> ObservationPolicy:
    legacy = None if publish is None else TelemetryPublishConfig.from_dict(publish)
    return ObservationPolicy(ObservationPolicyConfig.from_dict(observation), legacy)


def _wired(tmp_path):
    """Процесс с настоящим ``ProcessHeartbeat``, живым гейтом и часами теста."""
    svc = _FakeServices(logger=_FakeLogger())
    svc._config["telemetry"] = {"publish": BOOT_PUBLISH}
    svc._heartbeat._services._config["telemetry"] = {"publish": BOOT_PUBLISH}
    svc._heartbeat._telemetry_gate = svc._heartbeat._build_telemetry_gate()

    cfg_path = tmp_path / "system.yaml"
    cfg_path.write_text(yaml.safe_dump({"observability": {"log_level": "INFO"}}), encoding="utf-8")
    svc._config["observability_config_path"] = str(cfg_path)

    bc = BuiltinCommands(svc)
    bc._register_observability_commands()
    clock = _Clock()
    process_observability_layers(svc).clock = clock
    return svc, svc.command_manager.handlers, clock


def _apply(svc, origin: str = "test") -> dict:
    """Пересборка из слоёв — та же единственная точка, что у команд и watcher'а."""
    layers = process_observability_layers(svc)
    return apply_observability_layers(
        layers,
        logger=getattr(svc, "logger_manager", None),
        **telemetry_targets(svc),
        origin=origin,
    )


# =========================================================================== #
# Опасность 1 — рантайм-подмена гейта против такта heartbeat
# =========================================================================== #
class TestAtomicGateSwapAgainstTheTick:
    """Ссылка ``_telemetry_gate`` меняется на ПОЛНОСТЬЮ собранный объект.

    Шторм потоков здесь ничего не доказал бы: под GIL 3.12 вклиниться между
    двумя байткодами присваивания практически нечем, и зелёный такого теста
    означал бы «не поймали», а не «не бывает». Поэтому свойство проверяется
    БЕЛЫМ ЯЩИКОМ: конструктор нового гейта во время своей работы смотрит, что
    лежит в поле процесса, и обязан видеть там СТАРЫЙ гейт целиком. Инъекция
    «присвоить ссылку до сборки» краснит этот тест немедленно.
    """

    def test_field_still_holds_the_old_gate_while_the_new_one_is_being_built(self, tmp_path) -> None:
        svc, _, _ = _wired(tmp_path)
        hb = svc._heartbeat
        old_gate = hb._telemetry_gate
        assert old_gate is not None, "контроль: без живого гейта проверять подмену нечего"

        seen: list = []
        real_init = TelemetryGate.__init__

        def _spying_init(self, *args, **kwargs):
            seen.append(hb._telemetry_gate)
            real_init(self, *args, **kwargs)
            seen.append(hb._telemetry_gate)

        TelemetryGate.__init__ = _spying_init  # type: ignore[method-assign]
        try:
            hb.apply_observation_policy({"subtree_interval_sec": 0.25})
        finally:
            TelemetryGate.__init__ = real_init  # type: ignore[method-assign]

        assert seen, "конструктор гейта не звался — подмены не было вовсе"
        assert all(observed is old_gate for observed in seen), (
            f"в момент сборки нового гейта поле процесса держало не старый гейт: {seen}"
        )
        assert hb._telemetry_gate is not old_gate, "ссылка не переприсвоена — правка не подействовала"
        assert hb._telemetry_gate.policy.config.subtree_interval_sec == 0.25

    def test_new_gate_starts_with_an_empty_schedule(self, tmp_path) -> None:
        """Расписание нового гейта пустое — одна публикация сразу после правки.

        Свойство названо в докстринге и потому обязано быть измеримым: иначе
        «правка подействует не раньше следующего интервала» и «подействует
        сразу» неразличимы, а лечатся они разным.
        """
        svc, _, _ = _wired(tmp_path)
        hb = svc._heartbeat
        gate = hb._telemetry_gate
        granted = gate.due_plugin_metrics({"w": ["fps"]}, now=0.0)
        assert granted == {"w": {"fps"}}, granted
        # Второй запрос в том же окне — уже придержан (контроль живости расписания).
        assert gate.due_plugin_metrics({"w": ["fps"]}, now=0.1) == {"w": set()}

        hb.apply_observation_policy({"subtree_interval_sec": 60.0})
        fresh = hb._telemetry_gate.due_plugin_metrics({"w": ["fps"]}, now=0.1)
        assert fresh == {"w": {"fps"}}, (
            f"новый гейт унаследовал расписание старого: {fresh} — правка не видна ближайшую минуту"
        )

    def test_a_foreign_reload_does_not_reset_the_port_schedule(self, tmp_path) -> None:
        """``config.reload`` про ЧУЖУЮ ручку не пересобирает гейт порта.

        Пересборка обнуляет расписание, а зовут применение КАЖДЫЙ reload. Без
        сверки содержимого правка ``log_level`` молча меняла бы темп публикации
        порта — чужая ручка двигала бы предохранитель.
        """
        svc, handlers, _ = _wired(tmp_path)
        hb = svc._heartbeat
        before = hb._telemetry_gate
        res = handlers["config.reload"]({"observability": {"log_level": "DEBUG"}})
        assert res["success"] is True
        assert hb._telemetry_gate is before, "гейт порта пересобран правкой log_level"


# =========================================================================== #
# Опасность 2 — срок L3 и возврат к нижнему слою (кванторно, ≥2 применения)
# =========================================================================== #
class TestSessionTtlReturnsPolicyToTheLowerLayer:
    """Рантайм-правка политики порта умирает по сроку и возвращает НИЖНИЙ слой.

    Три применения слоёв, а не одно: L1 → L3 → возврат. Литералы разные у всех
    трёх состояний, поэтому «возврат не случился» и «возврат вернул не туда»
    различимы. Часы — зависимость объекта слоёв (не глобальный ``monotonic``).
    """

    L1_INTERVAL = 7.0
    L3_INTERVAL = 0.5

    #: Лист, решение по которому принимает ИМЕННО дефолт поддерева. Имени нет в
    #: белом списке ``BOOT_PUBLISH`` — и это условие теста, а не деталь: с
    #: порядком «явность → longest-prefix» (блокер Б1 ревью Ф4) явная запись
    #: ``metrics.fps`` перекрывает дефолт поддерева, и на листе ``fps`` темп
    #: перестал бы зависеть от ``subtree_interval_sec`` вовсе — тест мерил бы
    #: чужое правило и молчал бы про своё.
    PORT_ONLY_LEAF = "port_only_metric"

    @classmethod
    def _grants_over_two_ticks(cls, hb) -> int:
        """Сколько раз лист порта проехал за ДВА тика с шагом 1 с — НАБЛЮДАЕМЫЙ темп.

        Читать ``current_observation_policy`` мало: инъекция «частота дефолтного
        правила игнорируется» оставляет readback правдивым (он отдаёт поле
        конфига) и меняет только поведение. Измерено матрицей инъекций 4.1,
        заплата P4: без этой пары тест оставался зелёным. Считается на СВЕЖЕМ
        гейте, чтобы расписание не тянулось из прошлой фазы теста.
        """
        gate = hb._telemetry_gate
        return sum(1 for t in (100.0, 101.0) if gate.due_plugin_metrics({"w": [cls.PORT_ONLY_LEAF]}, now=t)["w"])

    def test_policy_returns_to_the_app_layer_after_the_deadline(self, tmp_path) -> None:
        svc, handlers, clock = _wired(tmp_path)
        hb = svc._heartbeat
        layers = process_observability_layers(svc)

        # Применение №1 — нижний слой (L1, «файл»).
        layers.replace_layer(
            LAYER_APP,
            {"observation": {"subtree_interval_sec": self.L1_INTERVAL}},
            source="system.yaml",
            origin="test:l1",
        )
        _apply(svc)
        assert hb.current_observation_policy()["subtree_interval_sec"] == self.L1_INTERVAL
        assert self._grants_over_two_ticks(hb) == 1, (
            "при интервале 7.0 с за два тика по секунде лист обязан проехать РОВНО раз "
            "— иначе значение слоя L1 наблюдаемо только в readback'е, а не в темпе"
        )

        # Применение №2 — рантайм-правка со сроком (L3).
        res = handlers["config.reload"](
            {"observability": {"observation": {"subtree_interval_sec": self.L3_INTERVAL}}, "ttl": 10}
        )
        assert res["success"] is True, res
        assert hb.current_observation_policy()["subtree_interval_sec"] == self.L3_INTERVAL, res
        assert self._grants_over_two_ticks(hb) == 2, (
            "рантайм-правка 0.5 с не изменила НАБЛЮДАЕМЫЙ темп публикации порта"
        )

        # Применение №3 — срок вышел, подметальщик вернул нижний слой.
        clock.advance(11)
        sweep_session_ttl(svc)
        assert hb.current_observation_policy()["subtree_interval_sec"] == self.L1_INTERVAL, (
            "после истечения срока политика не вернулась к слою L1 — «гейт закрыт» "
            "не имеет срока годности, а обязан иметь"
        )
        assert self._grants_over_two_ticks(hb) == 1, (
            "readback вернулся к слою L1, а темп публикации остался прежним — возврат объявлен и не случился"
        )

    def test_rule_set_is_one_opaque_leaf_so_its_deadline_can_be_swept(self, tmp_path) -> None:
        """Набор правил живёт в слоях ОДНИМ ключом — иначе срок не снять.

        Ключи набора — glob-паттерны с точками; per-ключевая бухгалтерия слоёв
        резала бы паттерн на сегменты пути, и подметальщик искал бы ключ, которого
        в дереве нет: возврат объявлялся бы и не случался. Проверяется ПОВЕДЕНИЕМ
        (правило исчезло по сроку), а не только составом константы.
        """
        assert OBSERVATION_RULES_PATH in OPAQUE_LAYER_PATHS, "набор правил перестал быть непрозрачным листом"

        svc, handlers, clock = _wired(tmp_path)
        hb = svc._heartbeat
        pattern = "processes.*.state.plugins.capture.drops"
        res = handlers["config.reload"](
            {"observability": {"observation": {"rules": {pattern: {"interval_sec": 0.25}}}}, "ttl": 5}
        )
        assert res["success"] is True, res
        assert pattern in hb.current_observation_policy()["rules"], res
        held = list(process_observability_layers(svc).session_keys())
        assert held == [OBSERVATION_RULES_PATH], f"набор правил разложился по слоям поштучно: {held}"

        clock.advance(6)
        sweep_session_ttl(svc)
        assert hb.current_observation_policy()["rules"] == {}, (
            "правило по пути пережило свой срок — снятие непрозрачного листа не сработало"
        )


# =========================================================================== #
# Опасность 3 — порядок при пересечении (решение исполнителя, ADR-PM-042)
# =========================================================================== #
class TestOverlappingRulesResolveByLongestPrefix:
    """Два правила на ОДИН путь — выигрывает точнее адресованное, не строжайшее.

    Сосед по проекту (``telemetry_reload._central_rule_for_metric``) на том же
    пространстве паттернов берёт СТРОЖАЙШИЙ интервал. Расхождение намеренное и
    записано в ``DECISIONS.md``; здесь оно закреплено литералом, чтобы
    «случайно унифицировали» не прошло молча.
    """

    PATH = f"processes.{PROC}.state.plugins.capture.fps"

    def test_narrow_rule_wins_over_wide_one_even_when_it_is_looser(self) -> None:
        policy = _policy(
            {
                "rules": {
                    "processes.*.state.plugins.**": {"interval_sec": 10.0},  # шире и СТРОЖЕ
                    "processes.*.state.plugins.capture.fps": {"interval_sec": 0.5},  # уже и мягче
                }
            },
            publish={},
        )
        decision = policy.resolve(self.PATH)
        assert decision.interval_sec == 0.5, (
            f"победил не самый точный паттерн: {decision} — при выборе «строжайшего» здесь "
            "стояло бы 10.0, и точечная правка оператора была бы невыразима"
        )
        assert decision.pattern == "processes.*.state.plugins.capture.fps", decision
        assert decision.source == SOURCE_RULE, decision

        # Якорь существования у широкого правила: на СВОЁМ пути оно действует.
        wide = policy.resolve(f"processes.{PROC}.state.plugins.other.latency_ms")
        assert wide.interval_sec == 10.0, wide

    def test_equally_specific_rules_resolve_deterministically(self) -> None:
        """Две одинаково специфичные — разрешаются паттерном, а не порядком словаря.

        Без третьей ступени ключа поведение зависело бы от порядка строк в YAML,
        и «одинаковый конфиг — одинаковое поведение» переставало бы выполняться
        молча. Победитель назван литералом: у обоих паттернов 4 литеральных
        сегмента и 6 сегментов всего, поэтому решает третья ступень — строка, и
        ``"…plugins.a.*"`` больше ``"…plugins.*.fps"`` (``'a' > '*'``). Правило
        произвольно, но ОДНО и то же при любом порядке ключей — проверяется
        именно это, а не «правильность» выбора.
        """
        a = "processes.*.state.plugins.*.fps"
        b = "processes.*.state.plugins.a.*"
        assert pattern_specificity(a)[:2] == pattern_specificity(b)[:2], (
            f"выбраны не равноспецифичные паттерны: {pattern_specificity(a)} / {pattern_specificity(b)}"
        )
        forward = _policy({"rules": {a: {"interval_sec": 0.5}, b: {"interval_sec": 9.0}}}, publish={})
        backward = _policy({"rules": {b: {"interval_sec": 9.0}, a: {"interval_sec": 0.5}}}, publish={})
        path = f"processes.{PROC}.state.plugins.a.fps"
        assert forward.resolve(path).interval_sec == backward.resolve(path).interval_sec, (
            "порядок ключей в конфиге изменил решение — детерминизма нет"
        )
        assert forward.resolve(path).pattern == b, forward.resolve(path)
        assert forward.resolve(path).interval_sec == 9.0, forward.resolve(path)

    def test_subtree_default_loses_to_any_explicit_path_rule(self) -> None:
        policy = _policy({"rules": {"processes.*.state.plugins.*.fps": {"interval_sec": 0.25}}}, publish={})
        assert policy.resolve(self.PATH).source == SOURCE_RULE
        # Якорь: соседний лист того же писателя — по-прежнему дефолт поддерева.
        neighbour = policy.resolve(f"processes.{PROC}.state.plugins.capture.drops")
        assert neighbour.source == SOURCE_SUBTREE_DEFAULT, neighbour
        assert neighbour.pattern == PORT_SUBTREE_PATTERN, neighbour


# =========================================================================== #
# Опасность 4 — правило по пути против ЛЕГАСИ-источника
# =========================================================================== #
class TestRuleBeatsLegacySourceOutsideStaysLegacy:
    """Легаси-секция ``telemetry.publish`` — источник, а не вторая дверь."""

    def test_path_rule_overrides_the_legacy_metric_rule_for_the_same_leaf(self) -> None:
        policy = _policy(
            {"rules": {"processes.*.state.plugins.*.fps": {"interval_sec": 0.5}}},
            publish={"metrics": {"fps": {"interval_sec": 30.0}}},
        )
        port = policy.resolve(f"processes.{PROC}.state.plugins.capture.fps")
        assert port.interval_sec == 0.5 and port.source == SOURCE_RULE, port
        # Та же метрика во фреймворковой плоскости — по-прежнему легаси-правило.
        framework = policy.resolve(f"processes.{PROC}.state.fps")
        assert framework.interval_sec == 30.0 and framework.source == SOURCE_LEGACY, framework

    def test_legacy_whitelist_still_denies_outside_the_port_subtree(self) -> None:
        policy = _policy(None, publish={"default_enabled": False, "metrics": {"fps": {}}})
        assert policy.resolve(f"processes.{PROC}.state.effective_hz").enabled is False
        assert policy.resolve(f"processes.{PROC}.state.fps").enabled is True
        # А поддерево порта переворот варианта «в» разрешает — обе половины рядом.
        assert policy.resolve(f"processes.{PROC}.state.plugins.a.anything").enabled is True

    def test_without_a_legacy_section_nothing_is_gated_outside_the_subtree(self) -> None:
        """Паритет с ``_build_telemetry_gate`` → ``None``: гейта нет вовсе."""
        policy = _policy(None, publish=None)
        outside = policy.resolve(f"processes.{PROC}.state.effective_hz")
        assert outside.enabled is True and outside.interval_sec == 0.0, outside


# =========================================================================== #
# Опасность 5 — голос про правило, не совпавшее ни с чем
# =========================================================================== #
class TestTypoInAPathRuleHasAVoice:
    """Опечатка в ПУТИ не судится никакой схемой — её видно только по счётчику."""

    def test_a_rule_that_never_matched_is_named(self) -> None:
        policy = _policy(
            {
                "rules": {
                    "procesess.*.state.plugins.*.fps": {"interval_sec": 1.0},  # опечатка в первом сегменте
                    "processes.*.state.plugins.*.fps": {"interval_sec": 2.0},
                }
            },
            publish={},
        )
        # Ф0.4 (m6) РАЗВЕРНУЛА это ожидание. Прежняя редакция требовала обоих
        # правил в `rules_matched_nothing` ДО первого резолва — то есть обвиняла
        # правило в тот же миг, когда его применили. Теперь «ещё не оценивалось»
        # и «оценивалось и не совпало» — два РАЗНЫХ поля, и до первого тика оба
        # правила едут в `rules_pending`, а обвиняемых нет.
        assert policy.rules_pending() == [
            "procesess.*.state.plugins.*.fps",
            "processes.*.state.plugins.*.fps",
        ], "до первого тика оценки оба правила обязаны быть «ещё не оценивались»"
        assert policy.rules_matched_nothing() == [], (
            "правило без единого цикла оценки обвинять не за что — у него не было шанса совпасть"
        )

        policy.resolve(f"processes.{PROC}.state.plugins.capture.fps")
        policy.mark_tick()
        assert policy.rules_matched_nothing() == ["procesess.*.state.plugins.*.fps"], (
            "правило с опечаткой не названо, либо названо совпавшее — счётчик врёт в одну из сторон"
        )
        assert policy.rules_pending() == [], "после первого тика «ещё не оценивалось» пусто"

    def test_empty_segment_in_a_pattern_is_rejected_by_the_schema(self) -> None:
        """Пустой сегмент — отказ, а не «правило про экзотику»."""
        try:
            ObservationPolicyConfig.from_dict({"rules": {"processes..state": {}}})
        except Exception as exc:  # noqa: BLE001 — важен факт отказа и адрес в тексте
            assert "processes..state" in str(exc), exc
        else:  # pragma: no cover — ветка существует ради явного провала
            raise AssertionError("паттерн с пустым сегментом принят молча")


# =========================================================================== #
# Опасность 6 — потолки видят правила по пути
# =========================================================================== #
class TestCapsSeePathRules:
    def test_tick_cap_names_a_glob_rule(self) -> None:
        """Правило по пути упирается в тик так же, как правило по имени."""
        legacy = TelemetryPublishConfig.from_dict({"tick_sec": 1.0})
        policy = _policy({"rules": {"processes.*.state.plugins.*.fps": {"interval_sec": 0.02}}}, publish={})
        capped = dict(capped_metrics(legacy, 1.0, policy))
        assert capped.get("processes.*.state.plugins.*.fps") == 0.02, capped
        # Якорь существования: без политики тот же вызов молчит про glob.
        assert "processes.*.state.plugins.*.fps" not in dict(capped_metrics(legacy, 1.0, None))

    def test_default_subtree_rule_is_capped_too(self) -> None:
        legacy = TelemetryPublishConfig.from_dict({})
        capped = dict(capped_metrics(legacy, 5.0, _policy({"subtree_interval_sec": 1.0})))
        assert capped.get(PORT_SUBTREE_PATTERN) == 1.0, capped

    def test_central_throttle_cap_is_reported_for_a_path_rule(self) -> None:
        """«no silent caps» действует и на язык Ф4 (ADR-PM-017)."""

        class _Throttle:
            rules = {"processes.**.state.plugins.*.fps": 2.0}

        caps = detect_throttle_caps(
            None,
            _Throttle(),
            observation_rules={"processes.*.state.plugins.*.fps": {"enabled": True, "interval_sec": 0.05}},
        )
        assert caps == {
            "processes.*.state.plugins.*.fps": {"publisher_interval_sec": 0.05, "throttle_interval_sec": 2.0}
        }, caps

    def test_no_central_throttle_is_not_a_confirmed_zero(self, tmp_path) -> None:
        """«Сверять было не с чем» и «потолков нет» — разные факты, разные поля.

        **Читается ОТВЕТ КОМАНДЫ, а не внутренний ``expanded``** (блокер Б2 ревью
        Ф4). Прежняя редакция смотрела в словарь, который наружу не отдавался
        вовсе: отчёт вычислялся и выбрасывался, а сторож доказывал харнесс.
        """
        svc, handlers, _ = _wired(tmp_path)
        res = handlers["config.reload"]({"observability": {"observation": {"subtree_interval_sec": 0.5}}})
        assert res["success"] is True, res
        applied = res.get("observation_applied")
        assert applied is not None, f"политика порта не доехала до ОТВЕТА команды: {sorted(res)}"
        assert applied["throttle_checked"] is False, applied
        assert "capped_by_throttle" not in applied, (
            "пустой отчёт о потолках при отсутствующем троттле читался бы как подтверждение"
        )


# =========================================================================== #
# Опасность 7 — вердикт и readback ходят одной дорогой
# =========================================================================== #
class TestVerdictReadsTheLiveGate:
    def test_live_readback_confirms_a_port_edit(self, tmp_path) -> None:
        svc, handlers, _ = _wired(tmp_path)
        requested = {"observation": {"subtree_interval_sec": 0.5}}
        res = handlers["config.reload"]({"observability": requested})
        assert res["success"] is True, res
        assert res["verified"]["verdict"] == "confirmed", res["verified"]
        assert res["verified"]["checked"] > 0, res["verified"]

    def test_a_stale_readback_is_judged_failed_not_confirmed(self, tmp_path) -> None:
        """Контроль небанальности: разойдись живой гейт с запросом — вердикт красный.

        Без этой половины ``confirmed`` выше мог бы означать «сверщик согласен
        сам с собой»: обе стороны считались бы из одного словаря.
        """
        svc, _, _ = _wired(tmp_path)
        effective = observability_effective(heartbeat=svc._heartbeat)
        assert "observation" in effective, effective
        verdict = observability_verified({"observation": {"subtree_interval_sec": 0.5}}, effective)
        assert verdict["verdict"] == "failed", verdict
        assert verdict["mismatches"], verdict


# =========================================================================== #
# Опасность 8 — «применено» против «действует» (находка матрицы инъекций)
# =========================================================================== #
class TestGateActiveSeparatesAppliedFromEffective:
    """``gate_active`` — единственный сигнал, отличающий «применено» от «действует».

    Найдено МАТРИЦЕЙ ИНЪЕКЦИЙ, не чтением: заплата «``gate_active`` всегда
    True» — все три точки (два ответа команды и readback) — оставляла набор
    из 2385 тестов ПОЛНОСТЬЮ зелёным. То есть докстринг обещал оператору
    различение, которого не держал ни один сторож.

    Почему это не косметика. У процесса без секции ``telemetry.publish`` гейта
    нет вовсе (``_build_telemetry_gate`` → ``None``, обратная совместимость), и
    политика порта запоминается, но НЕ действует: частота-предохранитель к
    публикации не применяется, потому что применять её некому. Ответ команды
    при этом честно говорит ``success``. Отличить «правило легло» от «правило
    работает» можно ровно по этому полю — и обе половины пары проверяются
    здесь рядом.
    """

    def test_policy_without_a_gate_is_applied_but_not_active(self) -> None:
        svc = _FakeServices(logger=_FakeLogger())
        heartbeat = svc._heartbeat
        # Секции telemetry.publish нет — паритет с боевым процессом, её не настроившим.
        assert heartbeat._build_telemetry_gate() is None, "предпосылка теста: гейта быть не должно"
        heartbeat._telemetry_gate = None

        applied = heartbeat.apply_observation_policy({"subtree_interval_sec": 7.0})

        assert applied["gate_active"] is False, f"политика без гейта обязана называться НЕ действующей: {applied}"
        # Якорь существования: она именно ПРИМЕНЕНА, а не отвергнута.
        assert applied["subtree_interval_sec"] == 7.0, applied
        assert applied["subtree"] == PORT_SUBTREE_PATTERN, applied
        # Readback — третья точка того же поля, и она врала вместе с первыми двумя.
        assert heartbeat.current_observation_policy()["gate_active"] is False

    def test_policy_with_a_live_gate_is_active(self, tmp_path) -> None:
        svc, _handlers, _clock = _wired(tmp_path)
        heartbeat = svc._heartbeat
        assert heartbeat._telemetry_gate is not None, "предпосылка теста: гейт живой"

        applied = heartbeat.apply_observation_policy({"subtree_interval_sec": 7.0})

        assert applied["gate_active"] is True, applied
        assert heartbeat.current_observation_policy()["gate_active"] is True
        # Литерал тот же, что в паре выше — различает пару ровно gate_active.
        assert applied["subtree_interval_sec"] == 7.0, applied
