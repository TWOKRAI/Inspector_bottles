"""GenericProcess — тонкий контейнер с plugin state machine.

Управляет state transitions плагинов:
    _init_application_threads():  IDLE → READY → RUNNING
    shutdown():                   * → STOPPED

Загружает плагины из config["plugins"], передаёт в state machine.
Команды плагинов автоматически регистрируются в CommandManager.
"""

from __future__ import annotations

import importlib
from typing import Any

from ..core.process_module import ProcessModule
from ..io import ProcessIO
from ..plugins.base import PluginContext, PluginState, ProcessModulePlugin


class GenericProcess(ProcessModule):
    """Тонкий контейнер. Только lifecycle + state transitions.

    Каждый элемент plugins — dict с ключами:
    - plugin_class: str — dotted path к классу ProcessModulePlugin
    - plugin_name: str — уникальное имя плагина в процессе
    - ... остальные поля — plugin-specific конфиг
    """

    def _init_application_threads(self) -> None:
        """Загрузить плагины и провести через IDLE → READY → RUNNING."""
        super()._init_application_threads()

        app_cfg = self.get_config("config") or {}
        plugin_defs: list[dict[str, Any]] = app_cfg.get("plugins", [])

        self._plugins: list[ProcessModulePlugin] = []
        self._plugin_contexts: list[PluginContext] = []

        if not plugin_defs:
            self._log_info(f"GenericProcess[{self.name}]: нет плагинов")
            return

        io = ProcessIO(self)
        base_ctx = PluginContext(
            process_name=self.name, config={}, process=self, io=io,
        )

        # Фаза 1: загрузка + IDLE → READY (configure + авторегистрация команд)
        for pdef in plugin_defs:
            plugin_class_path = pdef.get("plugin_class", "")
            plugin_name = pdef.get("plugin_name", "unknown")

            if not plugin_class_path:
                self._log_error(f"GenericProcess[{self.name}]: '{plugin_name}' без plugin_class")
                continue

            try:
                plugin = self._load_plugin(plugin_class_path, plugin_name)
            except Exception as e:
                self._log_error(f"GenericProcess[{self.name}]: загрузка '{plugin_name}': {e}")
                continue

            plugin_config = {
                k: v for k, v in pdef.items()
                if k not in ("plugin_class", "plugin_name")
            }
            ctx = base_ctx.with_config(plugin_config)

            try:
                plugin._do_configure(ctx)
                self._plugins.append(plugin)
                self._plugin_contexts.append(ctx)
                self._log_info(
                    f"GenericProcess[{self.name}]: '{plugin_name}' "
                    f"[{plugin.category}] {plugin.state.value}"
                )
            except Exception as e:
                self._log_error(f"GenericProcess[{self.name}]: configure '{plugin_name}': {e}")

        # Фаза 2: READY → RUNNING (start)
        for plugin, ctx in zip(self._plugins, self._plugin_contexts):
            try:
                plugin._do_start(ctx)
                self._log_info(
                    f"GenericProcess[{self.name}]: '{plugin.name}' {plugin.state.value}"
                )
            except Exception as e:
                self._log_error(f"GenericProcess[{self.name}]: start '{plugin.name}': {e}")

        self._log_info(
            f"GenericProcess[{self.name}]: {len(self._plugins)} плагин(ов)"
        )

    def _load_plugin(self, class_path: str, plugin_name: str) -> ProcessModulePlugin:
        """Загрузить класс плагина по dotted path."""
        module_path, class_name = class_path.rsplit(".", 1)
        module = importlib.import_module(module_path)
        cls = getattr(module, class_name)

        if not (isinstance(cls, type) and issubclass(cls, ProcessModulePlugin)):
            raise TypeError(f"'{class_path}' не является ProcessModulePlugin")

        instance = cls()
        if not instance.name:
            instance.name = plugin_name
        return instance

    def shutdown(self) -> bool:
        """* → STOPPED для всех плагинов (в обратном порядке)."""
        for plugin, ctx in reversed(list(zip(
            getattr(self, "_plugins", []),
            getattr(self, "_plugin_contexts", []),
        ))):
            try:
                plugin._do_shutdown(ctx)
                self._log_info(f"GenericProcess[{self.name}]: '{plugin.name}' {plugin.state.value}")
            except Exception as e:
                self._log_error(f"GenericProcess[{self.name}]: shutdown '{plugin.name}': {e}")

        return super().shutdown()
