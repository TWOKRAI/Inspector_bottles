# -*- coding: utf-8 -*-
"""Опасности МЕХАНИЗМА задачи 2.11 плана ``observability-closure`` (Р-11:
``DEFAULT_SUBTREE_INTERVAL_SEC = 0.0`` — «не чаще такта, без дополнительного
троттла»).

Правило проекта («три роли авторства», ``.claude/CLAUDE.md``): независимый
тестер (``test_f2_task211_reachable_subtree_default.py`` — НЕ трогать, это ТЗ)
уже закрыл контракт приёмки от лица акцептора; здесь — то, что видно только
по УСТРОЙСТВУ механизма и не описано критериями приёмки буквально. Ценность
этого файла — в докстринге каждого класса, отвечающем на вопрос «что здесь
может сломаться»:

1. Короткое замыкание нуля в ``TelemetryGate._grant`` меняет только
   БУХГАЛТЕРИЮ (запись в расписании), а не РЕШЕНИЕ — путь с нулевым
   интервалом получает ``True`` так же, как получал бы созревший ненулевой.
2. Порядок проверок не переставлен: ``enabled=False`` с нулевым интервалом
   по-прежнему даёт ``False`` — короткое замыкание нуля не имеет права
   обогнать проверку ``enabled``.
3. «Ограничено тиком» — утверждение об ЯВНОЙ заявке частоты, которую тик
   срезал. Явный ``interval_sec: 0.0`` оператора — легальная форма «частоты
   не прошу вовсе» (тот же смысл, что у нового дефолта поддерева) и не
   считается зажатым; тот же путь для каталога ИМЁН (легаси
   ``telemetry.publish.metrics``), не только для правил ПОРТА по пути.
4. ``subtree_enabled: False`` не делает поддерево кандидатом вовсе — короткое
   замыкание живёт в ГЕЙТЕ и не имеет права перепутать «поддерево выключено»
   с «поддерево ничего не просит».
5. Отрицательный/нечисловой ``interval_sec``, дошедший до ``capped_metrics``
   мимо схемы (сырым dict'ом от чужой ``effective_view()``), не роняет сверку
   и не искажает решение молча.
6. Пересборка гейта (смена политики на ``config.reload``/``telemetry.reconfigure``)
   не переносит чужое расписание вперёд — ни в одну, ни в другую сторону
   между нулевым и ненулевым интервалом.
7. Добор (найден оркестратором замером на боевых правилах троттла прототипа,
   2026-09-03): нулевой дефолт поддерева доходит и до ВТОРОГО сверщика
   потолков, ``detect_throttle_caps`` (central-троттл, не тик) —
   ``interval_sec <= 0`` обязан судиться по эффективному ТАКТУ, а не по
   голому нулю, и такт неизвестен вызывающему — кандидат пропускается, а не
   флагуется наугад.
"""

from __future__ import annotations

from typing import Any

from multiprocess_framework.modules.process_module.configs.observation_policy import (
    PORT_SUBTREE_PATTERN,
)
from multiprocess_framework.modules.process_module.configs.telemetry_publish_config import (
    MetricRule,
    TelemetryPublishConfig,
)
from multiprocess_framework.modules.process_module.heartbeat.telemetry import (
    TelemetryGate,
    capped_metrics,
)
from multiprocess_framework.modules.process_module.managers.telemetry_reload import (
    detect_throttle_caps,
)

from .test_observation_policy_review_f4 import PROC, _policy


# =========================================================================== #
# 1 — короткое замыкание нуля меняет БУХГАЛТЕРИЮ, не РЕШЕНИЕ
# =========================================================================== #
class TestZeroIntervalGrantsWithoutSchedulingAnEntry:
    """Опасность: короткое замыкание, добавленное задачей 2.11 в
    ``TelemetryGate._grant`` (``if interval <= 0.0: return True``), обязано
    менять ТОЛЬКО факт записи в ``_next_due``, а не решение «пускать ли». Если
    бы короткое замыкание случайно вернуло раннее ``False`` (например, спутав
    «интервал не заявлен» с «метрика выключена»), путь с нулевым интервалом
    перестал бы публиковаться вовсе — молча, без единого WARNING.
    """

    def test_zero_interval_grants_and_leaves_no_schedule_entry(self) -> None:
        """Как падает: если короткое замыкание отдаёт ``False`` вместо
        ``True`` — первая же строка; если замыкания нет вовсе и решение
        уходит в ``PathSchedule.due`` — вторая строка (``_next_due`` заведёт
        запись).
        """
        cfg = TelemetryPublishConfig(default_enabled=True, default_interval_sec=0.0, metrics={})
        gate = TelemetryGate(cfg)
        path = "processes.cam1.state.plugins.a.probe"

        granted = gate._grant(path, "probe", now=0.0)

        assert granted is True, granted
        assert path not in gate._next_due, gate._next_due

    def test_two_consecutive_zero_interval_grants_at_the_same_instant_are_both_true(self) -> None:
        """Контроль: нулевой интервал не троттлит вообще, даже без хода часов —
        не только «первый раз с пустого расписания», а СТАБИЛЬНО.
        """
        cfg = TelemetryPublishConfig(default_enabled=True, default_interval_sec=0.0, metrics={})
        gate = TelemetryGate(cfg)
        path = "processes.cam1.state.plugins.a.probe"

        first = gate._grant(path, "probe", now=0.0)
        second = gate._grant(path, "probe", now=0.0)

        assert first is True, "первое решение по пустому расписанию обязано быть True"
        assert second is True, (
            "второй грант В ТОТ ЖЕ момент времени обязан остаться True — нулевой интервал "
            "не троттлит вообще, даже без хода часов"
        )


# =========================================================================== #
# 2 — enabled=False побеждает даже при нулевом интервале
# =========================================================================== #
class TestDisabledRuleStillWinsOverZeroInterval:
    """Опасность: если короткое замыкание нуля поставить ДО проверки
    ``enabled`` (а не после неё, как в реализации), запрещённый путь с
    нулевым интервалом начнёт получать ``True`` — «отключено» перестанет
    быть отключено для этого частного случая.
    """

    def test_enabled_false_with_zero_interval_is_still_false(self) -> None:
        cfg = TelemetryPublishConfig(
            default_enabled=True,
            default_interval_sec=0.0,
            metrics={"probe": MetricRule(enabled=False, interval_sec=0.0)},
        )
        gate = TelemetryGate(cfg)

        granted = gate._grant("processes.cam1.state.probe", "probe", now=0.0)

        assert granted is False, "enabled=False обязан побеждать даже при interval_sec=0.0"

    def test_control_enabled_true_with_zero_interval_is_true(self) -> None:
        """Контроль пары: тот же нулевой интервал, но ``enabled=True`` —
        грант обязан пройти. Без этой половины первая была бы неотличима от
        «гейт вообще ничего не пускает»."""
        cfg = TelemetryPublishConfig(
            default_enabled=True,
            default_interval_sec=0.0,
            metrics={"probe": MetricRule(enabled=True, interval_sec=0.0)},
        )
        gate = TelemetryGate(cfg)

        granted = gate._grant("processes.cam1.state.probe", "probe", now=0.0)

        assert granted is True, granted


# =========================================================================== #
# 3 — явный ноль оператора не «зажат»; почти-ноль — обычная зажатая заявка
# =========================================================================== #
class TestExplicitZeroIsNotCappedButANearZeroValueIs:
    """«Ограничено тиком» описывает ЗАЯВКУ частоты, которую тик срезал —
    явный ноль оператора (``interval_sec: 0.0``) НЕ заявка, а «частоты не
    прошу вовсе», тот же смысл, что у дефолта поддерева. Пара с почти-нулём
    (``0.001``) доказывает, что граница — не «около нуля намеренно ослаблен
    гейт», а ровно ноль/не-ноль.

    Обе половины ``capped_metrics`` — правило ПОРТА (glob-путь, через
    ``policy``/``cap_candidates``) и легаси-каталог ИМЁН
    (``telemetry.publish.metrics``) — обязаны согласиться, иначе одна половина
    продолжала бы врать про «зажатость» нулевой заявки.
    """

    RULE_PATH = "processes.*.state.plugins.*.probe"

    def test_explicit_zero_rule_by_path_is_not_reported_as_capped(self) -> None:
        legacy = TelemetryPublishConfig.from_dict({})
        policy = _policy({"rules": {self.RULE_PATH: {"interval_sec": 0.0}}})

        capped = dict(capped_metrics(legacy, 5.0, policy))

        assert self.RULE_PATH not in capped, capped

    def test_control_near_zero_rule_by_path_is_still_reported_as_capped(self) -> None:
        legacy = TelemetryPublishConfig.from_dict({})
        policy = _policy({"rules": {self.RULE_PATH: {"interval_sec": 0.001}}})

        capped = dict(capped_metrics(legacy, 5.0, policy))

        assert capped.get(self.RULE_PATH) == 0.001, capped

    def test_explicit_zero_rule_by_name_is_not_reported_as_capped(self) -> None:
        """Тот же вопрос для ПЕРВОЙ половины ``capped_metrics`` — каталог
        явно настроенных имён (``config.metrics``), не только правила
        ПОРТА. ``policy=None`` изолирует эту половину от второй.
        """
        legacy = TelemetryPublishConfig.from_dict({"metrics": {"fps": {"enabled": True, "interval_sec": 0.0}}})

        capped = dict(capped_metrics(legacy, 5.0, None))

        assert "fps" not in capped, capped

    def test_control_near_zero_rule_by_name_is_still_reported_as_capped(self) -> None:
        legacy = TelemetryPublishConfig.from_dict({"metrics": {"fps": {"enabled": True, "interval_sec": 0.001}}})

        capped = dict(capped_metrics(legacy, 5.0, None))

        assert capped.get("fps") == 0.001, capped


# =========================================================================== #
# 4 — subtree_enabled=False не делает поддерево кандидатом
# =========================================================================== #
class TestSubtreeDisabledIsNotACandidateEvenThoughItsIntervalIsZero:
    """Опасность: ``subtree_enabled=False`` обязан выключать дефолт поддерева
    ЦЕЛИКОМ. Короткое замыкание нуля живёт в ``TelemetryGate._grant`` (после
    того, как ``ObservationPolicy.resolve`` УЖЕ решила ``enabled``), а не в
    самой политике — тест ловит регрессию, если бы кто-то перепутал «дефолт
    поддерева выключен оператором» с «дефолт поддерева ничего не просит по
    частоте» и разрешил бы путь по ошибке.
    """

    def test_disabled_subtree_falls_through_to_legacy(self) -> None:
        policy = _policy({"subtree_enabled": False}, publish={"default_enabled": False})

        decision = policy.resolve(f"processes.{PROC}.state.plugins.capture.probe")

        assert decision.source != "subtree_default", decision
        assert decision.enabled is False, decision  # легаси-зонтик default_enabled=False

    def test_control_subtree_enabled_true_is_the_candidate(self) -> None:
        """Контроль пары: та же секция, ``subtree_enabled=True`` — дефолт
        поддерева обязан вернуться победителем, иначе первая половина
        доказывала бы «дефолт поддерева не участвует вовсе», а не
        «выключенный дефолт не участвует»."""
        policy = _policy({"subtree_enabled": True}, publish={"default_enabled": False})

        decision = policy.resolve(f"processes.{PROC}.state.plugins.capture.probe")

        assert decision.source == "subtree_default", decision
        assert decision.enabled is True, decision
        assert decision.interval_sec == 0.0, decision


# =========================================================================== #
# 5 — мусорный/отрицательный interval_sec мимо схемы не роняет сверку
# =========================================================================== #
class _RawViewPolicy:
    """Заглушка политики: отдаёт ЗАРАНЕЕ собранный (возможно, кривой)
    ``effective_view()``.

    Не через ``ObservationPolicy`` — та валидирует ``interval_sec`` схемой
    (``MetricRule``/``ObservationPolicyConfig``, ``min=0.0``) на входе и
    никогда не построит такое значение сама. Опасность — в чужом объекте,
    реализующем тот же протокол ДУКОМ: ``capped_metrics`` вызывает
    ``policy.effective_view()``, не проверяя, откуда он взялся.
    """

    def __init__(self, view: dict) -> None:
        self._view = view

    def effective_view(self) -> dict:
        return self._view


def _raw_subtree_view(interval_sec: Any) -> dict:
    return {
        "subtree": PORT_SUBTREE_PATTERN,
        "subtree_enabled": True,
        "subtree_interval_sec": interval_sec,
        "rules": {},
    }


class TestCappedMetricsToleratesMalformedRawIntervals:
    """``cap_candidates``/``capped_metrics`` читают ``effective_view()`` как
    ЧУЖОЙ dict — вызывающий не обязан быть настоящим ``ObservationPolicy``.
    Отрицательное число или мусор не имеют права уронить сверку и не имеют
    права засчитаться как «зажато» — отсутствие валидной заявки частоты не
    заявка тем более, чем нулевая.
    """

    def test_negative_interval_does_not_crash_and_is_not_capped(self) -> None:
        """Как падает, если бы граница была ``interval < effective_tick`` без
        нижней отсечки: ``-1.0 < 5.0`` истинно, и мусорное отрицательное
        значение попало бы в отчёт как «зажато».
        """
        legacy = TelemetryPublishConfig.from_dict({})
        policy = _RawViewPolicy(_raw_subtree_view(-1.0))

        capped = dict(capped_metrics(legacy, 5.0, policy))

        assert PORT_SUBTREE_PATTERN not in capped, capped

    def test_non_numeric_interval_falls_back_to_the_legacy_default_and_does_not_crash(self) -> None:
        """Нечисловое значение не роняет сверку — используется
        ``legacy.default_interval_sec`` (тот же фолбэк, что уже стоит в
        ``capped_metrics`` для этого случая). Легаси-дефолт здесь ЗАДАН
        нулём намеренно, чтобы граница была однозначной: мусор — не заявка
        частоты, и жаловаться там не на что, ровно как у явного нуля.
        """
        legacy = TelemetryPublishConfig.from_dict({"default_interval_sec": 0.0})
        policy = _RawViewPolicy(_raw_subtree_view("не число"))

        capped = dict(capped_metrics(legacy, 5.0, policy))

        assert PORT_SUBTREE_PATTERN not in capped, capped

    def test_control_non_numeric_interval_with_a_capped_legacy_default_is_reported(self) -> None:
        """Контроль пары: тот же мусор, но легаси-дефолт НЕНУЛЕВОЙ и зажат
        тактом — фолбэк обязан реально участвовать в решении числом, а не
        просто «всегда безопасно молчать» независимо от входа.
        """
        legacy = TelemetryPublishConfig.from_dict({"default_interval_sec": 0.5})
        policy = _RawViewPolicy(_raw_subtree_view("не число"))

        capped = dict(capped_metrics(legacy, 5.0, policy))

        assert capped.get(PORT_SUBTREE_PATTERN) == 0.5, capped


# =========================================================================== #
# 6 — пересборка гейта не переносит чужое расписание
# =========================================================================== #
class TestGateRebuildStartsWithACleanScheduleRegardlessOfInterval:
    """Опасность: если бы расписание жило где-то ВНЕ гейта (модульная
    глобаль, атрибут класса), смена политики (интервал ``1.0`` → ``0.0`` или
    наоборот — то, что реально происходит на ``config.reload``/
    ``telemetry.reconfigure``, каждый из которых собирает НОВЫЙ
    ``TelemetryGate``, см. ``ProcessHeartbeat._make_gate``) переносила бы
    старые записи вперёд — расписание одного гейта продолжало бы придерживать
    решения другого.
    """

    PATH = "processes.cam1.state.plugins.a.probe"

    def test_nonzero_then_zero_rebuild_leaves_no_trace_of_the_old_schedule(self) -> None:
        cfg_nonzero = TelemetryPublishConfig(default_enabled=True, default_interval_sec=1.0, metrics={})
        gate1 = TelemetryGate(cfg_nonzero)
        assert gate1._grant(self.PATH, "probe", now=0.0) is True
        assert self.PATH in gate1._next_due, gate1._next_due  # расписание живое — есть с чем сравнивать

        # Та же "пересборка", что делает `_make_gate` на config.reload/reconfigure.
        cfg_zero = TelemetryPublishConfig(default_enabled=True, default_interval_sec=0.0, metrics={})
        gate2 = TelemetryGate(cfg_zero)

        assert self.PATH not in gate2._next_due, gate2._next_due  # новый гейт не наследует чужое расписание
        assert gate2._grant(self.PATH, "probe", now=0.0) is True
        assert self.PATH not in gate2._next_due, gate2._next_due  # и нулевой интервал не завёл свою запись

    def test_zero_then_nonzero_rebuild_schedules_cleanly(self) -> None:
        """Зеркало предыдущего: ноль → ненулевое, тоже без мусора и без
        потери троттлинга у нового правила."""
        cfg_zero = TelemetryPublishConfig(default_enabled=True, default_interval_sec=0.0, metrics={})
        gate1 = TelemetryGate(cfg_zero)
        assert gate1._grant(self.PATH, "probe", now=0.0) is True
        assert self.PATH not in gate1._next_due, gate1._next_due

        cfg_nonzero = TelemetryPublishConfig(default_enabled=True, default_interval_sec=1.0, metrics={})
        gate2 = TelemetryGate(cfg_nonzero)

        first = gate2._grant(self.PATH, "probe", now=0.0)
        second = gate2._grant(self.PATH, "probe", now=0.5)

        assert first is True, "первый грант нового гейта обязан пройти — расписание чистое"
        assert second is False, "новый ненулевой интервал обязан троттлить немедленно, без прогрева с нуля"


# =========================================================================== #
# 7 — detect_throttle_caps: ноль поддерева судится ТАКТОМ, не голым нулём
# =========================================================================== #
class _FakeCentralThrottle:
    """Держатель central-правил — форма ``ThrottleMiddleware`` по докстрингу
    ``detect_throttle_caps`` (только атрибут ``rules``)."""

    def __init__(self, rules: dict) -> None:
        self.rules = rules


class TestThrottleCapsJudgeZeroByTheEffectiveTickNotByZero:
    """Добор (найден оркестратором замером на боевых правилах троттла
    прототипа, ``manager_setup.py::_default_throttle_rules``, 2026-09-03,
    ПОСЛЕ первого прохода этой задачи): смена ``DEFAULT_SUBTREE_INTERVAL_SEC``
    на ``0.0`` доставляет буквальный ноль и во ВТОРОЙ сверщик потолков —
    ``detect_throttle_caps`` (central-троттл, ``managers/telemetry_reload.py``),
    не только в ``capped_metrics`` (тик). Судить его напрямую вернуло бы
    ровно тот шум, ради снятия которого Р-11 делалась, — только не в голосе
    ``_warn_capped_metrics``, а в поле ``capped_by_throttle`` ответа
    ``config.reload``.

    Throttle-правило ниже (``0.05`` с на весь ``processes.**.state.plugins.**``)
    — не импорт боевого ``manager_setup.py::_default_throttle_rules``:
    ``multiprocess_prototype`` лежит НИЖЕ ``multiprocess_framework`` по слоям
    (правило проекта, ``.sentrux/rules.toml``), framework-тесту нельзя на него
    ссылаться. Число (0.05 с) взято тем же порядком величины, что и боевой
    предохранитель (``_SAFETY_INTERVAL_SEC``), — этого достаточно, чтобы
    воспроизвести КЛАСС находки, не воспроизводя её дословно построчно.
    """

    def test_zero_interval_candidate_is_skipped_when_the_tick_is_unknown(self) -> None:
        """(а), половина 1: такт неизвестен (``effective_tick`` не передан,
        дефолт ``None``) — кандидат с нулевым интервалом не судится вовсе, а
        не «судится нулём» (что дало бы ложный cap почти всегда).
        """
        throttle = _FakeCentralThrottle({"processes.**.state.plugins.**": 0.05})

        caps = detect_throttle_caps(
            None,
            throttle,
            observation_rules={PORT_SUBTREE_PATTERN: {"enabled": True, "interval_sec": 0.0}},
        )

        assert caps == {}, caps

    def test_control_nonzero_interval_candidate_is_still_judged_without_a_tick(self) -> None:
        """(а), половина 2 — контроль: ненулевой интервал по-прежнему судится
        БЕЗ такта. Без этой половины первая доказывала бы «функция вообще
        перестала что-либо находить», а не «нулевой кандидат — особый случай».
        """
        throttle = _FakeCentralThrottle({"processes.**.state.plugins.**": 0.05})

        caps = detect_throttle_caps(
            None,
            throttle,
            observation_rules={PORT_SUBTREE_PATTERN: {"enabled": True, "interval_sec": 0.02}},
        )

        assert caps == {PORT_SUBTREE_PATTERN: {"publisher_interval_sec": 0.02, "throttle_interval_sec": 0.05}}, caps

    def test_a_tick_stricter_than_the_throttle_is_reported(self) -> None:
        """(б): такт СТРОЖЕ троттла (0.01 с при троттле 0.05 с) — срез
        реален, отчёт обязан появиться. Без этого контроля пункт «неизвестный
        такт не флагуется» читался бы как «ноль всегда молчит», а не «ноль
        молчит только когда сравнивать не с чем».
        """
        throttle = _FakeCentralThrottle({"processes.**.state.plugins.**": 0.05})

        caps = detect_throttle_caps(
            None,
            throttle,
            observation_rules={PORT_SUBTREE_PATTERN: {"enabled": True, "interval_sec": 0.0}},
            effective_tick=0.01,
        )

        assert caps == {PORT_SUBTREE_PATTERN: {"publisher_interval_sec": 0.01, "throttle_interval_sec": 0.05}}, caps

    def test_the_production_like_case_the_tick_is_softer_than_the_safety_throttle(self) -> None:
        """(в): такт боевого дефолта (5.0 с, ``heartbeat_interval_sec``) —
        мягче предохранителя троттла (0.05 с) на два порядка. Отчёт обязан
        остаться пустым, а не кричать про предохранитель, которого оператор
        не трогал (ровно находка оркестратора на боевых правилах прототипа).
        """
        throttle = _FakeCentralThrottle({"processes.**.state.plugins.**": 0.05})

        caps = detect_throttle_caps(
            None,
            throttle,
            observation_rules={PORT_SUBTREE_PATTERN: {"enabled": True, "interval_sec": 0.0}},
            effective_tick=5.0,
        )

        assert caps == {}, caps


class TestADegenerateTickIsNotATick:
    """Находка №2 ревью Task 2.11 (2026-09-03): «такта нет» — это не только ``None``.

    Чего не хватало соседнему классу выше: он покрывал ``None``, ``0.01`` и ``5.0`` —
    то есть отсутствие такта и два годных значения. Вырожденный такт (``0.0`` и
    отрицательный) в нём отсутствовал, а он ДОСТИЖИМ, и это проверено, а не
    предположено:

    * ``ObservabilityConfig.heartbeat_interval_sec`` объявлен с ``min=0.0`` — ноль
      схемно легален и означает «heartbeat отключён»;
    * ``ProcessHeartbeat.apply_heartbeat_interval`` отбивает только НЕЧИСЛО
      (``try/except`` вокруг ``float()``), поэтому отрицательное значение слоя
      проходит насквозь: прогон ревьюера дал ``_interval = -3.0`` и
      ``current_telemetry_tick() = -3.0``;
    * ``apply_observation_policy`` берёт этот readback и отдаёт в сверщик как есть.

    Замер ревьюера ДО починки, дословно: при ``effective_tick=0.0`` замещение
    возвращало ``{'processes.*.state.plugins.**': {'publisher_interval_sec': 0.0,
    'throttle_interval_sec': 0.05}}`` — тот самый отчёт, ради снятия которого добор
    и делался, вернувшийся через чёрный ход.

    Что сломается, если это перестанет быть правдой: оператор выключает heartbeat
    (``heartbeat_interval_sec: 0``) — законное действие — и получает при каждой
    пересборке политики тревогу про предохранитель, которого не трогал, с числом
    ``publisher_interval_sec: 0.0``, не означающим никакой частоты.
    """

    THROTTLE = {"processes.**.state.plugins.**": 0.05}
    ZERO_RULE = {PORT_SUBTREE_PATTERN: {"enabled": True, "interval_sec": 0.0}}

    def test_a_zero_tick_is_read_as_no_tick_at_all(self) -> None:
        """``effective_tick=0.0`` (heartbeat отключён) — судить нечем, отчёт пуст."""
        caps = detect_throttle_caps(
            None,
            _FakeCentralThrottle(self.THROTTLE),
            observation_rules=self.ZERO_RULE,
            effective_tick=0.0,
        )

        assert caps == {}, caps

    def test_a_negative_tick_is_read_as_no_tick_at_all(self) -> None:
        """Отрицательный такт — тоже «нет такта», а не «частота быстрее любой».

        Отдельным тестом от нуля, а не параметром: у них РАЗНЫЕ причины
        достижимости (ноль — законное выключение, отрицательное — дыра в
        ``apply_heartbeat_interval``), и слитые в один случай они перестали бы
        различаться при починке одной из причин.
        """
        caps = detect_throttle_caps(
            None,
            _FakeCentralThrottle(self.THROTTLE),
            observation_rules=self.ZERO_RULE,
            effective_tick=-3.0,
        )

        assert caps == {}, caps

    def test_control_a_nonzero_interval_is_still_judged_under_a_degenerate_tick(self) -> None:
        """Контроль: вырожденный такт глушит только кандидата БЕЗ заявки.

        Правило, у которого частота заявлена (0.02 с), от такта не зависит вовсе —
        его ask это он сам, — и обязано судиться по-прежнему. Без этой половины
        первые два теста были бы неотличимы от починки «при кривом такте функция
        замолкает целиком», а это спрятало бы настоящие срезы.
        """
        caps = detect_throttle_caps(
            None,
            _FakeCentralThrottle(self.THROTTLE),
            observation_rules={PORT_SUBTREE_PATTERN: {"enabled": True, "interval_sec": 0.02}},
            effective_tick=0.0,
        )

        assert caps == {PORT_SUBTREE_PATTERN: {"publisher_interval_sec": 0.02, "throttle_interval_sec": 0.05}}, caps
