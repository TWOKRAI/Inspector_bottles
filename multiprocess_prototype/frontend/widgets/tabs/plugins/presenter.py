"""PluginsPresenter — бизнес-логика таба плагинов.

Task E.5: мигрирован на AppServices DI. Принимает services: AppServices.
PluginRegistry берётся через services.plugins._registry bridge (PluginCatalog
Protocol не покрывает rich entry API: plugin_class, register_classes, inputs/outputs).
RegistersManager — через services.registers._rm bridge.
plugin_manager (discovery/hot-reload) — отдельный runtime-объект, не входит в
AppServices, передаётся explicit-параметром.

Pure Python (без Qt импортов).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from multiprocess_prototype.domain.app_services import AppServices


class PluginsPresenter:
    """Presenter для PluginsTab.

    Работает с PluginRegistry (через services.plugins._registry bridge) и
    RegistersManager (через services.registers._rm bridge). Управление путями —
    через plugin_manager (runtime-объект вне AppServices).
    """

    # Русские названия категорий
    CATEGORY_TITLES: dict[str, str] = {
        "source": "Источники",
        "processing": "Обработка",
        "output": "Вывод",
        "rendering": "Рендеринг",
        "control": "Управление",
        "utility": "Утилиты",
        "service": "Сервисы",
    }

    def __init__(self, services: AppServices, *, plugin_manager: Any = None) -> None:
        self._services = services
        # TODO Phase F: PluginCatalog Protocol не покрывает rich entry API
        # (plugin_class, register_classes, inputs/outputs) — bridge на raw registry.
        self._registry = getattr(services.plugins, "_registry", None)
        # TODO Phase F: RegistersBackend Protocol имеет другую сигнатуру —
        # get_fields() через raw RegistersManager bridge.
        self._rm = getattr(services.registers, "_rm", None)
        # plugin_manager (discovery/hot-reload) вне AppServices — runtime dep (Phase G).
        self._plugin_manager = plugin_manager

    def list_plugins(self) -> list[tuple[str, str, str]]:
        """Список плагинов: (name, display_text, category).

        Формат для MasterDetailLayout.set_items().
        """
        registry = self._registry
        if registry is None:
            return []

        result = []
        for entry in registry.list():
            name = entry.name
            display = f"{name} ({self.CATEGORY_TITLES.get(entry.category, entry.category)})"
            result.append((name, display, entry.category))
        return result

    def get_categories(self) -> list[str]:
        """Уникальные категории из реестра."""
        registry = self._registry
        if registry is None:
            return []

        cats = sorted({entry.category for entry in registry.list()})
        return cats

    def get_plugin_info(self, name: str) -> dict:
        """Информация о плагине для PluginInfoCard.

        Returns:
            dict с ключами: name, category, description, inputs, outputs, has_registers
        """
        registry = self._registry
        if registry is None:
            return {
                "name": name,
                "category": "",
                "description": "",
                "inputs": [],
                "outputs": [],
                "has_registers": False,
            }

        entry = registry.get(name)
        if entry is None:
            return {
                "name": name,
                "category": "",
                "description": "",
                "inputs": [],
                "outputs": [],
                "has_registers": False,
            }

        # Порты
        inputs = []
        outputs = []
        if hasattr(entry, "inputs"):
            inputs = [f"{p.name}: {p.dtype}" for p in (entry.inputs or [])]
        if hasattr(entry, "outputs"):
            outputs = [f"{p.name}: {p.dtype}" for p in (entry.outputs or [])]

        has_registers = bool(getattr(entry, "register_classes", None))

        return {
            "name": entry.name,
            "category": entry.category,
            "description": getattr(entry, "description", ""),
            "inputs": inputs,
            "outputs": outputs,
            "has_registers": has_registers,
        }

    def get_register_fields(self, plugin_name: str) -> list:
        """Получить FieldInfo для плагина с registers.

        Returns:
            list[FieldInfo] или пустой список.
        """
        rm = self._rm
        if rm is None:
            return []
        try:
            return rm.get_fields(plugin_name)
        except Exception:
            return []

    # ------------------------------------------------------------------ #
    #  Task 2.5 — управление путями плагинов                              #
    # ------------------------------------------------------------------ #

    def get_plugin_paths(self) -> list[str]:
        """Текущий список директорий поиска плагинов.

        Returns:
            Список строк-путей или [] если PluginManager не инициализирован.
        """
        pm = self._plugin_manager
        if pm is None:
            return []
        return [str(p) for p in pm.plugin_paths]

    def add_plugin_path(self, path: str) -> None:
        """Добавить новый путь к директориям поиска плагинов.

        Добавляет путь (если его нет в списке), сохраняет в user_overrides.yaml,
        и обновляет _plugin_paths в PluginManager для следующего rescan().

        Args:
            path: строковый путь к директории (абсолютный или относительный).
        """
        current = self.get_plugin_paths()
        if path in current:
            return
        new_list = current + [path]
        self._save_paths_to_overrides(new_list)
        # Обновить пути в PluginManager без его пересоздания
        pm = self._plugin_manager
        if pm is not None:
            pm._plugin_paths = [Path(p).resolve() for p in new_list]

    def remove_plugin_path(self, path: str) -> None:
        """Удалить путь из директорий поиска плагинов.

        Если пути нет в списке — ничего не делает.
        Сохраняет обновлённый список в user_overrides.yaml и обновляет PluginManager.

        Args:
            path: строковый путь для удаления.
        """
        current = self.get_plugin_paths()
        if path not in current:
            return
        new_list = [p for p in current if p != path]
        self._save_paths_to_overrides(new_list)
        # Обновить пути в PluginManager без его пересоздания
        pm = self._plugin_manager
        if pm is not None:
            pm._plugin_paths = [Path(p).resolve() for p in new_list]

    def rescan(self) -> str:
        """Запустить горячее переобнаружение плагинов через PluginManager.

        Returns:
            Строка-сводка результата в формате «Загружено: N, ошибок: M, новых: K».
            При отсутствии PluginManager возвращает «PluginManager не инициализирован».
        """
        pm = self._plugin_manager
        if pm is None:
            return "PluginManager не инициализирован"
        result = pm.rescan()
        return f"Загружено: {len(result.loaded)}, ошибок: {len(result.failed)}, новых: {len(result.new_plugins)}"

    def _save_paths_to_overrides(self, paths: list[str]) -> None:
        """Сохранить список путей плагинов в user_overrides.yaml.

        Читает существующий файл (или {} если нет), deep-merge'ит только ключ
        discovery.plugin_paths, записывает обратно. Остальные ключи не трогает.

        Args:
            paths: новый список строковых путей для сохранения.
        """
        from multiprocess_prototype.main import CONFIG_PATH

        override_path = CONFIG_PATH.parent / "user_overrides.yaml"

        # Читаем существующее содержимое
        existing: dict = {}
        if override_path.exists():
            try:
                with open(override_path, encoding="utf-8") as f:
                    existing = yaml.safe_load(f) or {}
            except yaml.YAMLError:
                existing = {}

        # Обновляем только discovery.plugin_paths
        discovery = existing.get("discovery", {})
        if not isinstance(discovery, dict):
            discovery = {}
        discovery["plugin_paths"] = paths
        existing["discovery"] = discovery

        # Записываем обратно
        with open(override_path, "w", encoding="utf-8") as f:
            yaml.dump(existing, f, allow_unicode=True, default_flow_style=False)
