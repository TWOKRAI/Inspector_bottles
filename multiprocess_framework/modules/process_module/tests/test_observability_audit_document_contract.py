# -*- coding: utf-8 -*-
"""Независимые тесты контракта D+E приёмки Ф8.5 — конверт документа аудита.

Пишутся ТОЛЬКО по приёмочным критериям, без чтения
``multiprocess_framework/modules/process_module/configs/observability_audit.py``: форма
конструктора (``sink``/``clock``/``log``) и вызова ``record(action, origin=..., key=...)``
взяты из текста приёмки. Соседний файл ``test_observability_audit_document_sink.py``
(автор — разработчик, хазард-тесты пиклинга/отказа стока) уже покрывает 2 одинаковых
вызова со здоровым стоком; здесь — недостающая независимая проверка: 10 одинаковых
вызовов при СТОКЕ, КОТОРЫЙ ВСЕГДА ОТКАЗЫВАЕТ (обе формы отказа — ``False`` и исключение),
и защита рода документа от переопределения лишним полем ``kind`` в вызове ``record``.
"""

from __future__ import annotations

from typing import Any, Dict, List

from multiprocess_framework.modules.process_module.configs.observability_audit import (
    ObservabilityAudit,
)


class _AlwaysFailingSink:
    """Сток, который отказывает КАЖДЫЙ раз — либо ``False``, либо исключением."""

    def __init__(self, *, raises: bool = False) -> None:
        self.calls: List[Dict[str, Any]] = []
        self._raises = raises

    def __call__(self, document: Dict[str, Any]) -> Any:
        self.calls.append(document)
        if self._raises:
            raise RuntimeError("БД недоступна")
        return False


class _RecordingSink:
    """Сток-список, который всегда успешен — для проверки конверта документа."""

    def __init__(self) -> None:
        self.documents: List[Dict[str, Any]] = []

    def __call__(self, document: Dict[str, Any]) -> Any:
        self.documents.append(document)
        return True


class TestTenIdenticalCallsCollapseToOneRingEntryUnderAFailingSink:
    """Приёмка D: схлопывание кольца обязано работать и при ОТКАЗЫВАЮЩЕМ стоке.

    Подметальщик повторяет один и тот же отказ каждый такт; без схлопывания сток,
    который никогда не берёт запись, за десять тактов насыпал бы десять попыток вместо
    одной строки в кольце — ту же самую цену, только на отказывающем пути.
    """

    def test_ten_calls_with_a_refusing_sink_give_one_ring_entry_with_repeats_ten(self) -> None:
        sink = _AlwaysFailingSink(raises=False)
        audit = ObservabilityAudit(sink=sink, clock=lambda: 1.0)

        for _ in range(10):
            audit.record("expire", origin="ttl-sweeper", key="scopes.SYSTEM", ok=False, error="занято")

        assert len(audit.ring) == 1, "десять одинаковых вызовов обязаны дать ОДНУ запись, а не десять"
        assert audit.ring[-1]["repeats"] == 10

    def test_ten_calls_with_a_raising_sink_also_collapse_to_one_entry(self) -> None:
        """Второе плечо той же формы отказа — сток бросает исключение, а не возвращает False."""
        sink = _AlwaysFailingSink(raises=True)
        audit = ObservabilityAudit(sink=sink, clock=lambda: 1.0)

        for _ in range(10):
            audit.record("expire", origin="ttl-sweeper", key="scopes.SYSTEM", ok=False, error="занято")

        assert len(audit.ring) == 1
        assert audit.ring[-1]["repeats"] == 10


class TestDocumentKindCannotBeOverriddenByAnExtraField:
    """Приёмка E: лишнее поле ``kind`` в вызове ``record`` не имеет права перебить род документа."""

    def test_extra_kind_kwarg_does_not_override_the_document_kind(self) -> None:
        sink = _RecordingSink()
        audit = ObservabilityAudit(sink=sink, clock=lambda: 1.0)

        audit.record("set", origin="command:config.reload", key="log_level", value="DEBUG", kind="что-то-чужое")

        assert len(sink.documents) == 1
        assert sink.documents[0]["kind"] == "audit"

    def test_document_without_the_extra_field_still_gets_kind_audit(self) -> None:
        """Контрольная проба: без чужого поля род документа и так ``audit`` — сравнение показывает,
        что защита срабатывает именно на подмену, а не на что-то ещё."""
        sink = _RecordingSink()
        audit = ObservabilityAudit(sink=sink, clock=lambda: 1.0)

        audit.record("set", origin="command:config.reload", key="log_level", value="DEBUG")

        assert sink.documents[0]["kind"] == "audit"
