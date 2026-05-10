"""wire_protocol — data classes для конфигурации wire (соединения между процессами).

Отвечает на вопрос: ЧТО такое wire?
- ShmConfig: параметры shared memory
- WireConfig: описание одного соединения (source → target)
- validate_wire(): проверка корректности конфигурации
- round-trip: from_topology_entry() / to_topology_entry()

Pure Python, 0 зависимостей (кроме dataclasses, typing).
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import Any


@dataclass(frozen=True)
class ShmConfig:
    """Конфигурация shared memory для wire."""

    # Имя SHM-региона; авто-генерация если пусто
    shm_name: str = ""
    # Количество слотов кольцевого буфера
    buffer_slots: int = 4
    # Процесс-владелец SHM; авто = source_process
    owner_process: str = ""
    # Стратегия создания: "direct" | "via_pm"
    strategy: str = "direct"


@dataclass(frozen=True)
class WireConfig:
    """Конфигурация одного wire (соединения между процессами).

    Формат source/target: "process_name.plugin_name.port_name"
    """

    # Уникальный ключ wire в topology
    wire_key: str
    # Источник в формате "process.plugin.port"
    source: str
    # Получатель в формате "process.plugin.port"
    target: str
    # Транспорт: "router" | "direct"
    transport: str = "router"
    # Конфигурация shared memory
    shm_config: ShmConfig = field(default_factory=ShmConfig)

    @property
    def source_process(self) -> str:
        """Имя процесса-источника (до первой точки)."""
        return self.source.split(".")[0]

    @property
    def target_process(self) -> str:
        """Имя процесса-получателя (до первой точки)."""
        return self.target.split(".")[0]

    def with_defaults(self) -> "WireConfig":
        """Заполнить авто-значения (shm_name, owner_process).

        Если shm_name пуст → f"shm_{source_process}_{target_process}"
        Если owner_process пуст → source_process
        Возвращает новый WireConfig (frozen).
        """
        # Вычисляем авто-значения только если они пусты
        shm_name = self.shm_config.shm_name
        if not shm_name:
            shm_name = f"shm_{self.source_process}_{self.target_process}"

        owner_process = self.shm_config.owner_process
        if not owner_process:
            owner_process = self.source_process

        # Создаём новый ShmConfig только если что-то изменилось
        if shm_name != self.shm_config.shm_name or owner_process != self.shm_config.owner_process:
            new_shm = replace(
                self.shm_config,
                shm_name=shm_name,
                owner_process=owner_process,
            )
            return replace(self, shm_config=new_shm)

        return self

    @classmethod
    def from_topology_entry(cls, key: str, entry: dict[str, Any]) -> "WireConfig":
        """Создать из записи topology dict.

        Ожидаемый формат entry:
        {
            "source": "proc.plugin.port",
            "target": "proc.plugin.port",
            "transport": "router",          # опционально
            "shm_config": {                 # опционально
                "shm_name": "...",
                "buffer_slots": 4,
                "owner_process": "...",
                "strategy": "direct",
            }
        }
        """
        shm_entry = entry.get("shm_config", {})
        shm_config = ShmConfig(
            shm_name=shm_entry.get("shm_name", ""),
            buffer_slots=shm_entry.get("buffer_slots", 4),
            owner_process=shm_entry.get("owner_process", ""),
            strategy=shm_entry.get("strategy", "direct"),
        )
        return cls(
            wire_key=key,
            source=entry.get("source", ""),
            target=entry.get("target", ""),
            transport=entry.get("transport", "router"),
            shm_config=shm_config,
        )

    def to_topology_entry(self) -> dict[str, Any]:
        """Конвертировать обратно в topology dict формат.

        Round-trip: from_topology_entry(key, to_topology_entry()) == self
        """
        return {
            "source": self.source,
            "target": self.target,
            "transport": self.transport,
            "shm_config": {
                "shm_name": self.shm_config.shm_name,
                "buffer_slots": self.shm_config.buffer_slots,
                "owner_process": self.shm_config.owner_process,
                "strategy": self.shm_config.strategy,
            },
        }


def validate_wire(wire: WireConfig) -> tuple[bool, str | None]:
    """Валидировать wire config.

    Проверки:
    - source != target (нет self-loop)
    - source_process != target_process (разные процессы)
    - source и target содержат минимум 2 точки (формат process.plugin.port)
    - buffer_slots >= 2

    Возвращает (True, None) если валидно, (False, "причина") если нет.
    """
    # Проверка формата: минимум process.plugin.port = 2 точки
    if wire.source.count(".") < 2:
        return False, f"source имеет неверный формат: '{wire.source}' (ожидается process.plugin.port)"

    if wire.target.count(".") < 2:
        return False, f"target имеет неверный формат: '{wire.target}' (ожидается process.plugin.port)"

    # Нет self-loop по полному пути
    if wire.source == wire.target:
        return False, f"source и target совпадают: '{wire.source}'"

    # Source и target в разных процессах
    if wire.source_process == wire.target_process:
        return False, (
            f"source_process и target_process совпадают: '{wire.source_process}' "
            f"(wire должен соединять разные процессы)"
        )

    # Минимальное число слотов буфера
    if wire.shm_config.buffer_slots < 2:
        return False, (
            f"buffer_slots={wire.shm_config.buffer_slots} слишком мало "
            f"(минимум 2)"
        )

    return True, None
