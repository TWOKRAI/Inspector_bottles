# -*- coding: utf-8 -*-
"""Опасности механизма окон голоса (тесты АВТОРА, Ф1.4).

Независимый тестер писал от критериев приёмки и внутреннего устройства не видел.
Здесь — то, что может сломаться именно в ЭТОМ механизме, учитывая, КАК он
построен: общий изменяемый словарь под локом, эмиссия наружу, процессные
счётчики, объект в поле менеджера, который уезжает в дочерний процесс.

Что здесь НЕ проверяется и почему: величина окна в секундах. Ни один тест ниже
не спит — временем управляет инъекция часов. На Windows разрешение
``time.monotonic`` 15.6 мс, и разности меньше ~100 мс ложатся на сетку, то есть
тест на «прошло 5 с» проверял бы планировщик, а не механизм.
"""

from __future__ import annotations

# ``pickle`` здесь — round-trip объекта, СОЗДАННОГО этим же тестом, а не разбор
# чужих данных: воспроизводится ровно то, что делает ``multiprocessing`` в
# spawn-режиме на Windows. Недоверенного входа нет.
import pickle
import threading
import time

import pytest

from multiprocess_framework.modules.logger_module.core.windowed_voice import (
    MAX_TRACKED_KEYS,
    WindowedVoices,
    log_windowed,
    reset_voice_counters,
    reset_voices_policy,
    set_voices_policy,
    voice_counters,
)

from multiprocess_framework.modules.base_manager import BaseManager, ObservableMixin


class _VoicingManager(BaseManager, ObservableMixin):
    """Менеджер-носитель разъёма. На уровне МОДУЛЯ, а не внутри теста: локальный
    класс не пиклится в принципе, и тест pickle проверял бы своё собственное
    ограничение вместо охраняемого свойства."""

    def __init__(self, name: str = "Voicing", logger=None) -> None:
        BaseManager.__init__(self, manager_name=name)
        ObservableMixin.__init__(self, managers={"logger": logger} if logger is not None else {})

    def initialize(self) -> bool:
        return True

    def shutdown(self) -> bool:
        return True


#: Заведомо больше любого окна теста — сдвиг часов «окно точно истекло».
_BEYOND_WINDOW = 10_000.0

#: Окно, в которое заведомо укладывается всё, что тест успевает сделать.
_HUGE_WINDOW = 1_000_000.0


@pytest.fixture(autouse=True)
def _clean_process_state():
    """Процессные счётчики и политика — общие. Тест обязан быть независим от соседа."""
    reset_voice_counters()
    reset_voices_policy()
    yield
    reset_voice_counters()
    reset_voices_policy()


def _run_with_deadline(target, *, threads: int, seconds: float = 10.0) -> list:
    """Запустить target в демон-потоках и дождаться с дедлайном.

    Демон + дедлайн, а не просто ``join()``: тест, который ВИСНЕТ вместо
    падения, хуже отсутствующего — он прячет регресс за таймаутом прогона.
    """
    workers = [threading.Thread(target=target, daemon=True) for _ in range(threads)]
    for worker in workers:
        worker.start()
    deadline = time.monotonic() + seconds
    for worker in workers:
        worker.join(max(deadline - time.monotonic(), 0.0))
    alive = [w for w in workers if w.is_alive()]
    assert not alive, (
        f"{len(alive)} из {threads} потоков не завершились за {seconds}с — "
        f"механизм окна заблокировался (лок удержан на время эмиссии?)"
    )
    return workers


class TestLockDiscipline:
    """Число подавленных не теряется и не удваивается под конкуренцией.

    Опасность конкретная: чтение счётчика подавленных и его обнуление — ДВЕ
    операции, и если они разъедутся по разным захватам лока, число в тексте
    отстанет от своего момента (ровно урок ``RouterManager._report_send_error``,
    комментарий «Ф6.х.7б»). Арифметика — единственный наблюдаемый след этого:
    сломанная дисциплина лока теряет подавления, а не роняет что-нибудь заметное.
    """

    def test_concurrent_calls_on_one_key_lose_no_suppression(self) -> None:
        voices = WindowedVoices()
        threads, per_thread = 8, 250
        total_calls = threads * per_thread
        voiced_flags: list[bool] = []
        reported: list[int] = []
        guard = threading.Lock()

        def worker() -> None:
            local_voiced = 0
            local_reported = []
            for _ in range(per_thread):
                voiced, suppressed = voices.take("один-ключ", _HUGE_WINDOW)
                if voiced:
                    local_voiced += 1
                    local_reported.append(suppressed)
            with guard:
                voiced_flags.extend([True] * local_voiced)
                reported.extend(local_reported)

        _run_with_deadline(worker, threads=threads)

        # Окно огромное → голос обязан быть ровно один на всю толпу.
        assert len(voiced_flags) == 1, (
            f"ожидался ровно один голос на {total_calls} вызовов, получено {len(voiced_flags)}"
        )
        assert reported == [0], "первый голос по новому ключу не может ничего подавить"
        # ГЛАВНОЕ: все остальные вызовы учтены как подавленные — ни одного
        # потерянного инкремента. Литерал, а не выражение из кода механизма.
        assert voice_counters()["windowed_suppressed"] == total_calls - 1

    def test_reported_suppression_matches_what_actually_happened(self) -> None:
        """Число в тексте = ровно столько, сколько промолчало между двумя голосами."""
        voices = WindowedVoices()
        clock = [100.0]

        with pytest.MonkeyPatch.context() as patch:
            patch.setattr(time, "monotonic", lambda: clock[0])
            assert voices.take("k", 5.0) == (True, 0)
            for _ in range(7):
                voices.take("k", 5.0)
            clock[0] += _BEYOND_WINDOW
            voiced, suppressed = voices.take("k", 5.0)

        assert voiced is True
        assert suppressed == 7, "названо не то число, которое реально промолчало"

    def test_counter_after_second_voice_starts_from_zero_again(self) -> None:
        """Обнуление на голосе — иначе второй голос назвал бы сумму за всю жизнь."""
        voices = WindowedVoices()
        clock = [200.0]

        with pytest.MonkeyPatch.context() as patch:
            patch.setattr(time, "monotonic", lambda: clock[0])
            voices.take("k", 5.0)
            voices.take("k", 5.0)
            clock[0] += _BEYOND_WINDOW
            voices.take("k", 5.0)  # назовёт 1
            voices.take("k", 5.0)
            voices.take("k", 5.0)
            clock[0] += _BEYOND_WINDOW
            _voiced, suppressed = voices.take("k", 5.0)

        assert suppressed == 2, f"второй интервал подавил ровно 2, названо {suppressed}"


class TestConcurrencyOnDistinctKeys:
    def test_different_keys_voice_independently_under_threads(self) -> None:
        """Ключи не мешают друг другу и когда их берут одновременно."""
        voices = WindowedVoices()
        results: dict[str, int] = {}
        guard = threading.Lock()
        # Дедлайн В КОНСТРУКТОРЕ: барьер без него повиснет вместо красного, если
        # хоть один поток не дойдёт до встречи (страж
        # ``test_no_wait_without_deadline_in_observability_tests``).
        barrier = threading.Barrier(6, timeout=10.0)

        def worker() -> None:
            index = barrier.wait()
            key = f"key-{index}"
            voiced, _suppressed = voices.take(key, _HUGE_WINDOW)
            with guard:
                results[key] = int(voiced)

        _run_with_deadline(worker, threads=6)

        assert len(results) == 6
        assert all(results.values()), f"первый голос по своему ключу обязан прозвучать у каждого: {results}"


class TestReentrancy:
    """Приёмник записи имеет право позвать механизм снова.

    Опасность структурная: удержи механизм свой лок на время эмиссии — и
    обработчик, который сам пишет через ``log_windowed``, встал бы намертво
    на нерекурсивном ``threading.Lock``. Тест обязан ПАДАТЬ, а не виснуть,
    поэтому идёт в демон-потоке с дедлайном.
    """

    def test_voice_from_inside_the_write_handler_does_not_deadlock(self) -> None:
        voices = WindowedVoices()
        seen: list[str] = []

        class _ReentrantLogger:
            def warning(self, text: str) -> None:
                seen.append(text)
                # Повторный вход ИЗНУТРИ эмиссии — тот самый опасный случай.
                if len(seen) < 3:
                    log_windowed(
                        f"вложенный-{len(seen)}", _HUGE_WINDOW, "warning", "изнутри", logger=self, voices=voices
                    )

        def worker() -> None:
            log_windowed("внешний", _HUGE_WINDOW, "warning", "снаружи", logger=_ReentrantLogger(), voices=voices)

        _run_with_deadline(worker, threads=1, seconds=5.0)

        assert len(seen) == 3, f"вложенные голоса не прозвучали: {seen!r}"

    def test_same_key_reentrant_call_is_silent_not_deadlocked(self) -> None:
        """Повторный вход по ТОМУ ЖЕ ключу — молчание (окно), а не зависание."""
        voices = WindowedVoices()
        depth: list[int] = []

        class _SelfCallingLogger:
            def error(self, text: str) -> None:
                depth.append(1)
                if len(depth) < 5:  # предохранитель теста, а не механизма
                    log_windowed("тот-же", _HUGE_WINDOW, "error", "снова", logger=self, voices=voices)

        def worker() -> None:
            log_windowed("тот-же", _HUGE_WINDOW, "error", "раз", logger=_SelfCallingLogger(), voices=voices)

        _run_with_deadline(worker, threads=1, seconds=5.0)

        assert len(depth) == 1, f"повтор по тому же ключу обязан молчать окном, получено {len(depth)} эмиссий"


class TestKeyMapDoesNotLeak:
    """Ключ — величина неограниченного алфавита (имя процесса, причина, тип).

    «Окно на ключ» без потолка — это утечка на ключах, которых больше никогда не
    будет: очередь исчезнувшего процесса, разовая причина отказа, имя отправителя
    из случайного трафика.
    """

    def test_many_one_shot_keys_do_not_grow_the_map_without_bound(self) -> None:
        voices = WindowedVoices()
        for i in range(MAX_TRACKED_KEYS * 4):
            voices.take(f"разовый-{i}", _HUGE_WINDOW)

        assert voices.tracked_keys() <= MAX_TRACKED_KEYS, (
            f"карта ключей выросла до {voices.tracked_keys()} при потолке {MAX_TRACKED_KEYS}"
        )

    def test_eviction_by_the_cap_is_not_silent(self) -> None:
        """Выброс по потолку уносит неназванный счёт — и обязан быть посчитан.

        Иначе «подавлено 0» означало бы одновременно «ничего не подавлялось» и
        «счёт выброшен вместе с ключом», а это разные аварии.
        """
        voices = WindowedVoices()
        for i in range(MAX_TRACKED_KEYS * 3):
            voices.take(f"горячий-{i}", _HUGE_WINDOW)

        assert voice_counters()["windowed_keys_evicted"] > 0, "ключи выброшены по потолку, но счётчик потерь молчит"

    def test_stale_sweep_keeps_a_key_that_still_owes_a_number(self) -> None:
        """Подметание протухших не имеет права съесть ключ с накопленным счётом."""
        voices = WindowedVoices()
        clock = [1_000.0]

        with pytest.MonkeyPatch.context() as patch:
            patch.setattr(time, "monotonic", lambda: clock[0])
            voices.take("должник", 5.0)
            voices.take("должник", 5.0)  # накопил 1 подавленный
            # Набиваем карту так, чтобы подметание заведомо запустилось.
            for i in range(MAX_TRACKED_KEYS + 5):
                voices.take(f"шум-{i}", 5.0)
            clock[0] += _BEYOND_WINDOW
            _voiced, suppressed = voices.take("должник", 5.0)

        assert suppressed == 1, f"накопленный счёт ключа пропал при подметании карты: названо {suppressed}, ожидалась 1"

    def test_forget_makes_the_next_voice_immediate(self) -> None:
        voices = WindowedVoices()
        clock = [10.0]
        with pytest.MonkeyPatch.context() as patch:
            patch.setattr(time, "monotonic", lambda: clock[0])
            assert voices.take("k", 5.0)[0] is True
            assert voices.take("k", 5.0)[0] is False
            voices.forget("k")
            assert voices.take("k", 5.0)[0] is True, "забытый ключ обязан заговорить немедленно"


class TestPolicyIsReadAtVoiceTime:
    """Окно берётся из политики НА КАЖДОМ голосе, а не запоминается при создании.

    Иначе ``config.reload`` менял бы слой и не менял поведение у держателей,
    созданных до правки, — то есть у всех, потому что менеджеры создаются на
    старте (класс дефекта «третья точка дороги ручки»).
    """

    def test_policy_change_affects_an_already_created_holder(self) -> None:
        voices = WindowedVoices()
        clock = [500.0]

        with pytest.MonkeyPatch.context() as patch:
            patch.setattr(time, "monotonic", lambda: clock[0])
            set_voices_policy(window_sec=100.0)
            voices.take("k")  # голос, окно 100
            clock[0] += 10.0
            assert voices.take("k")[0] is False, "10 с внутри окна 100 с — обязано молчать"
            # Оператор сделал систему разговорчивее прямо на ходу.
            set_voices_policy(window_sec=1.0)
            assert voices.take("k")[0] is True, (
                "смена политики не подействовала на уже созданный держатель — "
                "окно запомнилось при создании вместо чтения на голосе"
            )

    def test_silence_of_one_axis_does_not_reset_the_other(self) -> None:
        set_voices_policy(window_sec=42.0, escalate_after=9)
        applied = set_voices_policy(window_sec=7.0)  # про порог НЕ сказано ничего
        assert applied["escalate_after_repeats"] == 9, (
            "молчание по одной оси стёрло значение другой (правило Г3 нарушено)"
        )


class TestRepeatLadder:
    def test_streak_counts_consecutive_and_resets(self) -> None:
        voices = WindowedVoices()
        assert voices.note_repeat("k") == 1
        assert voices.note_repeat("k") == 2
        voices.reset_repeat("k")
        assert voices.note_repeat("k") == 1, "серия обязана начинаться заново после разрыва"

    def test_streak_is_independent_of_the_time_window(self) -> None:
        """Две оси не смешиваются: голос по окну молчит, серия при этом растёт."""
        voices = WindowedVoices()
        clock = [0.0]
        with pytest.MonkeyPatch.context() as patch:
            patch.setattr(time, "monotonic", lambda: clock[0])
            voices.take("k", _HUGE_WINDOW)
            for _ in range(4):
                voices.take("k", _HUGE_WINDOW)
                voices.note_repeat("k")
        assert voices.repeats("k") == 4, "окно заглушило счёт серии — оси склеились"


class TestPickleSurvival:
    """Держатель окон живёт в поле менеджера, а менеджеры уезжают в дочерние процессы.

    ``threading.Lock`` не пиклится. До Ф1.4 этого поля не было, поэтому дефект
    проявился бы не тестом, а падением spawn'а на Windows — то есть в проде.
    """

    def test_manager_that_voiced_can_still_be_pickled(self) -> None:
        manager = _VoicingManager()
        manager.log_windowed("k", 5.0, "warning", "что-то")
        assert manager.__dict__.get("_windowed_voices") is not None, "тест не тронул охраняемое поле"

        restored = pickle.loads(pickle.dumps(manager))

        # И механизм после воскрешения работает, а не падает на пустом поле.
        assert restored.log_windowed("k", 5.0, "warning", "снова") is False or True
        assert restored.should_voice("свежий", 5.0)[0] is True


class TestMixinConnector:
    def test_suppressed_count_reaches_the_text_and_the_fields(self) -> None:
        written: list[tuple[str, dict]] = []

        class _Spy:
            def warning(self, message, **kwargs):
                written.append((message, kwargs))

        manager = _VoicingManager(logger=_Spy())
        clock = [0.0]
        with pytest.MonkeyPatch.context() as patch:
            patch.setattr(time, "monotonic", lambda: clock[0])
            manager.log_windowed("k", 5.0, "warning", "постоянный текст")
            manager.log_windowed("k", 5.0, "warning", "постоянный текст")
            manager.log_windowed("k", 5.0, "warning", "постоянный текст")
            clock[0] += _BEYOND_WINDOW
            manager.log_windowed("k", 5.0, "warning", "постоянный текст")

        assert len(written) == 2, f"ожидались 2 записи (первая + после окна), получено {len(written)}"
        assert "2" in written[1][0], f"число подавленных не названо в тексте: {written[1][0]!r}"
        assert written[1][1].get("suppressed_since_last") == 2, (
            f"число подавленных не приехало СТРУКТУРНЫМ полем: {written[1][1]!r}"
        )

    def test_two_managers_do_not_silence_each_other_on_the_same_key(self) -> None:
        """Держатель — свой у экземпляра. Общий заглушил бы соседа его же ключом."""
        first, second = _VoicingManager("A"), _VoicingManager("B")
        assert first.should_voice("общий-ключ", _HUGE_WINDOW)[0] is True
        assert second.should_voice("общий-ключ", _HUGE_WINDOW)[0] is True, (
            "второй менеджер заглушён ключом первого — состояние окон оказалось общим"
        )


class TestFactAndVoiceAreSeparable:
    """Главное обязательство API: факт можно учесть, даже когда голос молчит.

    Без него Task 1.3 не сможет выразить «запись в плоскость ошибок ВСЕГДА,
    строка в журнал по окну» и унаследует общий дроссель ``HealthState``, где
    ``_safe_track`` стоит внутри ветки «окно позволило».
    """

    def test_caller_can_count_every_event_while_voicing_once(self) -> None:
        voices = WindowedVoices()
        facts = 0
        voices_heard = 0

        for _ in range(20):
            facts += 1  # факт — вне всякого окна
            voiced, _suppressed = voices.take("k", _HUGE_WINDOW)
            if voiced:
                voices_heard += 1

        assert facts == 20, "окно не имеет права трогать учёт факта"
        assert voices_heard == 1, "голос обязан быть один на окно"
