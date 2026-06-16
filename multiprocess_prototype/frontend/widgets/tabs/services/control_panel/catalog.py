"""NodeCatalog — перечисление нод/полей/команд активной топологии для пикера дашборда.

Дашборд-пикер «Добавить из ноды» выносит в пульт ВЫБРАННЫЕ параметры/команды
ДРУГИХ нод. Чтобы не дублировать логику, каталог переиспользует существующие
источники (в GUI-процессе они уже наполнены, см. app.py: PluginRegistry.discover):

  - ноды:   topology dict (processes[].plugins[]) из ``topology_bridge.topology``;
  - поля:   ``extract_fields(plugin_name, register_cls)`` по PluginRegistry entry
            (тот же экстрактор register-полей, что у инспектора Pipeline);
  - команды: ``PluginRegistry.get(plugin_name).plugin_class.commands``.

Чистый Python (без Qt) — пикер-диалог получает каталог через DI и легко тестируется.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Callable

from multiprocess_framework.modules.process_module.plugins import PluginRegistry
from multiprocess_framework.modules.registers_module.core.field_info import extract_fields


@dataclass(frozen=True)
class NodeRef:
    """Ссылка на ноду (плагин внутри процесса) активной топологии."""

    process_name: str
    plugin_index: int
    plugin_name: str
    category: str = ""

    @property
    def label(self) -> str:
        """Подпись для GUI: ``process.plugin`` (+ категория)."""
        base = f"{self.process_name}.{self.plugin_name}"
        return f"{base}  ({self.category})" if self.category else base


@dataclass(frozen=True)
class FieldRef:
    """Описание register-поля ноды (для param/monitor-контрола)."""

    name: str
    title: str
    field_type: type
    min_value: float | int | None
    max_value: float | int | None
    readonly: bool
    default: Any = None  # значение по умолчанию из схемы (fallback, если в config нет override)

    @property
    def is_numeric(self) -> bool:
        return self.field_type in (int, float)

    @property
    def is_bool(self) -> bool:
        return self.field_type is bool


class NodeCatalog:
    """Каталог нод/полей/команд для пикера (читает топологию + PluginRegistry)."""

    def __init__(self, topology_provider: Callable[[], Any] | Any) -> None:
        """topology_provider — callable, возвращающий topology dict, либо сам dict."""
        self._topology_provider = topology_provider

    # ------------------------------------------------------------------ #

    def _topology(self) -> dict:
        topo = self._topology_provider() if callable(self._topology_provider) else self._topology_provider
        return topo if isinstance(topo, dict) else {}

    def nodes(self) -> list[NodeRef]:
        """Все ноды активной топологии (процесс → плагины по индексу)."""
        out: list[NodeRef] = []
        for proc in self._topology().get("processes", []) or []:
            if not isinstance(proc, dict):
                continue
            pname = proc.get("process_name") or ""
            for idx, pl in enumerate(proc.get("plugins", []) or []):
                if not isinstance(pl, dict):
                    continue
                plugin = pl.get("plugin_name") or ""
                if not plugin:
                    continue
                out.append(NodeRef(pname, idx, plugin, pl.get("category") or ""))
        return out

    def fields(self, plugin_name: str, *, editable_only: bool = True) -> list[FieldRef]:
        """register-поля плагина (через PluginRegistry + extract_fields).

        editable_only=True отбрасывает readonly-поля (param-контрол их не правит).
        """
        entry = PluginRegistry.get(plugin_name)
        if entry is None:
            return []
        out: list[FieldRef] = []
        for rc in getattr(entry, "register_classes", []) or []:
            for fi in extract_fields(plugin_name, rc, getattr(entry, "category", "")):
                readonly = bool(getattr(fi.meta, "readonly", False)) if fi.meta else False
                if editable_only and readonly:
                    continue
                out.append(
                    FieldRef(
                        name=fi.field_name,
                        title=fi.title,
                        field_type=fi.field_type if isinstance(fi.field_type, type) else type(fi.default),
                        min_value=fi.min_value,
                        max_value=fi.max_value,
                        readonly=readonly,
                        default=fi.default,
                    )
                )
        return out

    def field_value(self, node: NodeRef, field_name: str, fallback: Any = None) -> Any:
        """Текущее значение поля ноды из config топологии (рецепт); fallback если нет override.

        Так proxy-контрол инициализируется значением, «которое было» (а не min поля).
        """
        for proc in self._topology().get("processes", []) or []:
            if not isinstance(proc, dict) or proc.get("process_name") != node.process_name:
                continue
            plugins = proc.get("plugins", []) or []
            if 0 <= node.plugin_index < len(plugins) and isinstance(plugins[node.plugin_index], dict):
                cfg = plugins[node.plugin_index].get("config") or {}
                if isinstance(cfg, dict) and field_name in cfg:
                    return cfg[field_name]
        return fallback

    def commands(self, plugin_name: str) -> list[str]:
        """Имена команд плагина (для action-контрола)."""
        entry = PluginRegistry.get(plugin_name)
        if entry is None:
            return []
        cmds = getattr(getattr(entry, "plugin_class", None), "commands", {}) or {}
        return list(cmds.keys())


# --------------------------------------------------------------------------- #
# Билдеры proxy-контрола (чистый Python — пикер-диалог только собирает значения).
# --------------------------------------------------------------------------- #


def _slug(*parts: str) -> str:
    """ASCII-слаг из частей (для стабильного id контрола)."""
    raw = "_".join(str(p) for p in parts if p)
    base = re.sub(r"[^a-z0-9]+", "_", raw.lower()).strip("_")
    return base or "ctl"


def control_type_for_field(field: FieldRef, *, numeric_as: str = "number") -> str:
    """Подобрать тип контрола под тип register-поля.

    numeric → number|slider; bool → toggle; иначе → text.
    """
    if field.is_bool:
        return "toggle"
    if field.is_numeric:
        return numeric_as if numeric_as in ("number", "slider") else "number"
    return "text"


def make_param_spec(
    node: NodeRef,
    field: FieldRef,
    *,
    ctype: str = "",
    label: str = "",
    value: Any = None,
) -> dict[str, Any]:
    """proxy-контрол правки register-поля чужой ноды (source=param → live field-write).

    value — стартовое значение контрола (текущее значение поля ноды); если None,
    ControlSpec возьмёт дефолт по типу. Передавай ``catalog.field_value(node, field.name)``,
    чтобы контрол показывал значение, «которое было» в рецепте, а не min.
    """
    ctype = ctype or control_type_for_field(field)
    spec: dict[str, Any] = {
        "id": _slug("param", node.plugin_name, field.name),
        "type": ctype,
        "label": label or f"{field.title} [{node.plugin_name}]",
        "source": "param",
        "target_process": node.process_name,
        "target_plugin_index": node.plugin_index,
        "target_field": field.name,
    }
    if value is not None:
        spec["value"] = value
    if ctype in ("slider", "number"):
        if field.min_value is not None:
            spec["min"] = float(field.min_value)
        if field.max_value is not None:
            spec["max"] = float(field.max_value)
    return spec


def make_action_spec(
    node: NodeRef,
    command: str,
    *,
    ctype: str = "button",
    label: str = "",
    value_arg: str = "",
    command_args: dict[str, Any] | None = None,
    vmin: float | None = None,
    vmax: float | None = None,
) -> dict[str, Any]:
    """proxy-контрол триггера команды чужой ноды (source=action → on_action_command).

    Кнопка (ctype=button) — чистый триггер. Слайдер/число со value_arg — передаёт
    своё значение в аргумент команды (напр. value_arg="pct" для robot_draw_set_speed),
    command_args — фиксированные аргументы (напр. {"device_id": "robot_main"}).
    """
    spec: dict[str, Any] = {
        "id": _slug("action", node.plugin_name, command),
        "type": ctype,
        "label": label or f"{command} [{node.plugin_name}]",
        "source": "action",
        "target_process": node.process_name,
        "target_plugin_index": node.plugin_index,
        "target_command": command,
        "value_arg": value_arg,
        "command_args": dict(command_args or {}),
    }
    if ctype in ("slider", "number"):
        if vmin is not None:
            spec["min"] = float(vmin)
        if vmax is not None:
            spec["max"] = float(vmax)
    return spec


__all__ = [
    "NodeCatalog",
    "NodeRef",
    "FieldRef",
    "control_type_for_field",
    "make_param_spec",
    "make_action_spec",
]
