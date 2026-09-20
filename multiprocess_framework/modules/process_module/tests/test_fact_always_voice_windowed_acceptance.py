# -*- coding: utf-8 -*-
"""Приёмочный тест (независимый tester, RED-до-реализации, Task 1.3a).

Механизм: «факт учитывается всегда, голос идёт по окну» в
``HealthState.report_error``.

Сегодняшний дефект (воспроизведён этим файлом, числа — из живого прогона):
запись в плоскость ошибок (``_safe_track``) стоит ВНУТРИ ``if should_log:``,
поэтому повтор одного отказа внутри окна throttle не оставляет в плоскости
ошибок ничего, кроме числа в ``errors``.

Целевое поведение (критерии приёмки из ТЗ):
1. N повторов одного отказа внутри окна → N записей в плоскости ошибок
   (``_track``), не больше ОДНОГО голоса (``_log``); каждая запись несёт СВОЙ
   контекст (разные потоки/поля не схлопываются).
2. Следующий голос после окна называет число подавленных.
3. Сверка — ПО КЛЮЧУ, из текста голоса, а не по процессному
   ``windowed_suppressed`` (общему на все ключи и всех держателей окон).
4. ``HealthState`` не имеет права держать собственное состояние окна —
   ни ``DEFAULT_THROTTLE``, ни ``_last_log_ts``.
5. Один инцидент — ОДНА строка в персистентном ``ObservabilityStore`` (сейчас,
   по факту живого прогона харнеса из настоящих ``ErrorManager``/
   ``LoggerManager`` — ДВЕ: kind='error' от плоскости ошибок и kind='log' от
   лог-дороги; расходится с числом «три» из ТЗ — см. "что оставлено открытым"
   в отчёте тестера). Запись, пришедшая через плоскость ошибок, несёт маркер
   ``origin=error_manager`` в ``extra``.

Форбидден-пути этого захода (независимый тестер, worktree на коммите ДО
реализации): plans/observability-closure/**, docs/reviews/**,
logger_module/DECISIONS.md — не читались.
"""

from __future__ import annotations

import threading
import time
from pathlib import Path
from typing import Any
from unittest.mock import Mock

import pytest

from ...logger_module.core.windowed_voice import WindowedVoices
from ..health.breaker import CircuitBreaker
from ..health.state import HealthState


# ---------------------------------------------------------------------------
# Гигиена общего процессного держателя окон (windowed_voice — модульный
# синглтон, разделяемый ВСЕМИ тестами процесса). Сброс до/после — не потому,
# что мы уверены, что HealthState будет использовать именно его (может завести
# свой, как это делает ObservableMixin._voices()), а потому что если будет
# использовать общий — тест обязан быть от него изолирован.
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _reset_shared_window_state():
    try:
        from ...logger_module.core.windowed_voice import reset_process_voices

        reset_process_voices()
        yield
        reset_process_voices()
    except ImportError:
        yield


def _no_throttle_clock() -> float:
    return time.time()


class _FakeMonotonic:
    """Управляемые МОНОТОННЫЕ часы окна голоса.

    Правка исполнителя (Task 1.3a): инъекция часов в окно ОКАЗАЛАСЬ возможна —
    ``WindowedVoices(clock=…)``. Прежняя редакция этого файла двигала окно
    настоящим ``time.sleep(0.45)`` при окне 0.15 с, потому что тестер такой
    двери не нашёл. Ассерты не тронуты, изменился только способ довести время
    до конца окна.
    """

    def __init__(self) -> None:
        self.t = 1_000.0

    def __call__(self) -> float:
        return self.t


def _make_state(
    breaker_threshold: int = 100_000,
    voices: Any = None,
) -> tuple[HealthState, list[tuple[BaseException, dict]], list[str]]:
    """HealthState с фейковыми log/track-колбэками + breaker, который НЕ мешает.

    breaker с намеренно огромным порогом: без этого N=5+ повторов подряд
    открыли бы circuit breaker (DEFAULT_FAIL_THRESHOLD=5) и его собственный
    ``set_status`` дал бы ПОСТОРОННИЙ голос, замусорив счёт log_calls этого
    теста. Живой прогон это подтвердил: без большого порога 5-й report_error
    добавляет в log_calls голос breaker'а, не относящийся к критерию 1.
    """
    track_calls: list[tuple[BaseException, dict]] = []
    log_calls: list[str] = []

    def track(exc: BaseException, payload: dict | None) -> None:
        track_calls.append((exc, dict(payload) if payload else {}))

    def log(msg: str, **_kw: Any) -> None:
        log_calls.append(msg)

    breaker = CircuitBreaker(fail_threshold=breaker_threshold, cooldown_sec=99_999.0, clock=_no_throttle_clock)
    state = HealthState(log=log, track=track, breaker=breaker, clock=_no_throttle_clock, voices=voices)
    return state, track_calls, log_calls


class _Boom(RuntimeError):
    """Тип-маркер этого файла — не пересекается по ключу с другими тестами."""


# ---------------------------------------------------------------------------
# Критерий 1 — факт всегда, голос по окну, контекст каждой записи свой
# ---------------------------------------------------------------------------


def test_n_repeats_within_window_give_n_error_plane_facts_from_different_threads() -> None:
    """N=5 отказов ОДНОГО ключа внутри окна → 5 записей в плоскости ошибок.

    Вхождения идут из РАЗНЫХ потоков (не только с разными fields) — по прямому
    указанию ТЗ («убедись, что различия доехали, а не схлопнулись»). Каждый
    поток передаёт свой context, чтобы отличать записи друг от друга.
    """
    state, track_calls, log_calls = _make_state()
    N = 5
    key_ctx = "criterion1_diff_threads"
    barrier = threading.Barrier(N, timeout=5.0)

    def worker(i: int) -> None:
        barrier.wait()
        try:
            raise _Boom("boom")
        except _Boom as exc:
            state.report_error(exc, context=key_ctx, thread_tag=f"worker-{i}")

    threads = [threading.Thread(target=worker, args=(i,), daemon=True) for i in range(N)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=5.0)
        assert not t.is_alive(), "поток не завершился за 5с — подозрение на deadlock в report_error"

    assert len(track_calls) == N, (
        f"ожидалось {N} записей в плоскости ошибок (факт — всегда), получено {len(track_calls)}: "
        f"{track_calls} (сегодняшний баг: _safe_track стоит внутри if should_log)"
    )
    assert len(log_calls) <= 1, (
        f"голос не чаще окна на ключ — ожидался максимум 1 голос из {N} повторов, "
        f"получено {len(log_calls)}: {log_calls}"
    )

    tags_seen = {payload.get("thread_tag") for _, payload in track_calls}
    expected_tags = {f"worker-{i}" for i in range(N)}
    assert tags_seen == expected_tags, (
        f"каждая из {N} записей обязана нести СВОЙ контекст (разный поток) — "
        f"различия схлопнулись: видно {tags_seen}, ожидалось {expected_tags}"
    )


# ---------------------------------------------------------------------------
# Критерий 2 — следующий голос после окна называет число подавленных
# ---------------------------------------------------------------------------


def test_voice_after_window_expiry_names_the_suppressed_count() -> None:
    """1 голос → 3 молчаливых повтора (окно) → окно истекло → голос называет 3."""
    window_clock = _FakeMonotonic()
    state, track_calls, log_calls = _make_state(voices=WindowedVoices(clock=window_clock))
    key_ctx = "criterion2_suppressed_count"
    window = 0.15  # величина окна теперь не связана с сеткой monotonic: часы инъектированы

    def fire() -> None:
        try:
            raise _Boom("boom")
        except _Boom as exc:
            state.report_error(exc, context=key_ctx, throttle=window)

    fire()  # 1: голос №1 (новый ключ)
    fire()  # 2: подавлен (в окне)
    fire()  # 3: подавлен (в окне)
    fire()  # 4: подавлен (в окне)

    assert len(log_calls) == 1, f"до истечения окна — только первый голос, получено {log_calls}"

    window_clock.t += window * 3  # окно заведомо истекло; настоящего sleep здесь больше нет

    fire()  # 5: окно истекло → голос №2, обязан назвать 3 подавленных с прошлой записи

    assert len(log_calls) == 2, f"после истечения окна ожидался второй голос, получено {log_calls}"
    second_voice = log_calls[1]
    assert "3" in second_voice, (
        f"второй голос обязан называть число подавленных с прошлой записи (3), текст голоса: {second_voice!r}"
    )


# ---------------------------------------------------------------------------
# Критерий 3 — сверка по ключу из текста голоса, НЕ по процессному счётчику
# ---------------------------------------------------------------------------


def test_suppressed_count_must_be_read_from_voice_text_not_the_process_wide_counter() -> None:
    """Процессный ``windowed_suppressed`` — общий на ВСЕ ключи и держателей окон.

    Не просто «текст содержит ключ» (это верно уже сегодня и ничего не
    доказывает про число подавленных — слабый вариант этого теста молча
    проходил и на баг-версии, находка тестера). Здесь numbers must diverge:
    наш ключ подавляется РОВНО 3 раза, чужой (шумовой) ключ — РОВНО 5 раз,
    оба бьют в ОДИН процессный счётчик. Кто сверит «подавлено у нашего ключа»
    с дельтой процессного счётчика — получит 3+5=8, а не 3. Правильный ответ
    (3) живёт только в тексте ВТОРОГО голоса нашего ключа.
    """
    try:
        from ...logger_module.core.windowed_voice import voice_counters
    except ImportError:
        pytest.skip("windowed_voice.voice_counters недоступен — процессный счётчик не существует в этой сборке")

    import re

    counter_before = voice_counters().get("windowed_suppressed", 0)

    window = 0.15
    window_clock = _FakeMonotonic()
    state, _track_calls, log_calls = _make_state(voices=WindowedVoices(clock=window_clock))
    key_ctx = "criterion3_our_key"

    def fire_ours() -> None:
        try:
            raise _Boom("boom")
        except _Boom as exc:
            state.report_error(exc, context=key_ctx, throttle=window)

    noise_state, _noise_track, _noise_log = _make_state(voices=WindowedVoices(clock=window_clock))

    def fire_noise() -> None:
        try:
            raise _Boom("noise")
        except _Boom as exc:
            noise_state.report_error(exc, context="criterion3_unrelated_noise_key", throttle=window)

    fire_ours()  # голос №1 нашего ключа (новый ключ — не в счёт подавленных)
    fire_noise()  # голос №1 шумового ключа (тоже новый — не в счёт)

    # Внутри окна: наш ключ подавлен РОВНО 3 раза, шумовой — РОВНО 5 раз.
    # Оба бьют в ОДИН и тот же процессный windowed_suppressed.
    for _ in range(3):
        fire_ours()
    for _ in range(5):
        fire_noise()

    window_clock.t += window * 3
    fire_ours()  # окно истекло → голос №2 нашего ключа, обязан назвать 3

    assert len(log_calls) == 2, f"ожидались 2 голоса нашего ключа (до/после окна), получено {log_calls}"
    second_voice = log_calls[1]
    match = re.search(r"\b3\b", second_voice)
    assert match is not None, (
        f"текст второго голоса ОБЯЗАН называть 3 (подавления именно нашего ключа): {second_voice!r}"
    )

    counter_after = voice_counters().get("windowed_suppressed", 0)
    process_wide_delta = counter_after - counter_before

    # Точное число сверки НЕ гарантируется (счётчик общий на весь процесс,
    # другие тесты сессии могли его тоже тронуть) — но конкретно наши 8
    # событий (3+5) обязаны попасть в дельту, и дельта в общем случае НЕ равна
    # 3. Явная проверка: дельта >= 8 (наш вклад пришёл), но "3" достаётся
    # ТОЛЬКО из текста, не из этого числа.
    assert process_wide_delta >= 8, (
        f"процессный счётчик обязан отразить оба потока подавлений (3+5=8), дельта {process_wide_delta} — "
        "если он меньше, сам механизм воспроизведения сломан, а не то, что тестируется"
    )
    assert process_wide_delta != 3, (
        "процессный счётчик СЛУЧАЙНО совпал с числом подавлений нашего ключа (3) — "
        "переприду тест с другим числом шумовых подавлений, чтобы разница была видна"
    )


# ---------------------------------------------------------------------------
# Критерий 4 — HealthState не держит собственного состояния окна
# ---------------------------------------------------------------------------


def test_health_state_does_not_own_default_throttle_constant() -> None:
    """Модуль state.py не имеет права публиковать DEFAULT_THROTTLE после правки.

    Сегодня — держит (см. ``multiprocess_framework/modules/process_module/health/state.py``),
    это и есть цель критерия 4: окно — общий механизм (``windowed_voice``), а не
    личная константа HealthState.
    """
    from ..health import state as state_module

    assert not hasattr(state_module, "DEFAULT_THROTTLE"), (
        "HealthState.state module ещё публикует DEFAULT_THROTTLE — собственное окно "
        "не выведено в общий механизм (windowed_voice.default_window_sec/process_voices)"
    )


def test_health_state_instance_does_not_carry_last_log_ts() -> None:
    """Инстанс HealthState не держит ``_last_log_ts`` — своей карты дросселя нет.

    Гоняем report_error дважды по одному ключу (ровно тот путь, что наполнял
    ``_last_log_ts`` раньше), затем смотрим на __dict__ инстанса.
    """
    state, _track_calls, _log_calls = _make_state()
    for _ in range(2):
        try:
            raise _Boom("boom")
        except _Boom as exc:
            state.report_error(exc, context="criterion4_no_own_state")

    assert "_last_log_ts" not in state.__dict__, (
        f"HealthState завёл собственную карту дросселя _last_log_ts: {state.__dict__.keys()} — "
        "окно обязано жить в общем держателе (windowed_voice.WindowedVoices), не в HealthState"
    )


# ---------------------------------------------------------------------------
# Критерий 5 — один инцидент = одна строка в сторе наблюдаемости
# ---------------------------------------------------------------------------


def _manager_config(tmp_path: Path, app: str) -> dict:
    return {
        "app_name": app,
        "log_directory": str(tmp_path),
        "enable_batching": False,
        "modules": {},
        "channels": {"a": {"type": "file", "enabled": True, "file_path": str(tmp_path / f"{app}.log")}},
        "scopes": {
            "SYSTEM": {"channels": ["a"]},
            "BUSINESS": {"channels": ["a"]},
            "DEBUG": {"channels": ["a"]},
        },
    }


@pytest.fixture
def real_process_with_store(tmp_path: Path):
    """Настоящие LoggerManager + ErrorManager + ProcessModule + ObservabilityStore.

    Тот же харнес, что ``test_incident_pair_carries_source.py`` использует для
    живой пары (``process_with_both_planes``), но со store-tap'ами на ОБА
    менеджера (``wire_observability_store``) — это и есть персистентный
    ObservabilityStore из критерия 5, а не live-хвост через router.
    """
    from ...error_module.core.error_manager import ErrorManager
    from ...logger_module.core.logger_manager import LoggerManager
    from ..core.process_module import ProcessModule
    from ..managers.observability_wiring import unwire_observability_store, wire_observability_store

    logger = LoggerManager(manager_name="AccLog", config=_manager_config(tmp_path, "acc_log"))
    logger.initialize()
    errors = ErrorManager(manager_name="AccErr", config=_manager_config(tmp_path, "acc_err"))
    errors.initialize()

    process = ProcessModule("camera_0")
    process.router_manager = Mock()
    process.logger_manager = logger
    process.error_manager = errors
    process._observability_hub = Mock()
    process.register_manager("logger", logger, enabled=True)
    process.register_manager("error", errors, enabled=True)

    db_path = str(tmp_path / "store.sqlite3")
    store, taps = wire_observability_store(
        error_manager=errors, logger_manager=logger, db_path=db_path, process="camera_0", min_level="INFO"
    )

    try:
        yield process, store
    finally:
        unwire_observability_store(store, taps)
        logger.shutdown()
        errors.shutdown()


def test_one_incident_gives_exactly_one_observability_store_row(real_process_with_store) -> None:
    """Один вызов report_error → РОВНО одна строка в персистентном сторе.

    Живой прогон харнеса ДО правки (репро тестера) даёт ДВЕ строки:
    kind='error' (через _safe_track → ErrorManager.track_error) и
    kind='log'/severity='warning' (через _safe_log → LoggerManager.warning) —
    дубль путей, который критерий 5 запрещает.
    """
    from ..health import HealthSelfTestError, get_or_create_health_state

    process, store = real_process_with_store
    state = get_or_create_health_state(process)

    state.report_error(HealthSelfTestError("single-incident"), context="grab_frame")

    store.flush_writers()  # Task 3.3: очередь store-tap'а дожать ДО чтения (write() больше не синхронна)
    rows = store.list_records(limit=100)
    assert len(rows) == 1, (
        f"один инцидент обязан дать ОДНУ строку в сторе, получено {len(rows)}: "
        f"{[(r.get('kind'), r.get('severity'), r.get('message')) for r in rows]}"
    )


def test_the_surviving_store_row_carries_the_error_manager_origin_marker(real_process_with_store) -> None:
    """Запись, дошедшая через плоскость ошибок, несёт ``origin=error_manager`` в extra.

    Маркер сегодня не существует нигде в коде (`grep -rn "origin.*error_manager"`
    — ноль совпадений на момент захода тестера), поэтому тест красный по
    отсутствию маркера, а не только по числу строк.
    """
    from ..health import HealthSelfTestError, get_or_create_health_state

    process, store = real_process_with_store
    state = get_or_create_health_state(process)

    state.report_error(HealthSelfTestError("single-incident"), context="grab_frame")

    store.flush_writers()  # Task 3.3: очередь store-tap'а дожать ДО чтения (write() больше не синхронна)
    rows = store.list_records(limit=100)
    markers = [(r.get("extra") or {}).get("origin") for r in rows]
    assert "error_manager" in markers, (
        f"ни одна запись не несёт origin=error_manager — маркер отсутствует: extra по строкам: "
        f"{[r.get('extra') for r in rows]}"
    )
