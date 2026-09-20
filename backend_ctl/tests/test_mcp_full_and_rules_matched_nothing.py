# -*- coding: utf-8 -*-
"""Task 0.4, критерии 3 и 4 — m6: ``rules_matched_nothing`` не смеет обвинять правило,
которое просто ещё не дожило до тика оценки.

Независимый приёмочный тест (RED, ДО реализации). Контракт — дословно acceptance
criteria плана:

    3. ``rules_matched_nothing`` содержит ТОЛЬКО правила, дожившие минимум до
       одного тика оценки. Правила, ещё не оценивавшиеся, едут отдельным полем
       ``rules_pending``. Ответ на перезагрузку конфига несёт ``evaluated_ticks``.
    4. Пара на диагностический ответ: правило, которое реально ни разу не
       совпало за ≥1 тик, ОБЯЗАНО попасть в ``rules_matched_nothing``
       (ложноотрицательная сторона). Свежесозданное правило НЕ должно туда
       попадать (ложноположительная сторона). Оба входа — тестами.

**Дизайн-решение тестера (не факт из кода — решение, которое я принимаю за
разработчика в отсутствие ``interface.py``).** Сегодня ``ObservationPolicy`` не
знает понятия «тик»: попадания (``_hits``) считаются ПО ПУТИ на каждый вызов
``resolve()``, а не по дискретному циклу оценки. Чтобы различить «ещё ни разу не
оценивалось» от «оценивалось и не совпало», нужна ОТДЕЛЬНАЯ единица счёта,
независимая от количества путей. Контракт, который эти тесты фиксируют как
спецификацию для разработчика:

- ``ObservationPolicy.evaluated_ticks -> int`` — сколько раз завершился полный
  цикл оценки (растёт вызовом ``mark_tick()``, а не ``resolve()``);
- ``ObservationPolicy.mark_tick() -> None`` — отметить завершение одного цикла;
- ``ObservationPolicy(..., evaluated_ticks: int = 0)`` — перенос счёта при
  пересборке политики, ТОЙ ЖЕ формы, что уже есть у ``hits=`` (см. докстринг
  конструктора и находку З3 ревью Ф4 — без переноса каждая соседняя правка
  обнуляла бы счётчик и держала бы здоровые правила в «pending» вечно);
- ``ObservationPolicy.rules_pending() -> list[str]`` — правила, для которых
  ``evaluated_ticks == 0``;
- ``ObservationPolicy.rules_matched_nothing()`` — правила с ``hits == 0``,
  ТОЛЬКО если ``evaluated_ticks >= 1`` (иначе — пусто, ещё рано судить);
- ``ObservationPolicy.effective_view()`` — несёт ключ ``evaluated_ticks``
  (это и есть «ответ на перезагрузку конфига» — ``apply_observation_policy``
  оборачивает ``effective_view()`` дословно, см.
  ``heartbeat/process_heartbeat.py``).

Если разработчик выберет другое имя/форму — это нормально, но тогда КОНКРЕТНО эти
тесты останутся red и потребуют ревизии дизайна, а не немой правки под них.
"""

from __future__ import annotations

from multiprocess_framework.modules.process_module.configs.observation_policy import (
    ObservationPolicy,
    ObservationPolicyConfig,
)

_HEALTHY_PATTERN = "processes.*.state.plugins.capture.fps"
_TYPO_PATTERN = "procesess.*.state.plugins.capture.fps"  # опечатка в первом сегменте — никогда не совпадёт
_HEALTHY_PATH = "processes.cam1.state.plugins.capture.fps"


def _policy_with_two_rules() -> ObservationPolicy:
    cfg = ObservationPolicyConfig.from_dict(
        {
            "rules": {
                _HEALTHY_PATTERN: {"interval_sec": 1.0},
                _TYPO_PATTERN: {"interval_sec": 1.0},
            }
        }
    )
    return ObservationPolicy(cfg, None)


def test_evaluated_ticks_starts_at_zero() -> None:
    policy = _policy_with_two_rules()
    assert policy.evaluated_ticks == 0


def test_mark_tick_increments_evaluated_ticks() -> None:
    policy = _policy_with_two_rules()
    policy.mark_tick()
    policy.mark_tick()
    policy.mark_tick()
    assert policy.evaluated_ticks == 3


def test_fresh_rule_before_any_tick_is_pending_not_matched_nothing() -> None:
    """Ложноположительная сторона (критерий 4): свежее правило НЕ обвиняется сразу."""
    policy = _policy_with_two_rules()
    assert policy.rules_pending() == sorted([_HEALTHY_PATTERN, _TYPO_PATTERN])
    assert policy.rules_matched_nothing() == [], (
        "правило без единого тика оценки не может быть виновным в «ни разу не совпало» — у него просто не было шанса"
    )


def test_rule_with_zero_hits_after_a_tick_is_matched_nothing() -> None:
    """Ложноотрицательная сторона (критерий 4): типо-правило реально ловится."""
    policy = _policy_with_two_rules()
    policy.resolve(_HEALTHY_PATH)  # даёт хиты ЗДОРОВОМУ правилу
    policy.mark_tick()
    assert policy.rules_matched_nothing() == [_TYPO_PATTERN], (
        "опечатка в пути обязана попасть в rules_matched_nothing после ≥1 тика оценки"
    )


def test_healthy_rule_with_hits_never_appears_in_matched_nothing() -> None:
    policy = _policy_with_two_rules()
    policy.resolve(_HEALTHY_PATH)
    policy.mark_tick()
    assert _HEALTHY_PATTERN not in policy.rules_matched_nothing()


def test_rules_pending_empties_out_after_first_tick() -> None:
    """После первого тика ни одно правило больше не «ещё не оценивалось»."""
    policy = _policy_with_two_rules()
    policy.resolve(_HEALTHY_PATH)
    policy.mark_tick()
    assert policy.rules_pending() == []


def test_evaluated_ticks_is_carried_across_policy_rebuild() -> None:
    """Тот же перенос, что уже есть у ``hits=`` (находка З3 ревью Ф4) — иначе
    каждая соседняя правка (``telemetry.reconfigure``) обнуляла бы счётчик и
    здоровые правила вечно сидели бы в ``rules_pending``."""
    original = _policy_with_two_rules()
    original.resolve(_HEALTHY_PATH)
    original.mark_tick()
    original.mark_tick()

    rebuilt = ObservationPolicy(
        original.config,
        original.legacy,
        hits=original.rule_hits(),
        evaluated_ticks=original.evaluated_ticks,
    )
    assert rebuilt.evaluated_ticks == 2


def test_effective_view_carries_evaluated_ticks() -> None:
    """«Ответ на перезагрузку конфига несёт evaluated_ticks» — граница ``effective_view()``:
    ``apply_observation_policy`` оборачивает её дословно в ответ команды/readback."""
    policy = _policy_with_two_rules()
    policy.mark_tick()
    policy.mark_tick()
    view = policy.effective_view()
    assert view["evaluated_ticks"] == 2
