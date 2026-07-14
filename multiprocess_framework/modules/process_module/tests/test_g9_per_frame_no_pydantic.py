# -*- coding: utf-8 -*-
"""Ф7 G.9(c): per-frame hot-path БЕЗ Pydantic-валидаций (grep-контракт против регрессии).

Инвариант (перф-ревью 2026-07-12 п.2): на пути кадра (receive → chain → send) не должно
быть Pydantic-валидаций/пересборки моделей на КАЖДЫЙ кадр — это аллокации+валидация в
hot-path. Двойная конверсия снята G.5 (`FW_DATA_PLANE_DICTS` → plain dict, см.
`test_data_receiver.TestDataPlaneDictsFlag`); Pydantic остаётся на конфигах/границах
(правила 1/5). Этот тест ловит РЕГРЕСС — если кто-то вернёт `model_validate`/`BaseModel(`
на hot-path модуль, тест покраснеет.

Комплементарен поведенческому `TestDataPlaneDictsFlag` (тот проверяет return_messages,
этот — что сам код hot-path не тянет Pydantic-валидацию).
"""

from __future__ import annotations

import pathlib
import re

# Модули на per-frame пути (получение → цепочка-исполнитель → отправка кадра).
# H-ревье 2026-07-14: список расширен файлами H-задачи — те же кадры на send/receive
# теперь проходят через транспорт + фасады памяти (reader/pool), которые H вынесла «за
# фасад» той же горячей дорожки. Пути module-qualified (корень = .../modules).
_HOT_PATH = [
    "process_module/generic/data_receiver.py",
    "process_module/generic/pipeline_executor.py",
    "process_module/io/process_io.py",
    "router_module/middleware/frame_shm_middleware.py",
    "shared_resources_module/memory/reader/shm_frame_reader.py",
    "shared_resources_module/memory/pool/loan_ledger.py",
]

# Признаки Pydantic-валидации/пересборки НА КАЖДЫЙ вызов (не конфиг-границы).
_PYDANTIC_PER_FRAME = re.compile(r"\.model_validate\(|\bBaseModel\(|\.model_dump\(|SchemaBase\(")

_MODULE_ROOT = pathlib.Path(__file__).resolve().parents[2]


def test_hot_path_modules_free_of_pydantic_validation():
    offenders = []
    for rel in _HOT_PATH:
        src = (_MODULE_ROOT / rel).read_text(encoding="utf-8")
        # Убираем строковые докстринги/комментарии грубо: интересует исполняемый код.
        for i, line in enumerate(src.splitlines(), 1):
            stripped = line.strip()
            if stripped.startswith("#"):
                continue
            if _PYDANTIC_PER_FRAME.search(line):
                offenders.append(f"{rel}:{i}: {stripped}")
    assert not offenders, "Pydantic-валидация вернулась на per-frame hot-path (G.9(c) регресс):\n" + "\n".join(
        offenders
    )
