"""CameraSettingsPresenter — логика фасада настроек камеры (без Qt).

Источник правды:
  desired — рецепт (plugin_config) + live в работающем плагине через IPC;
  actual  — state store (читает GUI-виджет через bindings, presenter не трогает).

Persist: «Сохранить» пишет desired в активный рецепт (RecipeStore.read_raw/save_raw).
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)

_PLUGIN = "camera_service"


class CameraSettingsPresenter:
    """Презентер камеры: live-команды через bridge + persist в рецепт.

    Зависимости через DI (Protocol-совместимые duck-typed объекты):
        bridge   — TopologyBridge: on_action_command(plugin, cmd, args).
        topology — TopologyRepository: load().to_dict() для поиска процесса камеры.
        recipes  — RecipeStore: get_active/read_raw/save_raw (persist).
    Любая зависимость может быть None → соответствующая операция деградирует
    в no-op с логом (backend/recipe недоступны).
    """

    def __init__(self, *, bridge: Any = None, topology: Any = None, recipes: Any = None) -> None:
        self._bridge = bridge
        self._topology = topology
        self._recipes = recipes
        # desired-параметры, накопленные в этой сессии (для persist).
        self._pending: dict[str, Any] = {}

    # --- topology ---

    def camera_process_name(self) -> str | None:
        """Найти имя процесса, содержащего плагин camera_service. None если нет."""
        if self._topology is None:
            return None
        try:
            topo = self._topology.load().to_dict()
        except Exception:
            return None
        for proc in topo.get("processes", []):
            plugins = proc.get("plugins", [])
            for p in plugins:
                name = p.get("plugin_name") if isinstance(p, dict) else str(p)
                if name == _PLUGIN:
                    return proc.get("process_name")
        return None

    @property
    def is_live(self) -> bool:
        """True если есть мост и процесс камеры в топологии (можно слать live)."""
        return self._bridge is not None and self.camera_process_name() is not None

    # --- live-команды (IPC к плагину) ---

    def apply_param(self, name: str, value: Any) -> bool:
        self._pending[name] = value
        return self._send("set_param", {"name": name, "value": value})

    def apply_mjpg(self, on: bool) -> bool:
        self._pending["mjpg"] = bool(on)
        return self._send("set_mjpg", {"on": bool(on)})

    def apply_resolution(self, width: int, height: int) -> bool:
        return self._send("set_resolution", {"width": int(width), "height": int(height)})

    def apply_fps(self, fps: int) -> bool:
        self._pending["fps"] = int(fps)
        return self._send("set_fps", {"fps": int(fps)})

    def _send(self, command: str, args: dict) -> bool:
        if self._bridge is None:
            logger.debug("CameraSettings: bridge недоступен — %s пропущена", command)
            return False
        try:
            return bool(self._bridge.on_action_command(_PLUGIN, command, args))
        except Exception as exc:
            logger.warning("CameraSettings: команда %s провалилась: %s", command, exc)
            return False

    # --- persist в рецепт ---

    def save(self) -> bool:
        """Сохранить desired-параметры в активный рецепт (plugin_config.params).

        Returns:
            True если рецепт обновлён и сохранён.
        """
        if self._recipes is None or not self._pending:
            return False
        try:
            slug = self._recipes.get_active()
            if not slug:
                return False
            raw = self._recipes.read_raw(slug)
            if not isinstance(raw, dict):
                return False
            if not _merge_camera_params(raw, dict(self._pending)):
                return False
            self._recipes.save_raw(slug, raw)
            return True
        except Exception as exc:
            logger.warning("CameraSettings: persist в рецепт провалился: %s", exc)
            return False


def _merge_camera_params(node: Any, pending: dict[str, Any]) -> bool:
    """Рекурсивно найти блок плагина camera_service и слить в него desired.

    fps/mjpg пишутся как поля верхнего уровня (register-subset через YAML-extra),
    остальные CAP_PROP — в подсловарь `params`. Возвращает True если блок найден.
    """
    found = False
    if isinstance(node, dict):
        if node.get("plugin_name") == _PLUGIN:
            params = node.setdefault("params", {})
            if not isinstance(params, dict):
                params = {}
                node["params"] = params
            for key, value in pending.items():
                if key in ("fps", "mjpg"):
                    node[key] = value
                else:
                    params[key] = value
            found = True
        for value in node.values():
            if _merge_camera_params(value, pending):
                found = True
    elif isinstance(node, list):
        for item in node:
            if _merge_camera_params(item, pending):
                found = True
    return found
