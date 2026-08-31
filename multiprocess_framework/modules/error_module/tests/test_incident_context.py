# -*- coding: utf-8 -*-
"""Н-14 — инцидент не беднее лог-дороги: контекст сайта доезжает до записи.

Приёмка F1 нашла асимметрию пары ``health.report(ERROR)``: лог-запись несла имя
источника, а инцидентная — ``module="unknown"`` и пустой ``context``. Вторая
половина дефекта жила здесь: :meth:`ErrorManager.track_error` читала из контекста
ДВА ключа и молча выбрасывала остальные, тогда как обычная запись
(``logger.error(msg, module=…, roi=…)``) их доносит.

Записи снимаются НАСТОЯЩИМ tap'ом настоящего менеджера — тем же механизмом,
которым едут live-хвост и стор. Шпион на ``self.error`` сторожил бы имя вызова,
а не доехавшее поле.
"""

from __future__ import annotations

from typing import Any, Dict, List

import pytest

from multiprocess_framework.modules.channel_routing_module.observability.record_display import (
    log_record_to_display,
)
from multiprocess_framework.modules.error_module.core.error_manager import ErrorManager


class _CapturingTap:
    """Приёмник tap'а: копит записи как есть (``write(dict)``)."""

    def __init__(self, name: str = "probe_tap") -> None:
        self.name = name
        self.records: List[Dict[str, Any]] = []

    @property
    def channel_type(self) -> str:
        return "probe"

    def write(self, record: Dict[str, Any]) -> Dict[str, Any]:
        self.records.append(dict(record))
        return {"success": True}

    def close(self) -> None:
        return None


@pytest.fixture
def errors_with_tap(tmp_path):
    mgr = ErrorManager(
        manager_name="IncidentProbe",
        config={
            "app_name": "incident",
            "log_directory": str(tmp_path),
            "enable_batching": False,
            "modules": {},
            "channels": {"a": {"type": "file", "enabled": True, "file_path": str(tmp_path / "a.log")}},
            "scopes": {
                "SYSTEM": {"channels": ["a"]},
                "BUSINESS": {"channels": ["a"]},
                "DEBUG": {"channels": ["a"]},
            },
        },
    )
    mgr.initialize()
    tap = _CapturingTap()
    mgr.add_tap(tap, min_level="DEBUG", name=tap.name)
    try:
        yield mgr, tap
    finally:
        mgr.remove_tap(tap.name)
        mgr.shutdown()


def _display(record: Dict[str, Any]) -> Dict[str, Any]:
    """Запись глазами подписчика — ЧЕРЕЗ production-конвертер, а не руками.

    Своё отображение ``extra`` → ``context`` было бы третьей позицией правила:
    тест остался бы зелёным, если бы конвертер перестал доносить контекст.
    """
    return log_record_to_display(record, process="probe")


def _context_of(record: Dict[str, Any]) -> Dict[str, Any]:
    """Контекст записи — там же, где его видит подписчик хвоста."""
    return dict((_display(record).get("extra") or {}).get("context") or {})


class TestIncidentKeepsItsContext:
    def test_extra_keys_reach_the_record(self, errors_with_tap):
        """Заявленное свойство: контекст сайта доезжает, а не выбрасывается.

        До правки в записи оставались только ``module`` и текст: ключи, ради
        которых сайт контекст и передавал, терялись молча.
        """
        mgr, tap = errors_with_tap

        mgr.track_error(
            ValueError("камера отвалилась"),
            {"module": "capture", "context": "grab_frame", "roi": "560,240", "attempt": 3},
        )

        assert tap.records, "инцидент не доехал до tap'а вовсе"
        ctx = _context_of(tap.records[-1])
        assert ctx.get("roi") == "560,240", f"ключ сайта потерян: {ctx}"
        assert ctx.get("attempt") == 3, f"ключ сайта потерян: {ctx}"

    def test_the_site_tag_stays_in_the_context_not_only_in_the_message(self, errors_with_tap):
        """``context`` — сайт-тег. Он и приставка к тексту, и поле записи.

        Оставь его только в тексте — и фильтр по сайту работал бы глазами,
        подстрокой сообщения, а не полем.
        """
        mgr, tap = errors_with_tap

        mgr.track_error(ValueError("сбой"), {"module": "capture", "context": "grab_frame"})

        record = tap.records[-1]
        assert _context_of(record).get("context") == "grab_frame", (
            f"сайт-тег остался только в тексте: {_context_of(record)}"
        )
        assert "grab_frame" in str(record.get("message", "")), "сайт-тег пропал из текста — прежняя форма сломана"

    def test_module_and_message_do_not_leak_into_the_context(self, errors_with_tap):
        """Служебные ключи — поля записи, а не её контекст.

        Иначе ``module`` приехал бы дважды и разными путями: полем и «данными».
        """
        mgr, tap = errors_with_tap

        mgr.track_error(ValueError("сбой"), {"module": "capture", "message": "при захвате", "roi": "1,2"})

        record = tap.records[-1]
        ctx = _context_of(record)
        assert "module" not in ctx and "message" not in ctx, f"служебные ключи протекли в контекст: {ctx}"
        assert record.get("module") == "capture"
        assert "при захвате" in str(record.get("message", ""))

    def test_without_a_stamp_the_module_is_still_named_unknown(self, errors_with_tap):
        """Дефолт менеджера НЕ трогается: штамп ставит вызывающий (ObservableMixin).

        Подставь менеджер сюда своё имя — и вторая позиция штампа разошлась бы
        с первой; «unknown» здесь честно означает «источник не назвали».
        """
        mgr, tap = errors_with_tap

        mgr.track_error(ValueError("сбой"))

        assert tap.records[-1].get("module") == "unknown"

    def test_an_ordinary_record_carries_the_same_shape(self, errors_with_tap):
        """Контроль: обычная запись — эталон, с которым инцидент сравнивается.

        Без него «контекст доехал» не отличить от «контекст никому не доезжает,
        просто теперь так же».
        """
        mgr, tap = errors_with_tap

        mgr.error("обычная запись", module="capture", roi="560,240")

        assert _context_of(tap.records[-1]).get("roi") == "560,240"
