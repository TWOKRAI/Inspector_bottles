# -*- coding: utf-8 -*-
"""Окно голоса на ключ: **факт учитывается всегда, строка в журнал — не чаще окна**.

Задача Ф1.4 плана ``observability-closure`` (находки M17, m2). До неё окно
журнала было переписано вручную минимум семь раз (по одному состоянию
``_last_log``/``_suppressed`` на файл), и каждая копия решала одну и ту же
задачу чуть-чуть по-своему: где-то троттлилась только запись, где-то вместе с
ней исчезал и учёт.

## Два обязательства, разделённые НАМЕРЕННО

Главное решение этого модуля — :meth:`WindowedVoices.take` возвращает
**решение**, а не совершает запись:

* **факт** — счётчик, запись в плоскость ошибок, инкремент статистики — остаётся
  на вызывающем и учитывается ВСЕГДА, окно его не касается;
* **голос** — строка в журнал — выпускается не чаще окна, и следующий голос
  называет, сколько событий было подавлено с прошлой записи.

Склеивать их в один вызов нельзя, и это не вкусовщина. Живой контрпример —
``process_module/health/state.py:290``: там ``_safe_track`` (запись в плоскость
ошибок с трассой и контекстом) стоит ВНУТРИ ``if should_log:``, потому что
своего окна у плоскости ошибок нет и был взят чужой — от журнала. Итог: повтор
в окне 5 с не оставляет в плоскости ошибок ничего, кроме числа. Тот, кто будет
чинить это место (Task 1.3), обязан иметь возможность написать

    voice, suppressed = self.should_voice(f"{type(exc).__name__}|{context}")
    self._safe_track(exc, ctx, fields)          # ← факт: ВСЕГДА
    if voice:                                    # ← голос: по окну
        self._log_error(text, suppressed=suppressed)

а не наследовать общий дроссель. :func:`log_windowed` — удобство для частого
случая «нужен только голос», а не единственная дверь.

## Ключи и память

Состояние живёт по ключу, ключи разных источников независимы. Карта ключей
ограничена (:data:`MAX_TRACKED_KEYS`): ключ с именем процесса или причины —
величина неограниченного алфавита, и «окно на ключ» без потолка стало бы утечкой
на ключах, которых больше никогда не будет. Подметание — сначала протухшие
(давно не голосившие И без накопленных подавлений), потом, если и это не
помогло, самые старые; выброс НЕ молчит — он растит ``windowed_keys_evicted``.

## Дисциплина лока

Решение и обнуление счётчика подавленных берутся под ОДНИМ локом (иначе число
в тексте отстаёт от своего момента — урок ``RouterManager._report_send_error``,
комментарий «Ф6.х.7б»). Сама запись в журнал делается ВНЕ лока: обработчик
записи имеет право позвать ``log_windowed`` повторно, и удержание лока на время
эмиссии превратило бы реентрантность в дедлок.
"""

from __future__ import annotations

import logging
import threading
import time
from typing import Any, Dict, List, Optional, Tuple

#: Дефолт окна, если политика процесса не задана конфигом.
#: Совпадает с величиной, до которой независимо сошлись все семь ручных копий
#: (``_SEND_ERROR_LOG_INTERVAL_SEC``, ``_NEVER_DROP_LOSS_LOG_INTERVAL_SEC``,
#: ``_system_evict_log_window``, ``_data_evict_log_window``,
#: ``_queue_missing_log_window``, ``HealthState.DEFAULT_THROTTLE``).
DEFAULT_WINDOW_SEC: float = 5.0

#: Сколько повторов ПОДРЯД по одному ключу терпится до эскалации INFO → WARNING.
#: Строго «больше порога»: N=3 означает, что четвёртый подряд говорит громко.
DEFAULT_ESCALATE_AFTER_REPEATS: int = 3

#: Потолок карты ключей на один держатель окон.
MAX_TRACKED_KEYS: int = 512

#: Во сколько окон молчания ключ считается протухшим и подметается.
_STALE_WINDOWS: int = 10

_policy_lock = threading.Lock()
_policy: Dict[str, Any] = {
    "window_sec": DEFAULT_WINDOW_SEC,
    "escalate_after_repeats": DEFAULT_ESCALATE_AFTER_REPEATS,
}

_totals_lock = threading.Lock()
_totals: Dict[str, int] = {"windowed_suppressed": 0, "windowed_keys_evicted": 0}


# ---------------------------------------------------------------------------
# Политика процесса (окно из конфига, а не из литерала)
# ---------------------------------------------------------------------------


def default_window_sec() -> float:
    """Действующее окно процесса, сек (``observability.voices.default_window_sec``)."""
    with _policy_lock:
        return float(_policy["window_sec"])


def escalate_after_repeats() -> int:
    """Порог эскалации повторов процесса (``observability.voices.escalate_after_repeats``)."""
    with _policy_lock:
        return int(_policy["escalate_after_repeats"])


def set_voices_policy(
    *,
    window_sec: Optional[float] = None,
    escalate_after: Optional[int] = None,
) -> Dict[str, Any]:
    """Задать политику голосов процесса. Возвращает применённый снимок.

    Зовётся сшивкой процесса (``wire_voices_policy`` на старте,
    ``apply_voices_policy`` на пересборке) — ровно тем же способом, каким
    в секцию наблюдаемости уже заведены ``documents``/``events``/``flight``:
    это не параметр менеджера, а политика, которую читает живой механизм.

    ``None`` означает «не трогать эту ось», а не «сбросить в дефолт»: молчание
    слоя не имеет права стирать заданное (правило Г3 этого проекта).
    """
    with _policy_lock:
        if window_sec is not None:
            _policy["window_sec"] = float(window_sec)
        if escalate_after is not None:
            _policy["escalate_after_repeats"] = int(escalate_after)
        return dict(_policy)


def reset_voices_policy() -> None:
    """Вернуть политику к встроенным дефолтам (фикстуры тестов)."""
    with _policy_lock:
        _policy["window_sec"] = DEFAULT_WINDOW_SEC
        _policy["escalate_after_repeats"] = DEFAULT_ESCALATE_AFTER_REPEATS


# ---------------------------------------------------------------------------
# Процессные счётчики (readback наблюдаемости)
# ---------------------------------------------------------------------------


def voice_counters() -> Dict[str, int]:
    """Счётчики механизма для ``get_stats()`` плоскости логов.

    Величины ПРОЦЕССНЫЕ, а не пер-менеджерные, и это сознательно: держателей окон
    в процессе много (роутер, реестр очередей, менеджер процессов), а плоскостей
    наблюдаемости, чей ``get_stats()`` уезжает в readback, — три. Пер-менеджерное
    число не доехало бы наружу ни от одного из настоящих потребителей.
    """
    with _totals_lock:
        return dict(_totals)


def reset_voice_counters() -> None:
    """Обнулить процессные счётчики (фикстуры тестов)."""
    with _totals_lock:
        for key in _totals:
            _totals[key] = 0


def _bump(key: str, value: int = 1) -> None:
    if value <= 0:
        return
    with _totals_lock:
        _totals[key] = _totals.get(key, 0) + value


# ---------------------------------------------------------------------------
# Держатель окон
# ---------------------------------------------------------------------------


class WindowedVoices:
    """Состояние окон по ключу. Потокобезопасен, не пиклится (держит лок)."""

    __slots__ = ("_lock", "_state", "_repeats")

    def __init__(self) -> None:
        self._lock = threading.Lock()
        # key -> [последний голос (monotonic), подавлено с него, окно этого ключа]
        self._state: Dict[str, List[float]] = {}
        # key -> сколько раз подряд событие повторилось (ось эскалации, без времени)
        self._repeats: Dict[str, int] = {}

    # -- окно ---------------------------------------------------------------

    def take(self, key: str, interval: Optional[float] = None) -> Tuple[bool, int]:
        """Решение о голосе по ключу. **Ничего не пишет и ничего не считает за вызывающего.**

        Args:
            key: адрес события. Разные ключи независимы.
            interval: окно, сек. ``None`` → политика процесса.

        Returns:
            ``(голосить?, подавлено_с_прошлой_записи)``. Первый вызов с новым
            ключом всегда даёт ``(True, 0)``. Внутри окна — ``(False, N)``, где
            ``N`` — сколько уже накоплено (число возвращается и на подавлении:
            вызывающему бывает нужно решить, не пора ли сказать иначе).
        """
        window = default_window_sec() if interval is None else float(interval)
        now = time.monotonic()
        evicted = 0
        with self._lock:
            entry = self._state.get(key)
            if entry is not None and (now - entry[0]) < window:
                entry[1] += 1
                suppressed = int(entry[1])
                voiced = False
            else:
                suppressed = int(entry[1]) if entry is not None else 0
                self._state[key] = [now, 0, window]
                voiced = True
                if len(self._state) > MAX_TRACKED_KEYS:
                    evicted = self._sweep_locked(now)
        # Инкременты процессных счётчиков — ВНЕ своего лока (порядок захвата
        # всегда «сначала лок держателя, потом лок счётчиков», обратного нет).
        if not voiced:
            _bump("windowed_suppressed", 1)
        _bump("windowed_keys_evicted", evicted)
        return voiced, suppressed

    def _sweep_locked(self, now: float) -> int:
        """Подмести карту ключей. Вызывается под ``self._lock``. Возвращает выброшенные."""
        for key in [k for k, e in self._state.items() if e[1] == 0 and (now - e[0]) > _STALE_WINDOWS * e[2]]:
            del self._state[key]
            self._repeats.pop(key, None)
        if len(self._state) <= MAX_TRACKED_KEYS:
            # Протухшие не считаются выброшенными: у них не было ни одного
            # неназванного подавления, терять было нечего.
            return 0
        # Потолок не взят подметанием — значит ключи горячие, и что-то придётся
        # выбросить. НЕ молчим об этом: иначе «подавлено 0» означало бы то же
        # самое, что «счёт выброшен вместе с ключом».
        #
        # Порядок жертв — сначала БЕЗДОЛЖНИКИ (нечего терять), внутри группы по
        # старшинству. Найдено собственным hazard-тестом: сортировка по одному
        # возрасту выбирает жертвой ровно тот ключ, который дольше всех копил
        # неназванный счёт, — то есть механизм терял в первую очередь самое
        # ценное, что у него было, и делал это тем охотнее, чем дольше жил.
        ordered = sorted(self._state.items(), key=lambda kv: (kv[1][1] > 0, kv[1][0]))
        evicted = 0
        for key, _entry in ordered[: len(self._state) - MAX_TRACKED_KEYS]:
            del self._state[key]
            self._repeats.pop(key, None)
            evicted += 1
        return evicted

    def forget(self, key: str) -> None:
        """Забыть ключ (событие кончилось — следующее заговорит немедленно)."""
        with self._lock:
            self._state.pop(key, None)
            self._repeats.pop(key, None)

    def tracked_keys(self) -> int:
        with self._lock:
            return len(self._state)

    # -- эскалация по повторам ПОДРЯД --------------------------------------

    def note_repeat(self, key: str) -> int:
        """Событие повторилось подряд. Возвращает длину серии (первое = 1)."""
        with self._lock:
            self._repeats[key] = self._repeats.get(key, 0) + 1
            return self._repeats[key]

    def reset_repeat(self, key: str) -> None:
        """Серия прервана (событие не случилось) — следующее начнёт счёт заново."""
        with self._lock:
            self._repeats.pop(key, None)

    def repeats(self, key: str) -> int:
        with self._lock:
            return self._repeats.get(key, 0)


#: Держатель окон «по умолчанию» — на процесс, для вызывающих без своего состояния.
_PROCESS_VOICES = WindowedVoices()


def process_voices() -> WindowedVoices:
    return _PROCESS_VOICES


def reset_process_voices() -> None:
    """Сбросить процессный держатель (фикстуры тестов)."""
    global _PROCESS_VOICES
    _PROCESS_VOICES = WindowedVoices()


# ---------------------------------------------------------------------------
# Удобство: «нужен только голос»
# ---------------------------------------------------------------------------


def compose_voice_text(msg: str, suppressed: int, ctx: Optional[Dict[str, Any]] = None) -> str:
    """Текст голоса: сообщение, контекст, число подавленных с прошлой записи.

    Контекст вклеивается В ТЕКСТ, а не уезжает структурным полем, потому что у
    этой двери приёмник — обычный stdlib-логгер, и структурного места у него нет.
    Дорога через :class:`ObservableMixin` кладёт тот же контекст полями.
    """
    parts: List[str] = [str(msg)]
    if ctx:
        parts.append(" ".join(f"{k}={v}" for k, v in ctx.items()))
    if suppressed:
        parts.append(f"(подавлено с прошлой записи: {suppressed})")
    return " ".join(parts)


def _default_logger() -> Any:
    """Приёмник по умолчанию — ВИД (``get_std_logger``), а не свой stdlib-логгер.

    Правило проекта «один пишущий логгер, остальное — вид поверх» здесь не
    формальность: прямой ``logging.getLogger`` в плоскости наблюдаемости уже
    дважды оказывался МЁРТВЫМ путём — у stdlib-root в процессах фреймворка нет
    ни одного хендлера, и 26 тысяч событий потери дали ноль строк в ``logs/``
    (Ф6.8). Вид связывается с процессным ``LoggerManager`` лениво, на первой
    записи, и потому работает и до его подъёма, и после.

    Страж ``test_plane_has_exactly_two_direct_stdlib_writers`` считает прямых
    писателей по AST и покраснел бы на возврате третьего. Импорт ленивый —
    ``adapters`` тянут ядро, а этот модуль ядром и является.
    """
    from ..adapters.std_facade import get_std_logger

    return get_std_logger(__name__, fallback_name=__name__)


def emit_voice(logger: Any, level: str, text: str) -> None:
    """Позвать у приёмника метод по имени уровня. Приёмник — любой утиный логгер."""
    target = logger if logger is not None else _default_logger()
    method = getattr(target, str(level).lower(), None)
    if callable(method):
        method(text)
        return
    # Утиный приёмник без метода уровня — не повод потерять запись.
    fallback = getattr(target, "log", None)
    if callable(fallback):
        fallback(logging.getLevelName(str(level).upper()), text)


def log_windowed(
    key: str,
    interval: Optional[float],
    level: str,
    msg: str,
    *,
    logger: Any = None,
    voices: Optional[WindowedVoices] = None,
    **ctx: Any,
) -> bool:
    """Сказать вслух не чаще окна ``interval`` на ключ ``key``.

    Удобство поверх :meth:`WindowedVoices.take` для случая, когда голос — это ВСЁ,
    что нужно. Если рядом есть факт (счётчик, запись в плоскость ошибок), зови
    ``take`` напрямую и учитывай факт безусловно.

    Args:
        key: адрес события; разные ключи не мешают друг другу.
        interval: окно, сек; ``None`` → политика процесса.
        level: имя уровня (``"info"`` / ``"warning"`` / ``"error"`` …).
        msg: постоянный текст. Переменную часть клади в ``ctx``, а не в текст —
            иначе ключ дросселя и текст разъедутся (m2: ``trace_id`` в тексте).
        logger: приёмник; ``None`` → stdlib-логгер этого модуля.
        voices: держатель окон; ``None`` → процессный.

    Returns:
        ``True``, если голос прозвучал.
    """
    holder = _PROCESS_VOICES if voices is None else voices
    voiced, suppressed = holder.take(key, interval)
    if not voiced:
        return False
    emit_voice(logger, level, compose_voice_text(msg, suppressed, ctx))
    return True
