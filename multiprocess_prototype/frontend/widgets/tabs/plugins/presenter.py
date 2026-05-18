"""PluginsPresenter — бизнес-логика таба плагинов.

Pure Python (без Qt импортов).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from multiprocess_prototype.frontend.app_context import AppContext


class PluginsPresenter:
    """Presenter для PluginsTab.

    Работает с PluginRegistry и RegistersManager через AppContext.
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

    def __init__(self, ctx: "AppContext") -> None:
        self._ctx = ctx

    def list_plugins(self) -> list[tuple[str, str, str]]:
        """Список плагинов: (name, display_text, category).

        Формат для MasterDetailLayout.set_items().
        """
        registry = self._ctx.plugin_registry()
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
        registry = self._ctx.plugin_registry()
        if registry is None:
            return []

        cats = sorted({entry.category for entry in registry.list()})
        return cats

    def get_plugin_info(self, name: str) -> dict:
        """Информация о плагине для PluginInfoCard.

        Returns:
            dict с ключами: name, category, description, inputs, outputs, has_registers
        """
        registry = self._ctx.plugin_registry()
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
        rm = self._ctx.registers_manager()
        if rm is None:
            return []
        try:
            return rm.get_fields(plugin_name)
        except Exception:
            return []
