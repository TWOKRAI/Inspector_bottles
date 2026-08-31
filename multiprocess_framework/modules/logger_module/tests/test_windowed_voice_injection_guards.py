"""Сторожа, поставленные по матрице инъекций против Task 1.4.

Матрица (6 заплаток, дерево ``D:/wti14`` на ``338b48c6``) нашла два свойства,
которые механизм заявляет, а не охраняет ничто:

* **I6 — лок.** ``self._lock`` снимался целиком (замена на ``nullcontext``), и
  все 57 тестов оставались зелёными. Автор предупредил об этом сам: его
  ``test_concurrent_calls_on_one_key_lose_no_suppression`` гоняет шторм потоков,
  но под GIL 3.12 потоки могут просто не вклиниться в критическую секцию —
  «ничего не потерялось» одинаково верно и с локом, и без него.
* **I4 — счётчик в readback.** Снятие ``_bump("windowed_suppressed", 1)``
  роняло ровно один тест, и НЕ тот, что отвечает за readback: приёмочный
  ``test_windowed_suppressed_key_is_in_the_publish_whitelist`` проверяет
  ЧЛЕНСТВО ключа в белом списке публикации, а не то, что величина растёт.
  Классический «контрол существует и мёртв».

Почему сторож лока смотрит на ЗАНЯТОСТЬ, а не на потерю счёта: потеря
инкремента под GIL недетерминирована, и тест на неё был бы флейком в одну
сторону и вакуумом в другую. Взаимное исключение — это и есть то, что лок
обещает, и оно наблюдаемо прямо: сколько исполнителей одновременно находится
внутри секции. Обещание — «не больше одного».
"""

from __future__ import annotations

import threading
import time

import pytest

from multiprocess_framework.modules.logger_module.core.windowed_voice import (
    WindowedVoices,
    reset_voice_counters,
    voice_counters,
)

#: Насколько расширяем критическую секцию, чтобы потоки успели встретиться.
#: На Windows разрешение ``time.monotonic`` — 15.6 мс, но здесь измеряется не
#: время, а факт одновременности, поэтому хватает и малой задержки.
_WIDEN_SEC = 0.002

#: Дедлайн на ``join``. Тест, который висит, хуже отсутствующего: он прячет
#: регрессию за таймаутом прогона, а не показывает её красным.
_JOIN_DEADLINE_SEC = 20.0


class _Occupancy:
    """Счётчик одновременных исполнителей внутри критической секции."""

    def __init__(self) -> None:
        self._inside = 0
        self.peak = 0
        self._guard = threading.Lock()

    def enter(self) -> None:
        with self._guard:
            self._inside += 1
            self.peak = max(self.peak, self._inside)

    def leave(self) -> None:
        with self._guard:
            self._inside -= 1


class _WatchedState(dict):
    """Карта ключей, которая сообщает о входе в секцию и расширяет её.

    ``take()`` читает карту через ``.get(key)`` под ``self._lock`` — значит
    инструментированный ``get`` исполняется РОВНО внутри критической секции.
    """

    def __init__(self, occupancy: _Occupancy) -> None:
        super().__init__()
        self._occupancy = occupancy

    def get(self, key, default=None):  # type: ignore[override]
        self._occupancy.enter()
        try:
            time.sleep(_WIDEN_SEC)
            return dict.get(self, key, default)
        finally:
            self._occupancy.leave()


class TestLockActuallyExcludes:
    """Лок держит секцию — проверяется занятостью, а не отсутствием потери."""

    def test_no_two_callers_are_inside_the_critical_section_at_once(self) -> None:
        occupancy = _Occupancy()
        voices = WindowedVoices()
        voices._state = _WatchedState(occupancy)  # noqa: SLF001 — инструментирование секции

        errors: list[BaseException] = []

        def hammer() -> None:
            try:
                for _ in range(15):
                    voices.take("one-key", 60.0)
            except BaseException as exc:  # noqa: BLE001 — падение потока обязано доехать до теста
                errors.append(exc)

        threads = [threading.Thread(target=hammer, daemon=True) for _ in range(8)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(_JOIN_DEADLINE_SEC)

        alive = [t.name for t in threads if t.is_alive()]
        assert not alive, f"потоки не завершились за {_JOIN_DEADLINE_SEC} с: {alive}"
        assert not errors, f"исключения в потоках: {errors}"

        # Литерал, а не выражение от кода: «не больше одного» — это и есть
        # обещание лока. Под снятым локом восемь потоков с расширенной секцией
        # встречаются внутри неё практически наверняка.
        assert occupancy.peak == 1, (
            f"внутри критической секции одновременно оказывалось до {occupancy.peak} исполнителей; лок не исключает"
        )


class TestSuppressionReachesTheReadbackNumber:
    """Подавление растит процессный счётчик, а не только числится в белом списке."""

    @pytest.fixture(autouse=True)
    def _clean_counters(self):
        reset_voice_counters()
        yield
        reset_voice_counters()

    def test_suppressed_calls_grow_the_published_counter(self) -> None:
        voices = WindowedVoices()

        voiced_first, _ = voices.take("k", 60.0)
        assert voiced_first is True, "первый вызов с новым ключом обязан голосить"

        for _ in range(7):
            voices.take("k", 60.0)

        # 7 — литерал: столько вызовов было подавлено. Вывести это число из
        # самого механизма значило бы согласиться с любым его ответом, включая 0.
        assert voice_counters()["windowed_suppressed"] == 7, (
            f"опубликованный счётчик показывает {voice_counters()['windowed_suppressed']}, а подавлено было 7"
        )

    def test_a_voice_that_was_not_suppressed_does_not_grow_the_counter(self) -> None:
        """Контроль к предыдущему: без подавления счётчик обязан остаться нулём.

        Без этой половины тест выше проходил бы и у счётчика, который растёт
        на КАЖДЫЙ вызов, — то есть перестал бы означать «подавлено».
        """
        voices = WindowedVoices()

        voices.take("a", 60.0)
        voices.take("b", 60.0)
        voices.take("c", 60.0)

        assert voice_counters()["windowed_suppressed"] == 0, (
            "три разных ключа голосят каждый, подавлений нет — счётчик обязан остаться нулём"
        )
