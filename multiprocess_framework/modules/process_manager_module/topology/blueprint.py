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

from loguru import logger
from pydantic import field_validator

from ...data_schema_module import FieldMeta, SchemaBase, register_schema
from ...process_module.plugins.port import Port, are_ports_compatible, validate_chain
from ...process_module.plugins.registry import PluginRegistry
from ...process_module.generic.generic_process_config import GenericProcessConfig, PluginConfig


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

    @field_validator("priority", mode="before")
    @classmethod
    def _priority_not_none(cls, v: Any) -> Any:
        """GUI-нормализованные рецепты пишут пустой скаляр как explicit-null (YAML `priority:`).

        priority — обязательный str с дефолтом, поэтому None/"" ломали бы валидацию при
        hot-apply (boot маскирует это base-merge'ем, hot-apply — нет). Приводим к дефолту.
        """
        return "normal" if v is None or v == "" else v

    process_class: Annotated[
        str,
        FieldMeta("Класс процесса", info="Dotted path к классу (по умолчанию GenericProcess)"),
    ] = ""

    protected: Annotated[
        bool,
        FieldMeta("Protected", info="always-on: replace_blueprint/hot-apply процесс не останавливает."),
    ] = False

    restart_policy: Annotated[
        dict[str, Any],
        FieldMeta(
            "Restart policy",
            info="Per-process авто-рестарт: {enabled, max_retries, backoff_sec, window_sec}. "
            "Пусто → глобальная политика. Рецепт задаёт для source/hub (Ф3.8/G1).",
        ),
    ] = {}

    # --- Data Pipeline routing (Phase 5) ---

    chain_targets: Annotated[
        list[str],
        FieldMeta("Chain targets", info="Куда отправлять результат pipeline (имена процессов)."),
    ] = []

    source_target_fps: Annotated[
        float,
        FieldMeta("Source target FPS", info="Целевой FPS для source-плагинов.", min=1.0),
    ] = 25.0

    inspector: Annotated[
        dict[str, Any],
        FieldMeta("Inspector", info="Режим корреляции DataReceiver: {mode: fanin|join, inputs, primary, ...}"),
    ] = {}

    io_peek: Annotated[
        dict[str, Any],
        FieldMeta("io-debug", info="Сводка in/out плагинов в дерево: {enabled, rate_hz, head_len}"),
    ] = {}

    # --- Domain-opaque bag (C6 рычаг 1) ---

    extras: Annotated[
        dict[str, Any],
        FieldMeta(
            "Extras",
            info="Domain-opaque мешок: pipeline-специфичные ключи (inspector/chain_targets/"
            "io_peek/...), которые framework не обязан знать по имени. Зеркалит формат "
            "app.yaml/manifest 'version + extras'. Типизированные поля выше — shorthand для "
            "самых частых ключей и имеют приоритет над одноимёнными в extras.",
        ),
    ] = {}

    metadata: Annotated[
        dict[str, Any],
        FieldMeta(
            "Metadata",
            info="Domain-opaque бэг GUI-редактора (домен-entity Process не имеет типизир. "
            "полей вроде inspector — при сохранении сворачивает их сюда). Раньше молча "
            "терялся (extra=ignore до model_validate, см. снятый _hoist_inspector_from_"
            "metadata); теперь обычное typed-поле — не отбрасывается. Единственный "
            "потребитель — SystemBlueprint.infer_missing_inspectors() (тонкая настройка "
            "inspector.timeout_sec/... из legacy metadata.inspector, Ф4.7).",
        ),
    ] = {}

    def as_generic_config(self) -> GenericProcessConfig:
        """Конвертировать в GenericProcessConfig для launcher."""
        # Восстановить PluginConfig-инстансы для агрегации memory
        plugin_configs = _restore_plugin_configs(self.plugins)

        # Базовые kwargs — process_class передаётся если задан
        base_kwargs: dict = dict(priority=self.priority)
        if self.process_class:
            base_kwargs["process_class"] = self.process_class
        # protected пробрасываем всегда (нужен PM для skip при replace_blueprint)
        if self.protected:
            base_kwargs["protected"] = self.protected
        # restart_policy per-process (Ф3.6): непустой → в GenericProcessConfig →
        # build() вынесет на верхний уровень proc_dict → ProcessMonitor._resolve_policy.
        if self.restart_policy:
            base_kwargs["restart_policy"] = self.restart_policy

        # Data Pipeline routing.
        # C6 рычаг 1: приоритет typed-поля, ИНАЧЕ extras[key] — 100% back-compat для старых
        # рецептов, новые доменные ключи живут в extras без правки framework-схемы.
        #
        # Fable MED-4: «задано явно» определяем через Pydantic model_fields_set, НЕ через
        # sentinel-значение. Раньше `!= 25.0` / `or []` считали явный typed=25.0 (или явный
        # пустой список) «незаданным» → extras молча побеждал явный пин рецепта. Теперь
        # рецепт, явно указавший поле, всегда имеет приоритет над одноимённым в extras.
        extras = self.extras or {}
        fields_set = self.model_fields_set

        def _pick(key: str, default):
            if key in fields_set:  # рецепт задал typed-поле явно — оно и побеждает
                # Fable LOW-5: конфликт typed≠extras при обоих заданных — предупреждаем.
                if key in extras and extras[key] != getattr(self, key):
                    logger.warning(
                        f"ProcessConfig[{self.process_name}]: typed-поле '{key}'="
                        f"{getattr(self, key)!r} перекрывает extras['{key}']={extras[key]!r} "
                        f"(typed-приоритет)."
                    )
                return getattr(self, key)
            return extras.get(key, default)

        chain_targets = _pick("chain_targets", [])
        source_fps = _pick("source_target_fps", 25.0)
        inspector = _pick("inspector", {})
        io_peek = _pick("io_peek", {})
        if chain_targets:
            base_kwargs["chain_targets"] = chain_targets
        if source_fps != 25.0:
            base_kwargs["source_target_fps"] = source_fps
        if inspector:
            base_kwargs["inspector"] = inspector
        if io_peek:
            base_kwargs["io_peek"] = io_peek

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
    def from_plugins(cls, process_name: str, *plugins: PluginConfig, priority: str = "normal") -> ProcessConfig:
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

    def infer_missing_inspectors(self) -> None:
        """Вывести inspector(join) из wires для процессов без явного inspector (Ф4.7).

        Заменяет костыль ``_hoist_inspector_from_metadata`` (снят вместе с этим методом):
        раньше корректность join зависела от того, попал ли ``inspector`` в правильное
        место рецепта (прямой ключ vs ``metadata`` — GUI-save мог молча уронить его туда,
        где бэкенд его не видел). Теперь join — СТРУКТУРНЫЙ факт графа wires, не зависит
        от расположения поля.

        Признак join: процесс получает REQUIRED-порт(ы) (``Port.optional is False``) от
        ≥2 РАЗНЫХ процессов-источников. Считаем именно процессы, не wires — один источник
        может слать несколько полей одним item (тот же ``data_type``, см.
        ``PipelineExecutor``/``SourceProducer``), поэтому N wires от одного процесса — всё
        ещё ОДИН вход для join. Опциональные порты (``optional=True`` — триггеры/
        best-effort сигналы, напр. пульт) НЕ считаются: подтверждено на живых рецептах —
        ``layout``/``points`` получают ≥2 источника, но все входы кроме одного
        опциональны → остаются fanin (иначе false positive).

        Тег входа берётся из SOURCE-порта wire (не target) — это имя = ``data_type``
        конвенция продюсера (``item.setdefault("data_type", "frame")``, плагины вроде
        ``line_filter`` переопределяют на свой output-порт), а НЕ имя порта получателя
        (может отличаться — см. ``center_crop.trigger_in`` ← источник
        ``line_filter.overlay``, тег всё равно "overlay"). "frame" — приоритетный
        тег/primary, если есть среди источников; иначе первый по алфавиту.

        Тонкая настройка (``timeout_sec``/``list_merge_keys``/``inactive_sec``) не
        выводима из графа — если есть в ``metadata.inspector`` (legacy GUI-save путь),
        подмешивается поверх структурного skeleton'а; ``metadata`` больше не молча
        теряется (``extra=ignore`` раньше отбрасывал её до ``model_validate``) — стала
        обычным typed-полем.

        Явный ``inspector`` (прямой typed-ключ ИЛИ ``extras["inspector"]``) —
        приоритетнее и НЕ переопределяется: ручная настройка выигрывает у вывода из графа.

        Мутирует ``self.processes`` IN PLACE. Вызывать ПОСЛЕ ``model_validate``
        (валидация уже сделала копию — мутация внутренней копии, не входа вызывающей
        стороны), ДО ``build_configs()``/``check()``.
        """
        # target_process -> {source_process -> {source_port_names}}, только REQUIRED
        # входы (optional-порты в join-обязательство не входят).
        required_sources: dict[str, dict[str, set[str]]] = {}

        for wire in self.wires:
            src_parts = wire.source.split(".")
            tgt_parts = wire.target.split(".")
            if len(src_parts) != 3 or len(tgt_parts) != 3:
                continue  # не "process.plugin.port" — пропускаем

            src_process, _src_plugin, src_port = src_parts
            tgt_process, tgt_plugin, tgt_port_name = tgt_parts

            entry = _find_plugin_entry(tgt_plugin, "")
            if entry is None:
                continue
            tgt_port = next((p for p in entry.inputs if p.name == tgt_port_name), None)
            if tgt_port is None or tgt_port.optional:
                continue

            by_source = required_sources.setdefault(tgt_process, {})
            by_source.setdefault(src_process, set()).add(src_port)

        for proc in self.processes:
            if proc.inspector or (proc.extras or {}).get("inspector"):
                continue  # явный inspector — приоритет, вывод не применяется

            sources = required_sources.get(proc.process_name, {})
            if len(sources) < 2:
                continue  # < 2 required-источников — join не нужен (fanin остаётся дефолтом)

            tags = ["frame" if "frame" in ports else sorted(ports)[0] for _src, ports in sorted(sources.items())]
            unique_tags = sorted(set(tags), key=lambda t: (t != "frame", t))
            primary = "frame" if "frame" in unique_tags else unique_tags[0]

            derived: dict[str, Any] = {"mode": "join", "inputs": unique_tags, "primary": primary}

            # Legacy-путь: тонкая настройка из metadata.inspector (структурные поля
            # mode/inputs/primary остаются авторитетны из wires, не из metadata).
            legacy = proc.metadata.get("inspector") if isinstance(proc.metadata, dict) else None
            if isinstance(legacy, dict):
                for key, value in legacy.items():
                    if key not in ("mode", "inputs", "primary"):
                        derived[key] = value

            proc.inspector = derived

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
        input_map: dict[str, Port] = {}  # address → Port
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

        # Ф4.3 (C-4): оживление validate_chain — детальная диагностика ВНУТРИпроцессной
        # линейной цепочки auto-wiring (какой плагин -> какой плагин, какой dtype
        # несовместим), точка сборки — этот же check(). Входы, уже покрытые явным
        # межпроцессным Wire (wired_inputs), исключаем из проверки: они не обязаны
        # совпадать с ВЫХОДОМ предыдущего по позиции плагина (fan-in — второй вход
        # приходит извне, а не по цепочке). Дублирует по сути bool-проверку
        # _is_covered_by_auto_wiring ниже (тот же are_ports_compatible), но с
        # человекочитаемым сообщением вместо generic «не подключён».
        for proc in self.processes:
            chain: list[tuple[str, list[Port], list[Port]]] = []
            for pdict in proc.plugins:
                plugin_name = pdict.get("plugin_name", "")
                plugin_class = pdict.get("plugin_class", "")
                entry = _find_plugin_entry(plugin_name, plugin_class)
                if entry is None:
                    chain.append((plugin_name, [], []))
                    continue
                addr_prefix = f"{proc.process_name}.{plugin_name}."
                chain_inputs = [p for p in entry.inputs if (addr_prefix + p.name) not in wired_inputs]
                chain.append((plugin_name, chain_inputs, list(entry.outputs)))
            errors.extend(validate_chain(chain))

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
        plugin_name = pdict.get("plugin_name", "")

        # Short-name resolution через PluginRegistry: если plugin_class пуст
        # или короткое имя — пытаемся найти entry.class_path.
        if not plugin_class_path or "." not in plugin_class_path:
            candidate = plugin_class_path or plugin_name
            entry = PluginRegistry.get(candidate) if candidate else None
            if entry is not None:
                plugin_class_path = entry.class_path

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
            if isinstance(attr, type) and issubclass(attr, PluginConfig) and attr is not PluginConfig:
                try:
                    configs.append(attr.model_validate(pdict))
                    break
                except Exception:  # nosec B110 — best-effort: перебор PluginConfig-наследников, несовпадение схемы ожидаемо
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
