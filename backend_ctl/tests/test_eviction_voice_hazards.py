"""
Hazard-тесты автора на голос вытеснения `EventHub` (Task 2.4, вход Н3-2).

Приёмочные тесты тестера (``test_eviction_voice.py``) проверяют контракт по
acceptance-критериям. Эти тесты — то, что видно только автору механизма:
дисциплина лока, независимость эпизодов РАЗНЫХ колец и граничные размеры
кольца, которые acceptance-тесты не покрывают дословно.
"""

from __future__ import annotations

import logging
import re
import threading

from backend_ctl.events import ALL_PLANE, EventHub

_LOGGER_NAME = "backend_ctl.events"


class FakeClock:
    """Управляемые часы — те же, что в test_eviction_voice.py (не дублируем
    импортом, чтобы hazard-файл не зависел от файла тестера)."""

    def __init__(self, start: float = 0.0) -> None:
        self._t = start

    def __call__(self) -> float:
        return self._t

    def advance(self, dt: float) -> None:
        self._t += dt


def _log_event(seq: int) -> dict:
    return {"type": "event", "command": "log.record", "data": {"seq": seq}}


def _ui_event(seq: int) -> dict:
    return {"type": "event", "command": "ui.event", "data": {"seq": seq}}


class _CollectingHandler(logging.Handler):
    """Складывает текст WARNING-записей hub'а в переданный список."""

    def __init__(self, sink: list) -> None:
        super().__init__()
        self.sink = sink

    def emit(self, record: logging.LogRecord) -> None:  # pragma: no cover - тривиально
        self.sink.append(record.getMessage())


class _LockProbeHandler(logging.Handler):
    """При получении записи хендлер пытается взять тот же ``self._cv`` hub'а
    ИЗ ДРУГОГО потока (через ``hub.stats()``). Если ``_log.warning()`` в
    ``emit()`` вызван ВНУТРИ ``with self._cv:`` — поток-реализация (T1) держит
    RLock, второй поток (T2) блокируется на попытке взять тот же лок, и
    ``done.wait(timeout)`` вернёт ``False``. Если голос звучит ВНЕ лока
    (контракт emit()) — T1 уже отпустил лок к моменту вызова хендлера, T2
    берёт лок мгновенно, ``done.wait`` возвращает ``True`` быстро.
    """

    def __init__(self, hub: EventHub) -> None:
        super().__init__()
        self.hub = hub
        self.probe_results: list = []  # bool: True = не завис, False = завис

    def emit(self, record: logging.LogRecord) -> None:
        done = threading.Event()

        def probe() -> None:
            self.hub.stats()  # берёт self._cv
            done.set()

        t = threading.Thread(target=probe, daemon=True)
        t.start()
        finished = done.wait(timeout=1.0)
        self.probe_results.append(finished)


# ---------------------------------------------------------------------------
# Hazard 1: голос звучит ВНЕ self._cv (докстринг emit(), Task 2.4).
# Падает ПО ТАЙМАУТУ daemon-потока, а не висит вечно (конвенция CLAUDE.md).
# ---------------------------------------------------------------------------


def test_voice_is_logged_outside_the_lock() -> None:
    maxlen = 3
    hub = EventHub(maxlen=maxlen)  # реальные монотонные часы — секунды роли не играют

    logger = logging.getLogger(_LOGGER_NAME)
    handler = _LockProbeHandler(hub)
    logger.addHandler(handler)
    logger.setLevel(logging.WARNING)
    try:
        exceptions: list = []

        def drive() -> None:
            try:
                for i in range(maxlen):
                    hub.emit(_log_event(i))
                hub.emit(_log_event(maxlen))  # переполнение -> голос -> хендлер
            except BaseException as exc:  # noqa: BLE001 — донести причину падения теста
                exceptions.append(exc)

        driver_thread = threading.Thread(target=drive, daemon=True)
        driver_thread.start()
        driver_thread.join(timeout=5.0)

        assert not driver_thread.is_alive(), "hub.emit() не завершился за 5с — похоже на зависание из-за лока"
        assert not exceptions, f"emit() бросил исключение в потоке: {exceptions}"
        assert handler.probe_results, "хендлер логгера ни разу не вызван — голос не прозвучал"
        assert all(handler.probe_results), (
            "hub.stats() из другого потока встал колом внутри хендлера => "
            "_log.warning() вызывается ПОД self._cv, а не после выхода из-под него"
        )
    finally:
        logger.removeHandler(handler)


# ---------------------------------------------------------------------------
# Hazard 2: эпизоды РАЗНЫХ колец независимы — нет общей на все ключи отметки
# времени. Ловит implementation, которая держит ОДИН last_eviction_ts вместо
# словаря по ключу: тогда недавний голос кольца A молча подавил бы ЗАКОННЫЙ
# первый голос кольца B (у B своя собственная история ещё пуста).
# ---------------------------------------------------------------------------


def test_recent_voice_on_one_ring_does_not_suppress_first_voice_on_another() -> None:
    maxlen = 3
    clock = FakeClock(start=0.0)
    hub = EventHub(maxlen=maxlen, clock=clock)

    records: list = []
    logger = logging.getLogger(_LOGGER_NAME)
    handler = _CollectingHandler(records)
    logger.addHandler(handler)
    logger.setLevel(logging.WARNING)
    try:
        # 1) заполнить и переполнить LOGS -> первый голос кольца logs (и, тем же
        #    вызовом, arrival — оба видят вытеснение впервые одновременно).
        for i in range(maxlen):
            hub.emit(_log_event(i))
        hub.emit(_log_event(maxlen))  # переполнение logs

        assert any("logs" in r for r in records), "не прозвучал голос logs при первом переполнении"

        # 2) БЕЗ сдвига часов — сразу заполнить и переполнить UI. У UI
        #    собственная история вытеснений пуста (last_eviction_ts["ui"] нет),
        #    поэтому голос ОБЯЗАН прозвучать, даже если logs/all только что
        #    отговорили на этом же "now".
        for i in range(maxlen):
            hub.emit(_ui_event(i))
        hub.emit(_ui_event(maxlen))  # переполнение ui — первый раз

        assert any("ui" in r for r in records), (
            "голос ui не прозвучал — похоже на общий (не per-ring) last_eviction_ts, "
            "недавний голос logs/all молча подавил законный первый голос ui"
        )
    finally:
        logger.removeHandler(handler)


def test_quiet_gap_on_one_ring_does_not_reset_or_extend_the_others_episode() -> None:
    """Обратное направление: долгое затишье кольца A не должно ни давать
    лишний голос кольцу B (у которого своя, ещё не истёкшая история), ни
    ошибочно продлевать эпизод B на основании часов A."""
    maxlen = 3
    clock = FakeClock(start=0.0)
    hub = EventHub(maxlen=maxlen, clock=clock)

    records: list = []
    logger = logging.getLogger(_LOGGER_NAME)
    handler = _CollectingHandler(records)
    logger.addHandler(handler)
    logger.setLevel(logging.WARNING)
    try:
        from backend_ctl.events import EVICTION_VOICE_QUIET_SEC

        for i in range(maxlen):
            hub.emit(_log_event(i))
        hub.emit(_log_event(maxlen))  # logs: голос #1 (эпизод logs начат в t=0)
        logs_voices_after_first = sum(1 for r in records if "logs" in r)
        assert logs_voices_after_first == 1

        # большое затишье, но БЕЗ новых событий logs вообще
        clock.advance(EVICTION_VOICE_QUIET_SEC + 1.0)

        # первое событие UI в жизни хаба — переполнения тут не будет (ring
        # только начинает заполняться), голосов не добавится ни для кого.
        hub.emit(_ui_event(0))
        assert sum(1 for r in records if "logs" in r) == logs_voices_after_first, (
            "затишье, пережитое ДРУГИМ кольцом, не должно порождать голос logs"
        )
    finally:
        logger.removeHandler(handler)


# ---------------------------------------------------------------------------
# Hazard 3: число в голосе — evicted ИМЕННО этого кольца, не seq, не size,
# не maxlen. Acceptance-тест тестера проверяет лишь "есть какое-то число" —
# эту дыру закрывает этот тест конкретными, заведомо различными числами.
# ---------------------------------------------------------------------------


def test_voice_number_is_this_rings_evicted_not_seq_size_or_maxlen() -> None:
    maxlen = 6  # seq=7, size=6, evicted=1 после ровно одного переполнения — все разные
    clock = FakeClock(start=100.0)
    hub = EventHub(maxlen=maxlen, clock=clock)

    records: list = []
    logger = logging.getLogger(_LOGGER_NAME)
    handler = _CollectingHandler(records)
    logger.addHandler(handler)
    logger.setLevel(logging.WARNING)
    try:
        # Кольца НАМЕРЕННО разведены по числу вытесненных. Если гнать только
        # log.record, arrival и 'logs' идут в ногу и оба дают evicted=1 — тогда
        # ассерт прошёл бы и в том случае, если реализация подставит под меткой
        # 'logs' число ЧУЖОГО кольца (совпадение констант прячет противоположные
        # реализации; находка ревью 2026-08-14, пункт 3).
        # 4 события в другую плоскость наполняют arrival, не трогая 'logs'.
        for i in range(4):
            hub.emit({"type": "event", "command": "ui.event", "data": {"record": {"kind": "button", "n": i}}})
        for i in range(maxlen):
            hub.emit(_log_event(i))
        hub.emit(_log_event(maxlen))  # ровно ОДНО переполнение 'logs' -> голос про 'logs'
    finally:
        logger.removeHandler(handler)

    logs_stats = hub.stats()["planes"]["logs"]
    assert logs_stats["evicted"] == 1
    assert logs_stats["seq"] == maxlen + 1  # 7
    assert logs_stats["size"] == maxlen  # 6
    # Контроль развода: у arrival число ДРУГОЕ, иначе тест снова ничего не различал бы.
    all_evicted = hub.stats()["all"]["evicted"]
    assert all_evicted != logs_stats["evicted"], (
        f"кольца не разведены: arrival evicted={all_evicted} совпал с logs evicted="
        f"{logs_stats['evicted']}, тест не отличит одно число от другого"
    )

    # Число берётся АДРЕСНО — из скобки при имени 'logs', а не «любое число в тексте».
    logs_texts = [t for t in records if "'logs'" in t]
    assert len(logs_texts) == 1
    text = logs_texts[0]
    match = re.search(r"'logs' \(вытеснено (\d+)", text)
    assert match is not None, f"не нашёл число при имени 'logs' в тексте {text!r}"
    assert int(match.group(1)) == 1, (
        f"ожидали при 'logs' ровно evicted=1 (не seq={logs_stats['seq']}, "
        f"не size/maxlen={maxlen}, не arrival evicted={all_evicted}), "
        f"получили {match.group(1)} в тексте {text!r}"
    )


# ---------------------------------------------------------------------------
# Hazard 4: граничные размеры кольца — maxlen=0 и maxlen=1.
# ---------------------------------------------------------------------------


def test_maxlen_zero_every_emit_is_an_eviction_but_voice_stays_one_per_episode() -> None:
    """deque(maxlen=0) не хранит ничего: len(ring) == ring.maxlen == 0 ДО
    любого append, значит каждая эмиссия — вытеснение с первого же события.
    Код не должен падать и обязан по-прежнему звучать один раз на эпизод."""
    clock = FakeClock(start=0.0)
    hub = EventHub(maxlen=0, clock=clock)

    records: list = []
    logger = logging.getLogger(_LOGGER_NAME)
    handler = _CollectingHandler(records)
    logger.addHandler(handler)
    logger.setLevel(logging.WARNING)
    try:
        hub.emit(_log_event(0))  # ring_was_full True с самого начала (0 == 0)
        assert len(records) == 1
        stats = hub.stats()["planes"]["logs"]
        assert stats["size"] == 0
        assert stats["evicted"] == 1

        # то же затишье (часы не двигались) -> второй голос НЕ добавляется
        hub.emit(_log_event(1))
        assert len(records) == 1
        assert hub.stats()["planes"]["logs"]["evicted"] == 2

        # затишье длиннее порога -> новый эпизод -> второй голос
        from backend_ctl.events import EVICTION_VOICE_QUIET_SEC

        clock.advance(EVICTION_VOICE_QUIET_SEC + 1.0)
        hub.emit(_log_event(2))
        assert len(records) == 2
    finally:
        logger.removeHandler(handler)


def test_maxlen_one_first_event_is_free_second_evicts() -> None:
    """Граница maxlen=1: единственное место в кольце заполняется первым
    событием без вытеснения, второе событие вытесняет его."""
    clock = FakeClock(start=0.0)
    hub = EventHub(maxlen=1, clock=clock)

    records: list = []
    logger = logging.getLogger(_LOGGER_NAME)
    handler = _CollectingHandler(records)
    logger.addHandler(handler)
    logger.setLevel(logging.WARNING)
    try:
        hub.emit(_log_event(0))
        assert len(records) == 0  # кольцо ещё не было полным -> без вытеснения

        hub.emit(_log_event(1))
        assert len(records) == 1  # переполнение -> голос

        stats = hub.stats()["planes"]["logs"]
        assert stats["size"] == 1
        assert stats["evicted"] == 1
    finally:
        logger.removeHandler(handler)


def test_all_plane_constant_used_for_arrival_ring_name() -> None:
    """Контракт п.6: имя arrival-кольца в голосе — константа ALL_PLANE."""
    assert ALL_PLANE == "all"

    clock = FakeClock(start=0.0)
    maxlen = 2
    hub = EventHub(maxlen=maxlen, clock=clock)

    records: list = []
    logger = logging.getLogger(_LOGGER_NAME)
    handler = _CollectingHandler(records)
    logger.addHandler(handler)
    logger.setLevel(logging.WARNING)
    try:
        for i in range(maxlen):
            hub.emit(_log_event(i))
        hub.emit(_log_event(maxlen))  # arrival и logs переполняются вместе
    finally:
        logger.removeHandler(handler)

    combined = " | ".join(records)
    assert f"'{ALL_PLANE}'" in combined, f"arrival-кольцо не названо константой ALL_PLANE в голосе: {combined!r}"
