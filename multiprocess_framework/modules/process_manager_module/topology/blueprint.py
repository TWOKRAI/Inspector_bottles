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

    @field_validator("process_class", mode="before")
    @classmethod
    def _process_class_not_none(cls, v: Any) -> Any:
        """Домен-entity ``Process.process_class`` — ``str | None = None`` (см. domain/entities/
        process.py); ``Process.to_dict()`` (``model_dump(mode="json")``) пишет ``None`` явно для
        процессов без явного класса. ``ProcessConfig.process_class`` — обязательный ``str`` с
        дефолтом ``""`` — без этого коэрсера ``SystemBlueprint.model_validate()`` падал бы на
        КАЖДОМ процессе без явного class (RS-5: обнаружено gate-валидацией ``check_structure()``
        на Save/load-from-file — см. ``_priority_not_none`` выше, тот же класс дефекта).
        """
        return "" if v is None else v

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

        **Известный edge (в): источник с ДВУМЯ РАЗНЫМИ тегами → берётся ОДИН (AU-3,
        follow-up В1, ADR-PMM-017 п.6).** Если источник шлёт ≥2 РАЗНЫХ source-порта
        одному target (напр. "frame" и "detections" — двойник живого
        ``circle_detector`` → ``circle_draw.frame``/``circle_draw.detections`` в
        ``hikvision_letter_robot.yaml``), тег на этот источник берётся ОДИН
        ("frame"-приоритет, иначе первый по алфавиту среди ВСЕХ src-портов этого
        источника, вне зависимости от того, на сколько разных target-портов они
        распределены) — не задокументированный полный список. Это НЕ доработано в
        группировку "1 источник = N тегов по числу его target-портов", потому что
        структурно неотличимо от легитимного "несколько полей ОДНОГО item на разные
        параметры соседнего плагина" (тот самый ``circle_draw`` — frame+detections из
        ОДНОГО кадра, не 2 независимых потока с разным timing) — граф wires не хранит
        "это один runtime item или два". См. ``ADR-PMM-017`` п.6.

        **ИНВАРИАНТ (ADR-PMM-017, process_manager_module/DECISIONS.md):** тег = имя
        source-порта совпадает с реальным runtime ``data_type`` ТОЛЬКО по конвенции
        «имя output-порта плагина == emitted data_type» — это конвенция кодовой базы,
        НЕ проверяемый инвариант схемы. Плагин, чей output-порт назван иначе, чем
        ``data_type``, который он реально ставит в item, даст расхождение
        ``inputs`` ↔ реальная корреляция (тихая деградация в passthrough одного
        primary по таймауту, без крэша). Два источника с ОДИНАКОВЫМ тегом (напр. две
        камеры, обе с source-портом "frame") коллапсируют в join с ОДНИМ элементом
        ``inputs`` — ждёт первый прибывший item с этим тегом, а не оба источника
        (было — plain fanin). Оба случая — задокументированная граница, не баг;
        рецепт, которому нужно иное поведение, обязан объявить явный ``inspector``
        (escape-hatch, включая ``{mode: fanin}``) — см. ADR-PMM-017 п.3/4.

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
        # входы (optional-порты в join-обязательство не входят). Группировка НЕ по
        # target_port (проверено на живом рецепте, AU-3/follow-up В1 — см. docstring
        # "Известный edge (в)"): источник, кормящий несколько РАЗНЫХ target-портов
        # ОДНОГО процесса (frame+detections одного item на 2 параметра плагина), не
        # отличим структурно от источника с genuinely двумя независимыми потоками —
        # группировка по source_process (не по source+target_port) сохраняет прежнее
        # поведение для обоих случаев.
        required_sources: dict[str, dict[str, set[str]]] = {}

        # (process_name, plugin_name) -> plugin_class — симметрия с check() (AU-4,
        # follow-up В1): там `_find_plugin_entry(plugin_name, plugin_class)` берёт
        # plugin_class ИЗ pdict, поэтому лукап плагина, находимого ТОЛЬКО по
        # class-path (нестандартное/переопределённое имя), там резолвится. Здесь
        # раньше всегда передавался "" вторым аргументом — class-path fallback
        # в `_find_plugin_entry` был мёртвым кодом для этого вызова.
        plugin_class_by_addr: dict[tuple[str, str], str] = {
            (proc.process_name, pdict.get("plugin_name", "")): pdict.get("plugin_class", "")
            for proc in self.processes
            for pdict in proc.plugins
        }

        for wire in self.wires:
            src_parts = wire.source.split(".")
            tgt_parts = wire.target.split(".")
            if len(src_parts) != 3 or len(tgt_parts) != 3:
                continue  # не "process.plugin.port" — пропускаем

            src_process, _src_plugin, src_port = src_parts
            tgt_process, tgt_plugin, tgt_port_name = tgt_parts

            tgt_plugin_class = plugin_class_by_addr.get((tgt_process, tgt_plugin), "")
            entry = _find_plugin_entry(tgt_plugin, tgt_plugin_class)
            if entry is None:
                continue
            tgt_port = next((p for p in entry.inputs if p.name == tgt_port_name), None)
            if tgt_port is None or tgt_port.optional:
                continue

            by_source = required_sources.setdefault(tgt_process, {})
            by_source.setdefault(src_process, set()).add(src_port)

        for proc in self.processes:
            # Явный inspector-конфиг: typed-поле приоритетнее extras["inspector"].
            explicit = proc.inspector or (proc.extras or {}).get("inspector") or {}
            # Escape-hatch (вывод НЕ применяется) — только если конфиг задаёт mode.
            # Mode-less конфиг (напр. {timeout_sec: 5}) — НЕ escape-hatch, а тонкая
            # настройка: вывод mode/inputs/primary из wires всё равно срабатывает, а
            # прочие ключи подмешиваются поверх (иначе mode-less inspector молча
            # отключал бы join — F2). Симметрично legacy metadata.inspector.
            if isinstance(explicit, dict) and explicit.get("mode"):
                continue

            sources = required_sources.get(proc.process_name, {})
            if len(sources) < 2:
                continue  # < 2 required-источников — join не нужен (fanin остаётся дефолтом)

            # Известный edge (в) (AU-3, follow-up В1, ADR-PMM-017 п.6, см. docstring):
            # источник с ≥2 РАЗНЫМИ src-портами даёт ОДИН тег на весь источник
            # ("frame"-приоритет, иначе первый по алфавиту) — не по числу его
            # target-портов. Задокументированная граница, не баг (см. docstring).
            tags = ["frame" if "frame" in ports else sorted(ports)[0] for _src, ports in sorted(sources.items())]
            unique_tags = sorted(set(tags), key=lambda t: (t != "frame", t))
            primary = "frame" if "frame" in unique_tags else unique_tags[0]

            derived: dict[str, Any] = {"mode": "join", "inputs": unique_tags, "primary": primary}

            # Тонкая настройка (структурные mode/inputs/primary остаются из wires):
            # mode-less явный inspector (typed/extras) + legacy metadata.inspector —
            # оба подмешивают только НЕ-структурные ключи (timeout_sec/… ) поверх skeleton.
            legacy = proc.metadata.get("inspector") if isinstance(proc.metadata, dict) else None
            for tuning in (explicit, legacy):
                if isinstance(tuning, dict):
                    for key, value in tuning.items():
                        if key not in ("mode", "inputs", "primary"):
                            derived[key] = value

            proc.inspector = derived
            # Снять mode-less shadow из extras: proc.inspector теперь авторитетен (в
            # model_fields_set через validate_assignment), но extras["inspector"] без mode
            # иначе провоцировал бы ложный conflict-warning в as_generic_config._pick.
            extras_insp = (proc.extras or {}).get("inspector")
            if isinstance(extras_insp, dict) and not extras_insp.get("mode"):
                proc.extras = {k: v for k, v in proc.extras.items() if k != "inspector"}

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

    def _duplicate_process_names(self) -> list[str]:
        """Дубли имён процессов — общая проверка для :meth:`check` и :meth:`check_structure`."""
        errors: list[str] = []
        process_names: set[str] = set()
        for proc in self.processes:
            if proc.process_name in process_names:
                errors.append(f"Дублирование имени процесса: '{proc.process_name}'")
            process_names.add(proc.process_name)
        return errors

    def check_structure(self) -> list[str]:
        """Публичный gate структурной валидации (RS-5, C-4): дубли имён + циклы.

        НЕ зависит от PluginRegistry — безопасен как gate на запись рецепта
        (единый Save, load-from-file) даже в разреженном окружении (headless/
        тесты), где полный :meth:`check` (порты/auto-wiring) даёт ложные wire-
        ошибки (см. audit 2026-07-12). По той же причине детекция циклов НЕ
        встроена в :meth:`check` — вынесена сюда, чтобы не расширять контракт
        pre-launch/boot/switch-валидации (``check()`` вызывается из
        ``backend/assembly/assembler.py`` на boot/switch — межпроцессная
        обратная связь p1<->p2, легальная request/response-пара, там не
        запрещена и не должна становиться внезапно недопустимой).

        Циклы ищутся на PROCESS-level графе (ребро source_proc -> target_proc
        для каждого wire). Wire ВНУТРИ одного процесса (source_proc ==
        target_proc — явный внутрипроцессный роутинг между плагинами одного
        процесса) НЕ считается ребром графа процессов и не может создать
        ложный self-loop цикл.

        Returns:
            Список ошибок. Пустой = граф структурно корректен (без циклов/дублей).
        """
        errors: list[str] = list(self._duplicate_process_names())

        edges: list[tuple[str, str]] = []
        for wire in self.wires:
            src_proc = wire.source.split(".")[0]
            tgt_proc = wire.target.split(".")[0]
            if src_proc and tgt_proc and src_proc != tgt_proc:
                edges.append((src_proc, tgt_proc))

        cycle = _find_cycle(edges)
        if cycle is not None:
            errors.append(f"Граф содержит цикл: {' -> '.join(cycle)}")

        return errors

    def check(self) -> list[str]:
        """Валидация чертежа до запуска.

        Проверяет:
        1. Дублирование имён процессов
        2. Цепочки плагинов внутри каждого процесса (auto-wiring)
        3. Wire-связи между процессами (совместимость портов)
        4. Все обязательные входы подключены

        НЕ проверяет циклы графа wires — та проверка живёт только в
        :meth:`check_structure` (RS-5 Save/load-gate); межпроцессная обратная
        связь (request/response) — легальный паттерн на boot/switch, и этот
        метод остаётся именно тем контрактом, что был до RS-5 (не расширяем
        pre-launch/boot-валидацию бесплатно вместе с gate-валидацией записи).

        Returns:
            Список ошибок. Пустой = всё ОК.
        """
        errors: list[str] = list(self._duplicate_process_names())

        # Раздельные карты входов и выходов — плагин может иметь
        # одноимённые input/output порты (e.g. "frame" → "frame")
        input_map: dict[str, Port] = {}  # address → Port
        output_map: dict[str, Port] = {}  # address → Port

        for proc in self.processes:
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


def _find_cycle(edges: list[tuple[str, str]]) -> list[str] | None:
    """DFS-поиск цикла в ориентированном графе process-level рёбер wires (RS-5, C-4).

    Args:
        edges: список рёбер (source_process, target_process).

    Returns:
        Список имён процессов вдоль найденного цикла (первый узел повторяется
        последним, чтобы явно показать замыкание), либо None если циклов нет.
    """
    graph: dict[str, list[str]] = {}
    for src, tgt in edges:
        graph.setdefault(src, []).append(tgt)
        graph.setdefault(tgt, [])

    WHITE, GRAY, BLACK = 0, 1, 2
    color: dict[str, int] = dict.fromkeys(graph, WHITE)
    path: list[str] = []

    def _visit(node: str) -> list[str] | None:
        color[node] = GRAY
        path.append(node)
        for neighbor in graph.get(node, []):
            neighbor_color = color.get(neighbor, WHITE)
            if neighbor_color == GRAY:
                cycle_start = path.index(neighbor)
                return [*path[cycle_start:], neighbor]
            if neighbor_color == WHITE:
                found = _visit(neighbor)
                if found is not None:
                    return found
        path.pop()
        color[node] = BLACK
        return None

    for start_node in list(graph):
        if color[start_node] == WHITE:
            found = _visit(start_node)
            if found is not None:
                return found
    return None


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
