# -*- coding: utf-8 -*-
"""Кольцо кадров по времени в RAM: вытеснение по секундам и байтам, доступ по времени, разрывы seq.

Purpose: хранить сжатые кадры (payload — непрозрачные bytes) за последние `buffer_seconds` секунд
под жёстким общим потолком `max_bytes`; отдавать кадр «на момент t» (`at`), диапазон и разрывы
(`range`), счётчики (`stats`). Один писатель, читатели под замком; JPEG кольцо не декодирует.

Порядок кольца — пара `(capture_ns, seq)`. Вытеснение считает секунды, не штуки: на 25 Гц и на
11,7 Гц кольцо держит одно и то же время. Закрепление, поиск по группе и экспорт — блок «T9b» ниже.
"""

from __future__ import annotations

import operator
import threading
from bisect import bisect_left, bisect_right
from collections import deque
from itertools import islice
from operator import itemgetter
from typing import NamedTuple

from Services.frame_buffer.segment import build_segment

__all__ = ["TimeRing"]

# Биты flags 0 и 1 зарезервированы форматом сегмента (has_device_frame_num, has_group_id);
# пользовательские флаги занимают биты 2..31.
_RESERVED_FLAG_BITS = 0b11
_FLAGS_MAX = 0xFFFFFFFF
_I64_MIN, _I64_MAX = -(2**63), 2**63 - 1  # поля записи индекса capture_ns, seq, device_frame_num, group_id — i64
_NS_PER_S = 1_000_000_000

_NEAREST, _PREV, _NEXT = "nearest", "prev", "next"
_MODES = (_NEAREST, _PREV, _NEXT)

_by_capture_ns = itemgetter(0)


class _Frame(NamedTuple):
    """Запись кольца; неизменяема, поэтому читатель, взявший ссылку, не видит «рваный» кадр."""

    capture_ns: int
    seq: int
    capture_ts: float
    payload: bytes
    device_frame_num: int | None
    group_id: int | None
    flags: int


def _as_i64(value: object) -> int | None:
    """Целое в диапазоне i64 (numpy-целые приводятся к int); не целое, bool и выход за диапазон — None."""
    if isinstance(value, bool):
        return None
    try:
        number = operator.index(value)
    except TypeError:
        return None
    return number if _I64_MIN <= number <= _I64_MAX else None


def _frame_dict(frame: _Frame) -> dict:
    """Кадр в виде dict с ключами at(); payload отдаётся без копии."""
    return {
        "payload": frame.payload,
        "capture_ns": frame.capture_ns,
        "capture_ts": frame.capture_ts,
        "seq": frame.seq,
        "device_frame_num": frame.device_frame_num,
        "group_id": frame.group_id,
        "flags": frame.flags,
    }


class TimeRing:
    """Кольцо кадров по времени. Один писатель (`append`), читатели — под общим замком."""

    def __init__(self, buffer_seconds: float, max_bytes: int, pin_max_bytes: int) -> None:
        """Без значений по умолчанию: числа ждут замера настоящих кадров (У5).

        Raises:
            ValueError: нечисловой или неположительный размер буфера; `pin_max_bytes` вне
                `0..max_bytes`. Текст исключения не содержит значений входа.
        """
        if not buffer_seconds > 0 or max_bytes <= 0:
            raise ValueError("buffer_seconds и max_bytes должны быть положительными")
        if pin_max_bytes < 0 or pin_max_bytes > max_bytes:
            raise ValueError("pin_max_bytes должен лежать в диапазоне 0..max_bytes")
        self._buffer_ns = int(round(buffer_seconds * _NS_PER_S))
        self._max_bytes = max_bytes
        self._pin_max_bytes = pin_max_bytes
        self._lock = threading.Lock()
        self._frames: deque[_Frame] = deque()
        self._gaps: list[dict] = []
        self._pins: dict[object, tuple[int, int]] = {}  # tag -> (t0, t1); порядок вставки = порядок вызова pin
        self._bytes_held = 0
        self._pinned_held = 0  # байты кадров кольца, лежащих под живыми пинами (счётчик, не скан)
        self._last_pair: tuple[int, int] | None = None  # (capture_ns, seq) последнего ПРИНЯТОГО кадра
        self._counters = {
            "bytes_held_peak": 0,
            "evicted_by_time": 0,
            "evicted_by_bytes": 0,
            "rejected_order": 0,
            "rejected_oversize": 0,
            "pins_released": 0,
        }

    # ------------------------------------------------------------------ запись

    def append(
        self,
        capture_ns: int,
        capture_ts: float,
        payload: bytes,
        seq: int,
        device_frame_num: int | None = None,
        group_id: int | None = None,
        flags: int = 0,
    ) -> None:
        """Принять кадр. Порядок: отказы -> бюджет пинов -> вытеснение по времени -> по байтам
        (до вставки, кольцо не превышает `max_bytes` ни на миг) -> вставка -> пик.

        Raises:
            ValueError: `flags` занимает зарезервированные биты 0/1 или не помещается в u32;
                `capture_ns`, `seq`, `device_frame_num`, `group_id` вне i64 (два последних — если
                не `None`); `capture_ts` не число (число приводится к float). Текст константный, без
                значения входа; кольцо и счётчики при отказе не меняются.
        """
        if flags & _RESERVED_FLAG_BITS or not 0 <= flags <= _FLAGS_MAX:
            raise ValueError("flags: биты 0 и 1 зарезервированы, допустимы биты 2..31")
        capture_ns, seq = _as_i64(capture_ns), _as_i64(seq)
        if capture_ns is None or seq is None:
            raise ValueError("capture_ns и seq должны быть целыми в диапазоне i64")
        if (device_frame_num is not None and (device_frame_num := _as_i64(device_frame_num)) is None) or (
            group_id is not None and (group_id := _as_i64(group_id)) is None
        ):
            raise ValueError("device_frame_num и group_id: None или целое в диапазоне i64")
        if isinstance(capture_ts, bool) or not isinstance(capture_ts, (int, float)):
            raise ValueError("capture_ts должен быть числом")
        try:
            capture_ts = float(capture_ts)
        except OverflowError:
            raise ValueError("capture_ts должен быть числом") from None
        if type(payload) is not bytes:
            payload = bytes(payload)
        size = len(payload)
        pair = (capture_ns, seq)
        with self._lock:
            if self._last_pair is not None and pair <= self._last_pair:
                self._counters["rejected_order"] += 1
                return
            if size > self._max_bytes:
                self._counters["rejected_oversize"] += 1
                return
            self._release_pins_over_budget(capture_ns, size)
            self._evict_by_time(capture_ns)
            self._evict_by_bytes(size)
            self._record_gap(capture_ns, seq)
            self._frames.append(_Frame(capture_ns, seq, capture_ts, payload, device_frame_num, group_id, flags))
            self._bytes_held += size
            if self._pins and self._is_pinned(capture_ns):
                self._pinned_held += size
            self._last_pair = pair
            if self._bytes_held > self._counters["bytes_held_peak"]:
                self._counters["bytes_held_peak"] = self._bytes_held
            self._drop_stale_gaps()

    def _record_gap(self, capture_ns: int, seq: int) -> None:
        """Разрыв seq относительно последнего принятого кадра; seq не растёт — рестарт камеры."""
        if self._last_pair is None:
            return
        last_seq = self._last_pair[1]
        if seq == last_seq + 1:
            return
        restart = seq <= last_seq
        self._gaps.append(
            {
                "after_seq": last_seq,
                "before_seq": seq,
                "missed": 0 if restart else seq - last_seq - 1,
                "capture_ns": capture_ns,
                "restart": restart,
            }
        )

    def _drop_stale_gaps(self) -> None:
        """Разрыв живёт, пока его capture_ns не СТРОГО меньше capture_ns самого старого кадра."""
        if self._gaps:
            oldest = self._frames[0].capture_ns
            self._gaps = [gap for gap in self._gaps if gap["capture_ns"] >= oldest]

    def _evict_by_time(self, newest_ns: int) -> None:
        """Вытеснить незакреплённые кадры строго старше `newest - buffer` (граница включающая)."""
        cutoff = newest_ns - self._buffer_ns
        frames = self._frames
        i = 0
        while i < len(frames) and frames[i].capture_ns < cutoff:
            if self._is_pinned(frames[i].capture_ns):
                i += 1
                continue
            self._bytes_held -= len(frames[i].payload)
            del frames[i]
            self._counters["evicted_by_time"] += 1

    def _evict_by_bytes(self, need: int) -> None:
        """Освободить место под `need` байт: самый старый незакреплённый кадр; если все закреплены —
        освободить самый старый пин (условие 2 бюджета)."""
        frames = self._frames
        while self._bytes_held + need > self._max_bytes:
            victim = next((i for i, f in enumerate(frames) if not self._is_pinned(f.capture_ns)), None)
            if victim is not None:
                self._bytes_held -= len(frames[victim].payload)
                del frames[victim]
                self._counters["evicted_by_bytes"] += 1
            elif self._pins:
                self._release_oldest_pin()
            else:  # недостижимо: need <= max_bytes, а пустое кольцо вмещает его
                break

    # ------------------------------------------------------------------ чтение

    def at(self, t_ns: int, mode: str = _NEAREST) -> dict | None:
        """Кадр «на момент t»: `prev` — последний с capture_ns <= t, `next` — первый с capture_ns >= t,
        `nearest` — ближайший из них по |Δ| (при равенстве — prev). Нет кадра -> None.

        Raises:
            ValueError: неизвестный режим.
        """
        if mode not in _MODES:
            raise ValueError("mode должен быть nearest, prev или next")
        with self._lock:
            frames = self._frames
            lo = bisect_right(frames, t_ns, key=_by_capture_ns)  # frames[:lo] — capture_ns <= t
            hi = bisect_left(frames, t_ns, key=_by_capture_ns)  # frames[hi:] — capture_ns >= t
            prev_frame = frames[lo - 1] if lo > 0 else None
            next_frame = frames[hi] if hi < len(frames) else None
        if mode == _PREV:
            found = prev_frame
        elif mode == _NEXT:
            found = next_frame
        elif prev_frame is None:
            found = next_frame
        elif next_frame is None or t_ns - prev_frame.capture_ns <= next_frame.capture_ns - t_ns:
            found = prev_frame
        else:
            found = next_frame
        return None if found is None else _frame_dict(found)

    def range(self) -> dict:
        """`{"t_min_ns", "t_max_ns", "frames", "gaps"}`; пустое кольцо — `None`, `None`, 0, `[]`."""
        with self._lock:
            if not self._frames:
                return {"t_min_ns": None, "t_max_ns": None, "frames": 0, "gaps": []}
            return {
                "t_min_ns": self._frames[0].capture_ns,
                "t_max_ns": self._frames[-1].capture_ns,
                "frames": len(self._frames),
                "gaps": [dict(gap) for gap in self._gaps],
            }

    def stats(self) -> dict:
        """Число кадров и счётчики одним снимком (ключи — в README)."""
        with self._lock:
            frames = self._frames
            span_s = (frames[-1].capture_ns - frames[0].capture_ns) / _NS_PER_S if frames else 0.0
            return {
                "frames": len(frames),
                "bytes_held": self._bytes_held,
                "span_s": float(span_s),
                **self._counters,
            }

    # ------------------------------------------------------------------ T9b: закрепление

    def pin(self, t0_ns: int, t1_ns: int, tag: object) -> None:
        """Закрепить интервал `[t0, t1]` (оба конца включены) под тегом: кадры интервала, в том числе
        те, что придут ПОСЛЕ вызова, не вытесняются. Повторный `pin` с тем же тегом заменяет интервал
        и считается новым вызовом (становится самым «молодым» пином).

        Raises:
            ValueError: `t0 > t1` (текст без значений входа).
        """
        if t0_ns > t1_ns:
            raise ValueError("pin: начало интервала позже конца")
        with self._lock:
            self._pins.pop(tag, None)
            self._pins[tag] = (t0_ns, t1_ns)
            self._recount_pinned()
            self._release_pins_over_budget(None, 0)

    def unpin(self, tag: object) -> None:
        """Снять пин; неизвестный тег — ничего не делает. Кадры возвращаются вытеснению при `append`."""
        with self._lock:
            if self._pins.pop(tag, None) is not None:
                self._recount_pinned()

    def _is_pinned(self, capture_ns: int) -> bool:
        return any(t0 <= capture_ns <= t1 for t0, t1 in self._pins.values())

    def _recount_pinned(self) -> None:
        """Пересчёт счётчика закреплённых байт сканом кольца: при `pin`, `unpin` и освобождении пина
        (кадр под двумя пинами считается один раз). На `append` счётчик только растёт на `size`."""
        self._pinned_held = sum(len(f.payload) for f in self._frames if self._is_pinned(f.capture_ns))

    def _pinned_bytes(self, extra_ns: int | None, extra_size: int) -> int:
        """Закреплённые байты по счётчику плюс ещё не вставленный кадр `extra_ns`, если он закреплён."""
        if extra_ns is not None and self._is_pinned(extra_ns):
            return self._pinned_held + extra_size
        return self._pinned_held

    def _release_oldest_pin(self) -> None:
        """Освободить пин, вызванный раньше остальных; со счётчиком `pins_released`."""
        del self._pins[next(iter(self._pins))]
        self._counters["pins_released"] += 1
        self._recount_pinned()

    def _release_pins_over_budget(self, extra_ns: int | None, extra_size: int) -> None:
        """Условие 1 бюджета: закреплено больше `pin_max_bytes` -> освобождать самый старый пин."""
        while self._pins and self._pinned_bytes(extra_ns, extra_size) > self._pin_max_bytes:
            self._release_oldest_pin()

    # ------------------------------------------------------------------ T9b: группа и экспорт

    def find_group(self, group_id: int | None) -> list[dict]:
        """Кадры группы в порядке `(capture_ns, seq)`; `None` ничего не находит."""
        if group_id is None:
            return []
        with self._lock:
            found = [f for f in self._frames if f.group_id == group_id]
        return [_frame_dict(f) for f in found]

    def export(self, t0_ns: int, t1_ns: int) -> dict:
        """`{"blob": bytes, "index": bytes}` — те же байты и тот же индекс, что пойдут на диск (T12).

        Границы включающие, порядок `(capture_ns, seq)`, смещения с нуля вплотную; пустой диапазон —
        пустые `blob` и `index`. Кольцо не меняется. Под замком берётся только срез ссылок на `bytes`;
        склейка блока (на 120 с — около 1,2 ГБ) идёт вне замка, чтобы не остановить писателя.

        Raises:
            ValueError: `t0 > t1` (симметрия с `pin`: перепутанные концы не должны молча давать пустой
                результат; текст без значений входа).
        """
        if t0_ns > t1_ns:
            raise ValueError("export: начало диапазона позже конца")
        with self._lock:
            frames = self._frames
            lo = bisect_left(frames, t0_ns, key=_by_capture_ns)
            hi = bisect_right(frames, t1_ns, key=_by_capture_ns)
            chosen = list(islice(frames, lo, hi)) if lo < hi else []
        blob, index = build_segment(_frame_dict(f) for f in chosen)
        return {"blob": blob, "index": index}
