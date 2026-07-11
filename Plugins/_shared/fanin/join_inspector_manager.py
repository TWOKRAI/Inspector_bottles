"""JoinInspectorManager — корреляция N именованных входов по seq_id.

Обобщение InspectorManager (region fan-in) на generic multi-input join:
вместо count-trigger (total_regions) ждёт НАБОР именованных входов по `data_type`
(напр. {"frame", "overlay"}), коррелируя их по `seq_id`.

Семантика (паттерн ROS ApproximateTimeSynchronizer / GStreamer GstAggregator):
- Полный набор требуемых data_type для seq_id → merge → on_ready([merged]).
- Left-join: primary (напр. "frame") пришёл, окно истекло, second-входов нет →
  эмитим то, что собрано (кадр без overlay). Без primary — дроп (рисовать не на чем).
- Auto-passthrough: если необязательный вход неактивен > inactive_sec (фильтр молчит /
  нет маршрута / упал) — он исключается из ожидаемого набора, primary не ждёт его
  каждый кадр (иначе FPS просядет на ожидании).
- merge: list-ключи (`overlay` и т.п.) конкатенируются («со всех линий суммируются»);
  скаляры — last-wins (primary имеет приоритет, мёржится первым).
- TTL: наборы старше 2*timeout выселяются; счётчик дропов в drop_count.

Items без `data_type` или без `seq_id` → немедленный pass-through (безопасный fallback).
Используется DataReceiver вместо InspectorManager, когда процесс в join-режиме.
"""

from __future__ import annotations

import math
import threading
import time
from typing import Callable, Iterable


class JoinInspectorManager:
    """Корреляция именованных входов (по data_type) по ключу seq_id.

    Args:
        required_inputs: имена входов (значения data_type), напр. {"frame", "overlay"}.
        primary: имя primary-входа (на нём строится left-join), напр. "frame".
        timeout_sec: окно ожидания неполного набора (мал — 50–100мс для real-time).
        list_merge_keys: ключи item, которые при merge конкатенируются (списки фигур).
        inactive_sec: вход, не приходивший дольше — исключается из ожидаемого набора.
        on_ready: callback(items) — список из одного слитого item.
    """

    def __init__(
        self,
        required_inputs: Iterable[str],
        primary: str = "frame",
        timeout_sec: float = 0.08,
        list_merge_keys: Iterable[str] = ("overlay",),
        inactive_sec: float = 1.0,
        on_ready: Callable[[list[dict]], None] | None = None,
        log_info: Callable[[str], None] | None = None,
        log_error: Callable[[str], None] | None = None,
        log_debug: Callable[[str], None] | None = None,
    ) -> None:
        self._required = set(required_inputs)
        self._primary = primary
        self._required.add(primary)  # primary всегда обязателен
        self._timeout_sec = timeout_sec
        self._list_keys = set(list_merge_keys)
        self._inactive_sec = inactive_sec
        self._on_ready = on_ready or (lambda items: None)
        self._log_info = log_info or (lambda msg: None)
        self._log_error = log_error or (lambda msg: None)
        self._log_debug = log_debug or (lambda msg: None)

        # Буфер: {seq_id: {data_type: item}}
        self._buffer: dict[int, dict[str, dict]] = {}
        # Время первого item набора: {seq_id: monotonic}
        self._timestamps: dict[int, float] = {}
        # Последняя активность входа: {data_type: monotonic}
        self._last_seen: dict[str, float] = {}

        self._drop_count = 0
        self._merge_count = 0
        self._lock = threading.Lock()

    # ------------------------------------------------------------------
    def _effective_required(self, now: float) -> set[str]:
        """Набор реально ожидаемых входов: primary + недавно активные второстепенные.

        Неактивный второстепенный вход (фильтр молчит / нет маршрута) исключается,
        чтобы primary не ждал его каждый кадр (auto-passthrough).
        """
        eff = {self._primary}
        for dt in self._required:
            if dt == self._primary:
                continue
            last = self._last_seen.get(dt, -math.inf)
            if now - last <= self._inactive_sec:
                eff.add(dt)
        return eff

    def _merge(self, by_type: dict[str, dict]) -> dict:
        """Слить items по data_type в один. primary первым (его скаляры приоритетны);
        list-ключи (overlay) конкатенируются по всем входам.
        """
        order = [self._primary] + [dt for dt in by_type if dt != self._primary]
        merged: dict = {}
        for dt in order:
            item = by_type.get(dt)
            if item is None:
                continue
            for k, v in item.items():
                if k in self._list_keys and isinstance(v, list):
                    prev = merged.get(k)
                    merged[k] = (prev if isinstance(prev, list) else []) + v
                elif k not in merged:
                    merged[k] = v
        return merged

    # ------------------------------------------------------------------
    def on_item(self, item: dict) -> None:
        """Принять один item; коррелировать по seq_id, эмитить при полном наборе."""
        data_type = item.get("data_type")
        seq_id = item.get("seq_id")

        # Безопасный fallback: без тегов корреляция невозможна → pass-through.
        if data_type is None or seq_id is None:
            self._on_ready([item])
            return

        now = time.monotonic()
        ready: dict | None = None
        with self._lock:
            self._last_seen[data_type] = now
            if seq_id not in self._buffer:
                self._buffer[seq_id] = {}
                self._timestamps[seq_id] = now
            if data_type in self._buffer[seq_id]:
                self._log_debug(
                    f"JoinInspectorManager: дубликат data_type='{data_type}' для seq_id={seq_id}, перезапись"
                )
            self._buffer[seq_id][data_type] = item

            eff = self._effective_required(now)
            if eff.issubset(set(self._buffer[seq_id].keys())):
                ready = self._merge(self._buffer[seq_id])
                self._merge_count += 1
                self._buffer.pop(seq_id, None)
                self._timestamps.pop(seq_id, None)

        if ready is not None:
            self._on_ready([ready])

    def check_timeouts(self) -> None:
        """Left-join по истечении окна + TTL-выселение. Вызывать периодически."""
        now = time.monotonic()
        emit: list[dict] = []
        with self._lock:
            for seq_id in list(self._timestamps.keys()):
                elapsed = now - self._timestamps[seq_id]
                if elapsed <= self._timeout_sec:
                    continue
                by_type = self._buffer.get(seq_id, {})
                if self._primary in by_type:
                    # Left-join: primary есть — эмитим, что собрано (без second-входов).
                    emit.append(self._merge(by_type))
                    self._log_debug(
                        f"JoinInspectorManager: left-join flush seq_id={seq_id}, got={sorted(by_type.keys())}"
                    )
                else:
                    # Нет primary — рисовать не на чем, дроп.
                    self._drop_count += 1
                    self._log_debug(
                        f"JoinInspectorManager: drop seq_id={seq_id} (нет primary "
                        f"'{self._primary}', got={sorted(by_type.keys())})"
                    )
                self._buffer.pop(seq_id, None)
                self._timestamps.pop(seq_id, None)

        for merged in emit:
            self._on_ready([merged])

    @property
    def pending_count(self) -> int:
        with self._lock:
            return len(self._buffer)

    @property
    def drop_count(self) -> int:
        """Сколько наборов выселено без primary (телеметрия)."""
        return self._drop_count

    @property
    def merge_count(self) -> int:
        """Сколько наборов успешно слито (телеметрия)."""
        return self._merge_count
