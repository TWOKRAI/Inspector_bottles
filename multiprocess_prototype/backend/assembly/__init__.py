"""assembly — канонический сборщик proc_dict из blueprint-топологии.

Пакет содержит:

- ``BlueprintAssembler`` — stateless трансформер: (нормализованный blueprint dict)
  → ``{name: proc_dict}``.  Внутри — ТОЛЬКО framework-примитивы (carve-out-ready).
- ``normalize_blueprint`` — app-glue: применяет per-category defaults из
  ``SystemConfig``.
- ``BlueprintInvalid`` — ошибка валидации topology (несёт список ошибок).
- ``FullReplacePlanner`` — стратегия полной замены (diff + commands, 5 фаз).
"""

from .assembler import BlueprintAssembler, BlueprintInvalid
from .normalize import normalize_blueprint
from .planner import FullReplacePlanner

__all__ = [
    "BlueprintAssembler",
    "BlueprintInvalid",
    "FullReplacePlanner",
    "normalize_blueprint",
]
