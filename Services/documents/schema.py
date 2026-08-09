# -*- coding: utf-8 -*-
"""``DocumentRow`` — SQL-проекция документа.

Форма взята у ``Services/sql/action_log/schema_ext.py``: примитивные колонки плюс один
JSON-текст для произвольной части. Причина та же — ``SchemaBaseMapper`` умеет отображать
только примитивы, а состав полей документа зависит от его рода (у аудита ``origin`` и
``action``, у вердикта — изделие и уверенность) и в колонки не раскладывается.

Колонки выбраны по тому, ЧТО спрашивают у документа в инциденте: «какого рода», «когда»,
«кто/что источник», «чем именно» — и по чему из этого нужен индекс.
"""

from __future__ import annotations

import json
from typing import Any, Dict

from multiprocess_framework.modules.data_schema_module import SchemaBase

__all__ = ["DocumentRow", "to_document_row", "from_document_row"]

#: Потолок сериализации payload. Документ не имеет права стать вторым местом
#: хранения конфигурации — та же граница, что у кольца аудита (_VALUE_CAP=1024),
#: но шире: документ долговечен, и обрезать его агрессивнее журнала бессмысленно.
PAYLOAD_CAP = 8192


class DocumentRow(SchemaBase):
    """Строка таблицы ``documents``.

    Все поля — примитивы, поэтому маппер кладёт их в колонки напрямую.
    """

    class SQLMeta:
        table_name = "documents"
        primary_key = ["doc_id"]
        # ts — единственный индекс, который нужен ретеншену и чтению «свежие первыми».
        # (kind, ts) — чтение одной плоскости за период, самый частый запрос вкладки.
        indexes = [("ts",), ("kind", "ts")]

    doc_id: str
    kind: str
    ts: float
    #: Кто породил документ: имя процесса (аудит) либо линия/пост (вердикт).
    source: str = ""
    #: Короткая человекочитаемая суть — то, что видно в списке без раскрытия payload.
    summary: str = ""
    #: Остальное, как JSON-текст. Пусто → "{}".
    payload_json: str = "{}"


def to_document_row(document: Dict[str, Any], doc_id: str) -> DocumentRow:
    """Свернуть документ-dict в строку таблицы.

    Ключи ``kind``/``ts``/``source``/``summary`` уходят в свои колонки, ВСЁ остальное —
    в ``payload_json``. Разделения «известные поля» и «extra» на входе нет намеренно:
    вызывающий не обязан знать раскладку колонок, иначе она стала бы частью контракта
    и любое её изменение ломало бы всех писателей.
    """
    payload = {k: v for k, v in document.items() if k not in ("kind", "ts", "source", "summary")}
    text = json.dumps(payload, ensure_ascii=False, default=str)
    if len(text) > PAYLOAD_CAP:
        # Обрезаем ЯВНО и с отметкой: молча усечённый JSON не разобрать обратно,
        # а документ без признака усечения врёт полнотой.
        text = json.dumps(
            {"_truncated": True, "_original_len": len(text), "_head": text[:PAYLOAD_CAP]},
            ensure_ascii=False,
        )
    return DocumentRow(
        doc_id=doc_id,
        kind=str(document["kind"]),
        ts=float(document["ts"]),
        source=str(document.get("source", "")),
        summary=str(document.get("summary", "")),
        payload_json=text,
    )


def from_document_row(row: DocumentRow) -> Dict[str, Any]:
    """Развернуть строку обратно в документ-dict (round-trip к ``to_document_row``).

    Битый ``payload_json`` не роняет чтение: документ отдаётся без payload, но с
    признаком ``_payload_error``. Инцидент разбирают по документам — потерять всю
    страницу из-за одной испорченной строки хуже, чем отдать её неполной.
    """
    try:
        payload = json.loads(row.payload_json)
        if not isinstance(payload, dict):
            payload = {"_payload_error": "not_a_dict", "_raw": row.payload_json[:200]}
    except (ValueError, TypeError):
        payload = {"_payload_error": "invalid_json", "_raw": row.payload_json[:200]}

    return {
        "doc_id": row.doc_id,
        "kind": row.kind,
        "ts": row.ts,
        "source": row.source,
        "summary": row.summary,
        **payload,
    }
