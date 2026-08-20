# -*- coding: utf-8 -*-
"""Авторские hazard-тесты резолвера подстановочного сегмента счётчиков.

**Что может сломаться именно в ЭТОМ механизме, учитывая, как он устроен.**
``ProcessMonitor._read_state_counter`` заменяет одну точку — «прочитать целое по
пути» — на «прочитать поддерево, обойти детей, сложить одноимённые листья». Всё
опасное лежит в местах, которых у точечного чтения не было:

1. *Поддерева нет.* Раньше промах пути возвращал ``None``, и монитор шёл к
   следующему кандидату. Резолвер обязан вести себя так же — иначе ``0`` от
   пустого места ЗАСЛОНИТ плоских кандидатов, идущих следом в ``counter_paths``,
   и правило починится «в одну сторону»: новый адрес заработает, старый умрёт.
   Класс ровно тот, ради которого фаза и затевалась.
2. *Поддерево есть, но одноимённых листьев в нём нет.* Отличается от (1) тем,
   что ``handle_state_get`` отвечает ``ok`` со словарём — путь для обхода
   успешный, а сигнала нет. Тот же вывод: ``None``, не ``0``.
3. *Лист нечисловой.* ``None`` (снятое показание), строка, ``float``, ``bool``
   (подкласс ``int``! ``True`` стал бы «счётчиком 1»). Ни один из них не смеет
   ни попасть в сумму, ни отменить сумму соседа: писатель, сломавший свой лист,
   не должен ослеплять правило для остальных.
4. *Два писателя.* Проверяется НЕ «сумма посчиталась», а свойство, ради которого
   сумму выбрали: рост ЛЮБОГО писателя виден. Обе перестановки, потому что
   «первый резолвящийся» ошибается ровно на одной из них.
5. *Сброс.* Уход писателя уменьшает сумму скачком — рестарт/стоп плагина не
   должен читаться как всплеск потерь.
6. *Форма пути.* Двух подстановок механизм не разрешает; отказ обязан быть
   ГРОМКИМ (лог), а не тихим ``None`` — тихий отказ здесь неотличим от «правило
   мертво», а именно за этим фаза и охотится.

Читается всё через ``_read_state_counter`` — публичную-по-факту точку монитора,
которую зовёт ``_check_counter_alerts``; проверки уровня «алерт вышел» лежат в
``test_alerting.py`` (``TestDropsRuleAgainstRealTickOutput``) и не дублируются
здесь намеренно: тут — арифметика резолвера, там — свойство правила.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

from ..core.alert_rules import AlertRule
from ..core.restart_policy import RestartPolicy
from ..monitor.process_monitor import ProcessMonitor

_WILDCARD = "processes.cam.state.plugins.*.drops"


def _monitor_over(tree: dict[str, Any]):
    """Монитор поверх НАСТОЯЩЕГО TreeStore, наполненного ``tree``.

    Настоящий store, а не словарь-фейк: резолвер спрашивает ПОДДЕРЕВО, и фейк
    «путь → значение» отвечал бы на этот вопрос иначе, чем боевой StateStore, —
    тест согласился бы с собственной моделью вместо системы.
    """
    from ...state_store_module.manager.state_store_manager import StateStoreManager

    ssm = StateStoreManager()
    if tree:
        ssm.store.merge("", tree)
    pm = MagicMock()
    pm._process_configs = {}
    pm._state_store_manager = ssm
    mon = ProcessMonitor(pm, restart_policy=RestartPolicy(enabled=True))
    return pm, mon, ssm


def _plugins(**writers: Any) -> dict:
    return {"processes": {"cam": {"state": {"plugins": dict(writers)}}}}


class TestMissingAndEmpty:
    def test_absent_subtree_reads_as_no_signal(self) -> None:
        """Поддерева нет → ``None`` (не ``0``): следующий кандидат обязан получить ход."""
        _pm, mon, _ssm = _monitor_over({})
        assert mon._read_state_counter(_WILDCARD) is None

    def test_empty_subtree_reads_as_no_signal(self) -> None:
        """Поддерево есть, но пусто — тот же вывод, ДРУГОЙ путь исполнения.

        Здесь ``handle_state_get`` отвечает ``ok`` со словарём (в предыдущем
        тесте — ``error``), то есть ветка кода другая. Раздельные тесты, потому
        что починка одной ветки не чинит вторую.
        """
        _pm, mon, ssm = _monitor_over({})
        ssm.store.merge("", _plugins())
        assert mon._read_state_counter(_WILDCARD) is None

    def test_writers_without_the_leaf_read_as_no_signal(self) -> None:
        """Писатели есть, а листа ``drops`` ни у кого нет → ``None``."""
        _pm, mon, _ssm = _monitor_over(_plugins(capture={"fps": 12}, mask={"frame_count": 3}))
        assert mon._read_state_counter(_WILDCARD) is None

    def test_falls_through_to_the_flat_candidate_when_the_subtree_is_absent(self) -> None:
        """Свойство, ради которого «пусто» = ``None``, а не ``0``.

        Плоский писатель (прямая запись в ``state``, дорога мимо
        ``publish_metric``) обязан оставаться видимым, пока плагинного поддерева
        нет. Если резолвер вернёт ``0``, монитор возьмёт его первым и плоский
        кандидат не будет опрошен НИКОГДА.

        Бьёт по ветке «поддерева НЕТ» — ранний выход по ``not isinstance(dict)``.
        Соседние два теста бьют по веткам «поддерево ЕСТЬ, но пусто» и «писатели
        есть, листа нет», и это ДРУГОЙ код: узкая инъекция «пусто → 0» в самом
        накопителе оставляет этот тест зелёным (измерено ревью Task 1.4,
        находка 7), а те — нет.
        """
        _pm, mon, ssm = _monitor_over({})
        ssm.store.set("processes.cam.state.drops", 9)
        rule = AlertRule(
            "r",
            counter_paths=(_WILDCARD.replace("cam", "{process}"), "processes.{process}.state.drops"),
        )
        resolved = [mon._read_state_counter(p) for p in rule.paths_for("cam")]
        assert resolved == [None, 9]

    def test_falls_through_to_the_flat_candidate_when_the_subtree_is_empty(self) -> None:
        """Тот же вывод по ДРУГОЙ ветке: поддерево есть, писателей в нём нет.

        Добавлен по ревью Task 1.4 (находка 7): один тест выше покрывал только
        ранний выход, поэтому узкая инъекция в накопитель суммы свойство
        «плоский кандидат остаётся достижим» не убивала.
        """
        _pm, mon, ssm = _monitor_over(_plugins())
        ssm.store.set("processes.cam.state.drops", 9)
        rule = AlertRule(
            "r",
            counter_paths=(_WILDCARD.replace("cam", "{process}"), "processes.{process}.state.drops"),
        )
        resolved = [mon._read_state_counter(p) for p in rule.paths_for("cam")]
        assert resolved == [None, 9]

    def test_falls_through_when_writers_exist_but_none_carries_the_leaf(self) -> None:
        """Третья ветка: писатели есть, листа ``drops`` нет ни у кого.

        Здесь обход доходит до конца и ``total`` остаётся ``None`` — ровно то
        место, куда бьёт инъекция «пусто → 0».
        """
        _pm, mon, ssm = _monitor_over(_plugins(capture={"fps": 12}))
        ssm.store.set("processes.cam.state.drops", 9)
        rule = AlertRule(
            "r",
            counter_paths=(_WILDCARD.replace("cam", "{process}"), "processes.{process}.state.drops"),
        )
        resolved = [mon._read_state_counter(p) for p in rule.paths_for("cam")]
        assert resolved == [None, 9]


class TestNonNumericLeaves:
    def test_none_leaf_is_not_a_signal(self) -> None:
        """Снятое показание (``None``) сигнала не даёт."""
        _pm, mon, _ssm = _monitor_over(_plugins(capture={"drops": None}))
        assert mon._read_state_counter(_WILDCARD) is None

    def test_string_leaf_is_not_a_signal(self) -> None:
        _pm, mon, _ssm = _monitor_over(_plugins(capture={"drops": "12"}))
        assert mon._read_state_counter(_WILDCARD) is None

    def test_float_leaf_is_not_a_signal(self) -> None:
        """Контракт счётчика — целое; дробный лист для правила невидим.

        Названный потолок, а не забытая ветка: тот же фильтр стоит в
        ``counter_growth``, и разойтись им нельзя.
        """
        _pm, mon, _ssm = _monitor_over(_plugins(capture={"drops": 12.5}))
        assert mon._read_state_counter(_WILDCARD) is None

    def test_bool_leaf_is_not_a_counter_of_one(self) -> None:
        """``bool`` — подкласс ``int``: ``True`` не смеет стать «счётчиком 1»."""
        _pm, mon, _ssm = _monitor_over(_plugins(capture={"drops": True}))
        assert mon._read_state_counter(_WILDCARD) is None

    def test_broken_writer_does_not_blind_the_healthy_neighbour(self) -> None:
        """Два писателя, РАЗНЫЙ тип значения: испорченный не отменяет исправного.

        ``11``, а не ``11.0`` и не ``None``: сумма обязана быть частичной. Это
        решение — писатель со сломанным листом теряет видимость сам, но не
        ослепляет правило для соседей.
        """
        _pm, mon, _ssm = _monitor_over(_plugins(alpha={"drops": 11}, bravo={"drops": "не число"}))
        assert mon._read_state_counter(_WILDCARD) == 11

    def test_non_dict_child_under_plugins_is_skipped(self) -> None:
        """Ребёнок-скаляр (кривая запись прямо в ``plugins.<имя>``) не роняет обход."""
        _pm, mon, ssm = _monitor_over(_plugins(alpha={"drops": 4}))
        ssm.store.set("processes.cam.state.plugins.stray", 99)
        assert mon._read_state_counter(_WILDCARD) == 4


class TestTwoWriters:
    def test_sum_over_writers(self) -> None:
        _pm, mon, _ssm = _monitor_over(_plugins(alpha={"drops": 4}, bravo={"drops": 6}))
        assert mon._read_state_counter(_WILDCARD) == 10

    def test_growth_of_the_first_writer_is_visible(self) -> None:
        """Свойство, а не арифметика: рост A виден при стоящем B."""
        _pm, mon, ssm = _monitor_over(_plugins(alpha={"drops": 4}, bravo={"drops": 6}))
        before = mon._read_state_counter(_WILDCARD)
        ssm.store.set("processes.cam.state.plugins.alpha.drops", 9)
        assert mon._read_state_counter(_WILDCARD) == before + 5

    def test_growth_of_the_second_writer_is_visible(self) -> None:
        """Обязателен рядом с предыдущим: «первый резолвящийся» ошибается ровно здесь."""
        _pm, mon, ssm = _monitor_over(_plugins(alpha={"drops": 4}, bravo={"drops": 6}))
        before = mon._read_state_counter(_WILDCARD)
        ssm.store.set("processes.cam.state.plugins.bravo.drops", 11)
        assert mon._read_state_counter(_WILDCARD) == before + 5

    def test_order_of_writers_does_not_change_the_result(self) -> None:
        """Сумма не зависит от порядка вставки — иначе dict-порядок стал бы контрактом."""
        _pm, mon_a, _ = _monitor_over(_plugins(alpha={"drops": 4}, bravo={"drops": 6}))
        _pm2, mon_b, _ = _monitor_over(_plugins(bravo={"drops": 6}, alpha={"drops": 4}))
        assert mon_a._read_state_counter(_WILDCARD) == mon_b._read_state_counter(_WILDCARD) == 10


class TestResetSemantics:
    def test_departed_writer_lowers_the_sum(self) -> None:
        """Уход писателя — уменьшение суммы (наблюдаемый факт, до трактовки)."""
        _pm, mon, ssm = _monitor_over(_plugins(alpha={"drops": 4}, bravo={"drops": 6}))
        assert mon._read_state_counter(_WILDCARD) == 10
        ssm.store.delete("processes.cam.state.plugins.bravo")
        assert mon._read_state_counter(_WILDCARD) == 4

    def test_a_drop_in_the_sum_is_not_growth(self) -> None:
        """…и трактовка: правило на уменьшении молчит (рестарт ≠ всплеск потерь).

        Проверяется сквозь ``_check_counter_alerts``, а не сквозь
        ``counter_growth``: связка «резолвер → база → правило» и есть то место,
        где сброс мог бы стать алертом.
        """
        pm, mon, ssm = _monitor_over(_plugins(alpha={"drops": 4}, bravo={"drops": 6}))
        os_proc = MagicMock()
        os_proc.name = "cam"
        pm._process_registry.os_processes = [os_proc]
        published: list[tuple[str, Any]] = []
        mon._publish_state = lambda p, v: published.append((p, v))  # type: ignore[assignment]

        mon._check_counter_alerts()  # база = 10
        ssm.store.delete("processes.cam.state.plugins.bravo")  # осталось 4
        mon._check_counter_alerts()

        assert not any("drops_growing" in p for p, _ in published)
        assert mon._counter_baseline[("drops_growing", "cam")] == 4


class TestPathShape:
    def test_two_wildcards_are_refused_loudly(self) -> None:
        """Отказ громкий: ``None`` + запись в лог, а не тихий ``None``.

        Тихий отказ здесь неотличим от «правило мертво» — ровно тот класс, ради
        которого механизм и переделывался.
        """
        pm, mon, _ssm = _monitor_over(_plugins(alpha={"drops": 4}))
        assert mon._read_state_counter("processes.*.state.plugins.*.drops") is None
        assert pm._log_warning.called, "двойная подстановка отвергнута молча"

    def test_path_without_wildcard_keeps_the_exact_read(self) -> None:
        """Форма без ``*`` — прежнее точечное чтение, бит-в-бит."""
        _pm, mon, ssm = _monitor_over({})
        ssm.store.set("processes.cam.state.drops", 7)
        assert mon._read_state_counter("processes.cam.state.drops") == 7
        assert mon._read_state_counter("processes.cam.state.nope") is None

    def test_leading_wildcard_is_refused_loudly(self) -> None:
        """Ведущая ``*``: префикса нет — отказ ТОТ ЖЕ громкий, что у двух подстановок.

        Ревью Task 1.4, находка 5: умирал молча (``None`` без единой записи в
        лог), хотя весь механизм затевался против «правило мертво и не жалуется».
        """
        pm, mon, _ssm = _monitor_over(_plugins(alpha={"drops": 4}))
        assert mon._read_state_counter("*.state.drops") is None
        assert pm._log_warning.called, "ведущая подстановка отвергнута молча"

    def test_wildcard_at_the_tail_collects_the_writer_names_not_leaves(self) -> None:
        """``*`` последним сегментом собирает ДЕТЕЙ, а не одноимённые листья.

        Форма вырожденная и в правилах не используется; тест фиксирует, что она
        не падает и не выдаёт случайное число: у детей-словарей целых значений
        нет, значит сигнала нет.
        """
        _pm, mon, _ssm = _monitor_over(_plugins(alpha={"drops": 4}))
        assert mon._read_state_counter("processes.cam.state.plugins.*") is None


class TestNewWriterArrival:
    """ПРИХОД писателя — названный потолок, а не проверенная гарантия.

    Уход писателя прощён ``counter_growth``'ом (уменьшение суммы = сброс, роста
    нет). Приход — НЕ прощён: новый писатель с ненулевым первым значением
    поднимает сумму скачком, и правило прочтёт это как рост. Найдено ревью
    Task 1.4 (находка 2); докстринг ``_read_state_counter`` называл только уход.

    Тесты ПРИШПИЛИВАЮТ сегодняшнее — ложное — поведение, а не объявляют его
    правильным. Приём осознанный: базу пер-писателя в Task 1.4 не делаем (она
    меняет форму ``_counter_baseline``, общую с плоскими кандидатами), и без
    такого теста будущая починка выглядела бы случайной регрессией. Когда базу
    заведут — тест обязан покраснеть, и красным он скажет «ожидание пора
    менять», а не «что-то сломалось».
    """

    @staticmethod
    def _armed(tree: dict):
        pm, mon, ssm = _monitor_over(tree)
        os_proc = MagicMock()
        os_proc.name = "cam"
        pm._process_registry.os_processes = [os_proc]
        published: list[tuple[str, Any]] = []
        mon._publish_state = lambda p, v: published.append((p, v))  # type: ignore[assignment]
        return mon, ssm, published

    def test_arriving_writer_with_a_nonzero_first_value_raises_a_false_alert(self) -> None:
        """Сегодня: приезд второго писателя с ``drops=500`` → алерт «вырос на 500».

        Достижимо не гипотетически: ``RingBuffer.drops_count`` — величина
        КУМУЛЯТИВНАЯ, такой писатель приедет с ненулевым первым значением.
        ``CapturePlugin`` стартует с нуля и этой дорогой не ходит.
        """
        mon, ssm, published = self._armed(_plugins(alpha={"drops": 0}))

        mon._check_counter_alerts()  # база = 0
        ssm.store.set("processes.cam.state.plugins.bravo.drops", 500)  # ПРИХОД
        mon._check_counter_alerts()

        reasons = [v for p, v in published if p.endswith("drops_growing.reason")]
        assert reasons, (
            "поведение изменилось: приход писателя больше не даёт алерт. Если "
            "заведена база пер-писателя — это ПОЧИНКА: обнови ожидание теста, "
            "снятый потолок в докстринге _read_state_counter и в ADR-PMM-021"
        )
        assert "вырос на 500" in str(reasons[0]), (
            f"величина ложного алерта изменилась: {reasons!r} — механизм суммы поменялся, потолок надо перепроверить"
        )

    def test_a_writer_arriving_at_zero_is_silent(self) -> None:
        """Пара-контроль: приход писателя с нулём алерта НЕ даёт.

        Без него предыдущий тест неотличим от «любой приход шумит» — а шумит
        именно ненулевое первое значение. Это и есть граница потолка.
        """
        mon, ssm, published = self._armed(_plugins(alpha={"drops": 7}))

        mon._check_counter_alerts()  # база = 7
        ssm.store.set("processes.cam.state.plugins.bravo.drops", 0)  # приход с нулём
        mon._check_counter_alerts()

        assert not any("drops_growing" in p for p, _ in published)
