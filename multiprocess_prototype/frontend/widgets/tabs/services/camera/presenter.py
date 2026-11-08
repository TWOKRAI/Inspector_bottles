"""CameraSettingsPresenter — логика фасада настроек камеры (без Qt).

Источник правды:
  desired — рецепт (plugin_config) + live в работающем плагине через IPC;
  actual  — state store (читает GUI-виджет через bindings, presenter не трогает).

Persist: «Сохранить» кладёт desired в модель редактора командами SetPluginConfig
(PluginInstance.config камеры), затем сохраняет общим Save активной топологии (save_active).
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from multiprocess_framework.modules.logger_module import get_std_logger
from multiprocess_prototype.domain.commands import SetPluginConfig
from multiprocess_prototype.recipes.save import RecipeValidationError

logger = get_std_logger(__name__)

_PLUGIN = "camera_service"
# Точный текст, которым _save_active_topology сообщает о конфликте с внешней правкой файла.
_CONFLICT_TEXT = "Рецепт изменён снаружи — перезагрузите его"
# Поля регистра CameraServiceRegisters: по команде на ключ; остальные CAP_PROP уходят в config["params"].
_REGISTER_KEYS = ("fps", "mjpg")


class CameraSettingsPresenter:
    """Презентер камеры: live-команды через bridge + persist через модель редактора и общий Save.

    Зависимости через DI (Protocol-совместимые duck-typed объекты):
        bridge   — TopologyBridge: on_action_command(plugin, cmd, args).
        topology — TopologyRepository: load().to_dict() для поиска процесса камеры.
        recipes  — RecipeStore: get_active() (есть ли активный рецепт).
        commands — CommandDispatcher: dispatch(SetPluginConfig) в модель редактора.
        save_active — общий Save редактора (callable() -> bool; конфликт = RuntimeError).
    Persist = SetPluginConfig в модель + save_active; файл рецепта презентер не трогает.
    Любая зависимость может быть None → соответствующая операция деградирует
    в no-op с логом (backend/recipe недоступны).
    """

    def __init__(
        self,
        *,
        bridge: Any = None,
        topology: Any = None,
        recipes: Any = None,
        commands: Any = None,
        save_active: Callable[[], bool] | None = None,
    ) -> None:
        self._bridge = bridge
        self._topology = topology
        self._recipes = recipes
        self._commands = commands
        self._save_active = save_active
        # Текст конфликта последнего save() (пусто, если конфликта не было).
        self._last_error = ""
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

    # --- persist через модель редактора ---

    @property
    def last_error(self) -> str:
        """Причина отказа последнего save() или "": конфликт с внешней правкой, отказ валидации Save (Task 1.16 m1).

        Иные ошибки (в т.ч. прочие ``RuntimeError``) сюда не попадают.
        """
        return self._last_error

    def _find_camera(self) -> tuple[str, int, dict] | None:
        """Первый процесс с camera_service: (process_name, индекс в plugins, config плагина)."""
        if self._topology is None:
            return None
        topo = self._topology.load().to_dict()
        for proc in topo.get("processes", []):
            for idx, p in enumerate(proc.get("plugins", [])):
                name = p.get("plugin_name") if isinstance(p, dict) else str(p)
                if name == _PLUGIN:
                    config = p.get("config") if isinstance(p, dict) else None
                    return proc.get("process_name"), idx, config if isinstance(config, dict) else {}
        return None

    def save(self) -> bool:
        """Положить desired-параметры в модель редактора (SetPluginConfig) и сохранить общим Save.

        fps/mjpg — по команде на ключ; остальные CAP_PROP — одна команда ``params`` со
        значением «текущий config.params модели + pending» (слияние в backend неглубокое).
        pending сбрасывается только после успешного save_active (при конфликте нужен для повтора).

        Returns:
            True если save_active вернул True. Конфликт или отказ валидации -> False + last_error; иная ошибка -> False.
        """
        self._last_error = ""
        if self._recipes is None or self._commands is None or self._save_active is None or not self._pending:
            return False
        try:
            if not self._recipes.get_active():
                return False
            found = self._find_camera()
            if found is None:
                return False
            process, idx, config = found
            pending = dict(self._pending)
            for key in _REGISTER_KEYS:
                if key in pending:
                    self._commands.dispatch(SetPluginConfig(process, idx, key, pending.pop(key)))
            if pending:
                current = config.get("params")
                merged = {**current, **pending} if isinstance(current, dict) else pending
                self._commands.dispatch(SetPluginConfig(process, idx, "params", merged))
            ok = bool(self._save_active())
        except RuntimeError as exc:
            if str(exc) == _CONFLICT_TEXT:
                logger.warning("CameraSettings: %s", _CONFLICT_TEXT)
                self._last_error = _CONFLICT_TEXT
            else:
                logger.warning("CameraSettings: сохранение не удалось (%s)", type(exc).__name__)
            return False
        except RecipeValidationError as exc:
            logger.warning("CameraSettings: сохранение отклонено (%s)", type(exc).__name__)
            self._last_error = "; ".join(exc.errors) or str(exc)
            return False
        except Exception as exc:
            logger.warning("CameraSettings: сохранение не удалось (%s)", type(exc).__name__)
            return False
        if ok:
            self._pending.clear()
        return ok


def _merge_camera_params(node: Any, pending: dict[str, Any]) -> bool:
    """Рекурсивно найти блок плагина camera_service и слить в него desired.

    fps/mjpg пишутся как поля верхнего уровня (register-subset через YAML-extra),
    остальные CAP_PROP — в подсловарь `params`. Возвращает True если блок найден.

    FREEZE (C-30, Task 1.10): живых вызывающих нет, Камера пишет через ``SetPluginConfig``; функция не удаляется
    (принцип 3). Скрытый дефект: пишет ``params`` и поля верхнего уровня, а не ``config:`` плагина — не
    использовать без исправления (вердикт CTO Q2).
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
