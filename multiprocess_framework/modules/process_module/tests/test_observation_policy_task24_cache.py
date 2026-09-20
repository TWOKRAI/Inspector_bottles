# -*- coding: utf-8 -*-
"""Сторожа задачи 2.4 — кэш решений политики и его инвалидация (Ф2).

Task 2.4 добавляет мемоизацию ``(путь) → PolicyDecision`` на экземпляр
:class:`~...configs.observation_policy.ObservationPolicy` — до неё каждый
резолв заново перебирал все правила оператора и заново разбирал их паттерны
(``ObservationPolicy.resolve`` стоил 11.87 мкс сам по себе, см. коммит Task 2.1
и докстринг ``resolve``). Опасны здесь ровно два места, оба названы владельцем
задачи прямым текстом:

1. **Кэш не должен пережить смену политики.** Политика неизменяема ПОСЛЕ
   сборки, но объект политики ЗАМЕНЯЕТСЯ целиком на каждый
   ``config.reload``/``telemetry.reconfigure``
   (``ProcessHeartbeat._install_observation_policy``). Кэш обязан жить НА
   ЭКЗЕМПЛЯРЕ — тогда замена объекта автоматически стартует с пустого кэша.
   Кэш, вынесенный в модульную глобаль или на класс, пережил бы замену и
   отвечал бы по СТАРЫМ правилам сколь угодно долго после reload'а.
2. **Счёт попаданий (`rule_hits`) обязан считаться и на кэш-хите.** До кэша
   каждый резолв заново проходил по всем правилам и инкрементил счётчик
   совпавшего правила; кэш убирает повторный проход, но не имеет права
   убирать вместе с ним и инкремент — иначе `rule_hits`/`rules_matched_nothing`
   начнут лгать про часто читаемое, живое правило (тот же класс дефекта, что
   уже разбирала находка З3 ревью Ф4 у пары ``count=True``/``count=False``).

Оба свойства доказаны инъекцией — скриптовой правкой файла, а не рассуждением.
Предсказания записаны в докстринге каждого класса ДО прогона.
"""

from __future__ import annotations

import yaml

from multiprocess_framework.modules.process_module.commands.builtin_commands import BuiltinCommands
from multiprocess_framework.modules.process_module.configs.observability_layers import (
    process_observability_layers,
)
from multiprocess_framework.modules.process_module.configs.observation_policy import (
    SOURCE_RULE,
    SOURCE_SUBTREE_DEFAULT,
    ObservationPolicy,
    ObservationPolicyConfig,
)
from multiprocess_framework.modules.process_module.configs.telemetry_publish_config import (
    TelemetryPublishConfig,
)

from .test_telemetry_commands import _FakeLogger, _FakeServices
from .test_telemetry_layers import BOOT_PUBLISH

PROC = "cam1"


def _policy(observation: dict | None = None, publish: dict | None = None) -> ObservationPolicy:
    legacy = None if publish is None else TelemetryPublishConfig.from_dict(publish)
    return ObservationPolicy(ObservationPolicyConfig.from_dict(observation), legacy)


def _wired(tmp_path):
    """Процесс с настоящим ``ProcessHeartbeat``, живым гейтом и командами.

    Дословная копия ``_wired`` из ``test_observation_policy_review_f4.py`` —
    файлы этого набора намеренно не делят хелперы (см. докстринги соседей),
    каждый набор инъекций самодостаточен.
    """
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


# =========================================================================== #
# 1 — кэш не переживает смену политики (reload обязан пробиваться)
# =========================================================================== #
class TestCacheDoesNotSurviveAPolicyReplacement:
    """Задача 2.4, опасное место 1: кэш живёт НА ЭКЗЕМПЛЯРЕ, не в модульной глобали.

    **Предсказание до прогона.** Со здоровой реализацией (``self._cache = {}``
    в конструкторе) тест ниже ЗЕЛЁНЫЙ: путь прогревается на политике ДО
    reload'а (решает дефолт поддерева, ``enabled=True``), затем ``config.reload``
    добавляет правило, запрещающее этот же путь, — и следующий резолв обязан
    увидеть НОВОЕ правило, потому что reload собирает НОВЫЙ объект
    ``ObservationPolicy`` (``ProcessHeartbeat._install_observation_policy``) с
    пустым кэшем. Инъекция (см. отчёт задачи) переносит ``self._cache`` в
    модульную переменную, общую для всех политик процесса, — тогда прогретое
    ДО reload'а решение (``enabled=True``) переживёт замену объекта и подменит
    собой решение новой политики; тест обязан стать КРАСНЫМ.
    """

    PATTERN = "processes.*.state.plugins.*.cache_task24_probe"
    PATH = f"processes.{PROC}.state.plugins.capture.cache_task24_probe"

    def test_a_rule_added_by_reload_wins_over_a_pre_reload_cache_hit(self, tmp_path) -> None:
        svc, handlers = _wired(tmp_path)
        hb = svc._heartbeat

        # Прогрев ДО reload: правил оператора на этот путь ещё нет, решает
        # дефолт поддерева порта. Резолвим ДВАЖДЫ — типичный горячий путь:
        # несколько тиков идут раньше, чем оператор вообще тронул конфиг.
        pre = hb._observation_policy.resolve(self.PATH)
        assert pre.enabled is True, f"предпосылка сорвана: путь не разрешён дефолтом поддерева: {pre}"
        assert pre.source == SOURCE_SUBTREE_DEFAULT, pre
        hb._observation_policy.resolve(self.PATH)

        res = handlers["config.reload"](
            {"observability": {"observation": {"rules": {self.PATTERN: {"enabled": False}}}}}
        )
        assert res["success"] is True, res

        post = hb._observation_policy.resolve(self.PATH)
        assert post.enabled is False, (
            f"новое правило reload'а не подействовало — решение осталось от политики ДО reload "
            f"(кэш пережил замену объекта): {post}"
        )
        assert post.source == SOURCE_RULE, post

    def test_the_replacement_is_a_new_object_not_a_mutation(self, tmp_path) -> None:
        """Пара-контроль: reload собирает НОВЫЙ объект, а не мутирует старый.

        Без этой половины предыдущий тест доказывал бы только «решение
        поменялось» — а не то, ЧТО обеспечивает инвалидацию (новый объект
        политики, не переиспользованный).
        """
        svc, handlers = _wired(tmp_path)
        hb = svc._heartbeat
        before = hb._observation_policy
        res = handlers["config.reload"](
            {"observability": {"observation": {"rules": {self.PATTERN: {"enabled": False}}}}}
        )
        assert res["success"] is True, res
        assert hb._observation_policy is not before, (
            "reload переиспользовал СТАРЫЙ объект политики — тогда инвалидация кэша "
            "держится на чём-то другом, не на замене объекта"
        )


# =========================================================================== #
# 2 — кэш-хит продолжает считаться в rule_hits
# =========================================================================== #
class TestCacheHitStillCountsAsAHit:
    """Задача 2.4, опасное место 2: счёт попаданий отделён от кэша, но не отключён.

    **Предсказание до прогона.** Со здоровой реализацией три резолва ОДНОГО и
    того же пути дают ``rule_hits() == {RULE: 3}`` — первый резолв промахивается
    мимо кэша и считает, следующие два бьют в кэш и СЧИТАЮТ ТОЖЕ. Инъекция,
    переносящая инкремент внутрь ветки ``if cached is None`` (то есть считающая
    только промахи), оставит ``rule_hits() == {RULE: 1}`` — тест обязан стать
    КРАСНЫМ на втором `assert`.
    """

    RULE = "processes.*.state.plugins.*.fps"
    PATH = f"processes.{PROC}.state.plugins.capture.fps"

    def test_three_resolves_of_the_same_path_count_three_hits(self) -> None:
        policy = _policy({"rules": {self.RULE: {"interval_sec": 1.0}}}, publish={})
        policy.resolve(self.PATH)
        policy.resolve(self.PATH)  # первый кэш-хит
        policy.resolve(self.PATH)  # второй кэш-хит
        assert policy.rule_hits() == {self.RULE: 3}, (
            f"кэш-хиты не считаются в rule_hits: {policy.rule_hits()} — счётчик лжёт про живое правило"
        )
        assert policy.rules_matched_nothing() == [], policy.rules_matched_nothing()

    def test_a_diagnostic_read_after_warm_cache_still_does_not_count(self) -> None:
        """Пара-контроль (переносит З3 ревью Ф4 на прогретый кэш).

        Кэш не должен приносить и обратную поломку: диагностическое чтение
        (``count=False``) обязано молчать, даже когда путь уже в кэше после
        боевого резолва.
        """
        policy = _policy({"rules": {self.RULE: {"interval_sec": 1.0}}}, publish={})
        policy.resolve(self.PATH)  # боевой резолв — считает, путь попадает в кэш
        before = dict(policy.rule_hits())
        policy.resolve(self.PATH, count=False)
        policy.resolve(self.PATH, count=False)
        assert policy.rule_hits() == before, (
            f"диагностическое чтение сдвинуло счёт на прогретом кэше: было {before}, стало {policy.rule_hits()}"
        )

    def test_an_unrelated_rule_still_reports_matched_nothing_after_the_cache_warms(self) -> None:
        """Пара-контроль: прогрев кэша ОДНОГО правила не портит бухгалтерию соседа.

        Опечатка ``rules_matched_nothing`` — единственный голос про мёртвое
        правило (докстринг метода). Если бы кэш случайно склеивал счёт между
        путями/правилами, это правило перестало бы отвечать «ни разу не
        совпало», хотя ни с чем не совпадало НИКОГДА.
        """
        typo_rule = "procesess.*.state.plugins.*.typo"  # намеренная опечатка первого сегмента
        policy = _policy({"rules": {self.RULE: {"interval_sec": 1.0}, typo_rule: {"interval_sec": 1.0}}}, publish={})
        policy.mark_tick()
        for _ in range(5):
            policy.resolve(self.PATH)
        assert policy.rules_matched_nothing() == [typo_rule], policy.rules_matched_nothing()
        assert policy.rule_hits()[self.RULE] == 5, policy.rule_hits()
        assert policy.rule_hits()[typo_rule] == 0, policy.rule_hits()
