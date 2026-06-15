"""ControlPanelPresenter — логика вкладки «Пульт» (без Qt).

Две оси:
  - ОПЕРАЦИЯ (нажать/сдвинуть/ввести): live-команда плагину control_panel через
    bridge.on_action_command (по plugin_name) — мгновенный сигнал в pipeline.
  - НАБОР контролов (add/remove/update): live-команда + ПЕРСИСТ в рецепт через
    domain SetPluginConfig (поле ``controls`` ноды) — тот же editor-store, что у
    редактора Pipeline (единый источник правды), save рецепта пишет на диск.
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)

_PLUGIN = "control_panel"


class ControlPanelPresenter:
    """Презентер пульта: операция (live) + правка набора (live + персист в рецепт)."""

    def __init__(self, *, bridge: Any = None, services: Any = None) -> None:
        self._bridge = bridge
        self._services = services

    # --- Операция (только live, набор не меняется) ---

    def operate(self, control_id: str, value: Any) -> bool:
        """Применить значение контрола → сигнал на порт (set_control)."""
        return self._send("set_control", {"id": control_id, "value": value})

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
        if self._services is None or not process_name:
            logger.debug("ControlPanel: персист пропущен (services/process_name недоступны)")
            return
        from multiprocess_prototype.domain.commands import SetPluginConfig

        try:
            self._services.commands.dispatch(
                SetPluginConfig(
                    process_name=process_name,
                    plugin_index=plugin_index,
                    field="controls",
                    value=controls,
                )
            )
        except Exception as exc:  # noqa: BLE001 — персист не должен валить GUI
            logger.warning("ControlPanel: персист контролов в рецепт не удался: %s", exc)

    def _send(self, command: str, args: dict | None = None) -> bool:
        if self._bridge is None:
            logger.debug("ControlPanel: bridge недоступен — %s пропущена", command)
            return False
        try:
            return bool(self._bridge.on_action_command(_PLUGIN, command, args or {}))
        except Exception as exc:  # noqa: BLE001
            logger.warning("ControlPanel: команда %s провалилась: %s", command, exc)
            return False
