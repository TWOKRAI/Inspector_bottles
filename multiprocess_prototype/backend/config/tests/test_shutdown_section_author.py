# -*- coding: utf-8 -*-
"""Авторский hazard-тест Task 1.4m: ``shutdown.pre_stop`` принимает ЛЮБЫЕ записи списка.

Тип элемента — ``Any`` намеренно: негодную запись проверяет и логирует PM
(``parse_pre_stop``), а не загрузка конфига. Сужение типа (например, до
``list[dict[str, str]]``) уронило бы загрузку ``ValidationError`` вместо ERROR в PM.
"""

from __future__ import annotations

from multiprocess_framework.modules.process_manager_module.process.pre_stop import parse_pre_stop
from multiprocess_prototype.backend.config.schemas import SystemConfig


def test_pre_stop_accepts_bad_entries_and_pm_rejects_them() -> None:
    """Три негодные записи: загрузка проходит дословно, схема PM отвергает все три."""
    raw = [
        1,
        {"process": "devices"},
        {"process": "devices", "command": "c", "args": {}, "timeout_s": "35"},
    ]

    cfg = SystemConfig.model_validate({"shutdown": {"pre_stop": raw}})

    assert cfg.shutdown.pre_stop == [
        1,
        {"process": "devices"},
        {"process": "devices", "command": "c", "args": {}, "timeout_s": "35"},
    ]
    steps, errors = parse_pre_stop(cfg.shutdown.pre_stop)
    assert steps == []
    assert len(errors) == 3, f"ожидалось 3 ошибки PM, получено {errors}"
