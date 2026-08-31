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
from contextlib import contextmanager
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


@contextmanager
def _swallowing():
    """Погасить бросок ``report_error``, чтобы судить ФАКТЫ, а не форму отказа.

    Сторож, держащийся на ``pytest.raises``, обесточивается любым ``try/except``
    в реализации — ревью Task 1.3a поймало именно это. Здесь бросок гасится
    намеренно: проброс проверяет отдельный тест, а этот смотрит, что учтено.
    """
    try:
        yield
    except AssertionError:
        pass


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
    def test_a_throwing_window_holder_still_leaves_the_whole_fact(self) -> None:
        """ВЕСЬ факт — счётчик, плоскость и breaker — переживает отказ держателя окон.

        Сторож находки Major 2 ревью Task 1.3a. Проверяется ПОЛНОТА вызова, а не
        форма отказа, и это разница с ценой: прежний сторож закреплял
        ``pytest.raises``, то есть любой ``try/except`` вокруг ``take()``
        обесточил бы его целиком, а поломка «блок breaker перенесён ниже решения
        о голосе» не красила из 142 сторожей НИ ОДНОГО.

        Что ловилось этой дырой (замер ревью, 5 вхождений одного отказа):

            КОНТРОЛЬ (обычный держатель):  errors=5 плоскость=5 status=degraded breaker=open
            ОПЫТ     (держатель бросает):  errors=5 плоскость=5 status=ok       breaker=closed

        Факт записан весь, breaker не накормлен ни разу — статус не деградировал
        бы НИКОГДА, хотя ``PluginContext.health`` и ADR-PM-045 оба перечисляют
        подряд-счётчик breaker среди того, что делает ``report_error``.

        Порог ``2`` взят, чтобы продвижение читалось С ОБЕИХ сторон: после
        первого вхождения ``closed`` (не «щёлкнуло само»), после второго
        ``open`` (не «стоит на месте»). Порог ``1`` был бы слеп к счётчику,
        который прибавляет по два.
        """
        tracked: list[str] = []
        voices: list[str] = []
        state = HealthState(
            log=voices.append,
            track=lambda exc, payload: tracked.append(str((payload or {}).get("context"))),
            breaker=CircuitBreaker(fail_threshold=2, cooldown_sec=1_000_000.0),
            voices=_ThrowingVoices(),
        )

        # Бросок наружу — решённый контракт (перехват стоит у вызывающего,
        # ``process_hooks``), но сторож на нём НЕ держится: гасим и судим факты.
        for _ in range(1):
            with _swallowing():
                state.report_error(_raise_boom("boom"), context="order", throttle=_WINDOW_NEVER)

        assert tracked == ["order"], f"факт потерян отказом ЧУЖОГО механизма: {tracked}"
        assert state.snapshot()["errors"] == 1
        assert state.snapshot()["breaker"] == "closed", "breaker щёлкнул раньше своего порога"

        with _swallowing():
            state.report_error(_raise_boom("boom"), context="order", throttle=_WINDOW_NEVER)

        snap = state.snapshot()
        assert len(tracked) == 2, tracked
        assert snap["errors"] == 2
        assert snap["breaker"] == "open", (
            f"breaker не накормлен: подряд-счётчик стоит НИЖЕ решения о голосе и теряется его броском — {snap}"
        )
        assert snap["status"] == "degraded", snap
        # (в) голоса инцидента нет — держатель бросил ДО него. Строка статуса от
        # открывшегося breaker'а при этом есть, и она же доказывает, что ветка
        # breaker'а реально исполнилась, а не была угадана по снапшоту.
        status_lines = [v for v in voices if v.startswith("[health] status")]
        incident_voices = [v for v in voices if not v.startswith("[health] status")]
        assert incident_voices == [], f"голос прозвучал вопреки отказу держателя: {incident_voices}"
        assert status_lines, f"ветка breaker'а не сказала ни слова: {voices}"

    def test_the_throw_from_the_holder_is_not_swallowed(self) -> None:
        """Пара к тесту выше: бросок ДОХОДИТ до вызывающего — это решённый контракт.

        Глушить его здесь незачем и вредно: перехват уже стоит у вызывающего
        (``logger_module/core/process_hooks.py`` ловит ``BaseException``, поднимает
        ``hook_delivery_failures`` и пишет ``emergency_log``), то есть вторым
        исключением поверх первого бросок не становится — он становится
        ПОСЧИТАННОЙ потерей доставки. Проглоти его ``report_error`` сам — потеря
        стала бы невидимой, и счётчик доставки перестал бы значить что-либо.
        """
        state = HealthState(breaker=_quiet_breaker(), voices=_ThrowingVoices())
        with pytest.raises(AssertionError):
            state.report_error(_raise_boom("boom"), context="order", throttle=_WINDOW_NEVER)


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

        Плоскость ошибок здесь настоящая (``track=…``) — по ревью Task 1.3a это
        стало условием маркера, а не декорацией теста: без дороги маркер был бы
        утверждением о строке, которой нет (пара тестов ниже).
        """
        seen: list[dict] = []

        def log(msg: str, **kwargs: Any) -> None:
            seen.append(dict(kwargs))

        state = HealthState(log=log, track=lambda exc, payload: None, breaker=_quiet_breaker())
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

    def test_no_marker_when_there_is_no_road_to_the_error_plane(self) -> None:
        """Дороги нет (``track=None``) — маркер был бы утверждением о НЕсуществующей строке.

        Маркер говорит логгер-tap'у «эту запись пропусти, у инцидента уже есть
        своя строка». Сказать это, не отдав факт никуда, значит вычесть инцидент
        из стора целиком — ровно находка Major 1 ревью Task 1.3a, замеренная
        строками стора (контроль 1, опыт 0).
        """
        seen: list[dict] = []
        state = HealthState(
            log=lambda msg, **kwargs: seen.append(dict(kwargs)),
            track=None,
            breaker=_quiet_breaker(),
        )
        state.report_error(_raise_boom("boom"), context="noplane", throttle=_WINDOW_NEVER)

        assert seen, "голос обязан прозвучать даже без плоскости ошибок"
        assert "origin" not in seen[0], f"маркер поставлен без второй дороги: {seen[0]}"

    def test_no_marker_when_the_error_plane_refused(self) -> None:
        """Приёмник бросил — второй дороги фактически не было, маркер лжив так же.

        Пара к тесту выше по ДРУГОЙ причине отсутствия факта: там дороги нет
        вовсе, здесь она есть и отказала. Обе обязаны читаться одинаково.
        """
        seen: list[dict] = []

        def track(exc: BaseException, payload: dict | None) -> None:
            raise OSError("плоскость ошибок недоступна")

        state = HealthState(
            log=lambda msg, **kwargs: seen.append(dict(kwargs)),
            track=track,
            breaker=_quiet_breaker(),
        )
        state.report_error(_raise_boom("boom"), context="refused", throttle=_WINDOW_NEVER)

        assert seen, "отказ плоскости не имеет права проглотить голос"
        assert "origin" not in seen[0], f"маркер поставлен, хотя плоскость отказала: {seen[0]}"


# ---------------------------------------------------------------------------
# Текст исключения — чужой код, и он имеет право бросить
# ---------------------------------------------------------------------------


class TestAThrowingStrDoesNotCostTheFact:
    def test_an_exception_whose_str_raises_is_still_counted(self) -> None:
        """``str(exc)`` стоит первым в ``report_error`` — и был единственной дырой в «ВСЕГДА».

        Ревью Task 1.3a: исключение с самодельным бросающим ``__str__`` уносило
        наружу ``ValueError`` при ``errors=0`` и нуле записей плоскости. То есть
        отказ ЧУЖОГО кода (``__str__`` исключения) стоил ВЕСЬ факт — ровно тот
        класс, который задача 1.3a и разбирает.
        """

        class _EvilStr(RuntimeError):
            def __str__(self) -> str:
                raise ValueError("__str__ бросил")

        tracked: list[Any] = []
        state = HealthState(
            track=lambda exc, payload: tracked.append(payload),
            breaker=_quiet_breaker(),
        )
        state.report_error(_EvilStr(), context="evil", throttle=_WINDOW_NEVER)

        snap = state.snapshot()
        assert snap["errors"] == 1, f"факт потерян отказом __str__: {snap}"
        assert len(tracked) == 1, tracked
        assert "__str__" in snap["last_error"]["message"], (
            f"заглушка обязана НАЗЫВАТЬ причину, а не выглядеть пустым сообщением: {snap['last_error']}"
        )

    def test_a_normal_exception_still_carries_its_own_text(self) -> None:
        """Контроль: защита не имеет права подменить текст здорового исключения заглушкой."""
        state = HealthState(breaker=_quiet_breaker())
        state.report_error(_raise_boom("камера отвалилась"), context="ok", throttle=_WINDOW_NEVER)

        assert state.snapshot()["last_error"]["message"] == "камера отвалилась", state.snapshot()


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
