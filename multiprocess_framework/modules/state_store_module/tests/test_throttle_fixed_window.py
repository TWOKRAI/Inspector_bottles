# -*- coding: utf-8 -*-
"""Ф8.2 — троттл считает окна, а не разности: предохранитель перестал резать своих.

`ThrottleMiddleware` сравнивал ``(now - last) < interval``, отсчитывая от МОМЕНТА
предыдущего пропуска. Такая семантика измеряет РАЗНОСТЬ двух показаний часов и потому
зависит от их разрешения. На Windows ``time.monotonic`` — это ``GetTickCount64()`` с
разрешением 15.625 мс (``time.get_clock_info('monotonic').resolution``), поэтому
промежуток, реально равный 50 мс, читается как 46.875 мс — «меньше интервала» — и
запись отбрасывается. Публикатор с периодом, равным интервалу правила, терял половину.

Резидуал #6 плана `telemetry-publish-control` объяснял это «фазовым рассогласованием
двух monotonic-часов». Объяснение неверное: часы здесь ОДНИ (``self._now``), а причина —
разрешение. Записано отдельно, потому что уверенное неверное объяснение переживает баг.

Фиксированная сетка (``floor(now / interval)``) отображает АБСОЛЮТНОЕ время на окна и
разностей не меряет — от разрешения часов она не зависит вовсе.

Часы во всех тестах инжектированы явным списком показаний: сон и реальное время сделали
бы проверку флаки, а числа ниже — литералы, а не вычисленные из проверяемого кода.
"""

from __future__ import annotations

from typing import List

from multiprocess_framework.modules.state_store_module.middleware.throttle import (
    ThrottleMiddleware,
)

#: Разрешение ``GetTickCount64()`` — 1/64 секунды.
_TICK = 0.015625
#: Интервал правила. Выбран НЕ равным кратному тика: именно так выглядит живой
#: `_SAFETY_INTERVAL_SEC = 0.05`, на котором дефект и живёт.
_INTERVAL = 0.05
#: Приходы ровно с тем шагом, который даёт ``sleep(0.05)`` на квантованных часах:
#: три тика = 46.875 мс, то есть МЕНЬШЕ интервала при чтении разностью.
_STAMPS: List[float] = [k * 3 * _TICK for k in range(20)]

_PATH = "processes.cam.state.fps"
_RULES = {"processes.**.state.fps": _INTERVAL}


def _mw(stamps: List[float], rules=None) -> ThrottleMiddleware:
    """Троттл на списке показаний часов: каждый вызов ``self._now()`` берёт следующее."""
    it = iter(stamps)
    return ThrottleMiddleware(dict(rules or _RULES), clock=lambda: next(it))


def _passes_via_set(mw: ThrottleMiddleware, n: int) -> int:
    return sum(1 for _ in range(n) if mw.before_set(_PATH, 1.0, "heartbeat", {})[0])


class TestQuantizedClockNoLongerHalvesTheRate:
    """Главное свойство: предохранитель прозрачен для трафика НА своём пределе."""

    def test_publisher_at_the_rule_interval_is_not_halved(self) -> None:
        """18 из 20 приходов доезжают. Два потерянных попали в уже израсходованное окно.

        Литерал 18 — не «сколько получилось», а следствие раскладки: окно метрики
        ``floor(k * 0.046875 / 0.05)`` повторяется на k=1 и k=17, остальные растут.
        """
        assert _passes_via_set(_mw(_STAMPS), len(_STAMPS)) == 18

    def test_same_arrivals_under_the_old_sliding_rule_lose_half(self) -> None:
        """Вторая половина пары: НА ТЕХ ЖЕ приходах прежняя семантика даёт 10 из 20.

        Без этого плеча число 18 не о чем не говорит — «много» и «столько же, сколько
        было» на зелёном тесте выглядят одинаково. Здесь прежнее правило воспроизведено
        локально, а не позаимствовано из кода под проверкой.
        """
        mw = _mw(_STAMPS)
        mw._blocked_by_window = (  # type: ignore[method-assign]
            lambda last, now, interval: last is not None and (now - last) < interval
        )

        assert _passes_via_set(mw, len(_STAMPS)) == 10


class TestWindowBoundary:
    def test_two_arrivals_straddling_a_boundary_both_pass(self) -> None:
        """Принятая цена сетки, названная вслух: пара через границу проходит целиком.

        0.049 и 0.051 при интервале 0.05 лежат в РАЗНЫХ окнах, хотя разделены 2 мс.
        Прежнее правило вторую придержало бы. Тест пинует смену контракта: «не более
        одной записи на окно» вместо «минимальный интервал между двумя пропущенными».
        """
        mw = _mw([0.049, 0.051])

        assert mw.before_set(_PATH, 1.0, "heartbeat", {})[0] is True
        assert mw.before_set(_PATH, 2.0, "heartbeat", {})[0] is True

    def test_two_arrivals_inside_one_window_yield_one_pass(self) -> None:
        """Обратная сторона: внутри ОДНОГО окна проходит ровно одна запись."""
        mw = _mw([0.051, 0.099])

        assert mw.before_set(_PATH, 1.0, "heartbeat", {})[0] is True
        assert mw.before_set(_PATH, 2.0, "heartbeat", {})[0] is False


class TestSafetyNetStillHolds:
    def test_runaway_publisher_is_capped_at_one_record_per_window(self) -> None:
        """Роль предохранителя не потеряна: шторм 10× режется до одной записи на окно.

        50 приходов с шагом ``interval / 10`` укладываются в 5 окон → 5 пропусков.
        """
        stamps = [k * (_INTERVAL / 10) for k in range(50)]

        assert _passes_via_set(_mw(stamps), len(stamps)) == 5

    def test_interval_zero_still_blocks_everything_after_first_check(self) -> None:
        """Полная блокировка живёт своей веткой ДО оконной проверки и не задета."""
        mw = _mw([0.0, 10.0, 20.0], rules={"processes.**.state.fps": 0})

        assert [mw.before_set(_PATH, 1.0, "heartbeat", {})[0] for _ in range(3)] == [
            False,
            False,
            False,
        ]

    def test_unruled_path_is_never_throttled(self) -> None:
        """Путь без правила проходит всегда — сетка на него не распространяется."""
        mw = _mw([0.0, 0.001, 0.002])

        assert [mw.before_set("other.path", 1.0, "s", {})[0] for _ in range(3)] == [
            True,
            True,
            True,
        ]


class TestBothPathsShareOneRule:
    """``before_set`` и ``before_merge`` обязаны судить одним предикатом.

    Раньше сравнение стояло в ДВУХ местах отдельными копиями — классическая точка
    расхождения (правку внесли бы в одно). Теперь предикат один, и разойтись им
    структурно нечем; тест сторожит, что merge-путь действительно ходит через него,
    а не завёл себе третью копию.
    """

    def test_merge_path_obeys_the_same_window_rule(self) -> None:
        stamps = [0.049, 0.051, 0.099]
        mw = _mw(stamps)

        first = mw.before_merge("processes.cam.state", {"fps": 1.0}, "heartbeat", {})
        second = mw.before_merge("processes.cam.state", {"fps": 2.0}, "heartbeat", {})
        third = mw.before_merge("processes.cam.state", {"fps": 3.0}, "heartbeat", {})

        # 0.049 → окно 0; 0.051 → окно 1 — пара через границу проходит, ровно как в set.
        assert first == (True, {"fps": 1.0})
        assert second == (True, {"fps": 2.0})
        # 0.099 → окно 1 повторно. Все покрытые листья придержаны, поэтому merge
        # ОТКЛОНЯЕТСЯ целиком и вторым элементом едут исходные данные, а не пустое
        # поддерево (``before_merge``: ``if not kept: return False, data``). Судить
        # здесь надо по флагу — payload при отказе не является результатом.
        assert third[0] is False
        # Придержанное легло в pending, а тайминг остался на пропуске окна 1.
        assert mw._last_pass[_PATH] == 0.051
        assert mw._pending[_PATH] == (3.0, "heartbeat")


class TestTimestampHygiene:
    """``_last_pass`` обязан остаться ТАЙМСТАМПОМ, а не стать индексом окна.

    Поле читают ДВА механизма: оконный предикат (сравнивает с ``now``) и уборка
    ``_maybe_lazy_prune`` (отбраковывает по возрасту ``now - ts > threshold``).
    Соблазн «хранить сразу индекс, раз предикат его и считает» ломает второй.

    Существующий страж роста (``test_lazy_prune_bounds_growth_under_unique_path_stream``
    в ``test_throttle.py``) этого НЕ ловит, и причина поучительная: он берёт
    ``interval = 1.0`` и целые секунды на часах, а при таких числах
    ``floor(now / 1.0) == now`` — две реализации совпадают поэлементно, и подмена
    невидима. Проверено запуском: под инъекцией «класть индекс» все 18 тестов
    уборки и flush остаются зелёными. Тесты ниже берут интервал, на котором индекс
    и таймстамп расходятся.
    """

    def test_last_pass_stores_the_clock_reading(self) -> None:
        mw = _mw([12.345])

        mw.before_set(_PATH, 1.0, "heartbeat", {})

        assert mw._last_pass[_PATH] == 12.345

    def test_lazy_prune_still_bounds_growth_when_index_differs_from_timestamp(self) -> None:
        """Уборка обязана срабатывать и при интервале, где индекс ≠ таймстамп.

        Поток уникальных путей длиннее порога lazy-prune, часы идут шагом ``interval``.
        С таймстампом переживают только записи моложе ``interval × 10`` — словарь
        остаётся много меньше потока. С индексом окна разность ``now - ts`` вырождается
        (при шаге, равном интервалу, индекс растёт быстрее секунд), протухших не
        находится вовсе, и словарь распухает до полного потока — то есть уборки нет.
        """
        n_paths = 1200
        stamps = [i * _INTERVAL for i in range(n_paths)]
        mw = _mw(stamps, rules={"cameras.**.state.fps": _INTERVAL})

        for i in range(n_paths):
            mw.before_set(f"cameras.{i}.state.fps", i, "heartbeat", {})

        assert len(mw._last_pass) < n_paths, "уборка не сработала — словарь растёт без предела"
        assert len(mw._last_pass) <= 1000
