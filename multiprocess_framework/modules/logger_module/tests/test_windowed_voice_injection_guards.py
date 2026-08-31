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

Ниже в этом же файле — сторожа находок РЕВЬЮ той же задачи (major 3 и minor 6):
насыщенная должниками карта съедала только что созданный ключ, а карта серий
не имела потолка вовсе. Оба свойства механизм заявлял и не охранял ничем.

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
    MAX_TRACKED_KEYS,
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


class TestASaturatedMapDoesNotEatTheKeyItJustCreated:
    """Ревью Task 1.4: карта из одних должников выбрасывала СВЕЖИЙ ключ.

    Воспроизведение (дословно из вердикта ревью):

        после заполнения: tracked = 512, windowed_suppressed = 512
        пять подряд take('hot', 100.0) -> [(True,0)] * 5
        tracked = 512, 'hot' в карте: False, windowed_keys_evicted = 5

    То есть механизм отключался ровно в том состоянии, ради которого заведён:
    пять голосов из пяти при окне 100 с. Причина точечная — жертвы сортируются
    «бездолжники первыми», а только что вставленный ключ бездолжник по
    построению и потому единственный кандидат своей группы.

    Сегодня латентно (у роутера и реестра очередей кардинальность ключей —
    единицы), но Task 1.3a приносит сюда ключ ``f"{тип исключения}|{context}"``
    с неограниченным алфавитом.
    """

    @pytest.fixture(autouse=True)
    def _clean_counters(self):
        reset_voice_counters()
        yield
        reset_voice_counters()

    @staticmethod
    def _saturate_with_debtors(voices: WindowedVoices) -> None:
        """Заполнить карту до потолка ключами, у которых есть НЕНАЗВАННЫЙ счёт.

        Второй ``take`` по каждому ключу и делает его должником: первый голосит,
        второй подавляется и растит ``entry[1]``. Без должников тест был бы
        вакуумен — свежий ключ конкурировал бы с такими же бездолжниками и
        уцелел бы по возрасту даже у сломанной версии.
        """
        for i in range(MAX_TRACKED_KEYS):
            key = f"debtor-{i}"
            voices.take(key, 100.0)
            voices.take(key, 100.0)

    def test_a_fresh_key_voices_once_and_stays_in_the_map(self) -> None:
        voices = WindowedVoices()
        self._saturate_with_debtors(voices)
        assert voices.tracked_keys() == MAX_TRACKED_KEYS, "карта обязана стоять на потолке до начала опыта"

        decisions = [voices.take("hot", 100.0) for _ in range(5)]

        # Литералы, а не выражения от механизма: первый голос, дальше молчание с
        # растущим счётом подавленных. Сломанная версия давала [(True, 0)] * 5.
        assert decisions == [(True, 0), (False, 1), (False, 2), (False, 3), (False, 4)], (
            f"свежий ключ не пережил собственную вставку: {decisions}"
        )

    def test_the_fresh_key_survives_while_a_debtor_is_evicted_instead(self) -> None:
        """Вторая половина: жертва всё-таки нашлась, и это НЕ свежий ключ.

        Без неё предыдущий тест проходил бы и у версии, которая просто перестала
        подметать: потолок карты — тоже обещание, и разменивать одно на другое
        молча нельзя.
        """
        voices = WindowedVoices()
        self._saturate_with_debtors(voices)

        voices.take("hot", 100.0)

        assert voices.tracked_keys() == MAX_TRACKED_KEYS, "потолок карты обязан остаться взятым"
        assert voices.take("hot", 100.0) == (False, 1), "'hot' обязан остаться в карте, а не родиться заново"
        assert voice_counters()["windowed_keys_evicted"] == 1, (
            f"ровно один ключ обязан быть выброшен, а не ноль и не пять: {voice_counters()}"
        )


class TestTheRepeatsMapIsBoundedToo:
    """Ревью Task 1.4, minor 6: потолка у карты СЕРИЙ не было вовсе.

    Замер ревью: 50 000 ``note_repeat`` разными ключами → ``len(_repeats) ==
    50000`` при ``tracked_keys() == 0``. Шапка модуля при этом утверждала, что
    «карта ключей ограничена», — верно для ``_state`` и неверно для ``_repeats``,
    которой ``note_repeat`` живёт единолично.
    """

    def test_a_flood_of_one_off_keys_does_not_grow_the_map_without_bound(self) -> None:
        voices = WindowedVoices()

        for i in range(MAX_TRACKED_KEYS * 4):
            voices.note_repeat(f"one-off-{i}")

        assert len(voices._repeats) <= MAX_TRACKED_KEYS, (  # noqa: SLF001 — предмет проверки
            f"карта серий выросла до {len(voices._repeats)} при потолке {MAX_TRACKED_KEYS}"  # noqa: SLF001
        )

    def test_the_long_series_is_the_last_thing_to_be_dropped(self) -> None:
        """Пара-контроль: потолок не имеет права стирать то, ради чего ось заведена.

        Без этой половины «карта ограничена» проходило бы и у версии, которая
        просто чистит карту целиком, — то есть у версии, где серия обнуляется
        шумом соседей и порог не берётся никогда.
        """
        voices = WindowedVoices()
        for _ in range(50):
            length = voices.note_repeat("the-symptom")
        assert length == 50, f"серия обязана считаться подряд: {length}"

        for i in range(MAX_TRACKED_KEYS * 4):
            voices.note_repeat(f"one-off-{i}")

        assert voices.repeats("the-symptom") == 50, (
            f"длинная серия потеряна под наплывом одноразовых ключей: {voices.repeats('the-symptom')}"
        )
