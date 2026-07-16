"""Pydantic-схемы для system.yaml — валидация defaults."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated, Any, Literal

import yaml
from pydantic import BaseModel, Field

from multiprocess_framework.modules.data_schema_module import (
    FieldMeta,
    SchemaBase,
    deep_merge,
)
from multiprocess_framework.modules.process_module.configs import (
    ObservabilityConfig,
    TelemetryPublishConfig,
)


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


class BackendCtlSection(SchemaBase):
    """Dev-инструмент: SocketChannel для headless-управления бэкендом (BackendDriver/MCP).

    Гейт сокета. Включённый — поднимает TCP-endpoint в ProcessManager (localhost),
    через который driver шлёт те же router-команды, что GUI. В проде держать выключенным.
    Env BACKEND_CTL=1 — независимый escape-hatch (включает без правки yaml).
    """

    enabled: Annotated[
        bool,
        FieldMeta("Backend-control сокет", info="Поднять dev-сокет управления бэкендом (BackendDriver/MCP)."),
    ] = False

    port: Annotated[
        int,
        FieldMeta("Порт сокета", info="TCP-порт backend-control endpoint (localhost).", min=1024, max=65535),
    ] = 8765

    host: Annotated[
        str,
        FieldMeta("Bind-адрес", info="Адрес привязки сокета. Только localhost для dev-безопасности."),
    ] = "127.0.0.1"


class TelemetrySection(SchemaBase):
    """Глобальные дефолты публикации телеметрии (PC 1.3, Фаза 1 плана telemetry-publish-control).

    ``publish`` — framework-контракт ``TelemetryPublishConfig`` (per-метрика вкл/выкл +
    частота, publisher-gate в heartbeat, PC 1.1/1.2). Дефолт — **None** («секция
    отсутствует»): ``BlueprintAssembler`` кладёт ключ ``telemetry`` в ``proc_dict['config']``
    ТОЛЬКО когда секция реально задана (здесь глобально ИЛИ per-process в
    ``blueprint.processes[].telemetry``). Если задать ``publish`` явно (даже пустым
    ``{}``) — секция считается заданной, и heartbeat строит ``TelemetryGate`` для всех
    процессов (backward-compat завязан именно на отсутствие/присутствие, см. PC 1.2
    ``_build_telemetry_gate``).

    ``throttle`` — задел под центральный store-троттл (Фаза 2 плана). Поле заведено под
    будущий ``build_throttle_rules(sys_config)``, но в PC 1.3 НЕ читается нигде.
    """

    publish: Annotated[
        TelemetryPublishConfig | None,
        FieldMeta(
            "Публикация телеметрии",
            info="Глобальный дефолт per-метрика вкл/выкл + частота (per-process в "
            "рецепте переопределяет). None = секция отсутствует — публикация без "
            "гейта, как до PC 1.x.",
        ),
    ] = None

    throttle: Annotated[
        dict[str, float],
        FieldMeta(
            "Центральный троттл (задел Фазы 2)",
            info="Правила {glob_pattern: min_interval_sec} для ThrottleMiddleware "
            "StateStoreManager. Заведено под Фазу 2 — build_throttle_rules пока их не читает.",
        ),
    ] = {}


class SystemConfig(SchemaBase):
    """Корневая схема system.yaml."""

    system: SystemSection = SystemSection()
    camera: CameraDefaults = CameraDefaults()
    processing: ProcessingDefaults = ProcessingDefaults()
    display: DisplayDefaults = DisplayDefaults()
    storage: StorageDefaults = StorageDefaults()
    discovery: DiscoverySection = DiscoverySection()
    backend_ctl: BackendCtlSection = BackendCtlSection()
    observability: ObservabilityConfig = ObservabilityConfig()
    telemetry: TelemetrySection = TelemetrySection()

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


def _deep_merge(base: dict, override: dict) -> dict:
    """Рекурсивно слить override поверх base.

    Тонкий делегат канонического ``deep_merge`` (дубль D3 / задача C5).
    Правила сохранены: dict+dict мержатся рекурсивно, иначе override заменяет
    base; аргументы не мутируются. Имя оставлено для обратной совместимости.

    Args:
        base:     Базовый словарь (нижний приоритет).
        override: Словарь переопределений (верхний приоритет).

    Returns:
        Новый dict — результат глубокого слияния.
    """
    return deep_merge(base, override)


def load_system_config(path: Path | str | None = None) -> SystemConfig:
    """Загрузить и валидировать system.yaml, автоматически подхватывая user_overrides.yaml.

    Если рядом с system.yaml существует user_overrides.yaml — его содержимое
    deep-merge'ится поверх базового конфига (override имеет приоритет).
    Пустой или невалидный user_overrides.yaml игнорируется с предупреждением.

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

    # Автоматически подхватить user_overrides.yaml рядом с system.yaml
    override_path = path.parent / "user_overrides.yaml"
    if override_path.exists():
        try:
            with open(override_path, encoding="utf-8") as f:
                override_raw = yaml.safe_load(f) or {}
            raw = _deep_merge(raw, override_raw)
        except yaml.YAMLError as e:
            print(f"[config] user_overrides.yaml: ошибка разбора: {e}")

    return SystemConfig.model_validate(raw)


# ---------------------------------------------------------------------------
# Схемы для displays.yaml (Task 4.4)
# ---------------------------------------------------------------------------


class DisplayEntrySchema(BaseModel):
    """Pydantic-схема одной записи дисплея — валидирует displays.yaml.

    Соответствует полям ``DisplayEntry`` из display_module.
    Намеренно НЕ импортирует ``DisplayEntry`` — схема работает на dict-уровне
    (Dict at Boundary). Конвертация в ``DisplayEntry`` — в ``displays_loader.py``.

    Attributes:
        id:                 Уникальный идентификатор дисплея (ключ в реестре).
        name:               Человекочитаемое имя дисплея.
        width:              Ширина кадра в пикселях (1..7680).
        height:             Высота кадра в пикселях (1..7680).
        format:             Формат пикселей кадра.
        fps_limit:          Ограничение частоты кадров (0..240).
        ring_buffer_blocks: Количество SHM-блоков в ring-buffer (1..32).
    """

    id: str
    name: str
    width: Annotated[int, Field(gt=0, le=7680)]
    height: Annotated[int, Field(gt=0, le=7680)]
    format: Literal["BGR", "RGB", "GRAY", "RGBA"]
    fps_limit: Annotated[float, Field(ge=0.0, le=240.0)]
    ring_buffer_blocks: Annotated[int, Field(ge=1, le=32)]


class DisplaysConfig(BaseModel):
    """Pydantic-схема файла displays.yaml — список записей дисплеев.

    Корневой объект при валидации через ``model_validate(raw_dict)``.
    Пустой список ``displays`` — допустимое состояние (нет зарегистрированных дисплеев).

    Attributes:
        displays: Список записей дисплеев.
    """

    displays: list[DisplayEntrySchema] = []
