# -*- coding: utf-8 -*-
"""
record_display — нормализация записей наблюдаемости в единый display-вид (Ф5.20b).

Живой хвост hub→GUI (Ф5.20b) и целая история из стора (Ф5.20a) должны отдавать
панели РАВНЫЙ по форме record, иначе виджет знал бы два формата. Стор возвращает
из ``list_records`` строку ``{id, kind, module, ts, severity, message, extra(dict)}``;
здесь тот же вид (без ``id``) собирается из двух живых источников:

  - hub-запись (дренаж log/stats):   {kind, module, ts, severity|metric_type, ...}
  - LogRecord-dict (error-tap):       {timestamp, level, scope, message, module, extra}

Функции чистые (Qt-free, без внешних зависимостей) — переиспользуются push-каналом
и тестируются в изоляции.
"""

from __future__ import annotations

from typing import Any, Dict

from .observability_store import KIND_ERROR, KIND_STATS

_ENVELOPE_KEYS = ("kind", "module", "ts", "severity", "message")


def hub_record_to_display(record: Dict[str, Any]) -> Dict[str, Any]:
    """Нормализовать hub-запись (drain log/stats) в display-вид.

    Симметрично ``observability_store._row_from_record``, но ``extra`` — dict (не
    JSON-строка): live-запись едет в GUI как pickle-safe dict, без промежуточной
    сериализации. Для stats severity=metric_type, message=metric (как в сторе).
    """
    kind = record.get("kind", "")
    module = record.get("module", "")
    ts = float(record.get("ts", 0.0) or 0.0)

    if kind == KIND_STATS:
        severity = str(record.get("metric_type", "")).lower()
        message = record.get("metric", "")
        extra: Dict[str, Any] = {"value": record.get("value"), "tags": record.get("tags", {})}
    else:
        severity = str(record.get("severity", "")).lower()
        message = record.get("message", "")
        extra = {k: v for k, v in record.items() if k not in _ENVELOPE_KEYS}

    return {"kind": kind, "module": module, "ts": ts, "severity": severity, "message": message, "extra": extra}


def log_record_to_display(record_dict: Dict[str, Any], kind: str = KIND_ERROR) -> Dict[str, Any]:
    """Нормализовать LogRecord-dict (error/critical у tap'а) в display-вид.

    На вход — ``LogRecord.to_dict()``: {timestamp, level, scope, message, module, extra}.
    По дизайну Ф5.16 error/critical идут write-through в реальный менеджер, а tap
    ловит их у sink'а — поэтому kind по умолчанию 'error'.
    """
    return {
        "kind": kind,
        "module": record_dict.get("module", ""),
        "ts": float(record_dict.get("timestamp", 0.0) or 0.0),
        "severity": str(record_dict.get("level", "")).lower(),
        "message": record_dict.get("message", ""),
        "extra": record_dict.get("extra", {}) or {},
    }
