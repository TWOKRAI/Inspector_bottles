# -*- coding: utf-8 -*-
"""Авторские сторожа Task 2.5 (m11) — внутренние опасности перевода легаси в правила.

Отдельный файл от независимого тестера (`test_observation_policy_task25_legacy_adapter.py`,
стадия 1) — по конвенции проекта авторские тесты добавочные, а не замена, и
провенанс двух ролей обязан быть виден раздельно (см. `.claude/modes/dev.md`
§«Тест authorship»). Здесь — три опасности, которые видны только изнутри
реализации (`observation_policy.py`), а не из критериев приёмки:

1. **Round-trip не воскрешает устаревший легаси-паттерн на ступени TIER_RULE.**
   `ObservationPolicy.config` в bootstrap-состоянии (``config=None``) содержит
   переведённые легаси-паттерны (``**``/``**.<имя>``) — это САМ факт, который
   читает АК3 задания. Но `.config` — это ровно то, что
   ``ProcessHeartbeat._make_gate`` кормит ОБРАТНО в конструктор как
   операторский аргумент при КАЖДОЙ следующей пересборке гейта (единая точка
   сборки на три дороги — старт, ``telemetry.reconfigure``, ``config.reload``
   с секцией порта). Без безусловного фильтра
   (``_is_legacy_reserved_pattern``) устаревший перевод первой сборки дожил
   бы до второй на ступени ``TIER_RULE`` — на ДВЕ ступени выше назначенного
   ``TIER_UMBRELLA`` — и обогнал бы СВЕЖЕЕ решение легаси второго вызова.
2. **Небутстрап-конструкция (``config`` — реальный объект) НИКОГДА не
   подмешивает легаси в `.config`.** Это охраняет ИДЕМПОТЕНТНОСТЬ
   ``ProcessHeartbeat.apply_observation_policy``: та функция сравнивает
   ``live.config.model_dump()`` со свежим
   ``ObservationPolicyConfig.from_dict(section)``, чтобы пропустить
   пересборку гейта на ``config.reload``, не тронувший операторскую секцию.
   Подмешай легаси безусловно — и сравнение расходилось бы на КАЖДОМ
   ``config.reload`` любого процесса с активным ``telemetry.publish``
   (то есть почти всегда — см. боевой ``system.yaml``), молча сбрасывая
   расписание порта.
3. **Граница bootstrap — буквальный ``None``, а не «пустой конфиг».** Тестер
   (и большинство существующих тестов) строит политику через
   ``_policy({}, publish=...)`` — РЕАЛЬНЫЙ, дефолтный ``ObservationPolicyConfig``,
   не ``None``. Перепутай границу — и паритетный набор АК1 начал бы получать
   bootstrap-перевод, которого сегодняшний код не делал НИКОГДА, меняя
   поведение той самой лестницы, парity которой задача обязана сохранить.

Ни один тест не трогает `_impl`/реализацию — только конструирует
``ObservationPolicy`` теми же путями, что и продакшн-код
(``heartbeat/process_heartbeat.py::_make_gate``), и проверяет наблюдаемый
результат.
"""

from __future__ import annotations

from multiprocess_framework.modules.process_module.configs.observation_policy import (
    SOURCE_LEGACY,
    ObservationPolicy,
    ObservationPolicyConfig,
)
from multiprocess_framework.modules.process_module.configs.telemetry_publish_config import (
    TelemetryPublishConfig,
)

from .test_observation_policy_review_f4 import PROC


class TestRoundTripDoesNotPromoteStaleLegacyToTierRule:
    """Опасность 1 — устаревший bootstrap-перевод не обгоняет свежее решение.

    **Уточнение по инъекции (проверено руками, предсказание было ýже факта).**
    Ожидалось, что снятие фильтра ``_is_legacy_reserved_pattern`` покрасит
    только эти два теста (round-trip). На практике покраснел и третий —
    ``test_observation_policy_task25_legacy_adapter.py::TestReconfigureRoutesThroughTheSameTranslator
    ::test_reconfigure_gives_the_same_provenance_as_load`` — потому что фильтр
    защищает не только ВТОРУЮ сборку: bootstrap-перевод (:func:`_translate_legacy_rules`)
    кладёт ``**``/``**.<имя>`` в ``self._config.rules`` уже на ПЕРВОЙ, и без
    фильтра эти же паттерны немедленно попадают в ``self._rules`` (TIER_RULE)
    в ТОЙ ЖЕ конструкции — раунд 2 не обязателен, чтобы капкан сработал.
    Название класса про "round-trip" остаётся верным (сценарий, который он
    воспроизводит, реален и тоже красит эти тесты), но не описывает границу
    фильтра целиком — граница безусловна с самого начала, не только при
    повторной сборке.
    """

    def test_second_construction_sees_the_fresh_legacy_decision_not_the_stale_one(self) -> None:
        """Round-trip ``ObservationPolicy(policy.config, ...)`` — как ``_make_gate``.

        Раунд 1: bootstrap (``config=None``) с ``latency_ms`` включённым явно.
        Раунд 2: та же политика пересобрана (``policy1.config`` кормится как
        операторский аргумент — буквально то, что делает ``_make_gate`` на
        второй и последующих сборках) поверх НОВОЙ легаси-секции, где
        ``latency_ms`` явно не упомянута и общее умолчание — ``False``.

        Без фильтра ``_is_legacy_reserved_pattern`` раунд 2 унаследовал бы
        ``"**.latency_ms": enabled=True`` из раунда 1 на ступени ``TIER_RULE``
        и решение осталось бы ``enabled=True`` — хотя вторая легаси-секция
        явно погасила метрику умолчанием.
        """
        legacy1 = TelemetryPublishConfig.from_dict({"metrics": {"latency_ms": {"enabled": True}}})
        policy1 = ObservationPolicy(None, legacy1)
        # Предпосылка: bootstrap действительно перевёл легаси в `.config.rules`
        # (иначе тест ничего не проверяет — рефлекс "докажи, что бутстрап сработал").
        assert "**.latency_ms" in policy1.config.rules, policy1.config.rules

        legacy2 = TelemetryPublishConfig.from_dict({"default_enabled": False, "metrics": {}})
        policy2 = ObservationPolicy(policy1.config, legacy2)

        decision = policy2.resolve(f"processes.{PROC}.state.latency_ms")
        assert decision.enabled is False, (
            f"устаревший `**.latency_ms` из bootstrap-перевода раунда 1 дожил до TIER_RULE "
            f"раунда 2 и обогнал свежее решение: {decision}"
        )
        assert decision.source == SOURCE_LEGACY, decision

    def test_a_plugin_subtree_path_still_prefers_the_subtree_default_after_round_trip(self) -> None:
        """Пара-контроль: капкан задания (зонтик глушит дефолт поддерева) — и после round-trip.

        Раунд 1 переводит зонтик ``default_enabled=False`` в ``"**"`` внутри
        ``.config.rules``. Раунд 2 (round-trip) не должен позволить этому
        паттерну подняться до ``TIER_RULE`` и обогнать
        ``TIER_SUBTREE_DEFAULT`` на ПЛАГИННОМ пути — ровно та ловушка, которую
        паритетный тест тестера (АК1, capture_fps/frame_count/drops) ловит на
        ПЕРВОЙ сборке; здесь та же ловушка проверяется на ВТОРОЙ.
        """
        legacy1 = TelemetryPublishConfig.from_dict({"default_enabled": False, "metrics": {}})
        policy1 = ObservationPolicy(None, legacy1)
        assert "**" in policy1.config.rules, policy1.config.rules

        legacy2 = TelemetryPublishConfig.from_dict({"default_enabled": False, "metrics": {}})
        policy2 = ObservationPolicy(policy1.config, legacy2)

        decision = policy2.resolve(f"processes.{PROC}.state.plugins.capture.brand_new_metric")
        assert decision.enabled is True, (
            f"зонтичный `**` из bootstrap-перевода обогнал дефолт поддерева порта на round-trip: {decision}"
        )
        assert decision.source == "subtree_default", decision


class TestNonBootstrapConstructionNeverMergesLegacyIntoConfig:
    """Опасность 2 — идемпотентность `apply_observation_policy` не задета."""

    def test_a_real_config_object_keeps_config_rules_untouched_by_legacy(self) -> None:
        """``config`` — РЕАЛЬНЫЙ (не ``None``) объект → `.config.rules` не растёт.

        Это ровно форма вызова ``ProcessHeartbeat.apply_observation_policy``
        (``ObservationPolicyConfig.from_dict(section)`` — всегда реальный
        объект) и ``_resolve_observation_policy`` — ни один из них не передаёт
        буквальный ``None``. Если бы легаси подмешивался здесь тоже,
        `apply_observation_policy` перестал бы пропускать пересборку на
        `config.reload`, не тронувший секцию порта.
        """
        real_config = ObservationPolicyConfig.from_dict({})
        legacy = TelemetryPublishConfig.from_dict({"metrics": {"fps": {"enabled": True}}})
        policy = ObservationPolicy(real_config, legacy)

        assert policy.config.rules == {}, (
            f"легаси подмешался в `.config` при небутстрап-конструкции: {policy.config.rules} — "
            "это сломает сравнение apply_observation_policy на каждом config.reload"
        )
        # Контроль: резолв по-прежнему видит легаси — механизм не "выключился",
        # просто не показан в `.config.rules`.
        assert policy.resolve(f"processes.{PROC}.state.fps").source == SOURCE_LEGACY

    def test_the_apply_observation_policy_equality_check_would_hold(self) -> None:
        """Прямая репродукция сравнения из ``apply_observation_policy``.

        ``live.config.model_dump() == свежий ObservationPolicyConfig.from_dict(section)``
        обязано остаться ИСТИННЫМ, когда операторская секция не менялась, даже
        при живом легаси. Тест не импортирует ``process_heartbeat.py``
        (вне области задачи 2.5) — воспроизводит сравнение буквально по
        докстрингу метода.
        """
        section = {"subtree_interval_sec": 0.3}
        legacy = TelemetryPublishConfig.from_dict({"metrics": {"shm": {"enabled": False}}})

        live = ObservationPolicy(ObservationPolicyConfig.from_dict(section), legacy)
        fresh = ObservationPolicyConfig.from_dict(section)  # то, что apply_observation_policy строит на КАЖДОМ вызове

        assert live.config.model_dump() == fresh.model_dump(), (
            "сравнение `apply_observation_policy` расходится на неизменной секции при живом "
            f"легаси: live={live.config.model_dump()!r} fresh={fresh.model_dump()!r}"
        )


class TestBootstrapBoundaryIsLiteralNoneNotAnEmptyConfig:
    """Опасность 3 — граница bootstrap не путает «None» с «оператор написал {}»."""

    def test_a_freshly_constructed_default_config_is_not_bootstrap(self) -> None:
        """``ObservationPolicyConfig()`` — РЕАЛЬНЫЙ объект с дефолтами, не ``None``.

        Ровно то, что строит вспомогательная функция тестера
        (``test_observation_policy_review_f4._policy``, ``ObservationPolicyConfig.from_dict({})``
        при пустом ``observation=None/{}``) — большинство существующих
        тестов конструируют политику именно так. Перепутай границу на «любой
        конфиг без явных правил» — и паритетный набор АК1 начал бы получать
        bootstrap-перевод на каждом вызове ``_policy({}, publish=...)``.
        """
        legacy = TelemetryPublishConfig.from_dict({"metrics": {"fps": {"enabled": True}}})
        policy = ObservationPolicy(ObservationPolicyConfig(), legacy)
        assert policy.config.rules == {}, (
            f"пустой, но реальный ObservationPolicyConfig() посчитан bootstrap'ом: {policy.config.rules}"
        )
