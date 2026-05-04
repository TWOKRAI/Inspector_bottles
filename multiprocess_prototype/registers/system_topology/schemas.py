"""SystemTopology — единая модель конфигурации системы.

Объединяет четыре секции, редактируемые разными вкладками UI:
  - processes / workers  (Tab «Процессы»)
  - cameras / regions    (Tab «Источники»)
  - pipeline             (Tab «Pipeline»)
  - displays             (Tab «Дисплеи»)

Каждая секция использует свой транспорт при apply:
  - IPC Commands  → processes/workers (lifecycle)
  - Register Writes → cameras/regions/pipeline (параметры)
  - Direct API → displays (UI-виджеты)

См. ADR: «Three transport patterns — unified model, not transport»
"""

from __future__ import annotations

from typing import Annotated, Any, Dict, List

from pydantic import Field

from multiprocess_framework.modules.data_schema_module import (
    FieldMeta,
    SchemaBase,
    register_schema,
)

from ..sources.schemas import CameraSourceConfig, RegionSourceConfig


# ---------------------------------------------------------------------------
# Секция 1: Процессы
# ---------------------------------------------------------------------------


@register_schema("ProcessDefinitionV1")
class ProcessDefinition(SchemaBase):
    """Определение процесса в системной топологии."""

    name: Annotated[
        str,
        FieldMeta("Имя", info="Уникальное имя процесса (camera_0, processor_1...)."),
    ] = ""

    class_path: Annotated[
        str,
        FieldMeta("Класс", info="Полный Python-путь к классу процесса."),
    ] = ""

    priority: Annotated[
        str,
        FieldMeta("Приоритет", info="normal / high / realtime."),
    ] = "normal"

    auto_start: Annotated[
        bool,
        FieldMeta("Автозапуск", info="Запустить процесс сразу после создания."),
    ] = True

    sort_order: Annotated[
        int,
        FieldMeta("Порядок", info="Порядок отображения в дереве."),
    ] = 0

    plugins: Annotated[
        list[dict[str, Any]],
        FieldMeta(
            "Плагины",
            info="Упорядоченный список конфигов плагинов (PluginConfig.model_dump()).",
        ),
    ] = Field(default_factory=list)

    def plugin_names(self) -> list[str]:
        """Извлекает plugin_name из каждого плагина в цепочке."""
        return [p.get("plugin_name", "") for p in self.plugins]


@register_schema("WorkerDefinitionV1")
class WorkerDefinition(SchemaBase):
    """Определение воркера (потока) в процессе."""

    process_ref: Annotated[
        str,
        FieldMeta("Процесс", info="FK → ключ в processes."),
    ] = ""

    name: Annotated[
        str,
        FieldMeta("Имя", info="Имя воркера внутри процесса."),
    ] = ""

    worker_type: Annotated[
        str,
        FieldMeta("Тип", info="router_poll / loop / task."),
    ] = "router_poll"

    enabled: Annotated[
        bool,
        FieldMeta("Активен", info="Включён/выключен."),
    ] = True

    protected: Annotated[
        bool,
        FieldMeta("Защищён", info="True = первый воркер, нельзя удалить через GUI."),
    ] = False

    target_interval_ms: Annotated[
        int,
        FieldMeta(
            "Интервал",
            info="Целевой интервал цикла в мс (0 = без ограничения).",
            min=0,
            max=60000,
            unit="мс",
        ),
    ] = 0

    sort_order: Annotated[
        int,
        FieldMeta("Порядок", info="Порядок отображения."),
    ] = 0


# ---------------------------------------------------------------------------
# Секция 4: Дисплеи
# ---------------------------------------------------------------------------


@register_schema("DisplayDefinitionV1")
class DisplayDefinition(SchemaBase):
    """Определение display-окна в системной топологии."""

    name: Annotated[
        str,
        FieldMeta("Имя", info="Отображаемое имя окна."),
    ] = ""

    source_ref: Annotated[
        str,
        FieldMeta(
            "Источник",
            info="camera_0 или processor_0.region_0.step_1.",
        ),
    ] = ""

    fps_limit: Annotated[
        int,
        FieldMeta("FPS лимит", info="Ограничение частоты обновления.", min=1, max=120),
    ] = 30


# ---------------------------------------------------------------------------
# Секция 5: Wires (межпроцессные связи)
# ---------------------------------------------------------------------------


@register_schema("ShmWireConfigV1")
class ShmWireConfig(SchemaBase):
    """Конфигурация SharedMemory для wire-канала."""

    shm_name: Annotated[
        str,
        FieldMeta("Имя SHM", info="Имя SharedMemory региона (уникальное в системе)."),
    ] = ""

    buffer_slots: Annotated[
        int,
        FieldMeta(
            "Слоты буфера",
            info="Количество слотов ring-buffer (>= 2 для безопасного чтения).",
            min=2,
            max=32,
        ),
    ] = 4

    owner_process: Annotated[
        str,
        FieldMeta(
            "Владелец",
            info="Процесс-владелец SHM (create=True). Обычно — процесс-отправитель.",
        ),
    ] = ""

    strategy: Annotated[
        str,
        FieldMeta(
            "Стратегия",
            info="direct — прямая запись производителем; via_pm — через ProcessManager.",
        ),
    ] = "direct"


@register_schema("WireDefinitionV1")
class WireDefinition(SchemaBase):
    """Связь между портами плагинов разных процессов.

    Формат адреса: "process_name.plugin_name.port_name"
    Пример: "camera_0.capture.frame" → "processor_0.color_mask.frame"
    """

    source: Annotated[
        str,
        FieldMeta("Источник", info="process.plugin.port — выходной порт."),
    ] = ""

    target: Annotated[
        str,
        FieldMeta("Приёмник", info="process.plugin.port — входной порт."),
    ] = ""

    description: Annotated[
        str,
        FieldMeta("Описание", info="Человекочитаемое описание связи."),
    ] = ""

    transport: Annotated[
        str,
        FieldMeta(
            "Транспорт",
            info="router — через RouterManager + SHM; direct — будущее.",
        ),
    ] = "router"

    shm_config: Annotated[
        Dict[str, Any],
        FieldMeta(
            "SHM конфиг",
            info="Конфигурация SharedMemory канала (ShmWireConfig.model_dump()).",
        ),
    ] = Field(default_factory=dict)


# ---------------------------------------------------------------------------
# SystemTopology — корневая модель
# ---------------------------------------------------------------------------


@register_schema("SystemTopologyV1")
class SystemTopology(SchemaBase):
    """Полная конфигурация системы — единый объект, редактируемый UI по секциям.

    Вкладки UI:
      Tab «Процессы»   → processes, workers
      Tab «Источники»  → cameras, regions
      Tab «Pipeline»   → pipeline
      Tab «Дисплеи»    → displays
      Tab «Конструктор» → wires (межпроцессные связи)
    """

    # Секция 1: Процессы (Tab «Процессы»)
    processes: Annotated[
        Dict[str, ProcessDefinition],
        FieldMeta("Процессы", info="Все пользовательские процессы."),
    ] = Field(default_factory=dict)

    workers: Annotated[
        Dict[str, WorkerDefinition],
        FieldMeta("Воркеры", info="Потоки-воркеры внутри процессов."),
    ] = Field(default_factory=dict)

    # Секция 2: Источники (Tab «Источники»)
    # Реюз существующих схем из registers/sources/schemas.py
    cameras: Annotated[
        Dict[str, CameraSourceConfig],
        FieldMeta("Камеры", info="Все источники (камеры)."),
    ] = Field(default_factory=dict)

    regions: Annotated[
        Dict[str, RegionSourceConfig],
        FieldMeta("Регионы", info="Все регионы всех камер."),
    ] = Field(default_factory=dict)

    # Секция 3: Pipeline (Tab «Pipeline»)
    pipeline: Annotated[
        Dict[str, dict],
        FieldMeta("Pipeline", info="region_key → конфигурация обработки."),
    ] = Field(default_factory=dict)

    # Секция 4: Дисплеи (Tab «Дисплеи»)
    displays: Annotated[
        Dict[str, DisplayDefinition],
        FieldMeta("Дисплеи", info="Display-окна с подписками на источники."),
    ] = Field(default_factory=dict)

    # Секция 5: Wires (Tab «Конструктор»)
    wires: Annotated[
        Dict[str, WireDefinition],
        FieldMeta("Связи", info="Межпроцессные wire-связи между портами плагинов."),
    ] = Field(default_factory=dict)

    # ------------------------------------------------------------------
    # Валидация FK (foreign key)
    # ------------------------------------------------------------------

    def validate_refs(self) -> List[str]:
        """FK-валидация: workers→processes, regions→cameras, wires→processes.plugins.

        Returns:
            Список ошибок (пустой = всё ок).
        """
        errors: list[str] = []

        # workers.process_ref → processes key
        for wk, w in self.workers.items():
            if w.process_ref and w.process_ref not in self.processes:
                errors.append(
                    f"Worker '{wk}': process_ref '{w.process_ref}' не найден в processes"
                )

        # regions.camera_ref → cameras key
        for rk, r in self.regions.items():
            if r.camera_ref and r.camera_ref not in self.cameras:
                errors.append(
                    f"Region '{rk}': camera_ref '{r.camera_ref}' не найден в cameras"
                )

        # displays.source_ref — мягкая проверка (может ссылаться на pipeline output)
        for dk, d in self.displays.items():
            if d.source_ref and not self._is_valid_source_ref(d.source_ref):
                errors.append(
                    f"Display '{dk}': source_ref '{d.source_ref}' не распознан"
                )

        # plugins внутри каждого процесса
        for pk, proc in self.processes.items():
            seen_names: set[str] = set()
            for idx, plugin in enumerate(proc.plugins):
                # Обязательные ключи: plugin_class и plugin_name
                missing = [k for k in ("plugin_class", "plugin_name") if k not in plugin]
                if missing:
                    errors.append(
                        f"Process '{pk}': plugin[{idx}] не содержит обязательных ключей: "
                        + ", ".join(missing)
                    )
                    continue
                # Дубли plugin_name внутри одного процесса
                pname = plugin["plugin_name"]
                if pname in seen_names:
                    errors.append(
                        f"Process '{pk}': дублирующийся plugin_name '{pname}' в plugins"
                    )
                else:
                    seen_names.add(pname)

        # wires: source/target → "process.plugin.port" должны ссылаться на существующие
        all_plugin_names: dict[str, set[str]] = {}
        for pk, proc in self.processes.items():
            all_plugin_names[pk] = {
                p.get("plugin_name", "") for p in proc.plugins
            }

        for wk, wire in self.wires.items():
            for field_name, addr in [("source", wire.source), ("target", wire.target)]:
                if not addr:
                    errors.append(
                        f"Wire '{wk}': {field_name} пустой"
                    )
                    continue
                parts = addr.split(".")
                if len(parts) != 3:
                    errors.append(
                        f"Wire '{wk}': {field_name} '{addr}' — ожидается формат "
                        f"'process.plugin.port'"
                    )
                    continue
                proc_name, plugin_name, _port_name = parts
                if proc_name not in self.processes:
                    errors.append(
                        f"Wire '{wk}': {field_name} — процесс '{proc_name}' не найден"
                    )
                elif plugin_name not in all_plugin_names.get(proc_name, set()):
                    errors.append(
                        f"Wire '{wk}': {field_name} — плагин '{plugin_name}' "
                        f"не найден в процессе '{proc_name}'"
                    )

        return errors

    def _is_valid_source_ref(self, ref: str) -> bool:
        """Проверить что source_ref валиден.

        Допустимые форматы:
          camera_{id}                     → камера из cameras
          processor_{id}.{region}.{step}  → выход pipeline
        """
        # Простая проверка: ссылается ли на известную камеру
        for cam_key, cam in self.cameras.items():
            if ref == f"camera_{cam.camera_id}":
                return True
            if ref == cam.process_name:
                return True
        # Pipeline output — формат processor_*.*.* допускаем
        if ref.startswith("processor_"):
            return True
        return False

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def workers_for_process(self, proc_key: str) -> Dict[str, WorkerDefinition]:
        """Все воркеры, привязанные к процессу."""
        return {k: v for k, v in self.workers.items() if v.process_ref == proc_key}

    def regions_for_camera(self, camera_key: str) -> Dict[str, RegionSourceConfig]:
        """Все регионы, привязанные к камере."""
        return {k: v for k, v in self.regions.items() if v.camera_ref == camera_key}


# ---------------------------------------------------------------------------
# Константы секций (для per-section dirty tracking)
# ---------------------------------------------------------------------------

SECTION_PROCESSES = "processes"
"""Секция процессов: processes + workers."""

SECTION_SOURCES = "sources"
"""Секция источников: cameras + regions."""

SECTION_PIPELINE = "pipeline"
"""Секция pipeline."""

SECTION_DISPLAYS = "displays"
"""Секция дисплеев."""

SECTION_WIRES = "wires"
"""Секция межпроцессных wire-связей (Tab «Конструктор»)."""

# Маппинг секция → ключи в SystemTopology
SECTION_KEYS = {
    SECTION_PROCESSES: ("processes", "workers"),
    SECTION_SOURCES: ("cameras", "regions"),
    SECTION_PIPELINE: ("pipeline",),
    SECTION_DISPLAYS: ("displays",),
    SECTION_WIRES: ("wires",),
}

ALL_SECTIONS = (
    SECTION_PROCESSES,
    SECTION_SOURCES,
    SECTION_PIPELINE,
    SECTION_DISPLAYS,
    SECTION_WIRES,
)


__all__ = [
    "ProcessDefinition",
    "WorkerDefinition",
    "DisplayDefinition",
    "ShmWireConfig",
    "WireDefinition",
    "SystemTopology",
    "SECTION_PROCESSES",
    "SECTION_SOURCES",
    "SECTION_PIPELINE",
    "SECTION_DISPLAYS",
    "SECTION_WIRES",
    "SECTION_KEYS",
    "ALL_SECTIONS",
]
