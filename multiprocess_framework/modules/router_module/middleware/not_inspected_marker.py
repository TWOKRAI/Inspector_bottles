# -*- coding: utf-8 -*-
"""Контракт маркера ``not_inspected`` (Task 4.7d-1).

Чистый модуль: ничего не импортирует из process_module. Маркер — лёгкий dict без кадра,
которым узел заменяет выброшенный при переполнении кадр под политикой ``overflow: every``
(поведение — Task 4.7d-2; здесь только форма и предикат).

Task 5.3: запись о разрыве (``build_gap``) — один dict на потерю любой длины (до ``GAP_CHUNK`` кадров) вместо
маркера на кадр. Запись — тоже маркер (``is_marker`` истинен); число потерянных кадров читается как
``item.get("count", 1)``.
"""

from __future__ import annotations

from typing import Any

NOT_INSPECTED = "not_inspected"

# Допустимые причины, по которым кадр не был проинспектирован.
MARKER_REASONS = ("lag", "stale_restore", "stale_exec", "door")

# Task 5.3: потолок ``count`` одной записи о разрыве. Разрыв из N кадров уезжает ⌈N/GAP_CHUNK⌉ сообщениями.
GAP_CHUNK = 1500


def build_marker(meta: dict[str, Any], *, reason: str, source: str) -> dict[str, Any]:
    """Собрать маркер по метаданным выброшенного кадра.

    Кадр и служебные SHM-ключи в маркер НЕ попадают. ``frame_id`` / ``camera_id`` копируются,
    только если ключ есть в ``meta`` (значение 0 сохраняется).
    """
    if reason not in MARKER_REASONS:
        raise ValueError(f"reason={reason!r} — expected one of {MARKER_REASONS}")
    marker: dict[str, Any] = {
        "inspection_status": NOT_INSPECTED,
        "overflow_marker": True,
        "reason": reason,
        "source": source,
        "trace_id": meta.get("trace_id") or "",
        "capture_ts": meta.get("capture_ts"),
    }
    for key in ("frame_id", "camera_id"):
        if key in meta:
            marker[key] = meta[key]
    marker["count"] = 1  # Task 5.3: маркер = потеря одного кадра (та же единица, что у записи о разрыве)
    return marker


def _count(item: dict[str, Any]) -> int:
    """Сколько потерянных кадров описывает вход (маркер без ключа ``count`` — один)."""
    return int(item.get("count", 1))


def _trace_ids(item: dict[str, Any]) -> list[Any]:
    """``trace_ids`` входа: у записи — свой список, у маркера — ``[trace_id]`` (пустой id сохраняется)."""
    if "trace_ids" in item:
        return list(item["trace_ids"])
    return [item.get("trace_id", "")]


def _tally(item: dict[str, Any], plural: str, singular: str) -> dict[str, int]:
    """Агрегат входа: у записи — ``reasons`` / ``sources``, у маркера — ``{reason: count}`` / ``{source: count}``."""
    if plural in item:
        return dict(item[plural])
    return {item.get(singular): _count(item)}


def _gap_fields(inputs: list[dict[str, Any]]) -> dict[str, Any]:
    """Поля записи любой длины: ``count``, ``trace_ids``, ``first/last_capture_ts``, ``reasons``, ``sources``."""
    trace_ids: list[Any] = []
    reasons: dict[str, int] = {}
    sources: dict[str, int] = {}
    stamps: list[Any] = []
    for item in inputs:
        trace_ids.extend(_trace_ids(item))
        for name, n in _tally(item, "reasons", "reason").items():
            reasons[name] = reasons.get(name, 0) + n
        for name, n in _tally(item, "sources", "source").items():
            sources[name] = sources.get(name, 0) + n
        if "trace_ids" in item:  # запись: её интервал
            stamps.extend((item.get("first_capture_ts"), item.get("last_capture_ts")))
        else:
            stamps.append(item.get("capture_ts"))
    known = [ts for ts in stamps if ts is not None]
    return {
        "count": sum(_count(item) for item in inputs),
        "trace_ids": trace_ids,
        "first_capture_ts": min(known) if known else None,
        "last_capture_ts": max(known) if known else None,
        "reasons": reasons,
        "sources": sources,
    }


def _build_record(inputs: list[dict[str, Any]]) -> dict[str, Any]:
    """Одна запись из входов, чья Σ ``count`` ≤ ``GAP_CHUNK``.

    ``count == 1`` (ровно один вход-маркер): маркер целиком + поля записи — кадр остаётся поимённым
    (``trace_id``, ``frame_id``, ``reason``). ``count > 1``: только поля записи плюс ``source`` (если источник
    один) и ``camera_id`` (если ключ есть у ВСЕХ входов и значение одно). Входы не мутируются.
    """
    fields = _gap_fields(inputs)
    if fields["count"] == 1 and len(inputs) == 1:
        record = dict(inputs[0])
        record.update(fields)
        return record
    record = {"inspection_status": NOT_INSPECTED, "overflow_marker": True, **fields}
    if len(fields["sources"]) == 1:
        record["source"] = next(iter(fields["sources"]))
    if all("camera_id" in item for item in inputs):
        camera = inputs[0]["camera_id"]
        if all(item["camera_id"] == camera for item in inputs):
            record["camera_id"] = camera
    return record


def build_gap(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Схлопнуть маркеры и записи о разрыве в записи (Task 5.3, поправка ADR-174 п. 4).

    Вход — маркеры (``build_marker``) и/или записи (результат ``build_gap``, в том числе от соседа). Вход
    неделим: у записи ``reasons`` не разложить по ``trace_id``. Упаковка жадная: входы идут в текущую запись,
    пока Σ ``count`` ≤ ``GAP_CHUNK``; вход, который переполнил бы её, открывает новую. Порядок ``trace_ids``
    = порядок входа; ``len(trace_ids) == count`` у каждой записи.

    Raises:
        ValueError: пустой вход (запись о разрыве нулевой длины не существует).
    """
    if not items:
        raise ValueError("build_gap: пустой вход — разрыва нет")
    records: list[dict[str, Any]] = []
    chunk: list[dict[str, Any]] = []
    chunk_count = 0
    for item in items:
        n = _count(item)
        if chunk and chunk_count + n > GAP_CHUNK:
            records.append(_build_record(chunk))
            chunk, chunk_count = [], 0
        chunk.append(item)
        chunk_count += n
    records.append(_build_record(chunk))
    return records


def meta_from_msg(msg: dict[str, Any]) -> dict[str, Any]:
    """Метаданные для ``build_marker`` из IPC-сообщения — по правилам ``DataReceiver._build_item``.

    ``trace_id`` / ``capture_ts`` — из ``msg["data"]``; ``frame_id`` / ``camera_id`` — из ``data``,
    иначе из ``msg``. Ключ копируется по наличию, не по истинности (значение 0 сохраняется).
    """
    data = msg.get("data") or {}
    meta: dict[str, Any] = {}
    for key in ("trace_id", "capture_ts"):
        if key in data:
            meta[key] = data[key]
    for key in ("frame_id", "camera_id"):
        if key in data:
            meta[key] = data[key]
        elif key in msg:
            meta[key] = msg[key]
    return meta


def is_marker(item: dict[str, Any]) -> bool:
    """Маркер переполнения — не любой кадр с тегом ``not_inspected`` (тег сбоя плагина идёт с кадром)."""
    return item.get("overflow_marker") is True and item.get("inspection_status") == NOT_INSPECTED


def is_marker_collection(items: object) -> bool:
    """Непустая коллекция целиком из маркеров ``not_inspected`` (единственное определение, Task 4.7d-2).

    Смешанная коллекция (маркер + обычный item) маркерной НЕ считается и идёт обычным путём. Обходит items:
    под ``chain.mutex`` приёмника не зовётся (там тип ``_MarkerBatch``, проверка O(1)).
    """
    return isinstance(items, (list, tuple)) and bool(items) and all(isinstance(i, dict) and is_marker(i) for i in items)
