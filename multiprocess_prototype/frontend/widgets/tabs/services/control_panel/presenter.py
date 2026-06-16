"""ControlPanelPresenter — логика вкладки «Пульт» (без Qt).

Две оси:
  - ОПЕРАЦИЯ (нажать/сдвинуть/ввести) — роутинг по ``source`` контрола (дашборд):
      * local   — set_control плагину control_panel → сигнал на свой порт (pipeline);
      * param   — правка register-поля ДРУГОЙ ноды через domain SetPluginConfig
                  (live field-write в живой процесс + персист в рецепт, app.py listener);
      * action  — триггер команды ДРУГОЙ ноды через bridge.on_action_command
                  (кнопка = чистый триггер; слайдер/число → значение в value_arg);
      * monitor — read-only, операция запрещена.
  - НАБОР контролов (add/remove): live-команда + ПЕРСИСТ в рецепт через domain
    SetPluginConfig (поле ``controls`` ноды пульта) — тот же editor-store, что у
    редактора Pipeline (единый источник правды), save рецепта пишет на диск.

Дашборд НЕ вводит нового IPC: param переиспользует live field-write инспектора,
action — тот же путь, что кнопка «Рисовать».
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)

_PLUGIN = "control_panel"


class ControlPanelPresenter:
    """Презентер пульта: операция (роутинг по source) + правка набора (live + персист)."""

    def __init__(self, *, bridge: Any = None, services: Any = None) -> None:
        self._bridge = bridge
        self._services = services

    # --- Операция (только live, набор не меняется) ---

    def operate(self, spec: dict, value: Any) -> bool:
        """Применить значение контрола, маршрутизируя по ``source`` спеки.

        spec — полная спецификация контрола (dict из current_controls).
        """
        source = str(spec.get("source") or "local")
        if source == "monitor":
            return False  # read-only — операции нет
        if source == "param":
            return self._write_param(spec, value)
        if source == "action":
            return self._trigger_action(spec, value)
        # local (дефолт): сигнал на свой порт через плагин.
        return self._send("set_control", {"id": spec.get("id"), "value": value})

    # --- Роутинг дашборда ---

    def _write_param(self, spec: dict, value: Any) -> bool:
        """source=param → live field-write register-поля целевой ноды (SetPluginConfig)."""
        proc = str(spec.get("target_process") or "")
        field = str(spec.get("target_field") or "")
        idx = int(spec.get("target_plugin_index") or 0)
        if not proc or not field:
            logger.debug("ControlPanel: param пропущен — target_process/field пусты (%s)", spec.get("id"))
            return False
        return self._dispatch_set_config(proc, idx, field, value)

    def _trigger_action(self, spec: dict, value: Any) -> bool:
        """source=action → триггер команды целевой ноды (bridge.on_action_command)."""
        if self._bridge is None:
            logger.debug("ControlPanel: action пропущен — bridge недоступен (%s)", spec.get("id"))
            return False
        plugin_name = self._resolve_plugin_name(spec)
        command = str(spec.get("target_command") or "")
        if not plugin_name or not command:
            logger.debug("ControlPanel: action пропущен — плагин/команда не резолвятся (%s)", spec.get("id"))
            return False
        args = self._build_action_args(spec, value)
        try:
            return bool(self._bridge.on_action_command(plugin_name, command, args))
        except Exception as exc:  # noqa: BLE001
            logger.warning("ControlPanel: action %s.%s провалился: %s", plugin_name, command, exc)
            return False

    @staticmethod
    def _build_action_args(spec: dict, value: Any) -> dict:
        """Аргументы команды: фикс. command_args + значение под value_arg (с коэрцией спеки)."""
        from Services.control_panel.controls import ControlSpec

        try:
            cs = ControlSpec(**{k: v for k, v in spec.items() if k in ControlSpec.model_fields})
            return cs.action_args(value)
        except Exception:  # noqa: BLE001 — fallback на сырую сборку, без коэрции
            args = dict(spec.get("command_args") or {})
            varg = spec.get("value_arg") or ""
            if varg:
                args[varg] = value
            return args

    def _resolve_plugin_name(self, spec: dict) -> str:
        """Имя плагина целевой ноды по (target_process, target_plugin_index).

        Источник — TopologyRepository (services.topology), как везде в GUI;
        у TopologyBridge нет публичного .topology (вернул бы None).
        """
        proc = spec.get("target_process")
        idx = int(spec.get("target_plugin_index") or 0)
        topo_repo = getattr(self._services, "topology", None)
        if topo_repo is None:
            return ""
        try:
            topo = topo_repo.load().to_dict()
        except Exception:  # noqa: BLE001
            return ""
        for p in topo.get("processes", []) or []:
            if isinstance(p, dict) and p.get("process_name") == proc:
                plugins = p.get("plugins", []) or []
                if 0 <= idx < len(plugins) and isinstance(plugins[idx], dict):
                    return plugins[idx].get("plugin_name") or ""
        return ""

    # --- Правка набора (live + персист в рецепт) ---

    def add(self, spec: dict, process_name: str, plugin_index: int, new_controls: list[dict]) -> bool:
        """Добавить контрол: live add_control + персист обновлённого набора."""
        ok = self._send("add_control", {"spec": spec})
        self._persist(process_name, plugin_index, new_controls)
        return ok

    def remove(self, control_id: str, process_name: str, plugin_index: int, new_controls: list[dict]) -> bool:
        """Удалить контрол: live remove_control + персист обновлённого набора."""
        ok = self._send("remove_control", {"id": control_id})
        self._persist(process_name, plugin_index, new_controls)
        return ok

    # --- Внутреннее ---

    def _persist(self, process_name: str, plugin_index: int, controls: list[dict]) -> None:
        """Записать набор контролов в конфиг ноды (editor-топология → рецепт при save)."""
        if not process_name:
            logger.debug("ControlPanel: персист пропущен (process_name недоступен)")
            return
        self._dispatch_set_config(process_name, plugin_index, "controls", controls)

    def _dispatch_set_config(self, process_name: str, plugin_index: int, field: str, value: Any) -> bool:
        """domain SetPluginConfig → editor-store + live field-write IPC (app.py listener).

        Единый путь: персист набора контролов (field="controls" на ноде пульта) И
        live-правка register-поля чужой ноды (param-источник дашборда).
        """
        if self._services is None:
            logger.debug("ControlPanel: SetPluginConfig пропущен (services недоступны)")
            return False
        from multiprocess_prototype.domain.commands import SetPluginConfig

        try:
            self._services.commands.dispatch(
                SetPluginConfig(
                    process_name=process_name,
                    plugin_index=plugin_index,
                    field=field,
                    value=value,
                )
            )
            return True
        except Exception as exc:  # noqa: BLE001 — не должен валить GUI
            logger.warning("ControlPanel: SetPluginConfig %s.%s не удался: %s", process_name, field, exc)
            return False

    def _send(self, command: str, args: dict | None = None) -> bool:
        if self._bridge is None:
            logger.debug("ControlPanel: bridge недоступен — %s пропущена", command)
            return False
        try:
            return bool(self._bridge.on_action_command(_PLUGIN, command, args or {}))
        except Exception as exc:  # noqa: BLE001
            logger.warning("ControlPanel: команда %s провалилась: %s", command, exc)
            return False
