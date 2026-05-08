"""Модели данных для ProcessesTab."""
from __future__ import annotations
from dataclasses import dataclass, field


@dataclass
class ProcessInfo:
    """Информация о процессе из topology."""

    name: str
    category: str  # "source" / "processing" / "output" / "control" / "utility"
    plugins: list[str] = field(default_factory=list)  # имена плагинов
    status: str = "unknown"
    pid: int | None = None
    fps: float = 0.0
    frame_count: int = 0
