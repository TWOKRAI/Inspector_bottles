"""ControlPanelPlugin — source-плагин «Пульт»: GUI-контролы → сигналы в pipeline.

Нода без кадров: в produce() лишь дренит накопленные эмиты контролов (по нажатию
кнопки / сдвигу слайдера / вводу в GUI-вкладке «Пульт») в items на выходные порты
out_1..out_N. Порт вяжется к потребителю в редакторе Pipeline.

Команды управления контролами приходят из потока message_processor (set_control/
emit_control/add_control/...), produce() читает из source-потока — обмен через
очередь под lock (как сигналы phone_camera).
"""

from __future__ import annotations

import threading
from typing import Any

from multiprocess_framework.modules.process_module.plugins import PluginContext
from multiprocess_framework.modules.process_module.plugins import Port
from multiprocess_framework.modules.process_module.plugins import ProcessModulePlugin
from multiprocess_framework.modules.process_module.plugins import register_plugin

from Services.control_panel.controls import ControlSpec, controls_to_dicts, parse_controls

from .registers import ControlPanelRegisters

# Размер пула выходных портов (фиксирован на уровне класса — каталог/редактор
# читают статические outputs). Контрол ссылается на один из out_1..out_N.
_PORT_POOL = 8


def _build_output_ports(n: int) -> list[Port]:
    """Сгенерировать пул выходных портов out_1..out_N (dtype any, optional)."""
    return [
        Port(
            name=f"out_{i}",
            dtype="any",
            optional=True,
            description=f"Сигнал контрола (порт {i})",
        )
        for i in range(1, n + 1)
    ]


@register_plugin(
    "control_panel",
    category="source",
    description="Пульт: GUI-контролы (кнопка/тумблер/слайдер/поле) → сигналы в pipeline",
)
class ControlPanelPlugin(ProcessModulePlugin):
    """Источник сигналов от GUI-контролов пульта."""

    name = "control_panel"
    category = "source"

    register_class = ControlPanelRegisters

    inputs: list[Port] = []
    outputs: list[Port] = _build_output_ports(_PORT_POOL)

    commands = {
        "get_controls": "cmd_get_controls",
        "set_control": "cmd_set_control",
        "emit_control": "cmd_emit_control",
        "add_control": "cmd_add_control",
        "remove_control": "cmd_remove_control",
        "update_control": "cmd_update_control",
    }

    # --- Lifecycle ---

    def configure(self, ctx: PluginContext) -> None:
        cfg = ctx.config
        self._ctx = ctx
        self._reg = self._init_register(ctx)

        self._panel_id: str = cfg.get("panel_id", "pult")
        self._controls: list[ControlSpec] = parse_controls(cfg.get("controls", []))
        self._state_proxy = ctx.state_proxy

        # Очередь эмитов: (port, value). Команда пишет, produce() читает.
        self._pending: list[tuple[str, Any]] = []
        self._lock = threading.Lock()

        ctx.log_info(f"ControlPanelPlugin[{self._panel_id}]: configured, контролов={len(self._controls)}")

    def start(self, ctx: PluginContext) -> None:
        self._publish_controls()

    def shutdown(self, ctx: PluginContext) -> None:
        ctx.log_info(f"ControlPanelPlugin[{self._panel_id}]: shutdown")

    def produce(self) -> list[dict]:
        """Слить накопленные эмиты контролов в items (по одному на эмит)."""
        with self._lock:
            if not self._pending:
                return []
            pending = self._pending
            self._pending = []
        items: list[dict] = []
        for port, value in pending:
            items.append({port: value, "data_type": "signal", "panel_id": self._panel_id})
            self._ctx.log_info(f"ControlPanelPlugin[{self._panel_id}]: сигнал {port} = {value!r}")
        return items

    # --- Внутреннее ---

    def _find(self, control_id: str) -> ControlSpec | None:
        for spec in self._controls:
            if spec.id == control_id:
                return spec
        return None

    def _queue_emit(self, port: str, value: Any) -> None:
        with self._lock:
            self._pending.append((port, value))

    def _publish_controls(self) -> None:
        """Опубликовать набор контролов в state (для реактивного GUI)."""
        if self._state_proxy is None:
            return
        self._state_proxy.merge(
            f"processes.{self._ctx.process_name}.state.control_panel",
            {"panel_id": self._panel_id, "controls": controls_to_dicts(self._controls)},
        )

    # --- Команды ---

    def cmd_get_controls(self, data: dict) -> dict:
        """Вернуть текущий набор контролов (специи + значения)."""
        return {"status": "ok", "panel_id": self._panel_id, "controls": controls_to_dicts(self._controls)}

    def cmd_set_control(self, data: dict) -> dict:
        """Задать значение контрола и эмитнуть его на порт.

        data: {"id": <control_id>, "value": <raw>}. Значение коэрцится по типу
        (toggle→bool, slider/number→clamp, text→str; button→trigger_value).
        """
        spec = self._find(str(data.get("id", "")))
        if spec is None:
            return {"status": "error", "message": "контрол не найден"}
        spec.value = spec.coerce(data.get("value"))
        self._queue_emit(spec.port, spec.value)
        return {"status": "ok", "id": spec.id, "value": spec.value, "port": spec.port}

    def cmd_emit_control(self, data: dict) -> dict:
        """Эмитнуть текущее значение контрола (кнопка-триггер / повтор)."""
        spec = self._find(str(data.get("id", "")))
        if spec is None:
            return {"status": "error", "message": "контрол не найден"}
        value = spec.trigger_value if spec.type == "button" else spec.value
        self._queue_emit(spec.port, value)
        return {"status": "ok", "id": spec.id, "value": value, "port": spec.port}

    def cmd_add_control(self, data: dict) -> dict:
        """Добавить контрол. data: {"spec": {...}} или поля контрола напрямую."""
        raw = data.get("spec") if isinstance(data.get("spec"), dict) else data
        specs = parse_controls([raw])
        if not specs:
            return {"status": "error", "message": "невалидная спецификация контрола"}
        spec = specs[0]
        if self._find(spec.id) is not None:
            return {"status": "error", "message": f"контрол '{spec.id}' уже существует"}
        self._controls.append(spec)
        self._publish_controls()
        return {"status": "ok", "id": spec.id}

    def cmd_remove_control(self, data: dict) -> dict:
        """Удалить контрол по id."""
        control_id = str(data.get("id", ""))
        before = len(self._controls)
        self._controls = [s for s in self._controls if s.id != control_id]
        if len(self._controls) == before:
            return {"status": "error", "message": "контрол не найден"}
        self._publish_controls()
        return {"status": "ok", "id": control_id}

    def cmd_update_control(self, data: dict) -> dict:
        """Обновить поля контрола. data: {"id": ..., "patch": {label/port/min/max/step}}."""
        spec = self._find(str(data.get("id", "")))
        if spec is None:
            return {"status": "error", "message": "контрол не найден"}
        patch = data.get("patch") if isinstance(data.get("patch"), dict) else {}
        allowed = {"label", "port", "min", "max", "step", "type", "trigger_value"}
        for key, val in patch.items():
            if key in allowed:
                setattr(spec, key, val)
        self._publish_controls()
        return {"status": "ok", "id": spec.id}
