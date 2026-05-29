"""io.py — двусторонняя сериализация PipelineModel ↔ SystemBlueprint.

Публичный API:
    graph_to_blueprint(model, name, description)
        → tuple[blueprint_dict, display_bindings, gui_positions]

    blueprint_to_graph(blueprint, display_bindings, model, gui_positions, display_registry)
        → None  (мутирует model)

display_bindings — список dict'ов вида:
    {"node_id": "process.plugin.port", "display_id": "<display_id>"}

gui_positions — dict вида:
    {"<node_id>": [x, y]}  (для всех узлов, включая display)

Примечание по target_process:
    ProcessConfig (SchemaBase) по умолчанию игнорирует extra-поля при
    model_validate → target_process в blueprint_dict["processes"] не вызывает
    ошибку Pydantic, но и не теряется — мы его явно сохраняем/восстанавливаем
    через topology dict.
"""

from __future__ import annotations

import logging
import warnings

from .model import PipelineModel

logger = logging.getLogger(__name__)


def graph_to_blueprint(
    model: PipelineModel,
    name: str = "default",
    description: str = "",
) -> tuple[dict, list[dict], dict]:
    """Конвертировать PipelineModel в blueprint_dict + display_bindings + gui_positions.

    Args:
        model: текущая модель pipeline (SSOT topology).
        name: имя blueprint'а (сохранится в рецепте).
        description: описание blueprint'а.

    Returns:
        Кортеж из трёх элементов:
        - blueprint_dict: dict, совместимый с SystemBlueprint.model_validate().
          Содержит ключи: name, description, processes, wires (только process→process).
        - display_bindings: list[dict] вида {"node_id": <source endpoint>, "display_id": ...}.
          G.4.2b: берутся напрямую из topology["displays"] (display = binding, не wire).
        - gui_positions: dict вида {"<node_id>": [x, y]} для всех узлов.
          Заполняется из topology["gui_positions"] если ключ присутствует.
    """
    topo = model.to_topology_dict()

    # --- display_bindings = привязки модели напрямую (G.4.2b) ---
    # display = binding: модель хранит {node_id: <source endpoint>, display_id},
    # ровно в формате диска. Wire⇄binding-конвертер удалён (display-wire больше нет).
    display_bindings: list[dict] = []
    for disp in topo.get("displays", []):
        if not isinstance(disp, dict):
            continue
        node_id = disp.get("node_id", "")
        display_id = disp.get("display_id", "")
        if node_id and display_id:
            display_bindings.append({"node_id": node_id, "display_id": display_id})

    # --- Все wire'ы — process→process (display-wire не существует) ---
    process_wires: list[dict] = []
    for wire in topo.get("wires", []):
        if not isinstance(wire, dict):
            continue
        wire_entry: dict = {"source": wire.get("source", ""), "target": wire.get("target", "")}
        if "description" in wire:
            wire_entry["description"] = wire["description"]
        process_wires.append(wire_entry)

    # --- Собираем processes ---
    # Сохраняем все поля из topology dict без изменений.
    # target_process — мета-поле GUI, SchemaBase его тихо игнорирует при model_validate.
    processes_raw = topo.get("processes", [])
    processes: list[dict] = []
    for proc in processes_raw:
        if not isinstance(proc, dict):
            continue
        # Копируем без ключей, специфичных только для topology/GUI
        # (но оставляем target_process — он нужен для GUI round-trip)
        proc_entry = dict(proc)
        processes.append(proc_entry)

    # --- Собираем gui_positions ---
    gui_positions: dict = dict(topo.get("gui_positions", {}))

    # --- Формируем blueprint_dict ---
    blueprint_dict: dict = {
        "name": name,
        "description": description,
        "processes": processes,
        "wires": process_wires,
    }

    return blueprint_dict, display_bindings, gui_positions


def blueprint_to_graph(
    blueprint: dict,
    display_bindings: list[dict],
    model: PipelineModel,
    gui_positions: dict | None = None,
    display_registry=None,
) -> None:
    """Наполнить PipelineModel из blueprint_dict + display_bindings.

    Предварительно очищает модель. Все ошибки при добавлении wire'ов —
    логируются как warnings (не падаем на невалидных ссылках).

    Args:
        blueprint: dict с ключами name/description/processes/wires.
        display_bindings: list[dict] вида {"node_id": ..., "display_id": ...}.
        model: модель для заполнения (будет очищена).
        gui_positions: dict {node_id: [x, y]} — если передан, записывается в topology.
        display_registry: опциональный реестр для получения display_name по display_id.
            Ожидается метод get(display_id) возвращающий объект с атрибутом name.
            Если None — display_name будет пустой строкой.
    """
    # --- Очистка модели ---
    model.from_topology_dict({"processes": [], "wires": [], "displays": []})

    # --- Загружаем процессы ---
    for proc in blueprint.get("processes", []):
        if not isinstance(proc, dict):
            continue

        name: str = proc.get("process_name", "")
        if not name:
            logger.warning("blueprint_to_graph: process без process_name — пропущен")
            continue

        # Получаем plugin_name из первого плагина (если есть)
        plugins: list = proc.get("plugins", [])
        plugin_name: str = ""
        if plugins and isinstance(plugins[0], dict):
            plugin_name = plugins[0].get("plugin_name", "")

        category: str = "utility"
        if plugins and isinstance(plugins[0], dict):
            category = plugins[0].get("category", "utility")

        config: dict = proc.get("config", {})

        model.add_process(name, plugin_name=plugin_name, category=category, config=config or None)

        # --- Восстанавливаем target_process если было ---
        target_process: str = proc.get("target_process", "")
        if target_process:
            # Находим только что добавленный процесс в topology и дописываем поле
            for p in model._topology.get("processes", []):
                if isinstance(p, dict) and p.get("process_name") == name:
                    p["target_process"] = target_process
                    break

        # --- Восстанавливаем полный список plugins (перезаписываем) ---
        # add_process создаёт упрощённый вариант — восстанавливаем исходный
        if plugins:
            for p in model._topology.get("processes", []):
                if isinstance(p, dict) and p.get("process_name") == name:
                    p["plugins"] = list(plugins)
                    break

    # --- Загружаем process→process wire'ы ---
    for wire in blueprint.get("wires", []):
        if not isinstance(wire, dict):
            continue
        source: str = wire.get("source", "")
        target: str = wire.get("target", "")
        if not source or not target:
            continue
        try:
            model.add_wire(source, target)
        except ValueError as exc:
            warnings.warn(
                f"blueprint_to_graph: не удалось добавить wire {source} → {target}: {exc}",
                stacklevel=2,
            )

    # --- Загружаем display_bindings → привязки модели напрямую (G.4.2b) ---
    # display = binding: запись {node_id: <source endpoint>, display_id}. Никаких
    # display-узлов и wire'ов — конвертер схлопнут (см. ADR DOM-001).
    for binding in display_bindings:
        if not isinstance(binding, dict):
            continue
        source: str = binding.get("node_id", "")  # source endpoint выхода
        display_id: str = binding.get("display_id", "")
        if not display_id:
            logger.warning("blueprint_to_graph: binding без display_id — пропущен")
            continue

        # Получаем display_name из реестра если доступен
        display_name: str = ""
        if display_registry is not None:
            try:
                entry = display_registry.get(display_id)
                if entry is not None:
                    display_name = getattr(entry, "name", "") or ""
            except Exception as exc:
                logger.warning("blueprint_to_graph: ошибка при обращении к display_registry: %s", exc)

        try:
            model.add_display(source, display_id, display_name)
        except ValueError:
            # Дубликат пары (source, display_id) — пропускаем
            pass

    # --- Записываем gui_positions если переданы ---
    if gui_positions:
        model._topology["gui_positions"] = dict(gui_positions)
