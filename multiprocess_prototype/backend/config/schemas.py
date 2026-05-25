"""Pydantic-схемы для system.yaml — валидация defaults."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated, Any, Literal

import yaml

from multiprocess_framework.modules.data_schema_module import FieldMeta, SchemaBase


class SystemSection(SchemaBase):
    """Глобальные системные параметры."""

    stop_timeout: Annotated[
        float,
        FieldMeta("Таймаут остановки", info="Время ожидания завершения процесса.", min=1.0, max=30.0, unit="с"),
    ] = 5.0

    shm_budget_mb: Annotated[
        int,
        FieldMeta("Бюджет SHM", info="Максимальный объём разделяемой памяти.", min=64, max=4096, unit="МБ"),
    ] = 512

    log_dir: Annotated[
        str,
        FieldMeta("Директория логов", info="Путь для записи лог-файлов. Пустая строка = по умолчанию."),
    ] = ""


class CameraDefaults(SchemaBase):
    """Defaults для capture-плагинов."""

    source_type: Annotated[
        Literal["simulator", "webcam", "hikvision", "file"],
        FieldMeta("Тип источника", info="Тип захвата видеопотока."),
    ] = "simulator"

    fps: Annotated[
        int,
        FieldMeta("Частота кадров", info="Целевой FPS захвата.", min=1, max=120, unit="fps"),
    ] = 25

    resolution_width: Annotated[
        int,
        FieldMeta("Ширина кадра", info="Горизонтальное разрешение захвата.", min=320, max=4096, unit="px"),
    ] = 640

    resolution_height: Annotated[
        int,
        FieldMeta("Высота кадра", info="Вертикальное разрешение захвата.", min=240, max=2160, unit="px"),
    ] = 480

    ring_buffer_size: Annotated[
        int,
        FieldMeta("Размер ring-буфера", info="Количество слотов в кольцевом буфере SHM.", min=2, max=10),
    ] = 3


class ProcessingDefaults(SchemaBase):
    """Defaults для processing-плагинов."""

    worker_pool_size: Annotated[
        int,
        FieldMeta("Размер пула воркеров", info="Количество потоков обработки. 0 = синхронный режим.", min=0, max=8),
    ] = 0


class DisplayDefaults(SchemaBase):
    """Defaults для дисплея."""

    enabled: Annotated[
        bool,
        FieldMeta("Включён", info="Отображать ли результат в GUI."),
    ] = True


class StorageDefaults(SchemaBase):
    """Defaults для хранения."""

    db_path: Annotated[
        str,
        FieldMeta("Путь к БД", info="Относительный путь к файлу SQLite базы данных."),
    ] = "data/inspector.db"

    batch_size: Annotated[
        int,
        FieldMeta("Размер батча", info="Количество записей в одной транзакции записи.", min=1, max=10000),
    ] = 100


class DiscoverySection(SchemaBase):
    """Настройки автообнаружения плагинов и сервисов при старте."""

    plugin_paths: Annotated[
        list[str],
        FieldMeta(
            "Директории плагинов",
            info="Директории для поиска плагинов. Относительные пути — от корня проекта.",
        ),
    ] = ["Plugins"]

    service_paths: Annotated[
        list[str],
        FieldMeta(
            "Директории сервисов", info="Директории для поиска сервисов. Задел для Phase 3, сейчас не используется."
        ),
    ] = ["Services"]

    auto_discover: Annotated[
        bool,
        FieldMeta(
            "Автообнаружение при старте",
            info="Если True — plugin_paths сканируются автоматически при старте приложения.",
        ),
    ] = True


class SystemConfig(SchemaBase):
    """Корневая схема system.yaml."""

    system: SystemSection = SystemSection()
    camera: CameraDefaults = CameraDefaults()
    processing: ProcessingDefaults = ProcessingDefaults()
    display: DisplayDefaults = DisplayDefaults()
    storage: StorageDefaults = StorageDefaults()
    discovery: DiscoverySection = DiscoverySection()

    def defaults_for_category(self, category: str) -> dict[str, Any]:
        """Получить defaults dict для категории плагина.

        Mapping: source → camera, processing → processing, output → display.
        """
        mapping = {
            "source": "camera",
            "processing": "processing",
            "output": "display",
            "storage": "storage",
        }
        section_name = mapping.get(category, category)
        section = getattr(self, section_name, None)
        if section is None:
            return {}
        return section.model_dump()


def load_system_config(path: Path | str | None = None) -> SystemConfig:
    """Загрузить и валидировать system.yaml.

    Args:
        path: путь к system.yaml (None = config/system.yaml рядом с этим файлом)

    Returns:
        Валидированный SystemConfig
    """
    if path is None:
        path = Path(__file__).parent / "system.yaml"
    else:
        path = Path(path)

    if not path.exists():
        # Нет файла — используем defaults
        return SystemConfig()

    with open(path, encoding="utf-8") as f:
        raw = yaml.safe_load(f) or {}

    return SystemConfig.model_validate(raw)
