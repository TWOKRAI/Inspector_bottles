# -*- coding: utf-8 -*-
"""Загрузчик сырых записей снимка `tools/otel_stand/samples/1f40ce0d/` для приёмочных
тестов Ф1 (`test_mapping_acceptance.py`, `test_resources_acceptance.py`).

НЕ файл теста (имя без `test_` — pytest его не собирает). Общий для обоих приёмочных
файлов, чтобы конверт `tail_debug.json` разбирался в одном месте.

Форма конверта (проверено чтением `tail_debug.json` напрямую, 2026-09-06):
``{"items": [{"seq": ..., "event": {"data": {"records": [...]} | {"record": {...}}}}]}``.
Карточка Task 1.0 (`docs/audits/2026-09-06_otel-input-shape.md`) даёт числа по родам через
верхний уровень конверта ("data.records") без вложенности "event" — это несовпадение с
фактической структурой файла (см. пункт «что оставлено открытым» отчёта тестера).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

# Services/otel_export/tests/_snapshot_fixtures.py -> repo root
REPO_ROOT = Path(__file__).resolve().parents[3]
SNAPSHOT_TAIL = REPO_ROOT / "tools" / "otel_stand" / "samples" / "1f40ce0d" / "tail_debug.json"


def load_snapshot_records(kind: str) -> list[dict[str, Any]]:
    """Все display-записи заданного ``kind`` из хвоста снимка ``1f40ce0d``.

    Возвращает записи КАК ЕСТЬ (без копий, без изменений) — они уже в display-виде
    (`kind, process, module, ts, severity, severity_number, metric, message, extra`),
    ровно та форма, которую `RecordMapper.to_otlp` объявляет входом (Pre в interfaces.py).
    """
    payload = json.loads(SNAPSHOT_TAIL.read_text(encoding="utf-8"))
    out: list[dict[str, Any]] = []
    for item in payload["items"]:
        data = item.get("event", {}).get("data", {})
        if "records" in data:
            candidates = data["records"]
        elif "record" in data:
            candidates = [data["record"]]
        else:
            candidates = []
        for rec in candidates:
            if rec and rec.get("kind") == kind:
                out.append(rec)
    return out
