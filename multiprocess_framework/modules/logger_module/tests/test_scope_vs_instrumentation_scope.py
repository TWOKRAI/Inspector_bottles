# -*- coding: utf-8 -*-
"""Ф3.2 — «одно имя = одно понятие» на оси scope (ADR-LOG-005).

Наш ``scope`` — ГРУППА логирования (ключ маршрутизации). ``InstrumentationScope``
в словаре OTel — ИСТОЧНИК записи, и у нас его носит ``module``. Имена похожи,
понятия разные, и путаница уже была: в проде нашлись пять мест, где словом
«scope» назван ``module``.

Документация такое не удержит, поэтому здесь два стража разного рода:

1. **Контрактный** — инвариант, который сломается, если поля перепутают:
   ``scope`` всегда имя из каталога групп, ``module`` — имя источника.
2. **Словарный** — запрет на те самые формулировки в слое наблюдаемости.
   Обычно grep по прозе — плохой тест; здесь он сторожит ровно то решение,
   ради которого задача делалась, и по образцу уже живущего в проекте стража
   «делегирующих обёрток быть не должно».
"""

from __future__ import annotations

import pathlib
import re
from typing import Any, Dict, List

import pytest

from multiprocess_framework.modules.logger_module.core.log_config import LogLevel, LogScope
from multiprocess_framework.modules.logger_module.core.logger_manager import LoggerManager

#: Пакеты слоя наблюдаемости, где слово «scope» обязано значить ровно одно.
_OBSERVABILITY_PACKAGES = (
    "multiprocess_framework/modules/channel_routing_module",
    "multiprocess_framework/modules/logger_module",
    "multiprocess_framework/modules/error_module",
    "multiprocess_framework/modules/statistics_module",
    "multiprocess_framework/modules/process_module/managers",
)

#: Формулировки, которыми `module` называли «скоупом». Каждая была найдена в
#: проде, а не выдумана: две в `record_display`, по одной в
#: `record_forward_channel`, `observability_wiring` и тесте `test_record_forward`.
_AMBIGUOUS = (
    re.compile(r"fine-grained\s+scope", re.I),
    re.compile(r"scope\s+логгера", re.I),
)


class _CollectingChannel:
    """Канал, запоминающий словари записей (то, что уедет наружу)."""

    def __init__(self, name: str = "collect") -> None:
        self._name = name
        self.records: List[Dict[str, Any]] = []

    @property
    def name(self) -> str:
        return self._name

    def write(self, data: Dict[str, Any]) -> Dict[str, Any]:
        self.records.append(data)
        return {"status": "success"}

    def close(self) -> None:
        pass


@pytest.fixture
def logger(tmp_path):
    config: Dict[str, Any] = {
        "app_name": "scope_vs_module",
        "log_directory": str(tmp_path),
        "enable_batching": False,
        "modules": {},
        "channels": {"f": {"type": "file", "enabled": True, "file_path": str(tmp_path / "a.log")}},
        "scopes": {"SYSTEM": {"enabled": True, "min_level": "DEBUG", "channels": ["f"]}},
    }
    mgr = LoggerManager(manager_name="ScopeProbe", config=config)
    mgr.initialize()
    try:
        yield mgr
    finally:
        mgr.shutdown()


class TestTheTwoFieldsAreNotInterchangeable:
    """Контракт: группа лежит в ``scope``, источник — в ``module``."""

    def test_group_goes_to_scope_and_source_goes_to_module(self, logger: LoggerManager) -> None:
        """Пара полей на одной записи: перепутать их — значит сломать этот тест.

        ``module`` намеренно взят точечным именем (Ф2.2): именно так выглядит
        ``InstrumentationScope.name`` у OTel, и именно его перепутали бы с
        группой.
        """
        sink = _CollectingChannel()
        logger.add_tap(sink, min_level="DEBUG", name="collect")

        logger.log(LogScope.SYSTEM, LogLevel.INFO, "проба", module="m.m.dispatch_module")

        assert len(sink.records) == 1
        record = sink.records[0]
        assert record["scope"] == "SYSTEM", "в scope уехала не группа логирования"
        assert record["module"] == "m.m.dispatch_module", "в module уехало не имя источника"

    def test_scope_is_a_catalog_name_never_a_source_name(self, logger: LoggerManager) -> None:
        """``scope`` — имя из каталога групп, а не точечное имя источника.

        Признак, по которому их и путают: точка. Имя группы её не содержит
        никогда, имя источника — почти всегда.
        """
        sink = _CollectingChannel()
        logger.add_tap(sink, min_level="DEBUG", name="collect")

        logger.log(LogScope.SYSTEM, LogLevel.INFO, "проба", module="a.b.c")

        scope = sink.records[0]["scope"]
        assert "." not in scope, f"в scope точечное имя '{scope}' — это имя источника, а не группы"
        assert scope in logger.config.scopes, "scope не найден в каталоге групп конфига"


class TestVocabularyGuard:
    """Словарный страж: «scope» в слое наблюдаемости значит только группу."""

    def test_no_source_name_is_called_a_scope(self) -> None:
        root = pathlib.Path(__file__).resolve().parents[4]
        hits: List[str] = []
        scanned = 0
        for package in _OBSERVABILITY_PACKAGES:
            package_dir = root / package
            assert package_dir.is_dir(), f"путь пакета не существует: {package_dir}"
            for path in package_dir.rglob("*.py"):
                scanned += 1
                text = path.read_text(encoding="utf-8", errors="replace")
                for line_no, line in enumerate(text.splitlines(), 1):
                    if any(pattern.search(line) for pattern in _AMBIGUOUS):
                        hits.append(f"{path.relative_to(root)}:{line_no}: {line.strip()}")
        # Самопроверка против молчащего детектора: страж, ничего не прочитавший,
        # зелен по любой причине — включая опечатку в пути. Число — порядок
        # величины слоя, а не точный счёт, чтобы не краснеть на каждый новый файл.
        assert scanned > 100, f"страж прочитал всего {scanned} файлов — он смотрит не туда"
        assert not hits, (
            "словом «scope» назван источник записи (это `module`, ADR-LOG-005). Найдено:\n  " + "\n  ".join(hits)
        )
