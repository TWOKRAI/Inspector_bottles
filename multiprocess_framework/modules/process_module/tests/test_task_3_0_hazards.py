# -*- coding: utf-8 -*-
"""Сторожа ОПАСНОСТЕЙ механизма Task 3.0 (observability-closure, Ф3) — от автора правки.

Отдельный файл от ``test_task_3_0_throttle_ask.py`` намеренно: там приёмка
независимого тестера, написанная по критериям и ДО реализации, здесь — то, что
видно только автору, когда он смотрит на собственный код и спрашивает «чем ЭТОТ
механизм может подвести», а не «выполнен ли критерий».

Механизм: :func:`~..managers.telemetry_reload.judge_throttle_caps` — сверщик
потолков central-троттла, обещание проекта «no silent caps» (ADR-PM-017).
Правка 3.0 сделала две вещи, и обе добавили новые способы соврать:

1. **Такт стал НИЖНЕЙ ГРАНИЦЕЙ ask'а** (F1). Раньше такт участвовал ровно в
   одном месте — замещал заявку, которой нет. Теперь он участвует ВСЕГДА, а
   значит любой мусор, проехавший в ``effective_tick``, попадает в
   арифметику каждого кандидата, а не только нулевых. Опасные формы мусора у
   числа в Python три, и все три сравниваются с нулём молча: ``bool``
   (``True > 0`` истинно), ``NaN`` (все сравнения ложны, но ``max`` его
   ПРОПУСКАЕТ наружу) и отрицательное значение (проезжает из слоя, см.
   ``apply_heartbeat_interval``). Мусор здесь не роняет ничего — он печатает
   оператору частоту, которой не будет, рядом со словом «потолок».
2. **Ответ стал парой** (F2). Появилась вторая корзина, и с ней — способ выдать
   ДВА показания об одном ключе: «потолок вот такой» и «рассудить было нечем».
   Ключи у половин разной природы (ИМЯ метрики против ПУТИ-паттерна), но
   строкой совпасть могут, а один проход теперь наполняет обе корзины.

Чего эти тесты НЕ проверяют (это забота приёмки тестера): сами критерии F1/F2 на
типовых числах и присутствие ключа ``capped_by_throttle_unjudged`` в ответе
``config.reload``.
"""

from __future__ import annotations

from multiprocess_framework.modules.process_module.managers.telemetry_reload import (
    detect_throttle_caps,
    judge_throttle_caps,
)

NAN = float("nan")


class _Throttle:
    """Central-троттл оркестратора: минимум того, что читает сверщик."""

    def __init__(self, rules) -> None:
        self.rules = rules


# =========================================================================== #
# Такт как нижняя граница: границы и знак
# =========================================================================== #
class TestTheTickIsALowerBoundAndItsEdges:
    """Что ломается: ask считается по ДВУМ числам вместо одного.

    Раньше ask был либо заявкой, либо тактом — две непересекающиеся ветки. Теперь
    это одна арифметика над парой, и у неё есть край (равенство) и знак
    (отрицательная заявка), на которых «безопасная сторона» ошибки меняется
    местами: перепутанный край даёт лишнее предупреждение, перепутанный знак —
    молчание там, где надо кричать, либо крик про частоту ``-1.0``.
    """

    def test_a_claim_equal_to_the_tick_is_reported_verbatim(self) -> None:
        """Заявка РОВНО равна такту — в отчёт идёт она, без сдвига на край.

        Край выбран потому, что здесь ошибка «>» против «>=» невидима в обычных
        числах: при заявке 1.0 и такте 1.0 любая из двух веток даёт 1.0, и
        только сравнение с СОСЕДНИМ полем отчёта (троттл 2.0) показывает, что
        ask не уехал ни в одну сторону.
        """
        caps, unjudged = judge_throttle_caps(
            {"metrics": {"fps": {"interval_sec": 1.0}}},
            _Throttle({"**.state.fps": 2.0}),
            effective_tick=1.0,
        )

        assert caps == {"fps": {"publisher_interval_sec": 1.0, "throttle_interval_sec": 2.0}}, caps
        assert unjudged == {}, unjudged

    def test_a_negative_claim_with_a_usable_tick_is_judged_by_the_tick(self) -> None:
        """Отрицательная заявка — это «заявки нет», а не «частота быстрее любой».

        Достижимость: ``interval_sec`` в правиле порта приходит из слоя конфига,
        и отрицательное значение отбивается не везде (тот же класс, что у
        вырожденного такта — см. долг ``apply_heartbeat_interval``, Task 2.11).
        Если бы отрицательная заявка доехала до арифметики буквально, ``max``
        вернул бы такт и здесь — но при НЕИЗВЕСТНОМ такте (следующий тест)
        она дала бы ``-1.0`` в поле ``publisher_interval_sec`` и потолок почти
        на любом правиле: троттл строже минус единицы всегда.
        """
        caps, unjudged = judge_throttle_caps(
            {"metrics": {"fps": {"interval_sec": -1.0}}},
            _Throttle({"**.state.fps": 3.0}),
            effective_tick=2.0,
        )

        assert caps == {"fps": {"publisher_interval_sec": 2.0, "throttle_interval_sec": 3.0}}, caps
        assert unjudged == {}, unjudged

    def test_a_negative_claim_without_a_tick_is_unjudged_not_reported(self) -> None:
        """Вторая половина пары: без такта отрицательная заявка НЕ судится.

        Именно здесь буквальное чтение знака и стало бы видно: ``-1.0`` — это
        частота, которой не бывает, и печатать её рядом со словом «потолок»
        значит утверждать несуществующий срез.
        """
        caps, unjudged = judge_throttle_caps(
            {"metrics": {"fps": {"interval_sec": -1.0}}},
            _Throttle({"**.state.fps": 3.0}),
            effective_tick=None,
        )

        assert caps == {}, caps
        assert unjudged == {"fps": "no_tick"}, unjudged


# =========================================================================== #
# Типы, которые выглядят числами
# =========================================================================== #
class TestValuesThatLookLikeNumbersButAreNot:
    """Что ломается: ``bool`` и ``NaN`` проходят ``isinstance(x, (int, float))``.

    В соседнем коде этого файла проверки ``isinstance(x, bool)`` уже стоят —
    значит класс не гипотетический, его один раз уже ловили. Правка 3.0 завела
    ТРЕТЬЕ место, где число попадает в арифметику (``effective_tick`` теперь
    участвует в каждом кандидате), и страж нужен именно там.
    """

    def test_a_boolean_tick_is_not_a_tick(self) -> None:
        """``effective_tick=True`` — это флаг, а не 1.0 секунды.

        ``True > 0.0`` в Python истинно, и без явной отбивки ``bool`` сверщик
        рассудил бы кандидата по «такту одна секунда», которого никто не
        настраивал, и напечатал бы ``publisher_interval_sec: 1.0``. Правильный
        исход — тот же, что у неизвестного такта: «не судили».
        """
        caps, unjudged = judge_throttle_caps(
            {"metrics": {"fps": {"interval_sec": 0.0}}},
            _Throttle({"**.state.fps": 2.0}),
            effective_tick=True,
        )

        assert caps == {}, caps
        assert unjudged == {"fps": "no_tick"}, unjudged

    def test_a_nan_tick_does_not_poison_a_valid_claim(self) -> None:
        """``NaN``-такт не должен просочиться в ask через ``max``.

        Ловушка тонкая и своя именно у ``max``: все сравнения с ``NaN`` ложны,
        поэтому ``max(1.0, NaN)`` возвращает **NaN**, а не 1.0. Живая заявка
        1.0 с при этом превратилась бы в ``publisher_interval_sec: nan``, и
        сравнение с троттлом (``2.0 > nan`` ложно) молча убрало бы РЕАЛЬНЫЙ
        срез из отчёта — то есть «no silent caps» перестало бы действовать от
        одного нечисла в readback'е.
        """
        caps, unjudged = judge_throttle_caps(
            {"metrics": {"fps": {"interval_sec": 1.0}}},
            _Throttle({"**.state.fps": 2.0}),
            effective_tick=NAN,
        )

        assert caps == {"fps": {"publisher_interval_sec": 1.0, "throttle_interval_sec": 2.0}}, caps
        assert unjudged == {}, unjudged

    def test_a_nan_tick_with_no_claim_is_read_as_no_tick(self) -> None:
        """Пара к предыдущему: без заявки ``NaN``-такт даёт «не судили».

        Без этой половины первая доказывала бы только «``NaN`` не мешает
        заявке», но не «``NaN`` не считается тактом»: заявка могла бы
        побеждать его и по ошибке.
        """
        caps, unjudged = judge_throttle_caps(
            {"metrics": {"fps": {"interval_sec": 0.0}}},
            _Throttle({"**.state.fps": 2.0}),
            effective_tick=NAN,
        )

        assert caps == {}, caps
        assert unjudged == {"fps": "no_tick"}, unjudged

    def test_a_nan_claim_is_read_as_no_claim_and_the_tick_wins(self) -> None:
        """Зеркало: ``NaN`` в ЗАЯВКЕ тоже не должен доехать до ``max``.

        Тот же механизм с другой стороны: ``max(NaN, 5.0)`` — это NaN. Заявка
        приходит из конфига оператора, где ``.nan`` — валидный YAML-скаляр,
        поэтому вход достижим не только из теста.
        """
        caps, unjudged = judge_throttle_caps(
            {"metrics": {"fps": {"interval_sec": NAN}}},
            _Throttle({"**.state.fps": 6.0}),
            effective_tick=5.0,
        )

        assert caps == {"fps": {"publisher_interval_sec": 5.0, "throttle_interval_sec": 6.0}}, caps
        assert unjudged == {}, unjudged

    def test_a_boolean_claim_stays_outside_both_reports(self) -> None:
        """``interval_sec=True`` не судится и в веер «не судил» тоже не идёт.

        Граница задачи 3.0, зафиксированная намеренно: нечисловой
        ``interval_sec`` в publish-дельте с самого начала значит «наследуй
        default — неоднозначно, не флагуем», и правка F2 этой семантики не
        трогала. Пришпилено литералом, чтобы расширение веера на другие причины
        было РЕШЕНИЕМ (с новой причиной-литералом), а не побочным эффектом.
        """
        caps, unjudged = judge_throttle_caps(
            {"metrics": {"fps": {"interval_sec": True}}},
            _Throttle({"**.state.fps": 2.0}),
            effective_tick=None,
        )

        assert caps == {}, caps
        assert unjudged == {}, unjudged


# =========================================================================== #
# Две половины в ОДНОМ проходе
# =========================================================================== #
class TestBothHalvesShareOnePass:
    """Что ломается: корзин стало две, а проход — один.

    До 3.0 половины наполняли один словарь, и «попасть в оба ответа» было
    невозможно физически. Теперь каждая половина может положить ОДИН И ТОТ ЖЕ
    строковый ключ в разные корзины, и ответ команды ``config.reload`` сказал бы
    про него два разных факта сразу.
    """

    #: Правило троттла, которое ловится ОБЕИМИ половинами: суффикс-матч по имени
    #: метрики (``_central_rule_for_metric``) и пересечение глобов по пути
    #: (``_central_rule_for_path_pattern``) дают на нём одно и то же правило.
    RULES = {"fps": 6.0}

    def test_one_key_never_appears_in_both_reports(self) -> None:
        """Ключ ``fps`` судим одной половиной и не судим другой — побеждает суд.

        Вход собран так, что половины расходятся: у метрики заявка есть (1.0 →
        капнута троттлом 6.0), у одноимённого правила порта заявки нет и такта
        нет (→ «не судили»). Утверждение сильнее молчания, поэтому ключ обязан
        остаться только в ``caps``.
        """
        caps, unjudged = judge_throttle_caps(
            {"metrics": {"fps": {"interval_sec": 1.0}}},
            _Throttle(self.RULES),
            observation_rules={"fps": {"enabled": True, "interval_sec": 0.0}},
            effective_tick=None,
        )

        assert caps == {"fps": {"publisher_interval_sec": 1.0, "throttle_interval_sec": 6.0}}, caps
        assert "fps" not in unjudged, unjudged

    def test_the_two_halves_do_not_hide_each_other(self) -> None:
        """Контроль к предыдущему: РАЗНЫЕ ключи обеих половин доезжают оба.

        Без этой половины «ключ только в caps» проходило бы и у сверщика,
        который вторую половину прохода просто не выполняет.
        """
        caps, unjudged = judge_throttle_caps(
            {"metrics": {"fps": {"interval_sec": 0.0}}},
            _Throttle({"fps": 6.0, "drops": 4.0}),
            observation_rules={"drops": {"enabled": True, "interval_sec": 0.0}},
            effective_tick=None,
        )

        assert caps == {}, caps
        assert unjudged == {"fps": "no_tick", "drops": "no_tick"}, unjudged


# =========================================================================== #
# Охват веера «не судил»
# =========================================================================== #
class TestTheUnjudgedFanIsNotTheWholeTree:
    """Что ломается: веер, который называет всё, не называет ничего.

    Решение реализации: кандидат попадает в ``unjudged`` только если на его
    адрес ЕСТЬ пересекающееся central-правило. Иначе ответ определён и без
    ask'а — потолку неоткуда взяться. Обратное решение (называть всех, кого не
    рассудили арифметически) залило бы веер каждым листом дерева при выключенном
    heartbeat'е, и поле, заведённое ради честности, читалось бы как шум — тот же
    исход, ради снятия которого делалась Р-11.
    """

    RULE = {"proc.state.fps": {"enabled": True, "interval_sec": 0.0}}

    def test_a_candidate_no_central_rule_can_touch_is_silent(self) -> None:
        """Правило троттла на ЧУЖОЙ адрес — кандидат не судим и не назван."""
        caps, unjudged = judge_throttle_caps(
            {},
            _Throttle({"other.state.drops": 2.0}),
            observation_rules=self.RULE,
            effective_tick=0.0,
        )

        assert caps == {}, caps
        assert unjudged == {}, unjudged

    def test_the_same_candidate_is_named_when_a_rule_can_touch_it(self) -> None:
        """Пара: то же правило порта, тот же непригодный такт — но правило
        троттла теперь пересекается, и кандидат обязан быть назван.

        Без этой половины предыдущая доказывала бы «веер всегда пуст».
        """
        caps, unjudged = judge_throttle_caps(
            {},
            _Throttle({"proc.state.fps": 2.0}),
            observation_rules=self.RULE,
            effective_tick=0.0,
        )

        assert caps == {}, caps
        assert unjudged == {"proc.state.fps": "no_tick"}, unjudged


# =========================================================================== #
# Обёртка
# =========================================================================== #
class TestTheWrapperKeepsTheOldContract:
    """Что ломается: у ``detect_throttle_caps`` сменился ТИП ответа.

    Вызывающие вне задачи 3.0 (``builtin_commands``, GUI-presenter, тесты
    соседних фаз) распаковывают ответ как словарь. Обёртка, вернувшая пару,
    сломала бы их не исключением, а тихо: ``dict(("caps", "unjudged"))``
    падает, но ``bool(pair)`` истинно всегда, и ветка «потолков нет» перестала
    бы срабатывать.
    """

    def test_the_wrapper_returns_a_plain_dict_not_the_pair(self) -> None:
        """Тип ответа — словарь, а не кортеж (страж «обёртка не сменила контракт»)."""
        caps = detect_throttle_caps(
            {"metrics": {"fps": {"interval_sec": 1.0}}},
            _Throttle({"**.state.fps": 6.0}),
            effective_tick=None,
        )

        assert isinstance(caps, dict), type(caps)
        assert caps == {"fps": {"publisher_interval_sec": 1.0, "throttle_interval_sec": 6.0}}, caps

    def test_no_throttle_at_all_is_an_empty_dict_from_both_entry_points(self) -> None:
        """``store_throttle=None`` — у процесса нет central-троттла (он у оркестратора).

        Ранний выход теперь стоит ДО создания обеих корзин, и это тот шов, на
        котором обёртка легче всего разошлась бы с ядром: у одной ветки ответ
        ``{}``, у другой — ``({}, {})``.
        """
        assert detect_throttle_caps({"metrics": {"fps": {"interval_sec": 1.0}}}, None) == {}
        assert judge_throttle_caps({"metrics": {"fps": {"interval_sec": 1.0}}}, None) == ({}, {})

    def test_an_empty_rule_set_is_an_empty_dict_from_both_entry_points(self) -> None:
        """Троттл есть, правил нет — сверять не с чем, но и «не судили» тут нет:
        отсутствие правил определяет ответ так же, как отсутствие пересечения."""
        assert detect_throttle_caps({"metrics": {"fps": {"interval_sec": 0.0}}}, _Throttle({})) == {}
        assert judge_throttle_caps({"metrics": {"fps": {"interval_sec": 0.0}}}, _Throttle({})) == ({}, {})

    def test_observation_rules_alone_still_reach_the_wrapper(self) -> None:
        """Боевой вызывающий (``apply_observation_policy``) шлёт ``publish_section=None``
        и работает ТОЛЬКО правилами порта — обёртка обязана донести и эту половину.

        Пришпилено потому, что обёртка перекладывает пять аргументов вручную:
        потерянный по дороге ``observation_rules`` дал бы ровно тот
        утвердительный ноль, против которого стоит вся эта функция.
        """
        caps = detect_throttle_caps(
            None,
            _Throttle({"proc.state.fps": 2.0}),
            observation_rules={"proc.state.fps": {"enabled": True}},
            default_interval_sec=0.5,
            effective_tick=None,
        )

        assert caps == {"proc.state.fps": {"publisher_interval_sec": 0.5, "throttle_interval_sec": 2.0}}, caps
