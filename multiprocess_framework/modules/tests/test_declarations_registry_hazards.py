# -*- coding: utf-8 -*-
"""Авторские hazard-тесты реестра объявлений (Ф0.1 «trust gate»).

**Что может сломаться в ЭТОМ механизме, учитывая, как он построен.** Приёмка
(``test_declarations_leak_*.py``, написана независимо и до реализации) сторожит
КОНТРАКТ: голый ``forget_declarations()`` отказывает, ``snapshot``/``restore``
существуют и откатывают, каталог фреймворка на закрытии сессии равен пятёрке.
Здесь — опасности УСТРОЙСТВА, которых из критериев не видно, потому что они
следуют из трёх решений реализации:

1. **``restore`` — возврат К СНИМКУ, а не «убрать лишнее».** Значит порядок
   восстановления вложенных снимков значит (:class:`TestNestedSnapshots`), а
   объявление, приехавшее ИМПОРТОМ во время теста, возврат уносит навсегда
   (:class:`TestRestoreCannotResurrectImports`) — отсюда догрев в фикстурах.

2. **Отказ поставлен на СИГНАТУРУ, а не на намерение.** Легитимных вызовов
   ``forget_declarations`` в дереве шестнадцать файлов, и все формы обязаны
   выжить — включая позиционный ``kind`` и ``names`` без ``kind``
   (:class:`TestLegitimateFormsSurvive`).

3. **Фикстура лечит след теста, сторож смотрит на живой реестр.** Их легко
   свести к тавтологии: если бы сторож судил по снимку, он согласился бы с
   чем угодно. :class:`TestFixtureAndGuardDoNotCancelEachOther` держит их
   раздельность, а :class:`TestGuardTellsLeakFromUnassembledScene` — то, ради
   чего сторож вообще переписан: два РАЗНЫХ факта под одним симптомом
   «каталог не тот».

``_RULES_CONSUMED`` — четвёртая ось: это часть состояния реестра, и снимок,
который её не видит, тихо включает соседям предупреждения о «позднем правиле»
(:class:`TestRulesConsumedIsPartOfTheState`).

Каждый тест возвращает реестр в исходное состояние сам: сторож сессии
(``conftest.py`` рядом) сверяет каталог на закрытии, и след, оставленный
hazard-тестом, покраснел бы у него — справедливо.
"""

from __future__ import annotations

import pytest

from multiprocess_framework.modules import observability_declarations as decls
from multiprocess_framework.modules.observability_declarations import (
    KIND_LOG_SOURCE,
    KIND_METRIC,
    declare_metric,
    declared_metrics,
    declared_rules,
    forget_declarations,
    restore,
    snapshot,
)
from multiprocess_framework.modules.tests._declarations_catalogue_guard import (
    EXPECTED_FRAMEWORK_METRICS,
    catalogue_verdict,
    loaded_producers,
    warm_producers,
)

_OWNER = __name__


class TestNestedSnapshots:
    """Снимок session-scope и снимок function-scope живут одновременно."""

    def test_inner_restore_keeps_what_the_outer_snapshot_saw(self) -> None:
        """Внешний снимок → объявление → внутренний снимок → шум → внутренний возврат.

        Внутренний возврат обязан унести только шум: объявление, сделанное между
        снимками, для внутреннего снимка — законное прошлое, а не мусор.
        """
        outer = snapshot()
        try:
            declare_metric("hazard_nested_between", owner=_OWNER)
            inner = snapshot()
            declare_metric("hazard_nested_noise", owner=_OWNER)
            restore(inner)

            assert "hazard_nested_between" in declared_metrics(), (
                "внутренний возврат унёс объявление, которое внутренний снимок ВИДЕЛ"
            )
            assert "hazard_nested_noise" not in declared_metrics(), (
                "внутренний возврат не убрал шум, появившийся после внутреннего снимка"
            )
        finally:
            restore(outer)

    def test_outer_restore_after_inner_restore_undoes_everything(self) -> None:
        """LIFO: внешний возврат последним возвращает состояние до обоих снимков."""
        outer = snapshot()
        declare_metric("hazard_nested_between", owner=_OWNER)
        inner = snapshot()
        declare_metric("hazard_nested_noise", owner=_OWNER)
        restore(inner)
        restore(outer)

        catalogue = declared_metrics()
        assert "hazard_nested_between" not in catalogue
        assert "hazard_nested_noise" not in catalogue

    def test_restoring_out_of_order_reinstates_the_inner_snapshot(self) -> None:
        """НЕ-LIFO порядок возвращает состояние ВНУТРЕННЕГО снимка — это поведение, а не гарантия.

        Зафиксировано поведением намеренно: ``restore`` тотален (кладёт ровно то,
        что в снимке), поэтому «внешний, потом внутренний» не откатывает, а
        накатывает более позднее состояние. Читателю фикстур это знать нужно:
        порядок teardown у pytest LIFO, и полагаться можно ровно на это.
        """
        outer = snapshot()
        try:
            declare_metric("hazard_order_probe", owner=_OWNER)
            inner = snapshot()
            restore(outer)
            assert "hazard_order_probe" not in declared_metrics(), "предпосылка: внешний возврат откатил"

            restore(inner)
            assert "hazard_order_probe" in declared_metrics(), (
                "возврат внутреннего снимка ПОСЛЕ внешнего обязан вернуть состояние снимка "
                "целиком — иначе restore не тотален и его результат зависит от истории вызовов"
            )
        finally:
            restore(outer)
            forget_declarations(KIND_METRIC, names=["hazard_order_probe"])

    def test_the_snapshot_is_a_copy_not_a_view(self) -> None:
        """Объявление после снятия не просачивается в уже снятый снимок."""
        state = snapshot()
        try:
            size_before = len(state.declared)
            declare_metric("hazard_snapshot_is_a_copy", owner=_OWNER)
            assert len(state.declared) == size_before, (
                "снимок изменился вместе с реестром — это вид, а не снимок, и возврат "
                "по нему вернул бы то состояние, от которого защищал"
            )
        finally:
            restore(state)


class TestRestoreCannotResurrectImports:
    """Возврат к снимку не воскрешает то, что объявлял ИМПОРТ."""

    def test_warm_up_cannot_resurrect_a_wiped_declaration(self) -> None:
        """Догрев производителей НЕ маскирует утечку — ключевое свойство стража.

        Сторож добирает каталог ``ensure_framework_producers()`` перед сверкой.
        Если бы догрев умел возвращать стёртое, сторож зеленел бы на любой
        утечке. Здесь это проверено, а не объяснено: имя стирается, догрев
        зовётся повторно, имени по-прежнему нет — ``import`` после первого раза
        модуль не исполняет.
        """
        warm_producers()
        assert "fps" in declared_metrics(), "предпосылка: производители дают 'fps'"

        state = snapshot()
        try:
            forget_declarations(KIND_METRIC, names=["fps"])
            assert "fps" not in declared_metrics(), "предпосылка: имя стёрто"

            warm_producers()

            assert "fps" not in declared_metrics(), (
                "повторный догрев вернул стёртое объявление — значит сторож, который "
                "греет перед сверкой, зазеленел бы на настоящей утечке"
            )
        finally:
            restore(state)
        assert "fps" in declared_metrics(), "возврат к снимку обязан вернуть 'fps'"


class TestLegitimateFormsSurvive:
    """Отказ голому вызову не задел ни одну живую форму (16 файлов в дереве)."""

    def test_names_without_kind_survives(self) -> None:
        declare_metric("hazard_form_names_only", owner=_OWNER)
        forget_declarations(names=["hazard_form_names_only"])
        assert "hazard_form_names_only" not in declared_metrics()

    def test_positional_kind_survives(self) -> None:
        """``forget_declarations("metric", names={...})`` и ``forget_declarations(KIND_LOG_SOURCE)``.

        Обе формы встречаются в дереве: первая — в шести файлах приёмки
        наблюдений, вторая — в ``logger_module/tests/test_source_declarations.py``.
        """
        declare_metric("hazard_form_positional", owner=_OWNER)
        forget_declarations("metric", names={"hazard_form_positional"})
        assert "hazard_form_positional" not in declared_metrics()

        state = snapshot()
        try:
            forget_declarations(KIND_LOG_SOURCE)  # сплошная очистка ОДНОЙ плоскости — жива
        finally:
            restore(state)

    def test_kind_keyword_with_names_survives(self) -> None:
        declare_metric("hazard_form_kw", owner=_OWNER)
        forget_declarations(kind=KIND_METRIC, names=["hazard_form_kw"])
        assert "hazard_form_kw" not in declared_metrics()

    def test_bare_call_is_the_only_form_that_raises(self) -> None:
        with pytest.raises(TypeError) as excinfo:
            forget_declarations()
        message = str(excinfo.value)
        assert "declarations_snapshot" in message
        for address in (
            "statistics_module/tests/conftest.py",
            "process_module/tests/conftest.py",
        ):
            assert address in message, (
                f"текст отказа не называет адрес фикстуры-замены {address!r}: следующий "
                f"автор голого вызова получит запрет без подсказки. Текст: {message!r}"
            )

    def test_explicit_none_kind_with_names_is_not_a_bare_call(self) -> None:
        """``kind=None`` вместе с ``names`` — законная форма (ищет имя во всех плоскостях)."""
        declare_metric("hazard_form_explicit_none", owner=_OWNER)
        forget_declarations(kind=None, names=["hazard_form_explicit_none"])
        assert "hazard_form_explicit_none" not in declared_metrics()


class TestRulesConsumedIsPartOfTheState:
    """Отметка «правила уже читались» переживает снимок/возврат в обе стороны."""

    def test_restore_brings_back_the_unconsumed_state(self) -> None:
        outer = snapshot()
        try:
            decls._RULES_CONSUMED = False  # исходное состояние процесса: снимок ещё не брали
            state = snapshot()
            declared_rules()  # чтение правил помечает реестр «снимок взят»
            assert decls._RULES_CONSUMED is True, "предпосылка: чтение правил ставит отметку"

            restore(state)

            assert decls._RULES_CONSUMED is False, (
                "возврат не снял отметку: тест, прочитавший правила, включил бы соседям "
                "предупреждения о «правило объявлено после сборки конфига»"
            )
        finally:
            restore(outer)

    def test_restore_brings_back_the_consumed_state(self) -> None:
        """Обратная сторона: снимок, снятый ПОСЛЕ чтения, возвращает отметку взведённой."""
        outer = snapshot()
        try:
            declared_rules()
            state = snapshot()
            decls._RULES_CONSUMED = False

            restore(state)

            assert decls._RULES_CONSUMED is True, (
                "возврат не восстановил взведённую отметку — состояние реестра восстановлено наполовину"
            )
        finally:
            restore(outer)


class TestGuardTellsLeakFromUnassembledScene:
    """Сторож обязан различать «утечка» и «производителей никто не импортировал»."""

    def test_verdict_is_none_on_the_exact_literal(self) -> None:
        assert catalogue_verdict(EXPECTED_FRAMEWORK_METRICS, producers=("p",)) is None

    def test_leak_verdict_names_extra_and_missing(self) -> None:
        catalogue = tuple(sorted(set(EXPECTED_FRAMEWORK_METRICS) - {"fps"} | {"чужое_имя"}))
        verdict = catalogue_verdict(catalogue, producers=("process_module.heartbeat.telemetry",))
        assert verdict is not None
        assert "чужое_имя" in verdict, "лишнее не названо поимённо"
        assert "'fps'" in verdict, "пропавшее не названо поимённо"
        assert "УТЕЧКА" in verdict

    def test_empty_catalogue_without_producers_is_not_called_a_leak(self) -> None:
        """Ноль наблюдений — не результат наблюдения.

        Пустой каталог при незагруженных производителях — несобранная сцена.
        Сторож, называющий это утечкой, отправляет читателя искать виновника,
        которого нет, и (что хуже) так же уверенно зеленеет, когда сцена не
        собралась, а имена совпали случайно.
        """
        verdict = catalogue_verdict((), producers=())
        assert verdict is not None, "расхождение обязано быть названо в любом случае"
        assert "УТЕЧКА" not in verdict
        assert "несобранная сцена" in verdict

    def test_the_guard_sees_real_producers_in_this_session(self) -> None:
        """Контроль к тесту выше: в живой сессии производители ДЕЙСТВИТЕЛЬНО загружены.

        Без него «не утечка, а сцена» проходил бы и в мире, где догрев сломан
        навсегда, — подтверждающий ноль засчитывается только в паре с контролем,
        дающим ненулевое.
        """
        assert warm_producers(), "догрев не привёл ни одного производителя в sys.modules"
        assert set(EXPECTED_FRAMEWORK_METRICS) <= set(declared_metrics()), (
            f"каталог сессии не содержит пятёрки фреймворка: {declared_metrics()!r}"
        )


class TestFixtureAndGuardDoNotCancelEachOther:
    """Фикстура лечит след теста; сторож смотрит на ЖИВОЙ реестр, а не на снимок."""

    def test_a_restored_leak_leaves_the_catalogue_clean(self) -> None:
        """След теста, накрытого фикстурой, до сторожа не доезжает — это и есть лечение.

        Сверяется ДЕЛЬТА каталога, а не совпадение с литералом пятёрки: этот файл
        собирается и корневым гейтом, где в одной сессии с ним живут прикладные
        объявления (плагины, прототип), и «каталог равен пятёрке» там ложно
        краснеет по чужой причине. Поймано прогоном корневого гейта, а не
        рассуждением: первая редакция теста была именно такой и упала.
        """
        before = declared_metrics()
        state = snapshot()
        declare_metric("hazard_leak_restored", owner=_OWNER)
        restore(state)  # то же, что делает declarations_snapshot в teardown

        assert declared_metrics() == before, "возврат оставил след теста в живом каталоге"

    def test_a_leak_outside_any_snapshot_still_reaches_the_guard(self) -> None:
        """А след теста БЕЗ фикстуры сторож ловит и называет — фикстура его не глушит."""
        try:
            declare_metric("hazard_leak_unrestored", owner=_OWNER)
            verdict = catalogue_verdict(declared_metrics(), producers=loaded_producers())
            assert verdict is not None, (
                "сторож не заметил объявления, оставленного в живом реестре: значит он "
                "судит не по реестру, и фикстура-соседка делает его тавтологией"
            )
            assert "hazard_leak_unrestored" in verdict
        finally:
            forget_declarations(KIND_METRIC, names=["hazard_leak_unrestored"])
