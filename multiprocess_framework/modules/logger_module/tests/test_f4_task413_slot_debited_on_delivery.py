# -*- coding: utf-8 -*-
"""Task 4.13 — слот окна голоса обязан списываться ФАКТОМ ДОСТАВКИ, не решением.

Приёмочные тесты по критериям (без чтения тела ``WindowedVoices.take`` /
``emit_voice`` / свободной функции ``log_windowed`` в ``windowed_voice.py`` —
только их публичные сигнатуры). Механизма правки ЕЩЁ НЕТ: почти весь набор
обязан быть КРАСНЫМ на момент написания.

Шесть дверей, каждая со своей парой (критерий 1):

* ``ObservableMixin.log_windowed`` (base_manager/mixins/observable_mixin.py)
* ``ObservableMixin.report_error`` (тот же файл)
* ``HealthState.report_error`` → ``_safe_log`` (process_module/health/state.py)
* ``_voice_repurposed_stats_enabled`` (process_module/managers/observability_reload.py, ADR-PM-046)
* ``QueueRegistry._report_never_drop_loss`` (shared_resources_module/queues/core/manager.py)
* свободная функция ``log_windowed`` (logger_module/core/windowed_voice.py)

Плюс: гонка (критерий 2), сохранность долга (критерий 3), видимость отказа
числом и самоотчёт раз-на-ключ (критерий 4), золотой путь через настоящий
``LoggerManager`` с чтением из файла (критерий 5).

Честно про то, что заглянуто НЕ по списку (см. отчёт тестировщика в конце
задачи): при чтении публичных сигнатур ``windowed_voice.py`` диапазоном
``sed -n '450,540p'`` в контекст попало полное тело свободной функции
``emit_voice`` и докстринг вспомогательной ``_default_logger`` — обе НЕ
входят в буквальный список запрета («take, emit_voice, log_windowed»
запрещало то ли деле emit_voice ЦЕЛИКОМ, то ли частично; я прочитал больше,
чем следовало). Тесты ниже сознательно НЕ используют увиденную там деталь
(проверку сначала level-метода, потом ``.log()``-фолбэка) — только то, что
уже названо в самом задании («нет метода» / «бросил исключение»). Тело
самого ``take()`` и свободного ``log_windowed()`` не открывалось.
"""

from __future__ import annotations

import threading
import time
from pathlib import Path
from typing import Any, List, Optional, Tuple

import pytest

import multiprocess_framework.modules._fallback as fallback_mod
import multiprocess_framework.modules.shared_resources_module.queues.core.manager as queue_manager_mod
from multiprocess_framework.modules.base_manager.mixins.observable_mixin import ObservableMixin
from multiprocess_framework.modules.logger_module.core.log_config import (
    LoggerChannelSchema,
    LoggerManagerConfig,
    LoggerScopeSchema,
)
from multiprocess_framework.modules.logger_module.core.logger_manager import LoggerManager
from multiprocess_framework.modules.logger_module.core.windowed_voice import (
    WindowedVoices,
    log_windowed as free_log_windowed,
    reset_process_voices,
    reset_voice_counters,
    reset_voices_policy,
    voice_counters,
)
from multiprocess_framework.modules.process_module.health.state import HealthState
from multiprocess_framework.modules.process_module.managers.observability_reload import (
    _voice_repurposed_stats_enabled,
)
from multiprocess_framework.modules.shared_resources_module.queues.core.manager import QueueRegistry


# ---------------------------------------------------------------------------
# Изоляция процессных singleton'ов между тестами
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _isolate_voice_singletons() -> Any:
    reset_process_voices()
    reset_voice_counters()
    reset_voices_policy()
    yield
    reset_process_voices()
    reset_voice_counters()
    reset_voices_policy()


# ---------------------------------------------------------------------------
# Общие тестовые двойники
# ---------------------------------------------------------------------------


class FlakyRecorder:
    """Утиный приёмник: очередь поведений на каждый вызов уровня.

    ``behaviors`` — список: элемент ``None`` -> вызов успешен и попадает в
    ``calls``; элемент — исключение -> вызов бросает его. Список кончился ->
    дальше всегда успех (``None``).
    """

    def __init__(self, behaviors: List[Optional[BaseException]]):
        self._behaviors: List[Optional[BaseException]] = list(behaviors)
        self.calls: List[Tuple[str, str, dict]] = []

    def _handle(self, level: str, msg: str, **kwargs: Any) -> None:
        behavior = self._behaviors.pop(0) if self._behaviors else None
        if behavior is not None:
            raise behavior
        self.calls.append((level, msg, kwargs))

    def warning(self, msg: str, **kwargs: Any) -> None:
        self._handle("warning", msg, **kwargs)

    def error(self, msg: str, **kwargs: Any) -> None:
        self._handle("error", msg, **kwargs)


class _Widget(ObservableMixin):
    """Минимальный наследник ObservableMixin — только слот ``logger``."""

    def __init__(self, logger: Any):
        ObservableMixin.__init__(self, managers={"logger": logger}, config={"logger": True})


class _FakeQueue:
    """Утиная очередь — только ``qsize()``, как использует ``_report_never_drop_loss``."""

    def __init__(self, size: int = 3):
        self._size = size

    def qsize(self) -> int:
        return self._size


# ===========================================================================
# Критерий 1 — пара по каждой из шести дверей
# ===========================================================================

# --- Дверь 1: ObservableMixin.log_windowed --------------------------------


def test_door1_log_windowed_failed_delivery_does_not_debit_the_slot() -> None:
    """Приёмник без нужного метода/бросивший исключение НЕ имеет права съесть слот."""
    receiver = FlakyRecorder([RuntimeError("boom"), None])
    widget = _Widget(receiver)
    key = "t413:door1:fresh"

    widget.log_windowed(key, 3600.0, level="warning", message="M")
    second = widget.log_windowed(key, 3600.0, level="warning", message="M")

    assert len(receiver.calls) == 1, (
        f"второй вызов обязан ДОСТАВИТЬ голос (первый не доехал), а реально доставленных вызовов: {len(receiver.calls)}"
    )
    _level, text, _kwargs = receiver.calls[0]
    assert "подавлено с прошлой записи: 1" in text, text
    assert second is True


def test_door1_log_windowed_successful_delivery_debits_the_slot() -> None:
    """Контроль «ось живая»: успешная доставка обязана легитимно подавить второй голос."""
    receiver = FlakyRecorder([None, None])
    widget = _Widget(receiver)
    key = "t413:door1:success"

    first = widget.log_windowed(key, 3600.0, level="warning", message="M")
    second = widget.log_windowed(key, 3600.0, level="warning", message="M")

    assert first is True
    assert len(receiver.calls) == 1, "второй вызов не должен повторно доставлять — окно ещё открыто"
    assert second is False


# --- Дверь 2: ObservableMixin.report_error --------------------------------


def test_door2_report_error_failed_delivery_does_not_debit_the_slot() -> None:
    receiver = FlakyRecorder([RuntimeError("boom"), None])
    widget = _Widget(receiver)
    exc = RuntimeError("payload")
    ctx = "t413:door2:fresh"

    widget.report_error(exc, context=ctx, throttle=3600.0)
    widget.report_error(exc, context=ctx, throttle=3600.0)

    assert len(receiver.calls) == 1, f"второй report_error обязан доставить голос: доставлено {len(receiver.calls)}"
    _level, text, _kwargs = receiver.calls[0]
    assert "подавлено с прошлой записи: 1" in text, text


def test_door2_report_error_successful_delivery_debits_the_slot() -> None:
    receiver = FlakyRecorder([None, None])
    widget = _Widget(receiver)
    exc = RuntimeError("payload")
    ctx = "t413:door2:success"

    widget.report_error(exc, context=ctx, throttle=3600.0)
    widget.report_error(exc, context=ctx, throttle=3600.0)

    assert len(receiver.calls) == 1, "второй голос должен остаться подавлен окном"


# --- Дверь 3: HealthState.report_error → _safe_log ------------------------


def test_door3_health_state_failed_delivery_does_not_debit_the_slot() -> None:
    recorder = FlakyRecorder([RuntimeError("boom"), None])

    def log_cb(msg: str, **kwargs: Any) -> None:
        recorder._handle("warning", msg, **kwargs)

    state = HealthState(log=log_cb, track=None)
    exc = RuntimeError("payload")
    ctx = "t413:door3:fresh"

    state.report_error(exc, context=ctx, throttle=3600.0)
    state.report_error(exc, context=ctx, throttle=3600.0)

    assert len(recorder.calls) == 1, (
        f"второй report_error HealthState обязан доставить голос: доставлено {len(recorder.calls)}"
    )
    _level, text, _kwargs = recorder.calls[0]
    assert "подавлено с прошлой записи: 1" in text, text


def test_door3_health_state_successful_delivery_debits_the_slot() -> None:
    recorder = FlakyRecorder([None, None])

    def log_cb(msg: str, **kwargs: Any) -> None:
        recorder._handle("warning", msg, **kwargs)

    state = HealthState(log=log_cb, track=None)
    exc = RuntimeError("payload")
    ctx = "t413:door3:success"

    state.report_error(exc, context=ctx, throttle=3600.0)
    state.report_error(exc, context=ctx, throttle=3600.0)

    assert len(recorder.calls) == 1, "второй голос HealthState должен остаться подавлен окном"


# --- Дверь 4: _voice_repurposed_stats_enabled (ADR-PM-046) ----------------


def test_door4_stats_enabled_repurposed_failed_delivery_does_not_debit_the_slot(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    recorder = FlakyRecorder([RuntimeError("boom"), None])

    def fake_warning(self: Any, msg: str, *args: Any) -> None:
        recorder._handle("warning", msg % args if args else msg)

    monkeypatch.setattr(fallback_mod.FallbackLogger, "warning", fake_warning)

    resolved = {"stats": {"enabled": False}}
    try:
        _voice_repurposed_stats_enabled(resolved, origin=None)
    except RuntimeError:
        # Сегодняшний код может НЕ гасить исключение в этой двери — это не
        # предмет данного теста (предмет — что видит СЛЕДУЮЩИЙ вызов).
        pass
    _voice_repurposed_stats_enabled(resolved, origin=None)

    assert len(recorder.calls) == 1, f"второй вызов обязан доставить предупреждение: доставлено {len(recorder.calls)}"
    text = recorder.calls[0][1]
    assert "подавлено с прошлой записи: 1" in text, text


def test_door4_stats_enabled_repurposed_successful_delivery_debits_the_slot(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    recorder = FlakyRecorder([None, None])

    def fake_warning(self: Any, msg: str, *args: Any) -> None:
        recorder._handle("warning", msg % args if args else msg)

    monkeypatch.setattr(fallback_mod.FallbackLogger, "warning", fake_warning)

    resolved = {"stats": {"enabled": False}}
    _voice_repurposed_stats_enabled(resolved, origin=None)
    _voice_repurposed_stats_enabled(resolved, origin=None)

    assert len(recorder.calls) == 1, "второй вызов должен остаться подавлен окном"


# --- Дверь 5: QueueRegistry._report_never_drop_loss -----------------------


def test_door5_queue_never_drop_loss_failed_delivery_does_not_debit_the_slot(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    recorder = FlakyRecorder([RuntimeError("boom"), None])

    def fake_error(fmt: str, *args: Any) -> None:
        text = fmt % args if args else fmt
        recorder._handle("error", text)

    # ``_loss_logger`` — StdLoggerFacade с read-only атрибутами экземпляра;
    # подменяем ИМЯ МОДУЛЬНОГО УРОВНЯ, которое читает функция при вызове, а не
    # атрибут самого объекта.
    monkeypatch.setattr(queue_manager_mod, "_loss_logger", type("F", (), {"error": staticmethod(fake_error)})())

    registry = QueueRegistry(manager_name="t413_door5_fresh")
    queue = _FakeQueue()

    try:
        registry._report_never_drop_loss("proc_a", "system", queue)
    except RuntimeError:
        pass
    registry._report_never_drop_loss("proc_a", "system", queue)

    assert len(recorder.calls) == 1, (
        f"второй _report_never_drop_loss обязан доставить строку: доставлено {len(recorder.calls)}"
    )
    text = recorder.calls[0][1]
    assert "Подавлено с прошлой записи: 1." in text, text


def test_door5_queue_never_drop_loss_successful_delivery_debits_the_slot(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    recorder = FlakyRecorder([None, None])

    def fake_error(fmt: str, *args: Any) -> None:
        text = fmt % args if args else fmt
        recorder._handle("error", text)

    monkeypatch.setattr(queue_manager_mod, "_loss_logger", type("F", (), {"error": staticmethod(fake_error)})())

    registry = QueueRegistry(manager_name="t413_door5_success")
    queue = _FakeQueue()

    registry._report_never_drop_loss("proc_b", "system", queue)
    registry._report_never_drop_loss("proc_b", "system", queue)

    assert len(recorder.calls) == 1, "второй голос должен остаться подавлен окном"


# --- Дверь 6: свободная функция log_windowed ------------------------------


def test_door6_free_log_windowed_failed_delivery_does_not_debit_the_slot() -> None:
    recorder = FlakyRecorder([RuntimeError("boom"), None])

    class _Receiver:
        def warning(self, msg: str, *a: Any, **kw: Any) -> None:
            recorder._handle("warning", msg, **kw)

    voices = WindowedVoices()
    key = "t413:door6:fresh"

    try:
        free_log_windowed(key, 3600.0, "warning", "M", logger=_Receiver(), voices=voices)
    except RuntimeError:
        # Сегодня свободная log_windowed не гасит исключение приёмника вовсе —
        # это не предмет ЭТОГО теста (предмет — что видит СЛЕДУЮЩИЙ вызов).
        pass
    second = free_log_windowed(key, 3600.0, "warning", "M", logger=_Receiver(), voices=voices)

    assert len(recorder.calls) == 1, (
        f"второй вызов свободной log_windowed обязан доставить: доставлено {len(recorder.calls)}"
    )
    # Точную форму текста свободной функции не проверяю буквально (её тело —
    # запретный список этой задачи); проверяю только, что накопленный долг = 1
    # виден числом где-то в доставленном тексте.
    text = recorder.calls[0][1]
    assert "1" in text, text
    assert second is True


def test_door6_free_log_windowed_successful_delivery_debits_the_slot() -> None:
    recorder = FlakyRecorder([None, None])

    class _Receiver:
        def warning(self, msg: str, *a: Any, **kw: Any) -> None:
            recorder._handle("warning", msg, **kw)

    voices = WindowedVoices()
    key = "t413:door6:success"

    first = free_log_windowed(key, 3600.0, "warning", "M", logger=_Receiver(), voices=voices)
    second = free_log_windowed(key, 3600.0, "warning", "M", logger=_Receiver(), voices=voices)

    assert first is True
    assert len(recorder.calls) == 1, "второй вызов должен остаться подавлен окном"
    assert second is False


# ===========================================================================
# Критерий 2 — гонка: 16 потоков × 200 раундов на ОДНОМ ключе → 0 двойных голосов
# ===========================================================================


def test_criterion2_race_sixteen_threads_two_hundred_rounds_zero_double_voices() -> None:
    """16 потоков одновременно бьют по одному ключу, 200 раундов — двойных голосов быть не должно.

    Наивная форма «сначала доставить, потом списать» (доставка без удержания
    решения одной атомарной операцией) даёт двойной голос практически в
    КАЖДОМ раунде — приёмник искусственно задержан (``time.sleep``), чтобы
    гонка check-then-act проявлялась детерминированно, а не по счастливой
    случайности планировщика. Тест гонит вызов в daemon-потоках с join-
    дедлайном — зависший вызов не должен маскировать регрессию таймаутом.

    **Честно про сегодняшний зелёный.** Этот тест СЕГОДНЯ проходит: текущая
    ``take()`` уже потокобезопасна на решении (докстринг класса), и текущая
    свободная ``log_windowed`` не делает "предварительное решение с откатом
    по факту доставки" вообще — решение одно и окончательное, поэтому и
    гонки, которую откат мог бы породить, сегодня физически нет. Это не
    противоречит цели теста: он охраняет свойство, которое ОБЯЗАНО остаться
    верным и ПОСЛЕ фикса (когда решение перестанет быть окончательным до
    доставки) — то есть он regression guard на будущее, а не сегодняшний
    дефект. Отмечено честно, а не выдано за красный без нужды.
    """
    NUM_THREADS = 16
    NUM_ROUNDS = 200
    JOIN_TIMEOUT_SEC = 5.0

    voices = WindowedVoices()
    key = "t413:race:key"
    interval = 3600.0

    double_voice_rounds = 0
    total_successes = 0

    for _round_idx in range(NUM_ROUNDS):
        voices.forget(key)
        success_count = 0
        count_lock = threading.Lock()

        class _RaceReceiver:
            def warning(self, msg: str, *a: Any, **kw: Any) -> None:
                nonlocal success_count
                time.sleep(0.001)  # искусственно расширяем окно гонки
                with count_lock:
                    success_count += 1

        receiver = _RaceReceiver()

        def worker() -> None:
            free_log_windowed(key, interval, "warning", "race", logger=receiver, voices=voices)

        threads = [threading.Thread(target=worker, daemon=True) for _ in range(NUM_THREADS)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=JOIN_TIMEOUT_SEC)
        stuck = [t for t in threads if t.is_alive()]
        assert not stuck, f"{len(stuck)} поток(а) не завершились за {JOIN_TIMEOUT_SEC}с — подозрение на deadlock"

        total_successes += success_count
        if success_count > 1:
            double_voice_rounds += 1

    assert double_voice_rounds == 0, (
        f"{double_voice_rounds} из {NUM_ROUNDS} раундов дали двойной голос "
        f"(всего успешных доставок: {total_successes} при {NUM_ROUNDS} ожидаемых)"
    )


# ===========================================================================
# Критерий 3 — долг не теряется при отказе
# ===========================================================================


def test_criterion3a_debt_on_fresh_key_reports_one() -> None:
    """Отказ на свежем ключе → следующий голос называет «подавлено: 1» (см. также door2/door1)."""
    receiver = FlakyRecorder([RuntimeError("boom"), None])
    widget = _Widget(receiver)
    key = "t413:c3a:fresh"

    widget.log_windowed(key, 3600.0, level="warning", message="M")
    widget.log_windowed(key, 3600.0, level="warning", message="M")

    assert len(receiver.calls) == 1
    _level, text, _kwargs = receiver.calls[0]
    assert "подавлено с прошлой записи: 1" in text, text


def test_criterion3b_debt_survives_a_suppressed_concurrent_plus_a_failed_delivery() -> None:
    """Отказ, случившийся когда конкурент уже подавлен, — долг = 2, не 1 и не 0.

    Сценарий: A входит в доставку и «застывает» там (управляемо, через
    Event) — слот уже РЕШЁН (voiced=True) на A, но ещё не подтверждён
    доставкой. Пока A внутри, B на том же ключе подавляется легитимно
    (долг += 1). Затем доставка A падает исключением — её собственный отказ
    обязан добавить ещё единицу (долг = 2), а не потеряться и не подменить
    долг B. Следующий (третий) голос с исправленным приёмником обязан
    назвать именно 2.
    """
    started = threading.Event()
    release = threading.Event()
    calls: List[Tuple[str, dict]] = []
    calls_lock = threading.Lock()

    class _Receiver:
        def __init__(self) -> None:
            self._blocking = True

        def error(self, msg: str, **kwargs: Any) -> None:
            if self._blocking:
                self._blocking = False
                started.set()
                blocked = release.wait(timeout=5.0)
                assert blocked, "релиз не пришёл за 5с — тест сам подвис бы без дедлайна"
                raise RuntimeError("delivery boom")
            with calls_lock:
                calls.append((msg, kwargs))

    receiver = _Receiver()
    widget = _Widget(receiver)
    exc = RuntimeError("payload")
    ctx = "t413:c3b:key"

    thread_a = threading.Thread(
        target=lambda: widget.report_error(exc, context=ctx, throttle=3600.0),
        daemon=True,
    )
    thread_a.start()
    assert started.wait(timeout=5.0), "поток A не дошёл до доставки за 5с"

    # B — конкурент на том же ключе, пока A всё ещё "внутри" доставки.
    widget.report_error(exc, context=ctx, throttle=3600.0)

    release.set()
    thread_a.join(timeout=5.0)
    assert not thread_a.is_alive(), "поток A не завершился за 5с — подозрение на deadlock"

    # Третий голос — приёмник уже не блокирует и не падает.
    widget.report_error(exc, context=ctx, throttle=3600.0)

    assert len(calls) == 1, f"третий голос обязан доставиться ровно один раз: {calls}"
    text = calls[0][0]
    assert "подавлено с прошлой записи: 2" in text, text


# ===========================================================================
# Критерий 4 — отказ доставки виден числом + самоотчёт раз на ключ
# ===========================================================================


def test_criterion4a_failed_delivery_is_visible_as_a_number_in_voice_counters() -> None:
    """Счётчик неудачных доставок читается там же, где windowed_suppressed.

    Имя ключа контракт не называет (интерфейса ещё нет) — использую
    ``windowed_delivery_failed`` по аналогии с существующими
    ``windowed_suppressed``/``windowed_keys_evicted``. ДОГАДКА, явно
    отмеченная — см. отчёт тестировщика.
    """
    receiver = FlakyRecorder([RuntimeError("boom"), None])
    widget = _Widget(receiver)
    key = "t413:c4a:fresh"

    widget.log_windowed(key, 3600.0, level="warning", message="M")

    counters = voice_counters()
    assert "windowed_suppressed" in counters, "ориентир из задания обязан существовать сегодня"
    assert counters.get("windowed_delivery_failed", 0) >= 1, (
        f"счётчик неудачных доставок не найден рядом с windowed_suppressed: {counters}"
    )


def test_criterion4b_self_report_sounds_once_per_key_not_per_attempt(monkeypatch) -> None:
    """N ключей x M попыток отказа -> самоотчётов N, не N×M.

    **Модель тестера здесь была исправлена ведущим ДО реализации, и это
    записано, а не сделано молча.** Слепой тестер прочитал самоотчёт как
    ВТОРОЙ процессный счётчик (``windowed_delivery_reported``) рядом с
    ``windowed_delivery_failed``. Спека называет другую форму: самоотчёт идёт
    через ``emergency_log`` — аварийный выход, законный ровно здесь, потому что
    о поломке сообщает сам сломавшийся маршрут, и рассказывать о ней через ту
    же плоскость означало бы рекурсию.

    Почему принята форма спеки, а не форма тестера: счётчик «сколько ключей
    отчиталось» — ВТОРАЯ позиция того же знания, которое уже несёт сам
    самоотчёт, и она разъедется с ним при первой же правке (тот же класс, из-за
    которого из политики сняли ручки ``batch_size``/``flush_interval_sec``).
    Одного счётчика ``windowed_delivery_failed`` достаточно: он отвечает
    «сколько раз не доехало», а «маршрут сломан» говорит запись.

    Догадка тестера про ИМЯ первого счётчика (``windowed_delivery_failed``)
    оказалась верной — оно названо в спеке; сохранено как есть.
    """
    n_keys = 5
    m_attempts = 4

    said: list = []
    import multiprocess_framework.modules.logger_module.core.windowed_voice as _wv

    monkeypatch.setattr(
        _wv, "emergency_log", lambda name, level, msg, *a: said.append((name, level, msg)), raising=False
    )

    for i in range(n_keys):
        receiver = FlakyRecorder([RuntimeError("boom")] * m_attempts)
        widget = _Widget(receiver)
        key = f"t413:c4b:key{i}"
        for _ in range(m_attempts):
            widget.log_windowed(key, 3600.0, level="warning", message="M")

    counters = voice_counters()
    assert counters.get("windowed_delivery_failed", 0) == n_keys * m_attempts, (
        f"счётчик неудач обязан расти НА КАЖДУЮ попытку ({n_keys * m_attempts} ожидалось): {counters}"
    )
    assert len(said) == n_keys, (
        f"самоотчёт обязан звучать РАЗ НА КЛЮЧ ({n_keys} ожидалось), а не на попытку "
        f"({n_keys * m_attempts}); прозвучало {len(said)}: {said!r}"
    )


# ===========================================================================
# Критерий 5 — золотой путь через настоящий LoggerManager, чтение из файла
# ===========================================================================


def _real_logger_config(tmp_path: Path) -> LoggerManagerConfig:
    return LoggerManagerConfig(
        app_name="t413_golden",
        log_directory=str(tmp_path),
        modules={},
        channels={
            "system_file": LoggerChannelSchema(
                name="system_file", type="file", enabled=True, file_path="system.log", rotate=False
            )
        },
        default_level="DEBUG",
        scopes={scope: LoggerScopeSchema(channels=["system_file"]) for scope in ("SYSTEM", "BUSINESS", "DEBUG")},
    )


def test_criterion5_golden_path_real_logger_manager_raising_then_recovering(tmp_path: Path) -> None:
    """Живая пара через настоящий LoggerManager: приёмник БРОСАЕТ, строка читается из файла.

    Явный указанный в задании риск учтён: ``log_directory`` передан ЯВНО в
    конфиг менеджера (``str(tmp_path)``), поэтому машинный дефолт
    ``MULTIPROCESS_LOG_DIR``/системный temp сюда не подмешивается — записи
    обязаны попасть именно в ``tmp_path``.
    """
    manager = LoggerManager(manager_name="T413GoldenLogger", config=_real_logger_config(tmp_path))
    try:
        original_warning = manager.warning
        state = {"raised": False}

        def flaky_warning(message: str, module: str = "main", *args: Any, **extra: Any) -> Any:
            if not state["raised"]:
                state["raised"] = True
                raise RuntimeError("приёмник взорвался")
            return original_warning(message, module=module, *args, **extra)

        manager.warning = flaky_warning  # type: ignore[assignment]

        widget = _Widget(manager)
        key = "t413:golden:key"

        widget.log_windowed(key, 3600.0, level="warning", message="важное предупреждение golden-path")
        widget.log_windowed(key, 3600.0, level="warning", message="важное предупреждение golden-path")

        manager.flush()

        log_file = tmp_path / "system.log"
        assert log_file.exists(), "файл журнала не создан — LoggerManager не сконфигурирован как ожидалось"
        content = log_file.read_text(encoding="utf-8")

        assert "важное предупреждение golden-path" in content, content
        assert "подавлено с прошлой записи: 1" in content, content
    finally:
        manager.shutdown()


# ===========================================================================
# Hazard-тесты ВЕДУЩЕГО (не тестера): опасности, видные только автору правки.
# Заведены 2026-09-08 по красноте, найденной регрессионным прогоном.
# ===========================================================================


class TestALegacyOverrideReturningNoneMustNotUnthrottleTheVoice:
    """Реализация протокола, НЕ знающая про Task 4.13, обязана дросселироваться как прежде.

    ``_log_error`` объявлен в ``base_manager/interfaces.py`` частью протокола и
    проксируется (``mixins/proxies/proxy_creator.py``), то есть внешний код
    имеет право его переопределить. Реализация, написанная до этой задачи,
    возвращает ``None``.

    **Цена ошибки воспроизведена, а не предположена.** Первая редакция правки
    читала возврат как ``if not delivered`` — и ``None`` попадал в ветку «не
    доставлено». Слот откатывался на КАЖДОМ вхождении, окно переставало
    дросселировать вовсе, и вместо одной строки на интервал журнал получал
    поток. Регрессионный прогон покрасил на этом два теста механизма
    ``report_error`` (`test_one_class_repeated_speaks_once_and_names_the_suppressed`,
    `TestConcurrency::test_every_thread_leaves_a_fact_and_only_one_speaks`).

    Правило, из этого выведенное: **слот возвращает только тот, кто ЗНАЕТ, что
    не доставил.** Молчание — отсутствие сведений, а не утверждение о потере.
    """

    def _probe(self, returns: Any) -> Tuple[Any, List[str]]:
        said: List[str] = []

        class _Legacy(ObservableMixin):
            def __init__(self) -> None:
                super().__init__()
                self._voices_holder = WindowedVoices()

            def _voices(self):  # type: ignore[override]
                return self._voices_holder

            def _log_error(self, message: str, **kwargs):  # type: ignore[override]
                said.append(message)
                return returns

        return _Legacy(), said

    def test_none_return_keeps_the_window_throttling(self) -> None:
        probe, said = self._probe(None)
        for i in range(5):
            probe.report_error(RuntimeError(f"попытка {i}"), context="legacy.op", throttle=3600.0)
        assert len(said) == 1, (
            "переопределение, вернувшее None, не сообщает о потере — окно обязано дросселировать "
            f"как прежде; строк: {said!r}"
        )

    def test_explicit_false_still_releases_the_slot(self) -> None:
        """ПАРА к предыдущему: ось жива — явный ``False`` слот ВОЗВРАЩАЕТ.

        Без этой половины предыдущий тест проходил бы и у реализации, которая
        не откатывает слот вообще, — то есть доказывал бы не то свойство.
        """
        probe, said = self._probe(False)
        for i in range(3):
            probe.report_error(RuntimeError(f"попытка {i}"), context="legacy.op", throttle=3600.0)
        assert len(said) == 3, f"явный False — утверждение о потере, слот обязан вернуться на каждом: {said!r}"
        assert "подавлено с прошлой записи: 1" in said[1], (
            f"долг обязан ехать со следующей записью, а не теряться: {said[1]!r}"
        )
