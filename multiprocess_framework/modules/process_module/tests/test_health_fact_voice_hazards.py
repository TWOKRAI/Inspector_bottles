# -*- coding: utf-8 -*-
"""Опасности механизма «факт всегда, голос по окну» (Task 1.3a, тесты АВТОРА).

Независимый тестер писал от критериев приёмки и внутренних опасностей этого
механизма не видел — его набор живёт в
``test_fact_always_voice_windowed_acceptance.py``. Здесь — вторая половина:
то, что видно только изнутри правки.

Правка вынесла ``_safe_track`` из-под ветки голоса и поставила ЕГО ПЕРВЫМ, до
решения о голосе. Отсюда четыре опасности, по одной на класс:

1. **гонка.** Запись плоскости теперь делается ВНЕ ``self._lock`` и на каждое
   вхождение, а не на одно из N. Два потока оказываются внутри приёмника
   одновременно — и если полезная нагрузка окажется общим словарём, поля
   вхождений перемешаются, а тест «5 записей из 5» этого не заметит: записей
   всё равно будет пять.
2. **реентрантность.** Приёмник плоскости имеет право сам позвать
   ``report_error`` (так выглядит любой sink, который логирует свои отказы).
   Удержание лока на время вызова превратило бы это в дедлок.
3. **порядок.** Решение о голосе принимает ЧУЖОЙ механизм (держатель окон).
   Упади он — факт обязан быть уже записан. Это и есть причина, по которой
   ``_safe_track`` стоит до ``take()``, а не после, как в иллюстрации ТЗ.
4. **отказ приёмника.** ``report_error`` зовут из веток «мы поймали
   исключение». Отказ учёта не имеет права стать вторым исключением поверх
   первого — свойство существовало до правки и обязано пережить её.

Время здесь не двигается ``sleep``: окно задаётся ``throttle`` (0.0 — «окно
уже истекло», огромное — «окно не истечёт никогда»), а где нужен ход часов —
инъекцией ``WindowedVoices(clock=…)``. Всё, что может заблокироваться, идёт в
демон-потоке с дедлайном на ``join``: тест, который вешается вместо падения,
хуже отсутствующего.
"""

from __future__ import annotations

import threading
from typing import Any

import pytest

from ...logger_module.core.windowed_voice import WindowedVoices
from ..health.breaker import CircuitBreaker
from ..health.state import HealthState

#: Окно, которое НЕ истечёт за прогон теста: голос будет ровно один.
_WINDOW_NEVER = 10_000.0

#: Окно, которое истекло всегда: голос на каждом вхождении.
_WINDOW_ALWAYS = 0.0

#: Дедлайн ожидания потока. Меньше него — флейк на загруженной машине, больше —
#: тест вешается вместо того, чтобы упасть.
_JOIN_TIMEOUT = 10.0


class _Boom(RuntimeError):
    """Тип-маркер этого файла: ключ окна не пересекается с соседними тестами."""


def _quiet_breaker() -> CircuitBreaker:
    """Breaker, который не откроется и не добавит посторонний голос ``degraded``."""
    return CircuitBreaker(fail_threshold=1_000_000, cooldown_sec=1_000_000.0)


def _raise_boom(msg: str) -> _Boom:
    """Настоящее возбуждённое исключение — с трассой, как на боевом сайте."""
    try:
        raise _Boom(msg)
    except _Boom as exc:
        return exc


# ---------------------------------------------------------------------------
# 1. Гонка: два потока сообщают одновременно
# ---------------------------------------------------------------------------


class TestConcurrentReportsKeepTheirOwnFields:
    def test_payloads_of_simultaneous_reports_do_not_mix(self) -> None:
        """N потоков ВНУТРИ приёмника одновременно — у каждого свои поля.

        Приёмник задерживается на барьере, пока в нём не соберутся все N: это и
        есть состояние, в котором общий словарь полезной нагрузки перемешал бы
        вхождения. Проверяется НЕ число записей (оно сошлось бы и на общем
        словаре), а то, что каждая запись после выхода из барьера всё ещё несёт
        СВОЙ тег.
        """
        n = 6
        inside = threading.Barrier(n, timeout=_JOIN_TIMEOUT)
        seen: list[tuple[str, str]] = []
        seen_lock = threading.Lock()

        def track(exc: BaseException, payload: dict | None) -> None:
            before = (payload or {}).get("thread_tag")
            inside.wait()  # все N приёмников одновременно держат свои payload
            after = (payload or {}).get("thread_tag")
            with seen_lock:
                seen.append((str(before), str(after)))

        state = HealthState(track=track, breaker=_quiet_breaker())
        errors: list[BaseException] = []

        def worker(i: int) -> None:
            try:
                state.report_error(
                    _raise_boom(f"boom-{i}"),
                    context="race",
                    throttle=_WINDOW_NEVER,
                    thread_tag=f"worker-{i}",
                )
            except BaseException as exc:  # noqa: BLE001 — падение потока не должно быть тишиной
                errors.append(exc)

        threads = [threading.Thread(target=worker, args=(i,), daemon=True) for i in range(n)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=_JOIN_TIMEOUT)
            assert not t.is_alive(), "поток не завершился — подозрение на дедлок в report_error"

        assert not errors, f"report_error бросил из потока: {errors}"
        assert len(seen) == n, f"в плоскость доехали не все вхождения: {seen}"
        assert all(before == after for before, after in seen), (
            f"полезная нагрузка вхождения изменилась, пока приёмник её держал: {seen}"
        )
        assert {after for _before, after in seen} == {f"worker-{i}" for i in range(n)}, (
            f"теги вхождений перемешались: {seen}"
        )
        assert state.snapshot()["errors"] == n

    def test_the_counter_survives_the_same_race(self) -> None:
        """Счётчик под локом: ни одно вхождение не потеряно (контроль к тесту выше)."""
        n = 24
        start = threading.Barrier(n, timeout=_JOIN_TIMEOUT)
        state = HealthState(breaker=_quiet_breaker())

        def worker(i: int) -> None:
            start.wait()
            state.report_error(_raise_boom("boom"), context="race_counter", throttle=_WINDOW_NEVER)

        threads = [threading.Thread(target=worker, args=(i,), daemon=True) for i in range(n)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=_JOIN_TIMEOUT)
            assert not t.is_alive(), "поток не завершился — подозрение на дедлок"

        assert state.snapshot()["errors"] == n


# ---------------------------------------------------------------------------
# 2. Реентрантность: report_error из обработчика записи плоскости
# ---------------------------------------------------------------------------


class TestReentrancyFromTheErrorPlaneHandler:
    def test_report_error_from_inside_track_does_not_deadlock(self) -> None:
        """Приёмник плоскости зовёт ``report_error`` — оба факта учтены, дедлока нет.

        Прогон идёт в демон-потоке с дедлайном: дедлок здесь обязан выглядеть
        падением по таймауту, а не вечно висящим тестом.
        """
        depth = threading.local()
        tracked: list[str] = []
        state_box: list[HealthState] = []

        def track(exc: BaseException, payload: dict | None) -> None:
            tracked.append(str((payload or {}).get("context")))
            if getattr(depth, "inside", False):
                return
            depth.inside = True
            try:
                # Вложенный инцидент ДРУГОГО ключа — так выглядит sink, который
                # сам сообщает о своём отказе.
                state_box[0].report_error(_raise_boom("inner"), context="inner", throttle=_WINDOW_NEVER)
            finally:
                depth.inside = False

        state = HealthState(track=track, breaker=_quiet_breaker())
        state_box.append(state)

        done = threading.Event()
        failure: list[BaseException] = []

        def run() -> None:
            try:
                state.report_error(_raise_boom("outer"), context="outer", throttle=_WINDOW_NEVER)
            except BaseException as exc:  # noqa: BLE001
                failure.append(exc)
            finally:
                done.set()

        worker = threading.Thread(target=run, daemon=True)
        worker.start()
        assert done.wait(timeout=_JOIN_TIMEOUT), "report_error не вернулся — дедлок на реентрантном входе"
        assert not failure, f"реентрантный вход бросил: {failure}"
        assert tracked == ["outer", "inner"], f"учтены не оба вхождения: {tracked}"
        assert state.snapshot()["errors"] == 2


# ---------------------------------------------------------------------------
# 3. Порядок: факт учтён до того, как решение о голосе может бросить
# ---------------------------------------------------------------------------


class _ThrowingVoices(WindowedVoices):
    """Держатель окон, который отказывает на решении. Так ведёт себя чужой механизм."""

    def take(self, key: str, interval: Any = None):  # type: ignore[override]
        raise AssertionError("держатель окон отказал")


class TestFactIsRecordedBeforeTheVoiceDecision:
    def test_a_throwing_window_holder_does_not_lose_the_fact(self) -> None:
        """Решение о голосе принимает чужой код; факт обязан быть записан ДО него.

        Обратный порядок (``take()`` первым, как в иллюстрации ТЗ) терял бы ровно
        то, ради чего задача и делалась: при отказе держателя окон вхождение не
        попало бы ни в счётчик, ни в плоскость ошибок.
        """
        tracked: list[str] = []
        state = HealthState(
            track=lambda exc, payload: tracked.append(str((payload or {}).get("context"))),
            breaker=_quiet_breaker(),
            voices=_ThrowingVoices(),
        )

        with pytest.raises(AssertionError):
            state.report_error(_raise_boom("boom"), context="order", throttle=_WINDOW_NEVER)

        assert tracked == ["order"], f"факт потерян отказом ЧУЖОГО механизма: {tracked}"
        assert state.snapshot()["errors"] == 1
        assert state.snapshot()["last_error"]["context"] == "order"


# ---------------------------------------------------------------------------
# 4. Отказ приёмника: учёт инцидента не становится вторым исключением
# ---------------------------------------------------------------------------


class TestARefusingSinkIsNotASecondException:
    def test_track_raising_does_not_escape_report_error(self) -> None:
        """Свойство существовало до правки и обязано пережить её."""
        calls: list[int] = []

        def track(exc: BaseException, payload: dict | None) -> None:
            calls.append(1)
            raise OSError("плоскость ошибок недоступна")

        state = HealthState(track=track, breaker=_quiet_breaker())
        state.report_error(_raise_boom("boom"), context="sink_refuses", throttle=_WINDOW_NEVER)

        assert calls == [1]
        assert state.snapshot()["errors"] == 1

    def test_the_voice_still_sounds_after_the_plane_refused(self) -> None:
        """Отказ плоскости не имеет права заодно проглотить голос.

        Пара к тесту выше: без неё «не бросил» доказывалось бы и полным
        молчанием — а молчание здесь и есть худший исход.
        """
        voices: list[str] = []
        state = HealthState(
            log=voices.append,
            track=lambda exc, payload: (_ for _ in ()).throw(OSError("нет плоскости")),
            breaker=_quiet_breaker(),
        )
        state.report_error(_raise_boom("boom"), context="sink_refuses", throttle=_WINDOW_NEVER)

        assert len(voices) == 1 and "[health]" in voices[0], voices

    def test_a_log_callback_that_takes_only_a_message_still_hears_the_voice(self) -> None:
        """Лесенка форм вызова ``_safe_log`` не теряет голос на узком колбэке.

        Правка добавила первую ступень (с полями), и колбэк вида
        ``lambda msg: …`` обязан по-прежнему получать строку — иначе маркер
        дедупа стоил бы нам всей лог-дороги health на минимальных приёмниках.
        """
        heard: list[str] = []
        state = HealthState(log=lambda msg: heard.append(msg), breaker=_quiet_breaker())
        state.report_error(_raise_boom("boom"), context="narrow_cb", throttle=_WINDOW_NEVER)
        assert len(heard) == 1 and heard[0].startswith("[health] _Boom @ narrow_cb"), heard


# ---------------------------------------------------------------------------
# Маркер дедупа путей — контракт HealthState с tap'ом стора
# ---------------------------------------------------------------------------


class TestTheVoiceCarriesTheDedupMarker:
    def test_voice_is_marked_as_already_recorded_by_the_error_plane(self) -> None:
        """Голос несёт ``origin=error_manager``; факт при этом идёт своей дорогой.

        Без маркера один инцидент кладёт в стор ДВЕ строки — факт и голос,
        — и «сколько у нас инцидентов» перестаёт быть вопросом с ответом.
        """
        seen: list[dict] = []

        def log(msg: str, **kwargs: Any) -> None:
            seen.append(dict(kwargs))

        state = HealthState(log=log, breaker=_quiet_breaker())
        state.report_error(_raise_boom("boom"), context="marker", throttle=_WINDOW_NEVER)

        assert seen and seen[0].get("origin") == "error_manager", seen

    def test_status_voice_is_not_marked(self) -> None:
        """Контроль: строка СТАТУСА маркера не несёт — за ней факта в плоскости нет.

        Иначе маркер означал бы «строка от health», а не «инцидент уже записан»,
        и дедуп молча съедал бы записи, у которых второй дороги не было.
        """
        seen: list[dict] = []

        def log(msg: str, **kwargs: Any) -> None:
            seen.append(dict(kwargs))

        state = HealthState(log=log, breaker=_quiet_breaker())
        state.degraded("причина")

        assert seen and "origin" not in seen[0], seen


# ---------------------------------------------------------------------------
# Окно голоса — своё у каждого HealthState, и оно НЕ управляет фактом
# ---------------------------------------------------------------------------


class TestWindowGovernsTheVoiceOnly:
    def test_expired_window_voices_every_time_while_the_plane_gets_every_fact(self) -> None:
        """Контроль к «окну не истечь»: при ``throttle=0`` голосов столько же, сколько фактов.

        Пара к остальным тестам файла, где окно огромно. Без неё «фактов N,
        голос 1» доказывалось бы и механизмом, который вообще разучился
        говорить.
        """
        voices: list[str] = []
        tracked: list[str] = []
        state = HealthState(
            log=voices.append,
            track=lambda exc, payload: tracked.append(str((payload or {}).get("context"))),
            breaker=_quiet_breaker(),
        )
        for _ in range(4):
            state.report_error(_raise_boom("boom"), context="always", throttle=_WINDOW_ALWAYS)

        assert len(tracked) == 4, tracked
        assert len(voices) == 4, voices

    def test_two_health_states_do_not_silence_each_other(self) -> None:
        """Держатель окон — свой у экземпляра, а не процессный.

        Два процесса в одном интерпретаторе (тесты, ProcessManager) дают
        одинаковый ключ ``"_Boom|shared_key"``. Общий держатель заглушил бы
        голос второго первым — то есть отказ второго процесса стал бы невидим.
        """
        first_voices: list[str] = []
        second_voices: list[str] = []
        first = HealthState(log=first_voices.append, breaker=_quiet_breaker())
        second = HealthState(log=second_voices.append, breaker=_quiet_breaker())

        first.report_error(_raise_boom("boom"), context="shared_key", throttle=_WINDOW_NEVER)
        second.report_error(_raise_boom("boom"), context="shared_key", throttle=_WINDOW_NEVER)

        assert len(first_voices) == 1, first_voices
        assert len(second_voices) == 1, second_voices

    def test_the_window_moves_on_its_own_injected_clock(self) -> None:
        """Окно живёт на МОНОТОННЫХ часах держателя, а не на настенных HealthState.

        Настенные часы можно перевести назад; окно на них молчало бы дольше, чем
        просили. Здесь двигаются часы держателя — и второй голос называет число
        подавленных с прошлой записи.
        """

        class _Mono:
            t = 100.0

            def __call__(self) -> float:
                return self.t

        clock = _Mono()
        voices: list[str] = []
        state = HealthState(log=voices.append, breaker=_quiet_breaker(), voices=WindowedVoices(clock=clock))

        for _ in range(4):  # 1 голос + 3 подавленных
            state.report_error(_raise_boom("boom"), context="clocked", throttle=5.0)
        assert len(voices) == 1, voices

        clock.t += 6.0
        state.report_error(_raise_boom("boom"), context="clocked", throttle=5.0)
        assert len(voices) == 2, voices
        assert "3" in voices[1], f"второй голос обязан назвать 3 подавленных: {voices[1]!r}"
