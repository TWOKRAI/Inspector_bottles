# -*- coding: utf-8 -*-
"""Сторожа находок РЕВЬЮ задачи 3.0 (`observability-closure`, Ф3, добор 3.0a).

Отдельный файл от `test_task_3_0_hazards.py` по той же причине, по какой
`test_observation_policy_review_f4.py` отделён от соседа: там опасности,
которые автор увидел сам, здесь — свойства, названные СНАРУЖИ, и через месяц
на вопрос «что именно нашло ревью» отвечает состав файла, а не git blame.

Три находки с кодом:

* **Н1 [major]** — отчёт о потолках считался по УСТАРЕВШЕМУ такту в том же
  `config.reload`: два ОДИНАКОВЫХ вызова подряд давали РАЗНЫЕ ответы, и первый
  утверждал «потолков нет» там, где потолок уже был. Лечение — отчёт стал
  последней строкой ленты применений (`observation_throttle_report`).
* **Н2 [minor]** — две дисциплины `bool` на одном входе: половина по ПУТИ
  исключала `bool`, половина по ИМЕНИ принимала. Живой троттл `bool` ИСПОЛНЯЕТ,
  поэтому исключение молча роняло работающее правило в «судили, потолка нет».
* **Н3 [minor]** — нечисловой интервал правила читался как «судили, потолка
  нет». Вторая причина веера: `"unreadable_rule"`.

Н4 (односторонняя развязка корзин) кода не потребовала — достижимость нулевая,
довод стоит комментарием у самой развязки.
"""

from __future__ import annotations

import yaml

from multiprocess_framework.modules.process_module.commands.builtin_commands import BuiltinCommands
from multiprocess_framework.modules.process_module.configs.observability_layers import (
    process_observability_layers,
)
from multiprocess_framework.modules.process_module.managers.telemetry_reload import judge_throttle_caps
from multiprocess_framework.modules.state_store_module.middleware.throttle import ThrottleMiddleware

from .test_telemetry_commands import _FakeLogger, _FakeServices
from .test_telemetry_layers import BOOT_PUBLISH

#: Дефолтное правило поддерева порта — ключ отчёта на этом харнесе.
SUBTREE = "processes.*.state.plugins.**"


class _Throttle:
    """Центральный троттл оркестратора: минимум того, что читает сверщик."""

    def __init__(self, rules) -> None:
        self.rules = rules


class _FakeStoreManager:
    """Держатель троттла (у обычного процесса его нет — он у оркестратора)."""

    def __init__(self, throttle) -> None:
        self._throttle = throttle

    def get_middleware(self, name):
        return self._throttle if name == "throttle" else None


def _wired(tmp_path, throttle_rules):
    """Процесс с настоящим `ProcessHeartbeat`, живым гейтом, командами и троттлом.

    Такт харнесса — `min(heartbeat_interval=5.0, tick_sec=1.0)` = **1.0 с**
    (`BOOT_PUBLISH`, `test_telemetry_layers.py`): числа тестов ниже выбраны
    относительно него.
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
    svc._state_store_manager = _FakeStoreManager(_Throttle(throttle_rules))
    return svc, svc.command_manager.handlers


def _report(handlers, payload):
    """Отчёт о потолках из ОТВЕТА команды (не из внутреннего словаря)."""
    applied = handlers["config.reload"](dict(payload))["observation_applied"]
    return (
        applied.get("capped_by_throttle"),
        applied.get("capped_by_throttle_unjudged", "<КЛЮЧА НЕТ>"),
    )


# =========================================================================== #
# Н1 — идемпотентность диагностики
# =========================================================================== #
class TestTwoIdenticalReloadsAnswerTheSame:
    """Находка Н1 [major]: отчёт считался по состоянию ДО правки того же вызова.

    Почему сторож именно на ПОВТОР, а не на «правильное число»: правильное
    число само по себе доказуемо и вручную подобранным тактом, а болезнь была в
    ПОРЯДКЕ — отчёт стоял выше стадий, которые правят его же вход. Единственная
    форма, в которой такой дефект виден снаружи, — «один и тот же жест отвечает
    по-разному в зависимости от того, каким он был по счёту». Поэтому оба
    вызова здесь дословно одинаковы, и сравниваются оба ответа, а не только
    второй.

    Что сломается, если это перестанет быть правдой: оператор (или агент)
    читает ответ первого `config.reload` и уходит с «потолков нет» при живом
    срезе; повторив ту же команду, получает другой ответ и не может решить,
    какой из двух верен.
    """

    def test_the_report_does_not_wait_for_a_second_reload_to_see_the_new_tick(self, tmp_path) -> None:
        """Веер «не судил» появляется на ПЕРВОМ вызове, выключившем heartbeat.

        Замер до правки (тот же вход, два вызова подряд)::

            reload#1 -> unjudged=<КЛЮЧА НЕТ>
            reload#2 -> unjudged={'processes.*.state.plugins.**': 'no_tick'}

        Это главный триггер F2: heartbeat выключают ровно этой командой, и
        именно на ней ответ молчал про несудимого кандидата.
        """
        _svc, handlers = _wired(tmp_path, {SUBTREE: 0.05})
        payload = {"observability": {"heartbeat_interval_sec": 0.0}}

        first = _report(handlers, payload)
        second = _report(handlers, payload)

        assert first == second, (first, second)
        assert first == ({}, {SUBTREE: "no_tick"}), first

    def test_a_real_cap_is_named_on_the_first_reload_that_creates_it(self, tmp_path) -> None:
        """Вторая грань: потолок называется сразу, а не со второго вызова.

        Замер до правки: `reload#1 -> caps={}` (то есть «потолков нет» — ложь),
        `reload#2 -> {…: {'publisher_interval_sec': 0.2, …}}`. Такт правится на
        0.2 с той же командой, троттл 0.5 с строже — срез реален с первого раза.
        """
        _svc, handlers = _wired(tmp_path, {SUBTREE: 0.5})
        payload = {"observability": {"heartbeat_interval_sec": 0.2}}

        first = _report(handlers, payload)
        second = _report(handlers, payload)

        assert first == second, (first, second)
        assert first == (
            {SUBTREE: {"publisher_interval_sec": 0.2, "throttle_interval_sec": 0.5}},
            "<КЛЮЧА НЕТ>",
        ), first

    def test_the_same_holds_for_the_tick_that_comes_from_the_telemetry_stage(self, tmp_path) -> None:
        """Третья грань — НЕ названная ревью, найдена при починке.

        Такт это `min(heartbeat_interval, tick_sec)`, и вторую половину правит
        ТЕЛЕМЕТРИЙНАЯ стадия, которая на ленте стоит ещё ниже стадии такта.
        Поэтому «перенести отчёт под `heartbeat_interval_sec`» было бы половиной
        лечения: замер до правки на этом же входе давал `reload#1 -> caps={}`,
        `reload#2 -> потолок`. Отчёт стоит ПОСЛЕ обеих стадий.
        """
        _svc, handlers = _wired(tmp_path, {SUBTREE: 0.5})
        payload = {
            "observability": {},
            "telemetry": {"publish": {"default_enabled": True, "tick_sec": 0.2, "metrics": {}}},
        }

        first = _report(handlers, payload)
        second = _report(handlers, payload)

        assert first == second, (first, second)
        assert first == (
            {SUBTREE: {"publisher_interval_sec": 0.2, "throttle_interval_sec": 0.5}},
            "<КЛЮЧА НЕТ>",
        ), first

    def test_a_reload_that_changes_nothing_still_reports_the_standing_cap(self, tmp_path) -> None:
        """Контроль к трём выше: без правки такта отчёт тоже устойчив.

        Без этой половины «два ответа совпали» доказывалось бы только там, где
        правка была, и сверщик, замолкающий на второй пересборке политики,
        прошёл бы все три теста.
        """
        _svc, handlers = _wired(tmp_path, {SUBTREE: 2.0})
        payload = {"observability": {"log_level": "INFO"}}

        first = _report(handlers, payload)
        second = _report(handlers, payload)

        assert first == second, (first, second)
        assert first == (
            {SUBTREE: {"publisher_interval_sec": 1.0, "throttle_interval_sec": 2.0}},
            "<КЛЮЧА НЕТ>",
        ), first


# =========================================================================== #
# Н2 — bool это правило, а не мусор
# =========================================================================== #
class TestABooleanRuleIsARule:
    """Находка Н2 [minor]: две дисциплины `bool` на одном входе.

    Половина сверщика по ПУТИ отбрасывала `bool` (`not isinstance(interval, bool)`),
    половина по ИМЕНИ — принимала. Отбрасывание молча роняло РАБОТАЮЩЕЕ правило
    в «судили, потолка нет»: пустой отчёт читается как факт.
    """

    def test_the_live_throttle_really_executes_a_boolean_rule(self) -> None:
        """ПОСЫЛКА правки, проверенная на живом `ThrottleMiddleware`, а не принятая.

        Без этого теста «принять `bool`» опиралось бы на утверждение о чужом
        модуле. `True` работает как интервал 1.0 (`interval == 0` ложно), `False`
        падает в ветку полной блокировки (`False == 0` истинно) — то есть оба
        значения троттл ИСПОЛНЯЕТ, и сверщик обязан их видеть.
        """
        path = "processes.cam1.state.plugins.capture.fps"

        as_interval = ThrottleMiddleware({path: True})
        passed = [as_interval.before_set(path, i, "test", {})[0] for i in range(3)]
        assert passed == [True, False, False], passed

        as_block = ThrottleMiddleware({path: False})
        blocked = [as_block.before_set(path, i, "test", {})[0] for i in range(3)]
        assert blocked == [False, False, False], blocked

    def test_a_true_rule_is_judged_as_one_second_by_both_halves(self) -> None:
        """`True` = интервал 1.0 с: строже заявки 0.5 с — потолок обязан быть назван."""
        caps, unjudged = judge_throttle_caps(
            {"metrics": {"fps": {"interval_sec": 0.5}}},
            _Throttle({"processes.**.state.fps": True, "proc.state.fps": True}),
            observation_rules={"proc.state.fps": {"enabled": True, "interval_sec": 0.5}},
            effective_tick=None,
        )

        assert caps == {
            "fps": {"publisher_interval_sec": 0.5, "throttle_interval_sec": 1.0},
            "proc.state.fps": {"publisher_interval_sec": 0.5, "throttle_interval_sec": 1.0},
        }, caps
        assert unjudged == {}, unjudged

    def test_a_false_rule_is_judged_as_a_full_block_by_both_halves(self) -> None:
        """`False` = полная блокировка: строже ЛЮБОЙ заявки, включая быструю.

        Пара к предыдущему: без неё «bool принят» доказано только тем значением,
        которое ведёт себя как обычный интервал.
        """
        caps, unjudged = judge_throttle_caps(
            {"metrics": {"fps": {"interval_sec": 0.01}}},
            _Throttle({"processes.**.state.fps": False, "proc.state.fps": False}),
            observation_rules={"proc.state.fps": {"enabled": True, "interval_sec": 0.01}},
            effective_tick=None,
        )

        assert caps == {
            "fps": {"publisher_interval_sec": 0.01, "throttle_interval_sec": 0.0},
            "proc.state.fps": {"publisher_interval_sec": 0.01, "throttle_interval_sec": 0.0},
        }, caps
        assert unjudged == {}, unjudged


# =========================================================================== #
# Н3 — нечитаемое правило это не «правила нет»
# =========================================================================== #
class TestAnUnreadableRuleIsNamedNotSwallowed:
    """Находка Н3 [minor]: строковый интервал молчал как «судили, потолка нет».

    Почему это не косметика: замер лида на живом `ThrottleMiddleware` показал,
    что строка НЕ троттлит, а роняет троттл со второго вызова
    (`TypeError: unsupported operand type(s) for /: 'float' and 'str'`).
    Значит молчание сверщика скрывало не потолок, а СЛОМАННОЕ правило — самый
    дорогой вид молчания, потому что его читают как подтверждение.

    Живого воспроизведения падения здесь намеренно НЕТ: пришпиливать чужой
    дефект (`state_store_module`) как ожидаемое поведение значит закрепить его.
    Сторожится только показание сверщика.
    """

    def test_a_string_interval_lands_in_the_fan_with_its_own_reason(self) -> None:
        """Правило есть, интервал не число → `"unreadable_rule"`, а не тишина."""
        caps, unjudged = judge_throttle_caps(
            {"metrics": {"fps": {"interval_sec": 0.0}}},
            _Throttle({"processes.**.state.fps": "0.05"}),
            effective_tick=None,
        )

        assert caps == {}, caps
        assert unjudged == {"fps": "unreadable_rule"}, unjudged

    def test_the_path_half_names_it_too(self) -> None:
        """Та же причина у половины по ПУТИ — иначе снова две дисциплины.

        Форма нечисла здесь другая (объект вместо скаляра — обычная описка
        оператора, пишущего правило как секцию), и намеренно НЕ ``None``:
        ``None`` в языке дельты троттла это маркер удаления
        (:data:`THROTTLE_REMOVE`), и в живых ``rules`` он не остаётся.
        """
        caps, unjudged = judge_throttle_caps(
            {},
            _Throttle({"proc.state.fps": {"interval_sec": 0.05}}),
            observation_rules={"proc.state.fps": {"enabled": True, "interval_sec": 1.0}},
            effective_tick=None,
        )

        assert caps == {}, caps
        assert unjudged == {"proc.state.fps": "unreadable_rule"}, unjudged

    def test_no_rule_at_all_stays_silent(self) -> None:
        """Пара-контроль: «правила нет» по-прежнему молчит.

        Если бы обе формы попали в веер, новая причина не значила бы ничего:
        отсутствие правила — самое частое состояние любого адреса.
        """
        caps, unjudged = judge_throttle_caps(
            {"metrics": {"fps": {"interval_sec": 0.0}}},
            _Throttle({"other.state.drops": 2.0}),
            effective_tick=None,
        )

        assert caps == {}, caps
        assert unjudged == {}, unjudged

    def test_a_readable_rule_next_to_an_unreadable_one_still_judges(self) -> None:
        """Названный потолок правки: адрес, покрытый обоими, судится по читаемому.

        Пришпилено литералом, потому что это ВЫБОР, а не следствие: расширить
        его до «называть и то и другое» нельзя, не заведя второй список в
        ответе. Пока сломанное правило рядом с рабочим молчит.
        """
        caps, unjudged = judge_throttle_caps(
            {"metrics": {"fps": {"interval_sec": 0.5}}},
            _Throttle({"processes.**.state.fps": 2.0, "other.**.state.fps": "0.05"}),
            effective_tick=None,
        )

        assert caps == {"fps": {"publisher_interval_sec": 0.5, "throttle_interval_sec": 2.0}}, caps
        assert unjudged == {}, unjudged
