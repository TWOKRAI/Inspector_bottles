"""SystemBlueprint — SchemaBase-чертёж системы.

Всё — SchemaBase: чертёж, процесс, связи.
Сериализуемый, валидируемый, редактируемый в UI, сохраняемый как рецепт.

Использование:
    blueprint = SystemBlueprint(
        name="color_mask_demo",
        processes=[
            ProcessConfig(process_name="camera_0", plugins=[...]),
            ProcessConfig(process_name="processor_0", plugins=[...]),
        ],
        wires=[
            Wire(source="camera_0.capture.frame", target="processor_0.color_mask.frame"),
        ],
    )

    errors = blueprint.validate()      # проверка портов до запуска
    configs = blueprint.build_configs() # → list[GenericProcessConfig]
"""

from __future__ import annotations

from typing import Annotated, Any

from ...data_schema_module import FieldMeta, SchemaBase, register_schema
from ..plugins.port import Port, are_ports_compatible
from ..plugins.registry import PluginRegistry
from .generic_process_config import GenericProcessConfig, PluginConfig


@register_schema("WireV1")
class Wire(SchemaBase):
    """Связь между портами разных процессов.

    Формат адреса: "process_name.plugin_name.port_name"
    Пример: "camera_0.capture.frame" → "processor_0.color_mask.frame"
    """

    source: Annotated[
        str,
        FieldMeta("Источник", info="process.plugin.port — выходной порт"),
    ] = ""

    target: Annotated[
        str,
        FieldMeta("Приёмник", info="process.plugin.port — входной порт"),
    ] = ""

    description: Annotated[
        str,
        FieldMeta("Описание", info="Человекочитаемое описание связи"),
    ] = ""


@register_schema("ProcessConfigV1")
class ProcessConfig(SchemaBase):
    """Конфиг одного процесса в чертеже — SchemaBase.

    Содержит упорядоченный список плагинов.
    Порядок = порядок выполнения (configure/start).
    Shutdown — в обратном порядке.
    """

    process_name: Annotated[
        str,
        FieldMeta("Имя процесса", info="Уникальное имя в системе"),
    ] = ""

    plugins: Annotated[
        list[dict[str, Any]],
        FieldMeta("Плагины", info="Упорядоченный список (PluginConfig.model_dump())"),
    ] = []

    priority: Annotated[
        str,
        FieldMeta("Приоритет", info="normal | high | low"),
    ] = "normal"

    process_class: Annotated[
        str,
        FieldMeta("Класс процесса", info="Dotted path к классу (по умолчанию GenericProcess)"),
    ] = ""

    # --- Data Pipeline routing (Phase 5) ---

    chain_targets: Annotated[
        list[str],
        FieldMeta("Chain targets", info="Куда отправлять результат pipeline (имена процессов)."),
    ] = []

    source_target_fps: Annotated[
        float,
        FieldMeta("Source target FPS", info="Целевой FPS для source-плагинов.", min=1.0),
    ] = 25.0

    def as_generic_config(self) -> GenericProcessConfig:
        """Конвертировать в GenericProcessConfig для launcher."""
        # Восстановить PluginConfig-инстансы для агрегации memory
        plugin_configs = _restore_plugin_configs(self.plugins)

        # Базовые kwargs — process_class передаётся если задан
        base_kwargs: dict = dict(priority=self.priority)
        if self.process_class:
            base_kwargs["process_class"] = self.process_class

        # Data Pipeline routing
        if self.chain_targets:
            base_kwargs["chain_targets"] = self.chain_targets
        if self.source_target_fps != 25.0:
            base_kwargs["source_target_fps"] = self.source_target_fps

        if plugin_configs:
            return GenericProcessConfig.from_plugins(
                process_name=self.process_name,
                plugin_configs=plugin_configs,
                **base_kwargs,
            )

        return GenericProcessConfig(
            process_name=self.process_name,
            plugins=self.plugins,
            **base_kwargs,
        )

    @classmethod
    def from_plugins(
        cls, process_name: str, *plugins: PluginConfig, priority: str = "normal"
    ) -> ProcessConfig:
        """Удобный конструктор: принимает PluginConfig-объекты напрямую."""
        return cls(
            process_name=process_name,
            plugins=[p.model_dump() for p in plugins],
            priority=priority,
        )


@register_schema("SystemBlueprintV1")
class SystemBlueprint(SchemaBase):
    """Чертёж всей системы — SchemaBase.

    Описывает процессы, плагины и связи между ними.
    Валидируемый, сериализуемый, редактируемый в UI.
    """

    name: Annotated[
        str,
        FieldMeta("Имя", info="Название конфигурации системы"),
    ] = "default"

    description: Annotated[
        str,
        FieldMeta("Описание", info="Что делает эта конфигурация"),
    ] = ""

    processes: Annotated[
        list[ProcessConfig],
        FieldMeta("Процессы", info="Список процессов с плагинами"),
    ] = []

    wires: Annotated[
        list[Wire],
        FieldMeta("Связи", info="Межпроцессные связи между портами"),
    ] = []

    def build_configs(self) -> list[GenericProcessConfig]:
        """Собрать список GenericProcessConfig для launcher."""
        return [p.as_generic_config() for p in self.processes]

    def shm_names(self) -> list[str]:
        """Все SHM-имена из всех процессов."""
        names = []
        for cfg in self.build_configs():
            mem = cfg.memory
            if mem:
                names.extend(k for k in mem if k != "coll")
        return names

    def check(self) -> list[str]:
        """Валидация чертежа до запуска.

        Проверяет:
        1. Цепочки плагинов внутри каждого процесса (auto-wiring)
        2. Wire-связи между процессами (совместимость портов)
        3. Все обязательные входы подключены

        Returns:
            Список ошибок. Пустой = всё ОК.
        """
        errors: list[str] = []

        # Раздельные карты входов и выходов — плагин может иметь
        # одноимённые input/output порты (e.g. "frame" → "frame")
        input_map: dict[str, Port] = {}   # address → Port
        output_map: dict[str, Port] = {}  # address → Port
        process_names = set()

        for proc in self.processes:
            if proc.process_name in process_names:
                errors.append(f"Дублирование имени процесса: '{proc.process_name}'")
            process_names.add(proc.process_name)

            for pdict in proc.plugins:
                plugin_name = pdict.get("plugin_name", "")
                plugin_class = pdict.get("plugin_class", "")

                # Ищем плагин в реестре для получения портов
                entry = _find_plugin_entry(plugin_name, plugin_class)
                if entry is None:
                    continue

                for port in entry.inputs:
                    addr = f"{proc.process_name}.{plugin_name}.{port.name}"
                    input_map[addr] = port

                for port in entry.outputs:
                    addr = f"{proc.process_name}.{plugin_name}.{port.name}"
                    output_map[addr] = port

        # Проверяем Wire-связи
        wired_inputs: set[str] = set()

        for wire in self.wires:
            if wire.source not in output_map:
                errors.append(f"Wire: источник '{wire.source}' не найден среди выходов")
                continue
            if wire.target not in input_map:
                errors.append(f"Wire: приёмник '{wire.target}' не найден среди входов")
                continue

            src_port = output_map[wire.source]
            tgt_port = input_map[wire.target]

            if not are_ports_compatible(src_port, tgt_port):
                errors.append(
                    f"Wire: {wire.source} ({src_port.dtype} {src_port.shape}) "
                    f"несовместим с {wire.target} ({tgt_port.dtype} {tgt_port.shape})"
                )
            else:
                wired_inputs.add(wire.target)

        # Проверяем обязательные входы
        for addr, port in input_map.items():
            if not port.optional and addr not in wired_inputs:
                # Входы внутри процесса могут быть покрыты auto-wiring
                # (предыдущий плагин в цепочке), пропускаем такие
                parts = addr.split(".")
                if len(parts) == 3:
                    proc_name = parts[0]
                    proc_cfg = next((p for p in self.processes if p.process_name == proc_name), None)
                    if proc_cfg and _is_covered_by_auto_wiring(proc_cfg, parts[1], port):
                        continue
                errors.append(f"Вход '{addr}' ({port.dtype}) не подключен")

        return errors

    def describe(self) -> str:
        """Текстовое описание чертежа."""
        lines = [f"Blueprint: {self.name}"]
        if self.description:
            lines.append(f"  {self.description}")
        for proc in self.processes:
            plugins = [p.get("plugin_name", "?") for p in proc.plugins]
            chain = " \u2192 ".join(plugins)
            lines.append(f"  {proc.process_name}: [{chain}]")
        if self.wires:
            lines.append("  Wires:")
            for w in self.wires:
                lines.append(f"    {w.source} \u2192 {w.target}")
        return "\n".join(lines)


# --- Вспомогательные функции ---

def _restore_plugin_configs(plugins_dicts: list[dict]) -> list[PluginConfig]:
    """Восстановить PluginConfig-инстансы из dict'ов."""
    import importlib

    configs = []
    for pdict in plugins_dicts:
        plugin_class_path = pdict.get("plugin_class", "")
        if not plugin_class_path:
            continue

        # Ищем config модуль рядом с plugin
        parts = plugin_class_path.rsplit(".", 2)
        if len(parts) < 3:
            continue

        config_module_path = f"{parts[0]}.config"
        try:
            config_module = importlib.import_module(config_module_path)
        except ImportError:
            continue

        for attr_name in dir(config_module):
            attr = getattr(config_module, attr_name)
            if (
                isinstance(attr, type)
                and issubclass(attr, PluginConfig)
                and attr is not PluginConfig
            ):
                try:
                    configs.append(attr.model_validate(pdict))
                    break
                except Exception:
                    pass

    return configs


def _find_plugin_entry(plugin_name: str, plugin_class: str):
    """Найти плагин в реестре по имени или class path."""
    entry = PluginRegistry.get(plugin_name)
    if entry:
        return entry

    # Fallback: поиск по class_path
    for e in PluginRegistry.list():
        if e.class_path == plugin_class:
            return e

    return None


def _is_covered_by_auto_wiring(proc: ProcessConfig, plugin_name: str, input_port: Port) -> bool:
    """Проверить покрыт ли вход auto-wiring внутри процесса.

    Если предыдущий плагин в цепочке имеет совместимый выход — покрыт.
    """
    plugin_names = [p.get("plugin_name", "") for p in proc.plugins]

    try:
        idx = plugin_names.index(plugin_name)
    except ValueError:
        return False

    if idx == 0:
        return False  # первый в цепочке — нет предшественника

    # Проверяем предыдущий плагин
    prev_name = plugin_names[idx - 1]
    prev_class = proc.plugins[idx - 1].get("plugin_class", "")
    prev_entry = _find_plugin_entry(prev_name, prev_class)
    if prev_entry is None:
        return False

    for out_port in prev_entry.outputs:
        if are_ports_compatible(out_port, input_port):
            return True

    return False
