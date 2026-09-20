# -*- coding: utf-8 -*-
"""Hazard-тесты механизма Task 0.4 (`plans/observability-closure/phase-0-trust-gate.md`).

Не поведение инструментов (его держит RED-набор независимого тестера,
`test_mcp_full_and_rules_*.py`), а **механизм**, который тестер увидеть не мог,
не читая реализацию:

1. Автодобавление ``full`` в схемы — это один цикл по реестру. Цикл, который
   молча ничего не делает (реестр пуст, условие не совпало), выглядит так же,
   как цикл, отработавший верно: оба дают зелёный. Поэтому здесь проверяется
   **непустота множества**, а не только отсутствие нарушителей — «ноль
   нарушителей» при нуле проверенных не значит ничего.
2. Автодобавление не должно затирать три схемы, объявившие ``full`` вручную,
   и не должно трогать ``required``.
3. ``rules_pending`` и ``rule_hits`` — два поля одного readback'а, и они обязаны
   быть согласованы КОНСТРУКЦИЕЙ, а не совпадением порядка вызовов. Сегодня
   ``resolve()`` и ``mark_tick()`` зовёт один и тот же ``TelemetryGate`` в одной
   ветке такта; второй вызывающий, резолвящий мимо такта, вернул бы ответ, где
   ``rule_hits`` показывает совпадения, а ``rules_pending`` рядом утверждает
   «ещё не оценивалось».
"""

from __future__ import annotations

import jsonschema

from backend_ctl.mcp_tools import TOOLS, _UNCAPPED_TOOLS


def _cappable() -> list:
    return [t for t in TOOLS if t.name not in _UNCAPPED_TOOLS]


class TestFullAutoSchema:
    def test_the_set_under_check_is_not_empty(self) -> None:
        """Сторож самого сторожа: капающих инструментов больше сорока.

        Без этой строки соседний тест «ни одного без ``full``» остаётся зелёным
        и на пустом реестре — то есть отвечает «нарушителей нет» там, где никого
        не проверял. Литерал написан, а не выведен из ``len(TOOLS)``.
        """
        assert len(_cappable()) >= 40

    def test_every_cappable_tool_carries_full_in_its_schema(self) -> None:
        """Нарушители — поимённо, а не числом: «12 инструментов» нечем чинить."""
        missing = sorted(t.name for t in _cappable() if "full" not in t.input_schema.get("properties", {}))
        assert missing == [], f"капающие инструменты без ручки full: {missing}"

    def test_manually_declared_full_is_not_overwritten(self) -> None:
        """Три схемы объявляли ``full`` до автодобавления — их описание обязано выжить.

        Автодобавление, затирающее ручное объявление, — это молчаливая потеря
        текста, который писали руками ради оператора.
        """
        described = [
            t.name for t in _cappable() if (t.input_schema["properties"]["full"].get("description") or "").strip()
        ]
        assert len(described) == len(_cappable()), "у части инструментов ручка full осталась без описания"

    def test_full_is_never_required(self) -> None:
        """Ручка опциональна везде: обязательный ``full`` сломал бы все вызовы без него."""
        offenders = sorted(t.name for t in _cappable() if "full" in (t.input_schema.get("required") or []))
        assert offenders == []

    def test_full_true_is_accepted_by_every_cappable_schema(self) -> None:
        """``full: true`` проходит валидацию у каждого капающего инструмента.

        Проверяется наблюдаемым эффектом (валидатор принял), а не наличием ключа:
        ``additionalProperties: false`` отвергал бы аргумент даже при объявленном
        свойстве, если бы механизм добавлял его не в ту секцию схемы.
        """
        rejected = []
        for tool in _cappable():
            schema = tool.input_schema
            instance = {
                name: _placeholder(schema["properties"].get(name, {})) for name in (schema.get("required") or [])
            }
            instance["full"] = True
            try:
                jsonschema.validate(instance, schema)
            except jsonschema.ValidationError as exc:  # noqa: PERF203 — нужен адрес нарушителя
                rejected.append((tool.name, exc.message))
        assert rejected == []


def _placeholder(prop: dict):
    if prop.get("enum"):
        return prop["enum"][0]
    types = prop.get("type", "string")
    types = types if isinstance(types, list) else [types]
    return {"string": "x", "integer": 1, "number": 1.0, "boolean": True, "array": [], "object": {}}.get(types[0], "x")


class TestPendingAndHitsCannotContradictEachOther:
    """Хазард 3: два поля одного ответа обязаны быть согласованы конструкцией."""

    def test_a_rule_with_hits_is_never_reported_as_pending(self) -> None:
        """Правило резолвили мимо такта: попадания есть, тиков ноль.

        Ожидание: правило НЕ в ``rules_pending`` — совпадение доказывает, что
        правило оценивали, и это доказательство сильнее счётчика тиков.
        Ломается ровно тогда, когда ``rules_pending`` начнёт смотреть только на
        возраст: тогда readback скажет «ещё не оценивалось» про правило, чьи
        попадания он же и показывает.
        """
        from multiprocess_framework.modules.process_module.configs.observation_policy import (
            ObservationPolicy,
            ObservationPolicyConfig,
        )

        rule = "processes.*.state.plugins.*.fps"
        policy = ObservationPolicy(
            ObservationPolicyConfig.from_dict({"rules": {rule: {"interval_sec": 1.0}}}),
            None,
        )
        assert policy.rules_pending() == [rule], "предпосылка: до резолва правило числится неоценённым"

        policy.resolve("processes.cam1.state.plugins.capture.fps")

        assert policy.rule_hits()[rule] == 1, "предпосылка: правило совпало"
        assert policy.rules_pending() == [], "правило с попаданием не может числиться «ещё не оценённым»"
        assert policy.rules_matched_nothing() == [], "и обвинять его тоже не за что"


class TestRuleAgeIsPerRuleNotPerPolicy:
    """Хазард 4: правило, ДОБАВЛЕННОЕ пересборкой, не наследует чужой возраст.

    Найдено слом-инъекцией «считать возраст от политики» — она дала **ноль**
    красных, то есть свойство существовало только в докстроке. А это ровно тот
    ложноположительный ответ, ради которого задача m6 и делается: правило,
    применённое на 50-м тике, обвинялось бы в «не совпало ни с чем» в тот же миг,
    ни разу не будучи оценённым.
    """

    RULE_OLD = "processes.*.state.plugins.*.fps"
    RULE_NEW = "processes.*.state.plugins.*.drops"

    def _policy(self, rules, **carry):
        from multiprocess_framework.modules.process_module.configs.observation_policy import (
            ObservationPolicy,
            ObservationPolicyConfig,
        )

        return ObservationPolicy(
            ObservationPolicyConfig.from_dict({"rules": {r: {"interval_sec": 1.0} for r in rules}}),
            None,
            **carry,
        )

    def test_a_rule_added_at_rebuild_starts_pending_while_its_neighbour_keeps_its_age(self) -> None:
        """Политика прожила 50 тиков; пересборка добавляет второе правило.

        Ожидание — ДВА факта сразу, и второй так же важен, как первый:
        новое правило едет в ``rules_pending`` (возраст свой, с нуля), а старое
        из ``rules_pending`` не возвращается (возраст перенесён). Проверять
        только первое — значит принять «сбросить возраст всем» за верную
        починку: тогда каждая правка конфига возвращала бы здоровые правила
        в «ещё не оценивались» и голос глох бы на любом движении пульта.
        """
        old = self._policy([self.RULE_OLD])
        for _ in range(50):
            old.mark_tick()
        assert old.rules_pending() == [], "предпосылка: старое правило своё окно уже прожило"
        assert old.evaluated_ticks == 50

        rebuilt = self._policy(
            [self.RULE_OLD, self.RULE_NEW],
            hits=old.rule_hits(),
            evaluated_ticks=old.evaluated_ticks,
            rule_first_tick=old.rule_first_tick(),
        )

        assert rebuilt.rules_pending() == [self.RULE_NEW], (
            "новое правило обязано быть «ещё не оценивалось», старое — нет"
        )
        assert rebuilt.rules_matched_nothing() == [self.RULE_OLD], (
            "старое правило прожило 50 тиков без единого совпадения — вот его и называем"
        )
